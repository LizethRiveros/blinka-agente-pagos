"""Atacante automático: busca un pago indebido con miles de facturas hostiles.

  python scripts/redteam.py                 # 5000 facturas, semilla 2026
  python scripts/redteam.py 20000 7         # 20000 facturas, semilla 7

Sale con código 1 si hay un pago indebido, una caída del motor, texto hostil que vuelva más permisiva
una decisión, o un error inyectado que el atacante no detecte.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from blinka import redteam

n = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
seed = int(sys.argv[2]) if len(sys.argv) > 2 else 2026
r = redteam.run_all(n, seed)
a, h = r["attack"], r["hostile_text"]

print("== Atacante contra el motor real (semilla %d)" % seed)
print("   %d facturas hostiles en %d juegos de reglas distintos" % (a["invoices"], a["rule_sets"]))
print("   el motor decidió: %d pagar, %d escalar, %d frenar" % (a["pay"], a["escalate"], a["block"]))
print("   PAGOS INDEBIDOS: %d   caídas del motor: %d   escalaciones de más: %d" % (a["unsafe"], a["crashes"], a["over_cautious"]))
for e in a["examples"]:
    print("   !! %s -> %s" % (e["problema"], e["caso"]))
print("== Texto hostil al final de la factura")
print("   %d probadas, decisiones más permisivas: %d" % (h["tested"], h["more_permissive"]))
print("== Prueba de la prueba: errores inyectados al motor (el atacante debe detectarlos)")
for m in r["mutants"]:
    mark = "detectado" if m["caught"] else ("NO detectado" if m["caught"] is False else "?")
    extra = " (%d pagos indebidos)" % m["unsafe_payments"] if m.get("unsafe_payments") else ""
    print("   %-32s %s%s" % (m["name"], mark, extra))
print("   detectados %d de %d" % (r["mutants_caught"], r["mutants_total"]))

ok = (not a["unsafe"] and not a["crashes"] and not h["more_permissive"] and r["mutants_caught"] == r["mutants_total"])
print("\nRESULTADO: " + ("OK" if ok else "FALLA"))
sys.exit(0 if ok else 1)
