"""Procesa el lote de facturas, registra cada decisión y aplica revisiones humanas."""
import csv
import io
import json
import os
import time

from .engine import PAY, BLOCK, ESCALATE, assert_safe, evaluate, new_state
from .extract import extract_document, read_document

DOC_TYPES = (".txt", ".pdf", ".png", ".jpg", ".jpeg")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DATA = os.path.join(ROOT, "data")
LOG = os.path.join(ROOT, "output", "decisions.jsonl")


def load_rules():
    with open(os.path.join(DATA, "rules.json"), encoding="utf-8") as f:
        return json.load(f)


def load_expected():
    try:
        with open(os.path.join(DATA, "expected.json"), encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def log(event):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(dict(event, ts=time.strftime("%Y-%m-%dT%H:%M:%S")), ensure_ascii=False) + "\n")


def run_batch(rules, extractor=extract_document):
    folder = os.path.join(DATA, "invoices")
    state, results = new_state(), []
    for name in sorted(os.listdir(folder)):
        if not name.lower().endswith(DOC_TYPES):
            continue
        ex, meta = extractor(read_document(os.path.join(folder, name)))
        res = evaluate(ex, rules, state, meta)
        res.update(file=name, extracted=ex, reader=meta, human=None)
        results.append(res)
        log({"event": "decision", "file": name, "decision": res["decision"], "readers": meta["readers"],
             "amount_usd": res["amount_usd"], "reason": res["reason"]})
    assert_safe(results)
    return {"results": results, "state": state}


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
    log({"event": "human_review", "file": file, "action": action, "by": reviewer})
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
                "decision_agente", "revision_humana", "verificaciones_fallidas", "motivo"])
    for r in batch["results"]:
        e, h = r["extracted"], r["human"]
        w.writerow([_cell(x) for x in (
            r["file"], e.get("invoice_number"), e.get("beneficiary"), e.get("currency"), e.get("amount"),
            r["amount_usd"], e.get("payment_rail"), r["decision"],
            ("aprobada" if h["action"] == "approve" else "rechazada") if h else "",
            "; ".join(c["name"] for c in r["checks"] if not c["ok"]), r["reason"])])
    return out.getvalue()
