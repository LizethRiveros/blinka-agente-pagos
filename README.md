# Wallqui: agente de pagos (reto Blinka)

Un agente que lee facturas (texto, PDF o foto), decide si **pagar, frenar o escalar a una persona** según las reglas de la empresa, y deja registrado por qué. No mueve dinero real.

**Idea central:** el modelo nunca decide. Solo *lee*. La decisión la toma un motor de reglas determinista, y el agente solo paga si **todas** las verificaciones pasan y, cuando hay dos lectores, **ambos coinciden**.

## Para quien lo revise

- [`docs/VERIFICACION.md`](docs/VERIFICACION.md): cómo comprobarlo todo en 10 minutos, con los casos trampa y qué decisión se espera de cada uno.
- [`docs/EXPLICACION.md`](docs/EXPLICACION.md): el diseño en detalle (por qué el modelo solo lee y el código decide).
- [`docs/PITCH.md`](docs/PITCH.md): pitch con lo que se dice y el clic de cada paso (`http://localhost:8765/?demo=1` lo guía en pantalla).
- [`docs/PARA_REVISORES.md`](docs/PARA_REVISORES.md): qué pidieron, qué entregamos y qué feedback buscamos.
- [`docs/GUION_DEMO.md`](docs/GUION_DEMO.md): guion del video de demo.

**Las 2 fotos las lee el OCR local; los 2 textos libres sin etiquetas solo una IA.** Durante el desarrollo, Claude Code leyó a mano esos textos y se pasaron por el motor: las decisiones salieron correctas. Es una comprobación manual, no la autonomía del agente con la API, que sigue pendiente de medir.

## Cómo correrlo

```
python server.py                        # http://localhost:8765  (PORT=… para otro puerto)
python -m unittest discover -s tests    # 43 pruebas
python scripts/eval.py                  # mide al agente contra la verdad conocida
python scripts/redteam.py               # atacante: 5000 facturas hostiles, busca UN pago indebido
python scripts/replay.py                # verifica la cadena del registro y reproduce cada decisión
python scripts/eval.py --claude         # además, con Claude (necesita ANTHROPIC_API_KEY en el entorno)
python scripts/eval.py --gemini         # alternativa: con Gemini (GEMINI_API_KEY de Google AI Studio, no la suscripción de la app)
```

Solo Python estándar (3.10+), sin instalar nada. Pillow se usa únicamente para *generar* las fotos de prueba, que ya vienen incluidas. `PyMuPDF` es opcional para leer PDFs más complejos.

## Lo que lo distingue: se puede probar, entender y auditar

Casi todo agente de pagos muestra «mira qué bien lee». Aquí el reto central es otro: **un solo pago indebido descalifica**, y eso no se demuestra con 40 facturas hechas a mano.

1. **Atacante automático** (`python scripts/redteam.py`, o el botón «Atacar al agente»). Lanza miles de facturas hostiles (montos pegados a cada borde, duplicados disfrazados, rutas no permitidas, monedas raras, lecturas en conflicto) contra reglas aleatorias, y un **verificador independiente** (`blinka/oracle.py`; no comparte código con el motor y usa aritmética exacta) comprueba que el motor nunca pague lo que la especificación prohíbe. Con la semilla 2026: **5000 facturas, 125 juegos de reglas, 0 pagos indebidos**. Además prueba que el atacante tiene dientes: se inyectan 10 errores a propósito al motor (un límite 1 USD más holgado, un umbral 1 centavo más alto, ignorar duplicados...) y **el atacante detecta los 10**. Esa prueba de la prueba destapó, mientras se construía, que el atacante original no veía 3 de ellos; se corrigió.
2. **Explicación contrafactual.** Cada factura no pagada dice **qué tendría que cambiar para que se pague** («subir la tolerancia a 50 %», «con las reglas de hoy se pagaría si el monto fuera de COP 4.896.000 o menos»). Cada propuesta se **verifica volviendo a correr el motor**; no es una opinión. Se muestra como información, no como recomendación.
3. **Registro encadenado y reproducible** (`blinka/ledger.py`). Cada decisión guarda el hash de la factura, las reglas vigentes, lo leído y el hash de la entrada anterior. Editar o borrar una línea rompe la cadena (`python scripts/replay.py`). Y como el motor es determinista, **cualquiera puede repetir cada decisión desde el registro y obtener exactamente lo mismo**: aun quien recalcule toda la cadena para falsificar una decisión queda en evidencia, porque esa decisión ya no se reproduce. Un agente cuyo juicio es un modelo no puede ofrecer esto.
4. **Simulador de reglas.** Antes de guardar un cambio, muestra qué decisiones cambiarían (incluidos los efectos en cadena por presupuesto).

Honestidad: el verificador independiente lo escribió el mismo autor que el motor, así que cubre errores de implementación, no un malentendido de la regla misma. El registro detecta alteraciones del medio, pero quien borre las últimas líneas no rompe la cadena; por eso cada lote tiene un sello (hash final) que conviene copiar aparte.

