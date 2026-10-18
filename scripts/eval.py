"""Mide al agente contra la verdad conocida de cada factura.

  python scripts/eval.py            # solo lector por reglas (siempre disponible)
  python scripts/eval.py --claude   # además, Claude + reglas (necesita ANTHROPIC_API_KEY en el entorno)
  python scripts/eval.py --gemini   # además, Gemini + reglas (necesita GEMINI_API_KEY de Google AI Studio)

Cada modo corre el lote completo y reporta:
  - decisiones correctas (solo documentos que ese modo puede leer),
  - pagos fuera de reglas (debe ser 0),
  - lecturas correctas por campo.
"""
import os
import sys
from functools import partial

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from blinka import runner
from blinka.engine import norm_inv, norm_name
from blinka.extract import extract_document

FIELDS = ("beneficiary", "amount", "currency", "due_date", "invoice_number")


def same(field, a, b):
    if a is None or b is None:
        return a is b
    if field == "amount":
        return abs(a - b) < 0.01
    if field == "beneficiary":
        return norm_name(a) == norm_name(b)
    if field == "invoice_number":
        return norm_inv(a) == norm_inv(b)
    return a == b


def run(label, use_llm):
    rules, exp = runner.load_rules(), runner.load_expected()
    batch = runner.run_batch(rules, extractor=partial(extract_document, use_llm=use_llm))
    m = runner.summarize(batch, rules)
    ok_field = {f: 0 for f in FIELDS}
    n = 0
    misses = []
    for r in batch["results"]:
        e = exp.get(r["file"])
        if not e:
            continue
        if e.get("needs_claude") and not ({"claude", "ocr", "gemini"} & set(r["reader"]["readers"])):
            continue
        n += 1
        for f in FIELDS:
            if same(f, r["extracted"].get(f), e["fields"][f]):
                ok_field[f] += 1
            else:
                misses.append("   lectura %-30s %-15s leyó %r, era %r" % (r["file"], f, r["extracted"].get(f), e["fields"][f]))
        if r["decision"] != e["expected"]:
            misses.append("   DECISIÓN %-30s dio %s, esperada %s: %s" % (r["file"], r["decision"], e["expected"], r["reason"]))
    print("== %s" % label)
    print("   documentos evaluados: %d  (no evaluados por requerir Claude: %d)" % (n, m["not_evaluated"]))
    print("   decisiones correctas: %.0f%%   autonomía: %.0f%%   pagos fuera de reglas: %d" % (
        m["accuracy"] * 100, m["autonomy"] * 100, m["unsafe_payments"]))
    print("   lectura correcta por campo: " + ", ".join("%s %.0f%%" % (f, 100 * ok_field[f] / n) for f in FIELDS))
    print("\n".join(misses) or "   (sin fallos)")
    return m


if __name__ == "__main__":
    run("Lector por reglas", False)
    if "--claude" in sys.argv:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            sys.exit("\nFalta ANTHROPIC_API_KEY en el entorno (no se imprime ni se guarda).")
        run("Claude + reglas (dos lectores)", True)
    if "--gemini" in sys.argv:
        if not os.environ.get("GEMINI_API_KEY"):
            sys.exit("\nFalta GEMINI_API_KEY en el entorno (clave de Google AI Studio; no se imprime ni se guarda).")
        os.environ.pop("ANTHROPIC_API_KEY", None)  # que el segundo lector sea Gemini, no Claude
        run("Gemini + reglas (dos lectores)", True)
