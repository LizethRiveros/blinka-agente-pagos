# Explicación del diseño

## El problema
El reto Blinka pide un agente que revise cuentas por pagar, decida cuáles pagar dentro de las reglas de la empresa y pida permiso a una persona cuando algo se sale. Se evalúa **autonomía** (cuánto decide bien solo), **seguridad** (cero pagos fuera de reglas; uno solo descalifica) y **explicabilidad**.

## Decisión de diseño central: el modelo lee, el código decide
Un modelo de lenguaje puede equivocarse con total seguridad o ser engañado por el texto de una factura. Por eso:

1. **Leer** (`blinka/extract.py`) extrae cinco datos: beneficiario, monto, moneda, vencimiento y número de factura.
2. **Decidir** (`blinka/engine.py`) es código determinista, sin modelo. Pagar solo ocurre si **las 10 verificaciones pasan**.
3. **Registrar** (`output/decisions.jsonl`) guarda cada decisión y cada revisión humana con su motivo.

Así, aunque la lectura falle, lo peor que ocurre es una escalada a una persona, no un pago indebido. Hay además una invariante en el código (`assert_safe`): detiene el lote si algún pago se aprobó con una verificación fallida.

## Las 10 verificaciones y qué pasa si fallan
| Verificación | Si falla |
|---|---|
| Lectura confiable (lectores coinciden, el documento no se contradice) | escalar |
| Datos completos | escalar |
| Moneda soportada | escalar |
| Sin duplicado | frenar |
| Límite duro por pago | frenar |
| Beneficiario permitido | escalar |
| Coincide con lo acordado (±tolerancia) | escalar |
| Aprobación humana por monto | escalar |
| Presupuesto del periodo | escalar |
| Vencimiento | escalar |

La decisión final es la más severa de las fallas (frenar > escalar > pagar).

## Dos lectores y la regla de coincidencia
- Lector por reglas: sin dependencias, lee texto y PDFs con texto (incluye comprimidos).
- Lector Claude (opcional, con `ANTHROPIC_API_KEY`): lee también fotos, escaneos y texto libre, enviándolos directamente al modelo.
- Si ambos leen distinto, o el documento trae totales contradictorios, **se escala**. Si nada se puede leer, se escala.
- El documento se trata como **dato**, nunca como instrucción: la factura 17 intenta ordenar un pago urgente y no tiene efecto.

## Explicabilidad
Cada factura en la pantalla muestra sus 10 verificaciones con su detalle y el motivo en lenguaje corriente (por ejemplo: "Se acordó 4,800,000 COP y la factura cobra 7,200,000 (+50.00%)"). No hace falta abrir el código.

## Qué dejamos fuera a propósito (lo pide el reto)
Pagos reales, abrir cuentas, verificar identidad de empresas, cumplimiento y fraude, y el diseño de la app de Blinka.

## Límites conocidos
- Tipos de cambio fijos y simulados en `data/rules.json`.
- Duplicados: por número de factura normalizado; sin número, por beneficiario + monto + moneda + vencimiento. Un duplicado con número distinto y datos iguales pasa, porque se asume un cobro legítimo (por ejemplo, un cobro fijo mensual).
- Datos ficticios escritos por el mismo autor del lector: miden el motor, no la comprensión de facturas reales.

## Bordes que se probaron a propósito
USD 2000.00 paga y 2000.01 escala. +2,00 % paga y +2,02 % escala. Con la prueba de mutaciones, esto destapó un error de redondeo real que ya está corregido.
