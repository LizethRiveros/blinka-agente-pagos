"""Verificador escrito por Gemini a partir de docs/ESPECIFICACION.md, sin ver el código del motor.

  python scripts/gemini_oracle.py prompt     # SIN API: copia al portapapeles el texto para pegarlo en la app de Gemini
  python scripts/gemini_oracle.py generate   # pide a Gemini el verificador y lo guarda en output/gemini_oracle.py
  python scripts/gemini_oracle.py compare    # corre el atacante usando ESE verificador contra el motor real

Necesita GEMINI_API_KEY (Google AI Studio) en el entorno solo para `generate`.
Antes de `compare`, LEE output/gemini_oracle.py: es código escrito por un modelo y `compare` lo ejecuta.
Un desacuerdo no significa que el motor esté mal: significa que la regla se entendió distinto
(o que la especificación tiene un hueco). Hay que decidir cuál tiene razón y corregir.
"""
import importlib.util
import json
import os
import re
import sys
import urllib.request

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
OUT = os.path.join(ROOT, "output", "gemini_oracle.py")

PROMPT = """Eres un ingeniero que escribe un VERIFICADOR independiente. Lee la especificación y escribe un módulo Python
(solo biblioteca estándar, usa decimal.Decimal para el dinero) con esta interfaz exacta:

    class Oracle:
        def __init__(self, rules): ...            # rules: diccionario descrito en la especificación
        def violations(self, ex, meta=None): ...  # devuelve lista de textos con las razones para no pagar; vacía = permitido
        def paid(self, ex): ...                   # se llama cuando la factura se pagó; actualiza lo gastado

violations() debe registrar la factura como «vista» (para detectar duplicados) cada vez que se llama.
Responde SOLO con el código Python, sin explicaciones ni bloques markdown.

ESPECIFICACIÓN:
"""


def prompt():
    """Sin API: deja el texto completo listo para pegar en la app o web de Gemini (y lo copia al portapapeles en Windows)."""
    with open(os.path.join(ROOT, "docs", "ESPECIFICACION.md"), encoding="utf-8") as f:
        text = PROMPT + f.read()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    path = os.path.join(os.path.dirname(OUT), "prompt_para_gemini.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    try:
        import subprocess
        subprocess.run(["clip"], input=text.encode("utf-16-le"), check=True)
        print("Copiado al portapapeles.")
    except Exception:
        print("No pude copiar al portapapeles; abre el archivo y copia su contenido.")
    print("Texto guardado en %s" % path)
    print("1) Pega en Gemini (gemini.google.com, modelo Pro).  2) Copia SOLO el código que responda.")
    print("3) Guárdalo como %s (el archivo debe empezar en 'import' o 'from', sin ```)." % OUT)
    print("4) Léelo y corre: python scripts/gemini_oracle.py compare")


def generate():
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        sys.exit("Falta GEMINI_API_KEY en el entorno (clave de Google AI Studio; no se imprime ni se guarda).")
    with open(os.path.join(ROOT, "docs", "ESPECIFICACION.md"), encoding="utf-8") as f:
        spec = f.read()
    model = os.environ.get("BLINKA_GEMINI_MODEL", "gemini-2.5-flash")
    body = {"contents": [{"role": "user", "parts": [{"text": PROMPT + spec}]}], "generationConfig": {"temperature": 0}}
    req = urllib.request.Request(
        "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent" % model, json.dumps(body).encode(),
        {"x-goog-api-key": key, "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        text = json.load(r)["candidates"][0]["content"]["parts"][0]["text"]
    code = re.sub(r"^```(?:python)?\s*|\s*```$", "", text.strip())
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("# Generado por Gemini (%s) a partir de docs/ESPECIFICACION.md. REVISAR antes de ejecutar.\n" % model + code + "\n")
    print("Guardado en %s (%d líneas). Léelo y luego corre: python scripts/gemini_oracle.py compare" % (OUT, code.count("\n") + 1))


def compare():
    if not os.path.exists(OUT):
        sys.exit("No existe %s. Corre primero: python scripts/gemini_oracle.py generate" % OUT)
    spec = importlib.util.spec_from_file_location("gemini_oracle", OUT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    from blinka import redteam
    with open(redteam.ROOT_RULES, encoding="utf-8") as f:
        base = json.load(f)
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 5000
    a = redteam.attack(redteam.real_engine, base, n, 2026, oracle_cls=mod.Oracle)
    print("== Verificador de Gemini contra el motor real (%d facturas, %d juegos de reglas)" % (a["invoices"], a["rule_sets"]))
    print("   el motor pagó algo que Gemini prohíbe: %d" % a["unsafe"])
    print("   el motor escaló/frenó algo que Gemini permitiría: %d" % a["over_cautious"])
    print("   caídas del motor: %d" % a["crashes"])
    for e in a["examples"]:
        print("   !! %s -> %s" % (e["problema"], e["caso"]))
    ok = not a["unsafe"] and not a["over_cautious"] and not a["crashes"]
    print("\nRESULTADO: " + ("COINCIDEN: dos escritores independientes entendieron la regla igual."
                              if ok else "DISCREPAN: revisar caso por caso quién entendió mal la regla."))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    {"prompt": prompt, "generate": generate, "compare": compare}.get(cmd, lambda: sys.exit(__doc__))()
