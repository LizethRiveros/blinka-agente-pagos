# Agente de pagos (reto Blinka)

Un agente que lee facturas (texto, PDF o foto), decide si **pagar, frenar o escalar a una persona** según las reglas de la empresa, y deja registrado por qué. No mueve dinero real.

**Idea central:** el modelo nunca decide. Solo *lee*. La decisión la toma un motor de reglas determinista, y el agente solo paga si **todas** las verificaciones pasan y, cuando hay dos lectores, **ambos coinciden**.

## Para quien lo revise

- [`docs/VERIFICACION.md`](docs/VERIFICACION.md): cómo comprobarlo todo en 10 minutos, con los casos trampa y qué decisión se espera de cada uno.
- [`docs/EXPLICACION.md`](docs/EXPLICACION.md): el diseño en detalle (por qué el modelo solo lee y el código decide).
- [`docs/GUION_DEMO.md`](docs/GUION_DEMO.md): guion del video de demo.

**Comprobación manual de las 4 facturas que solo lee Claude:** durante el desarrollo, Claude Code leyó a mano esas 4 (2 fotos y 2 textos libres) y se pasaron por el motor: las 4 decisiones salieron correctas (3 pagar, 1 escalar). Es una comprobación manual, no la autonomía del agente con la API, que sigue pendiente de medir.

## Cómo correrlo

```
python server.py                        # http://localhost:8765  (PORT=… para otro puerto)
python -m unittest discover -s tests    # 24 pruebas
python scripts/eval.py                  # mide al agente contra la verdad conocida
python scripts/eval.py --claude         # además, con Claude (necesita ANTHROPIC_API_KEY en el entorno)
```

Solo Python estándar (3.10+), sin instalar nada. Pillow se usa únicamente para *generar* las fotos de prueba, que ya vienen incluidas. `PyMuPDF` es opcional para leer PDFs más complejos.

## Cómo está pensado

1. **Leer** (`blinka/extract.py`). Cadena de lectura:
   - Texto o PDF con texto → lector por reglas, sin dependencias (incluye PDFs comprimidos).
   - Con `ANTHROPIC_API_KEY` → Claude lee también, y es el único que lee fotos y escaneos (los recibe directamente, sin OCR local).
   - Si los dos lectores **no coinciden**, o el documento trae **totales contradictorios**, se escala. Si nada se puede leer, se escala. Un `$` suelto no se interpreta como moneda.
   - El documento se trata como dato, nunca como instrucción.
2. **Decidir** (`blinka/engine.py`). 10 verificaciones: lectura confiable, datos completos, moneda soportada, duplicado, límite duro por pago, beneficiario permitido, coincide con lo acordado, umbral de aprobación humana, presupuesto del periodo y vencimiento. Todo lo que falla baja a `ESCALAR` (decide una persona) o `FRENAR`.
3. **Registrar** (`output/decisions.jsonl`): cada decisión y cada revisión humana, con su motivo. En la pantalla, cada factura muestra sus verificaciones y el documento original.

## Lo que se midió

38 facturas ficticias en `data/invoices/`: correo, chat, comprobante peruano con IGV, hilo con totales contradictorios, texto libre, 4 PDF y 2 fotos. Incluyen trampas: duplicado (con otro formato de número y sin número), mismo número de otro proveedor, beneficiario nuevo, moneda distinta a la acordada, moneda no configurada, inyección de instrucciones, vencida, presupuesto agotado y **bordes exactos** (USD 2000.00 paga y 2000.01 escala; +2,00% paga y +2,02% escala).

Resultado con el **lector por reglas** (`python scripts/eval.py`): 34 documentos evaluados, decisiones correctas 34/34, **0 pagos fuera de reglas** (sobre los 38). Los 4 documentos restantes (2 fotos y 2 textos sin etiquetas) solo los puede leer Claude: sin clave se escalan a una persona y no cuentan en el acierto.

> **Ojo con este número:** el lector por reglas y las facturas de prueba los escribí yo, así que ese 34/34 es una prueba de que el motor funciona, no de que el lector entienda facturas del mundo real. Ese es el motivo de existir de la lectura con Claude y del cruce de dos lectores. Los resultados con Claude **aún no se han medido**: `python scripts/eval.py --claude` los produce.

Las pruebas se validaron también con *mutaciones*: se rompió el motor a propósito de 6 formas (umbral, tolerancia, duplicados, presupuesto, normalización, pagar todo) y cada una hizo fallar alguna prueba. Eso destapó un error real de redondeo: una factura de USD 489,60 (+2,00% exacto) se habría escalado por error.

## Datos

Todo ficticio (empresa, proveedores, RUC). `scripts/gen_invoices.py` regenera las facturas y `data/expected.json` guarda la decisión y los campos verdaderos de cada una, solo para medir.

## Límites conocidos

- Tipos de cambio fijos en `data/rules.json` (simulados).
- Duplicados: por número de factura normalizado; sin número, por beneficiario+monto+moneda+vencimiento.
- Un duplicado con número *distinto* y mismos datos pasa: se asume cobro legítimo (p. ej. un cobro fijo mensual).
- El lector sin Claude no entiende texto libre ni fotos; las escala.
- Cumplimiento, fraude y verificación de identidad quedan fuera, como pide el reto.
