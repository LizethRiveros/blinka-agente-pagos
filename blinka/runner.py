"""Procesa el lote de facturas, registra cada decisión y aplica revisiones humanas."""
import copy
import csv
import io
import json
import os
import uuid

from . import ledger
from .counterfactual import explain
from .engine import PAY, BLOCK, ESCALATE, assert_safe, evaluate, new_state
from .extract import extract_document, read_document

DOC_TYPES = (".txt", ".pdf", ".png", ".jpg", ".jpeg")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DATA = os.path.join(ROOT, "data")
LEDGER = os.path.join(ROOT, "output", "ledger.jsonl")


def load_rules():
    with open(os.path.join(DATA, "rules.json"), encoding="utf-8") as f:
        return json.load(f)


def load_expected():
    try:
        with open(os.path.join(DATA, "expected.json"), encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def run_batch(rules, extractor=extract_document, ledger_path=None):
    path = ledger_path or LEDGER
    folder = os.path.join(DATA, "invoices")
    batch_id = uuid.uuid4().hex[:12]
    ledger.append(path, {"event": "batch_start", "batch": batch_id, "rules": rules,
                         "rules_sha": ledger.sha(ledger.canon(rules))})
    state, results = new_state(), []
    for name in sorted(os.listdir(folder)):
        if not name.lower().endswith(DOC_TYPES):
            continue
        file_path = os.path.join(folder, name)
        ex, meta = extractor(read_document(file_path))
        before = copy.deepcopy(state)
        res = evaluate(ex, rules, state, meta)
        res.update(file=name, extracted=ex, reader=meta, human=None,
                   what_if=explain(ex, meta, rules, before, res))
        results.append(res)
        with open(file_path, "rb") as f:
            doc_sha = ledger.sha(f.read())
        entry = ledger.append(path, {
            "event": "decision", "batch": batch_id, "file": name, "doc_sha": doc_sha, "extracted": ex,
            "meta": {k: meta.get(k) for k in ("readers", "conflicts", "ambiguous", "error")},
            "decision": res["decision"], "reason": res["reason"], "amount_usd": res["amount_usd"],
            "failed": [c["name"] for c in res["checks"] if not c["ok"]]})
        res["seal"] = entry["hash"]
    assert_safe(results)
    return {"id": batch_id, "results": results, "state": state, "ledger_path": path}


def review(batch, file, action, reviewer="persona de finanzas"):
    """Una persona aprueba o rechaza una factura escalada. Solo aplica a ESCALATE."""
    res = next((r for r in batch["results"] if r["file"] == file), None)
    if not res or res["decision"] != ESCALATE or res["human"]:
        raise ValueError("esa factura no está pendiente de aprobación")
    if action not in ("approve", "reject"):
        raise ValueError("acción inválida")
    res["human"] = {"action": action, "by": reviewer}
    if action == "approve":
        batch["state"]["spent_usd"] = round(batch["state"]["spent_usd"] + res["amount_usd"], 2)
    ledger.append(batch.get("ledger_path") or LEDGER, {"event": "human_review", "batch": batch["id"], "file": file,
                                                         "action": action, "by": reviewer})
    return res


def summarize(batch, rules):
    rs, exp = batch["results"], load_expected()
    has_claude = any("claude" in r["reader"]["readers"] for r in rs)
    # Lo que solo Claude puede leer (fotos, escaneos, texto sin formato) no se evalúa si Claude no leyó.
    scored = [r for r in rs if r["file"] in exp and (has_claude or not exp[r["file"]].get("needs_claude"))]
    unscored = sum(r["file"] in exp for r in rs) - len(scored)
    ok = [r for r in scored if r["decision"] == exp[r["file"]]["expected"]]
    unsafe = [r for r in rs if r["file"] in exp and r["decision"] == PAY and exp[r["file"]]["expected"] != PAY]
    auto = [r for r in ok if r["decision"] in (PAY, BLOCK)]
    return {
        "total": len(rs),
        "pay": sum(r["decision"] == PAY for r in rs),
        "block": sum(r["decision"] == BLOCK for r in rs),
        "escalate": sum(r["decision"] == ESCALATE for r in rs),
        "pending": sum(r["decision"] == ESCALATE and not r["human"] for r in rs),
        "spent_usd": batch["state"]["spent_usd"],
        "budget_usd": rules["period_budget_usd"],
        "accuracy": round(len(ok) / len(scored), 3) if scored else None,
        "autonomy": round(len(auto) / len(scored), 3) if scored else None,
        "unsafe_payments": len(unsafe),
        "not_evaluated": unscored,
        "claude_used": has_claude,
        "explained": sum(bool(r["reason"]) for r in rs),
    }


def _cell(v):
    """Evita inyección de fórmulas al abrir el CSV en Excel o Sheets (el texto viene de facturas externas)."""
    v = "" if v is None else str(v)
    return "'" + v if v[:1] in ("=", "+", "-", "@", "\t", "\r") else v


def export_csv(batch):
    """Registro para conciliar: qué se decidió con cada factura y por qué."""
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["archivo", "factura", "beneficiario", "moneda", "monto", "monto_usd", "ruta_de_pago",
                "decision_agente", "revision_humana", "verificaciones_fallidas", "motivo", "que_cambiaria_para_pagar", "sello"])
    for r in batch["results"]:
        e, h = r["extracted"], r["human"]
        w.writerow([_cell(x) for x in (
            r["file"], e.get("invoice_number"), e.get("beneficiary"), e.get("currency"), e.get("amount"),
            r["amount_usd"], e.get("payment_rail"), r["decision"],
            ("aprobada" if h["action"] == "approve" else "rechazada") if h else "",
            "; ".join(c["name"] for c in r["checks"] if not c["ok"]), r["reason"],
            "; ".join(c["text"] for c in (r.get("what_if") or {}).get("rule_changes", [])), r.get("seal", "")[:16])])
    return out.getvalue()


def simulate(batch, new_rules):
    """¿Qué cambiaría si se guardaran estas reglas? Vuelve a decidir con lo ya leído (sin releer ni registrar)."""
    state, changes, counts = new_state(), [], {PAY: 0, ESCALATE: 0, BLOCK: 0}
    for r in batch["results"]:
        res = evaluate(copy.deepcopy(r["extracted"]), new_rules, state, r["reader"])
        counts[res["decision"]] += 1
        if res["decision"] != r["decision"]:
            changes.append({"file": r["file"], "before": r["decision"], "after": res["decision"], "reason": res["reason"]})
    return {"changes": changes, "counts": counts,
            "note": "Las aprobaciones humanas ya dadas no se reaplican en la simulación."}
