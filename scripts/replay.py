"""Audita el registro de decisiones: verifica la cadena de hashes y reproduce cada decisión.

  python scripts/replay.py                       # output/ledger.jsonl
  python scripts/replay.py ruta/a/ledger.jsonl

Sale con código 1 si la cadena está rota o alguna decisión no se reproduce.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from blinka import ledger, runner

path = sys.argv[1] if len(sys.argv) > 1 else runner.LEDGER
v = ledger.verify(path)
if not v["ok"]:
    print("CADENA ROTA en la entrada %s: %s" % (v["bad_at"], v["problem"]))
    sys.exit(1)
print("Cadena íntegra: %d entradas. Sello final: %s" % (v["entries"], v["head"]))

rp = ledger.replay(path, os.path.join(runner.DATA, "invoices"))
print("Decisiones reproducidas desde lo registrado: %d" % rp["replayed"])
for w in rp["warnings"]:
    print("  aviso: " + w)
for m in rp["mismatches"]:
    print("  NO SE REPRODUCE: entrada %(seq)s, %(file)s: registrada %(registrada)s, reproducida %(reproducida)s" % m)
print("RESULTADO: " + ("OK, ninguna discrepancia" if not rp["mismatches"] else "FALLA"))
sys.exit(1 if rp["mismatches"] else 0)
