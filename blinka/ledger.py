"""Registro de decisiones encadenado por hash y reproducible.

Cada entrada guarda el hash de la anterior: si alguien edita, borra o reordena una línea del medio,
la cadena se rompe y `verify` lo detecta. Como el motor es determinista, `replay` vuelve a decidir
cada factura desde lo que quedó registrado (reglas vigentes + datos leídos) y comprueba que el
resultado sea idéntico. Un agente cuyo juicio es un modelo no puede ofrecer esto.

Límite conocido: quien borre las ÚLTIMAS líneas no rompe la cadena; por eso cada lote muestra su
sello (hash final) y conviene copiarlo aparte para cotejarlo.
"""
import copy
import hashlib
import json
import os
import time

from .engine import evaluate, new_state

GENESIS = "0" * 64


def canon(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha(text):
    if isinstance(text, str):
        text = text.encode("utf-8")
    return hashlib.sha256(text).hexdigest()


def _lines(path):
    try:
        with open(path, encoding="utf-8") as f:
            return [ln for ln in f.read().splitlines() if ln.strip()]
    except FileNotFoundError:
        return []


def read(path):
    out = []
    for ln in _lines(path):
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            out.append({"_corrupt": ln})
    return out


def head(path):
    """(hash de la última entrada, cantidad de entradas)."""
    lines = _lines(path)
    if not lines:
        return GENESIS, 0
    try:
        return json.loads(lines[-1]).get("hash", GENESIS), len(lines)
    except json.JSONDecodeError:
        return GENESIS, len(lines)


def _seal(entry):
    body = {k: v for k, v in entry.items() if k != "hash"}
    return sha(entry["prev"] + canon(body))


def append(path, event):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    prev, n = head(path)
    entry = dict(event, seq=n, ts=time.strftime("%Y-%m-%dT%H:%M:%S"), prev=prev)
    entry["hash"] = _seal(entry)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def verify(path):
    """Recalcula toda la cadena. Devuelve {ok, entries, head, bad_at, problem}."""
    prev = GENESIS
    entries = read(path)
    for i, e in enumerate(entries):
        if "_corrupt" in e:
            return {"ok": False, "entries": len(entries), "head": prev, "bad_at": i, "problem": "línea ilegible"}
        if e.get("seq") != i:
            return {"ok": False, "entries": len(entries), "head": prev, "bad_at": i,
                    "problem": "falta o sobra una entrada (seq %s, esperaba %d)" % (e.get("seq"), i)}
        if e.get("prev") != prev:
            return {"ok": False, "entries": len(entries), "head": prev, "bad_at": i, "problem": "no enlaza con la anterior"}
        if e.get("hash") != _seal(e):
            return {"ok": False, "entries": len(entries), "head": prev, "bad_at": i, "problem": "el contenido fue modificado"}
        prev = e["hash"]
    return {"ok": True, "entries": len(entries), "head": prev, "bad_at": None, "problem": None}


def replay(path, invoices_dir=None):
    """Vuelve a decidir cada factura registrada y compara. Devuelve {replayed, mismatches, warnings}.

    No relee documentos (eso podría requerir un modelo): reproduce la DECISIÓN a partir de lo leído,
    que queda registrado junto con el hash del documento. Si `invoices_dir` existe, avisa cuando un
    documento ya no coincide con el hash registrado.
    """
    ctx, amounts = {}, {}
    out = {"replayed": 0, "mismatches": [], "warnings": []}
    for e in read(path):
        kind, b = e.get("event"), e.get("batch")
        if kind == "batch_start":
            ctx[b] = (e["rules"], new_state())
        elif kind == "decision" and b in ctx:
            rules, state = ctx[b]
            res = evaluate(copy.deepcopy(e["extracted"]), rules, state, e.get("meta"))
            out["replayed"] += 1
            amounts[(b, e["file"])] = res["amount_usd"]
            if (res["decision"], res["reason"], res["amount_usd"]) != (e["decision"], e["reason"], e["amount_usd"]):
                out["mismatches"].append({"seq": e["seq"], "file": e["file"], "registrada": e["decision"],
                                          "reproducida": res["decision"]})
            if invoices_dir:
                p = os.path.join(invoices_dir, e["file"])
                if os.path.exists(p):
                    with open(p, "rb") as f:
                        if sha(f.read()) != e.get("doc_sha"):
                            out["warnings"].append("%s cambió desde que se decidió (seq %d)" % (e["file"], e["seq"]))
        elif kind == "human_review" and b in ctx and e.get("action") == "approve":
            rules, state = ctx[b]
            state["spent_usd"] = round(state["spent_usd"] + (amounts.get((b, e["file"])) or 0), 2)
    return out
