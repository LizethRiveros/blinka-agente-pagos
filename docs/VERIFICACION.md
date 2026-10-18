# Cómo verificar este proyecto (guía para el mentor)

Todo se puede comprobar en menos de 10 minutos, sin instalar nada más que Python 3.10+. Los datos son ficticios y no se mueve dinero real.

## 1. Las pruebas pasan (1 min)

```
python -m unittest discover -s tests
```
Esperado: `Ran 33 tests ... OK`.

## 2. Medición contra la verdad conocida (1 min)

```
python scripts/eval.py
```
Esperado (lector por reglas, sin clave de API):
- 36 documentos evaluados, decisiones correctas 100 %, **pagos fuera de reglas: 0**.
- Autonomía 53 %: las 4 facturas que solo puede leer Claude (2 fotos y 2 textos libres) se **escalan a una persona** en vez de adivinarse.

`data/expected.json` guarda la decisión y los campos verdaderos de cada factura, y solo se usa para medir.

## 3. Mirar la pantalla (3 min)

```
python server.py
```
Abre http://localhost:8765. Comprueba:
1. Arriba están las **reglas de la empresa**, editables (límite por pago, umbral de aprobación, presupuesto, tolerancia, vencimiento, tipos de cambio y beneficiarios).
2. Pulsa *Procesar facturas*. Cada factura muestra su decisión (pagar, frenar o escalar), **las verificaciones** y el motivo en palabras. Las escaladas tienen botones *Aprobar pago* / *Rechazar* para la persona, y esa revisión también queda registrada.
3. Cambia una regla (por ejemplo `approval_threshold_usd` a 500), pulsa *Guardar reglas* y vuelve a pulsar *Procesar facturas*: las decisiones cambian según la nueva regla.

## 4. Intentar romperlo (3 min)

Casos trampa incluidos en `data/invoices/` (el número es el prefijo del archivo):
| Archivo | Trampa | Decisión esperada |
|---|---|---|
| 06 | recordatorio de una factura ya recibida | frenar (duplicado) |
| 07 | beneficiario nuevo | escalar |
| 08, 13 | monto distinto a lo acordado | escalar |
| 11 | monto enorme | frenar (límite duro) |
| 16 | factura vencida | escalar |
| 17 | texto que ordena un pago urgente | escalar (no obedece la instrucción) |
| 21 / 22 | USD 2000.00 / 2000.01 (borde del umbral) | paga / escala |
| 23 / 24 | +2,00 % / +2,02 % (borde de tolerancia) | paga / escala |
| 18 | Estudio Pixel (Colombia) pide pagar por SPEI (ruta de México) | escalar (ruta no permitida) |
| 19 | CloudHost pide pagar en USDC (stablecoin) | escalar (ruta no permitida) |
| 25 | número de factura de otro proveedor | no es duplicado |
| 29 | moneda no configurada (JPY) | escalar |
| 32 | totales contradictorios en el mismo documento | escalar |
| 91 | presupuesto agotado | escalar |

Para probar uno nuevo, crea un `.txt` en `data/invoices/` con líneas como `Proveedor:`, `Total a pagar:`, `Vence:` y pulsa *Procesar facturas*.

## 5. Las pruebas de verdad detectan errores (opcional)

Las pruebas se validaron con **mutaciones**: se rompió el motor a propósito de 6 formas (umbral, tolerancia, duplicados, presupuesto, normalización, "pagar todo") y cada una hizo fallar al menos una prueba. Eso destapó un error real de redondeo: una factura de USD 489,60 (+2,00 % exacto) se habría escalado por error. Para repetirlo, cambia en `blinka/engine.py` por ejemplo `<= thr` por `< thr` y corre las pruebas: deben fallar.

## 6. Con Claude como segundo lector (necesita clave)

```
$env:ANTHROPIC_API_KEY = Read-Host "Clave"   # solo en esa ventana
python scripts/eval.py --claude
```
Con la clave, Claude lee también las fotos y el texto libre, y solo se paga si **ambos lectores coinciden**. **Este resultado aún no se ha medido con la API**; ver "Lo que está medido y lo que no" en el README.

## Lo que está verificado y lo que no
- ✔ El motor de reglas: determinista, 33 pruebas, mutaciones, bordes exactos, invariante `assert_safe` (nunca hay un PAGAR con una verificación fallida).
- ✔ Las 4 facturas que solo lee Claude, leídas a mano por Claude Code durante el desarrollo y pasadas por el motor: las 4 decisiones salieron correctas (3 pagar, 1 escalar). **Es una comprobación manual, no la autonomía del agente.**
- ✘ Autonomía del agente con Claude vía API: pendiente.
- ✘ Facturas del mundo real: todo es ficticio y escrito por el mismo autor del lector, así que el 100 % del lector por reglas prueba el motor, no que el lector entienda facturas reales.
