"""Motor de decisión: PAGAR / FRENAR / ESCALAR. Determinista, sin LLM.

Regla de oro: PAY solo si TODAS las verificaciones pasan. Cualquier falla baja la
decisión a ESCALATE (una persona decide) o BLOCK (no se paga), y se registra por qué.
"""
import re
import unicodedata
from datetime import date

PAY, ESCALATE, BLOCK = "PAY", "ESCALATE", "BLOCK"
SEVERITY = {PAY: 0, ESCALATE: 1, BLOCK: 2}


def norm_name(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).casefold()
    return re.sub(r"[^a-z0-9]", "", s)


def norm_inv(s):
    """'px 0231', 'PX-0231' y 'PX-231' son la misma factura."""
    c = re.sub(r"[^A-Z0-9]", "", (s or "").upper())
    m = re.fullmatch(r"([A-Z]*)(\d+)", c)
    return m.group(1) + str(int(m.group(2))) if m else c


def new_state():
    return {"spent_usd": 0.0, "seen": {}}


def usd(amount, currency, rules):
    rate = rules["fx_to_usd"].get(currency)
    return None if rate is None else round(amount * rate, 2)


def evaluate(ex, rules, state, meta=None):
    """ex: datos extraídos; meta: cómo se leyeron. Devuelve {decision, checks, reason, amount_usd}."""
    checks = []
    meta = meta or {}

    def check(name, ok, detail, on_fail):
        checks.append({"name": name, "ok": ok, "detail": detail, "on_fail": None if ok else on_fail})

    problems = ["Dos lecturas distintas: " + c for c in meta.get("conflicts", [])]
    if meta.get("ambiguous"):
        problems.append("El documento trae valores contradictorios en: %s." % ", ".join(meta["ambiguous"]))
    if meta.get("error"):
        problems.append(meta["error"])
    check("Lectura confiable", not problems,
          "Las lecturas coinciden y el documento no se contradice." if not problems else " ".join(problems),
          ESCALATE)

    missing = [k for k in ("beneficiary", "amount", "currency", "due_date") if not ex.get(k)]
    check(
        "Datos completos", not missing,
        "Se extrajo beneficiario, monto, moneda y vencimiento." if not missing
        else "No se pudo leer con certeza: %s." % ", ".join(missing),
        ESCALATE,
    )
    amount_usd = None
    if not missing:
        amount_usd = usd(ex["amount"], ex["currency"], rules)
        check(
            "Moneda soportada", amount_usd is not None,
            "%s convertida a USD: %.2f." % (ex["currency"], amount_usd or 0) if amount_usd is not None
            else "La moneda %s no está configurada en las reglas." % ex["currency"],
            ESCALATE,
        )

    # Duplicados: mismo número de factura; sin número, mismo beneficiario+monto+moneda+vencimiento.
    if ex.get("beneficiary"):
        who = norm_name(ex["beneficiary"])
        num = ("num", who, norm_inv(ex["invoice_number"])) if ex.get("invoice_number") else None
        amt = ("amt", who, ex["amount"], ex["currency"], ex["due_date"]) if not missing else None
        # Con número de factura se compara por número (los cobros fijos mensuales traen otro número);
        # sin número, por beneficiario+monto+moneda+vencimiento.
        to_check = [num] if num else [amt]
        dup = next((state["seen"][k] for k in to_check if k and k in state["seen"]), None)
        check("Sin duplicado", dup is None,
              "No coincide con ninguna factura anterior." if dup is None
              else "Ya se recibió antes (%s)." % dup, BLOCK)
        for k in (num, amt):  # se registran ambas para atrapar reenvíos con o sin número
            if k:
                state["seen"].setdefault(k, ex.get("invoice_number") or "misma combinación de datos")

    if amount_usd is not None:
        cap = rules["max_per_payment_usd"]
        check("Límite por pago", amount_usd <= cap,
              "USD %.2f ≤ límite USD %.2f." % (amount_usd, cap) if amount_usd <= cap
              else "USD %.2f supera el límite duro por pago de USD %.2f." % (amount_usd, cap), BLOCK)

        ben = next((b for b in rules["allowed_beneficiaries"]
                    if norm_name(b["name"]) == norm_name(ex["beneficiary"])), None)
        check("Beneficiario permitido", ben is not None,
              "%s está en la lista permitida." % ben["name"] if ben
              else "%s no está en la lista de beneficiarios permitidos." % ex["beneficiary"], ESCALATE)

        if ben:
            tol = rules["amount_tolerance_pct"] / 100
            same_cur = ben["currency"] == ex["currency"]
            gap = abs(ex["amount"] - ben["agreed_amount"]) / ben["agreed_amount"]
            ok = same_cur and gap <= tol + 1e-9  # evita fallar por redondeo justo en el borde
            check("Coincide con lo acordado", ok,
                  "Monto acordado %s %s; la factura está dentro de ±%s%%." % (
                      f"{ben['agreed_amount']:,.0f}", ben["currency"], rules["amount_tolerance_pct"]) if ok
                  else ("Se acordó en %s, la factura viene en %s." % (ben["currency"], ex["currency"]) if not same_cur
                        else "Se acordó %s %s y la factura cobra %s (%+.2f%%)." % (
                            f"{ben['agreed_amount']:,.0f}", ben["currency"], f"{ex['amount']:,.0f}",
                            (ex["amount"] / ben["agreed_amount"] - 1) * 100)),
                  ESCALATE)

        thr = rules["approval_threshold_usd"]
        check("Aprobación humana por monto", amount_usd <= thr,
              "USD %.2f no pasa el umbral de aprobación (USD %.2f)." % (amount_usd, thr) if amount_usd <= thr
              else "USD %.2f supera el umbral de USD %.2f: requiere aprobación humana." % (amount_usd, thr),
              ESCALATE)

        left = rules["period_budget_usd"] - state["spent_usd"]
        check("Presupuesto del periodo", amount_usd <= left,
              "Quedan USD %.2f del periodo; esta factura usa USD %.2f." % (left, amount_usd) if amount_usd <= left
              else "Solo quedan USD %.2f del presupuesto y esta factura necesita USD %.2f." % (left, amount_usd),
              ESCALATE)

    if ex.get("due_date"):
        days = (date.fromisoformat(rules["as_of"]) - date.fromisoformat(ex["due_date"])).days
        limit = rules["max_days_overdue"]
        check("Vencimiento", days <= limit,
              "Vence %s, dentro del plazo." % ex["due_date"] if days <= 0
              else ("Vencida hace %d días (tolerancia %d)." % (days, limit)), ESCALATE)

    failed = [c for c in checks if not c["ok"]]
    decision = max((c["on_fail"] for c in failed), key=SEVERITY.get, default=PAY)
    if decision == PAY:
        state["spent_usd"] = round(state["spent_usd"] + amount_usd, 2)
    reason = " ".join(c["detail"] for c in failed) if failed else "Cumple todas las reglas de la empresa."
    return {"decision": decision, "checks": checks, "reason": reason, "amount_usd": amount_usd}


def assert_safe(results):
    """Invariante de seguridad: ningún PAY con una verificación fallida."""
    for r in results:
        if r["decision"] == PAY:
            assert all(c["ok"] for c in r["checks"]), "pago aprobado fuera de las reglas: %s" % r["file"]