## Novedades

- **Exportar CSV** (botón en la pantalla): una fila por factura con la decisión, la revisión humana y el motivo, para conciliar qué se pagó y por qué. Las celdas que empiezan con `=`, `+`, `-` o `@` se neutralizan para que una factura maliciosa no inyecte fórmulas en Excel.
- **Más monedas** con tipos de cambio simulados: BRL, CLP, BOB, CRC y ZAR, además de USD, EUR, COP, MXN, PEN y ARS.
- **Ruta de pago por beneficiario** (SPEI, Bre-B, ACH, WIRE, SWIFT, LOCAL...): si una factura pide pagar por una ruta que ese proveedor no tiene permitida, por ejemplo una stablecoin (USDC), se escala a una persona.

## Cómo está pensado

1. **Leer** (`blinka/extract.py`). Cadena de lectura:
   - Texto o PDF con texto → lector por reglas, sin dependencias (incluye PDFs comprimidos).
   - Con `GEMINI_API_KEY` (y sin clave de Claude) → Gemini lee también, con el mismo contrato de solo lectura.
   - Fotos → OCR local con Tesseract (gratis, sin enviar nada a internet), y luego el mismo lector por reglas. Sin OCR ni IA, una foto se escala.
   - Con `ANTHROPIC_API_KEY` → Claude lee también, y además lee escaneos y texto libre sin etiquetas (los recibe directamente).
   - Si los dos lectores **no coinciden**, o el documento trae **totales contradictorios**, se escala. Si nada se puede leer, se escala. Un `$` suelto no se interpreta como moneda.
   - El documento se trata como dato, nunca como instrucción.
2. **Decidir** (`blinka/engine.py`). 11 verificaciones (la de ruta de pago solo aplica si la factura indica una): lectura confiable, datos completos, moneda soportada, duplicado, límite duro por pago, beneficiario permitido, ruta de pago permitida, coincide con lo acordado, umbral de aprobación humana, presupuesto del periodo y vencimiento. Todo lo que falla baja a `ESCALAR` (decide una persona) o `FRENAR`.
3. **Registrar** (`output/ledger.jsonl`): cada decisión y cada revisión humana, con su motivo, en un registro encadenado por hash (ver arriba). En la pantalla, cada factura muestra sus verificaciones y el documento original.

## Lo que se midió

40 facturas ficticias en `data/invoices/`: correo, chat, comprobante peruano con IGV, hilo con totales contradictorios, texto libre, 4 PDF y 2 fotos. Incluyen trampas: duplicado (con otro formato de número y sin número), mismo número de otro proveedor, beneficiario nuevo, moneda distinta a la acordada, moneda no configurada, inyección de instrucciones, vencida, presupuesto agotado y **bordes exactos** (USD 2000.00 paga y 2000.01 escala; +2,00% paga y +2,02% escala).

Resultado con el **lector por reglas + OCR local** (`python scripts/eval.py`): 38 documentos evaluados, decisiones correctas 38/38, **0 pagos fuera de reglas**. Los 2 documentos restantes (textos libres sin etiquetas) solo los puede leer una IA: sin ella se escalan a una persona y no cuentan en el acierto.

> **Ojo con este número:** el lector, el OCR y las facturas de prueba (fotos limpias, hechas por mí) son míos, así que ese 38/38 es una prueba de que el motor funciona, no de que la lectura aguante escaneos reales manchados. Ese es el motivo de existir de la lectura con IA y del cruce de dos lectores. Los resultados con IA por API **aún no se han medido**: `python scripts/eval.py --claude` o `--gemini` los producen.

Las pruebas se validaron también con *mutaciones*: se rompió el motor a propósito de 6 formas (umbral, tolerancia, duplicados, presupuesto, normalización, pagar todo) y cada una hizo fallar alguna prueba. Eso destapó un error real de redondeo: una factura de USD 489,60 (+2,00% exacto) se habría escalado por error.

## Datos

Todo ficticio (empresa, proveedores, RUC). `scripts/gen_invoices.py` regenera las facturas y `data/expected.json` guarda la decisión y los campos verdaderos de cada una, solo para medir.

## Límites conocidos

- Tipos de cambio fijos en `data/rules.json` (simulados).
- Duplicados: por número de factura normalizado; sin número, por beneficiario+monto+moneda+vencimiento.
- Un duplicado con número *distinto* y mismos datos pasa: se asume cobro legítimo (p. ej. un cobro fijo mensual).
- Las fotos se leen con OCR local (Tesseract, gratis, si está instalado; si no, se escalan). El texto libre sin etiquetas solo lo entiende una IA; sin ella se escala.
- Cumplimiento, fraude y verificación de identidad quedan fuera, como pide el reto.
