"""El registro contado en lenguaje corriente, para que alguien de finanzas lo lea sin abrir el código.

Cada línea sale de una entrada real del registro encadenado (ledger.jsonl) y conserva su sello,
así que lo que se lee es lo mismo que se verificó. También incluye una demostración de manipulación
sobre una COPIA temporal: nunca toca el registro verdadero.
"""
import copy
import json
import os
import tempfile

from . import ledger

VERB = {"PAY": "PAGÓ", "ESCALATE": "ESCALÓ a una persona", "BLOCK": "FRENÓ"}


def _money(n):
    return "{:,.2f}".format(n).rstrip("0").rstrip(".") if n is not None else "—"


def line(e):
    """Texto en lenguaje corriente de una entrada, o None si no se narra."""
    kind = e.get("event")
    if kind == "batch_start":
        r = e.get("rules", {})
        return ("Se abrió un lote de revisión con las reglas vigentes: máximo USD %s por pago, aprobación humana desde USD %s, "
                "presupuesto del periodo USD %s, tolerancia de %s %% sobre lo acordado."
                % (_money(r.get("max_per_payment_usd")), _money(r.get("approval_threshold_usd")),
                   _money(r.get("period_budget_usd")), _money(r.get("amount_tolerance_pct"))))
    if kind == "decision":
        x = e.get("extracted") or {}
        who = x.get("beneficiary") or "un emisor que no se pudo leer"
        what = "la factura %s" % x["invoice_number"] if x.get("invoice_number") else "el documento %s" % e.get("file")
        amt = " por %s %s" % (x.get("currency") or "", _money(x["amount"])) if x.get("amount") is not None else ""
        usd = " (≈ USD %s)" % _money(e["amount_usd"]) if e.get("amount_usd") is not None and x.get("currency") != "USD" else ""
        return "El agente %s %s de %s%s%s. Motivo: %s" % (VERB.get(e.get("decision"), e.get("decision")), what, who, amt, usd, e.get("reason"))
    if kind == "human_review":
        act = "APROBÓ" if e.get("action") == "approve" else "RECHAZÓ"
        return "Una persona (%s) %s el pago de %s." % (e.get("by", "finanzas"), act, e.get("file"))
    return None


def narrate(entries):
    out = []
    for e in entries:
        t = line(e)
        if t:
            out.append({"seq": e.get("seq"), "ts": e.get("ts"), "event": e.get("event"), "decision": e.get("decision"),
                        "action": e.get("action"), "file": e.get("file"), "text": t, "seal": (e.get("hash") or "")[:12]})
    return out


def batch_entries(path, batch_id=None):
    entries = [e for e in ledger.read(path) if "_corrupt" not in e]
    if batch_id is None:
        starts = [e["batch"] for e in entries if e.get("event") == "batch_start"]
        batch_id = starts[-1] if starts else None
    return batch_id, [e for e in entries if e.get("batch") == batch_id]


def readable_log(path, batch_id=None):
    batch_id, es = batch_entries(path, batch_id)
    return {"batch": batch_id, "lines": narrate(es), "chain": ledger.verify(path)}


def tamper_demo(path, batch_id=None):
    """Cambia una decisión en una COPIA del registro y muestra que la cadena se rompe en esa línea."""
    batch_id, es = batch_entries(path, batch_id)
    target = next((e for e in es if e.get("event") == "decision" and e.get("decision") == "ESCALATE"), None)
    if target is None:
        raise ValueError("no hay una decisión escalada para la demostración; procesa las facturas primero")
    entries = ledger.read(path)
    fake = copy.deepcopy(entries[target["seq"]])
    before, fake["decision"] = line(fake), "PAY"
    after = line(fake)
    entries[target["seq"]] = fake
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "copia.jsonl")
        with open(p, "w", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        res = ledger.verify(p)
    return {"seq": target["seq"], "before": before, "after": after, "chain": res}
