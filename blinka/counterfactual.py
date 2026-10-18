"""Explicación contrafactual: qué tendría que cambiar para que una factura se pague.

No basta con decir por qué se escaló; la persona necesita saber qué cambio la destraba. Cada
propuesta se VERIFICA volviendo a correr el motor con el cambio aplicado, así que no es una opinión:
si aparece como verificada, el motor la pagaría.
"""
import copy
import math
from datetime import date

from .engine import PAY, evaluate, norm_name

AMOUNT_CHECKS = {"Límite por pago", "Aprobación humana por monto", "Presupuesto del periodo", "Coincide con lo acordado"}


def _up(x):
    return math.ceil(round(x * 100, 6)) / 100


def _down(x):
    return math.floor(round(x * 100, 6)) / 100


def _fmt(x):
    return f"{x:,.2f}"


def _run(ex, meta, rules, state):
    return evaluate(copy.deepcopy(ex), rules, copy.deepcopy(state), meta)


def _passes(res, name):
    return any(c["name"] == name and c["ok"] for c in res["checks"])


def _fixes(ex, rules, state, res, failed):
    """Lista de (verificación, texto, función que aplica el cambio a una copia de las reglas)."""
    out = []
    a = res["amount_usd"]
    ben = next((b for b in rules["allowed_beneficiaries"] if norm_name(b["name"]) == norm_name(ex.get("beneficiary"))), None)

    if "Límite por pago" in failed and a is not None:
        v = _up(a)
        out.append(("Límite por pago", "subir el límite duro por pago a USD %s" % _fmt(v),
                    lambda r, v=v: r.__setitem__("max_per_payment_usd", v)))
    if "Aprobación humana por monto" in failed and a is not None:
        v = _up(a)
        out.append(("Aprobación humana por monto", "subir el umbral de aprobación humana a USD %s" % _fmt(v),
                    lambda r, v=v: r.__setitem__("approval_threshold_usd", v)))
    if "Presupuesto del periodo" in failed and a is not None:
        v = _up(state["spent_usd"] + a)
        out.append(("Presupuesto del periodo", "subir el presupuesto del periodo a USD %s" % _fmt(v),
                    lambda r, v=v: r.__setitem__("period_budget_usd", v)))
    if "Coincide con lo acordado" in failed and ben and ben["currency"] == ex.get("currency"):
        gap = abs(ex["amount"] - ben["agreed_amount"]) / ben["agreed_amount"] * 100
        v = math.ceil(gap * 100) / 100
        out.append(("Coincide con lo acordado", "subir la tolerancia sobre lo acordado a %s %%" % _fmt(v),
                    lambda r, v=v: r.__setitem__("amount_tolerance_pct", v)))
    if "Beneficiario permitido" in failed and ex.get("beneficiary") and ex.get("currency") and ex.get("amount"):
        def add(r):
            new = {"name": ex["beneficiary"], "country": "", "currency": ex["currency"],
                   "agreed_amount": ex["amount"], "concept": ""}
            if ex.get("payment_rail"):
                new["rails"] = [ex["payment_rail"]]
            r["allowed_beneficiaries"].append(new)
        out.append(("Beneficiario permitido", "agregar a «%s» a los beneficiarios permitidos (acordado: %s %s)" % (
            ex["beneficiary"], ex["currency"], _fmt(ex["amount"])), add))
    if "Ruta de pago permitida" in failed and ben:
        def allow(r, name=ben["name"]):
            b = next(b for b in r["allowed_beneficiaries"] if b["name"] == name)
            b["rails"] = list(b.get("rails") or []) + [ex["payment_rail"]]
        out.append(("Ruta de pago permitida", "permitir la ruta %s para %s" % (ex["payment_rail"], ben["name"]), allow))
    if "Vencimiento" in failed and ex.get("due_date"):
        days = (date.fromisoformat(rules["as_of"]) - date.fromisoformat(ex["due_date"])).days
        out.append(("Vencimiento", "tolerar hasta %d días de vencida" % days,
                    lambda r, d=days: r.__setitem__("max_days_overdue", d)))
    return out


def _others(failed, ex):
    notes = []
    if "Sin duplicado" in failed:
        notes.append("Ya se recibió antes: es el mismo cobro y no se paga dos veces. Ninguna regla lo cambia.")
    if "Lectura confiable" in failed:
        notes.append("Hay que revisar el documento: las lecturas no coinciden o se contradice a sí mismo.")
    if "Datos completos" in failed:
        notes.append("Faltan datos que el documento no trae con claridad; hay que pedirlos al proveedor.")
    if "Moneda soportada" in failed:
        notes.append("Configurar el tipo de cambio de %s en las reglas (hoy no existe)." % ex.get("currency"))
    if "Coincide con lo acordado" in failed and "se acordó" in failed["Coincide con lo acordado"]["detail"].lower() \
            and "viene en" in failed["Coincide con lo acordado"]["detail"]:
        notes.append("Se acordó en otra moneda: hay que aclarar con el proveedor antes de cambiar reglas.")
    return notes


def _max_amount(ex, meta, rules, state, failed):
    """Mayor monto (en la moneda de la factura) con el que el motor pagaría, o None."""
    if not set(failed) <= AMOUNT_CHECKS or not ex.get("amount") or not ex.get("currency"):
        return None
    rate = rules["fx_to_usd"].get(ex["currency"])
    ben = next((b for b in rules["allowed_beneficiaries"] if norm_name(b["name"]) == norm_name(ex.get("beneficiary"))), None)
    if not rate or not ben or ben["currency"] != ex["currency"]:
        return None
    usd_cap = min(rules["max_per_payment_usd"], rules["approval_threshold_usd"], rules["period_budget_usd"] - state["spent_usd"])
    v = _down(min(usd_cap / rate, ben["agreed_amount"] * (1 + rules["amount_tolerance_pct"] / 100)))
    for _ in range(6):
        if v > 0 and _run(dict(ex, amount=v), meta, rules, state)["decision"] == PAY:
            return v
        v = round(v - 0.01, 2)
    return None


def explain(ex, meta, rules, state, res):
    """state: el estado ANTES de decidir esta factura. Devuelve None si ya se pagó o no hay nada que decir."""
    if res["decision"] == PAY:
        return None
    try:
        failed = {c["name"]: c for c in res["checks"] if not c["ok"]}
        changes, all_apply = [], []
        for name, text, apply in _fixes(ex, rules, state, res, failed):
            r = copy.deepcopy(rules)
            apply(r)
            changes.append({"text": text, "verified": _passes(_run(ex, meta, r, state), name)})
            all_apply.append(apply)
        pays = None
        if all_apply:
            r = copy.deepcopy(rules)
            for apply in all_apply:
                apply(r)
            pays = _run(ex, meta, r, state)["decision"] == PAY
        top = _max_amount(ex, meta, rules, state, failed)
        return {"rule_changes": changes, "pays_with_rule_changes": pays, "other": _others(failed, ex),
                "max_amount": None if top is None else {"currency": ex["currency"], "amount": top}}
    except (KeyError, TypeError, ValueError, ZeroDivisionError, StopIteration):
        return None
