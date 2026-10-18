"""Verificador independiente: la especificación de «cuándo se puede pagar», escrita aparte del motor.

No importa nada de engine.py (ni sus normalizadores): reescribe cada regla con otro código y aritmética
exacta (Decimal). El atacante (redteam.py) comprueba que el motor NUNCA pague algo que este
verificador prohíbe. Limitación honesta: lo escribió el mismo autor que el motor, así que cubre
errores de implementación, no un malentendido de la regla misma.
"""
import re
import unicodedata
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal

CENT = Decimal("0.01")


def _alnum(s):
    s = unicodedata.normalize("NFD", s or "")
    return re.sub(r"[^a-z0-9]", "", "".join(c for c in s if unicodedata.category(c) != "Mn").lower())


def _invoice_key(s):
    m = re.fullmatch(r"([A-Z]*)0*(\d+)", re.sub(r"[^A-Z0-9]", "", (s or "").upper()))
    return (m.group(1), m.group(2)) if m else re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def _rail(s):
    t = re.sub(r"[^A-Z0-9]", "", (s or "").upper())
    if any(w in t for w in ("USDC", "USDT", "STABLECOIN")):
        return "USDC"
    for w in ("SPEI", "BREB", "SEPA", "PIX", "SWIFT", "ACH", "WIRE"):
        if w in t:
            return w
    return "LOCAL" if ("LOCAL" in t or "TRANSFERENCIA" in t) else t


def usd_of(amount, currency, rules):
    rate = rules["fx_to_usd"].get(currency)
    if rate is None:
        return None
    return (Decimal(repr(amount)) * Decimal(repr(rate))).quantize(CENT, rounding=ROUND_HALF_EVEN)


class Oracle:
    """Lleva su propia contabilidad (lo gastado y lo ya visto) y dice si una factura se puede pagar."""

    def __init__(self, rules):
        self.rules, self.spent, self.seen = rules, Decimal(0), set()

    def violations(self, ex, meta=None):
        """Lista de reglas que impiden pagar; vacía = pagar está permitido. Registra la factura como vista."""
        r, meta, v = self.rules, meta or {}, []
        if meta.get("conflicts") or meta.get("ambiguous") or meta.get("error"):
            v.append("lectura no confiable")
        complete = all(ex.get(k) for k in ("beneficiary", "amount", "currency", "due_date"))
        if not complete:
            v.append("datos incompletos")

        who = _alnum(ex.get("beneficiary") or "")
        keys = []
        if ex.get("beneficiary"):
            if ex.get("invoice_number"):
                keys.append(("num", who, _invoice_key(ex["invoice_number"])))
            if complete:
                keys.append(("amt", who, ex["amount"], ex["currency"], ex["due_date"]))
            probe = keys[0] if ex.get("invoice_number") else (keys[-1] if complete else None)
            if probe in self.seen:
                v.append("duplicado")
            self.seen.update(keys)

        usd = usd_of(ex["amount"], ex["currency"], r) if complete else None
        if complete and usd is None:
            v.append("moneda no configurada")
        if usd is not None:
            ben = next((b for b in r["allowed_beneficiaries"] if _alnum(b["name"]) == who), None)
            if usd > Decimal(repr(r["max_per_payment_usd"])):
                v.append("sobre el límite duro")
            if usd > Decimal(repr(r["approval_threshold_usd"])):
                v.append("sobre el umbral de aprobación")
            if usd > Decimal(repr(r["period_budget_usd"])) - self.spent:
                v.append("sin presupuesto")
            if ben is None:
                v.append("beneficiario no permitido")
            else:
                agreed = Decimal(repr(ben["agreed_amount"]))
                if ben["currency"] != ex["currency"] or \
                        abs(Decimal(repr(ex["amount"])) - agreed) / agreed > Decimal(repr(r["amount_tolerance_pct"])) / 100 + Decimal("1e-9"):
                    v.append("distinto de lo acordado")
                if ben.get("rails") and ex.get("payment_rail") and _rail(ex["payment_rail"]) not in {_rail(x) for x in ben["rails"]}:
                    v.append("ruta de pago no permitida")
        if ex.get("due_date"):
            late = (date.fromisoformat(r["as_of"]) - date.fromisoformat(ex["due_date"])).days
            if late > r["max_days_overdue"]:
                v.append("vencida")
        return v

    def paid(self, ex):
        """Registra un pago hecho (para el presupuesto)."""
        self.spent += usd_of(ex["amount"], ex["currency"], self.rules)
