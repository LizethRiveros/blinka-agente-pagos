# Explicación del diseño

## El problema
El reto Blinka pide un agente que revise cuentas por pagar, decida cuáles pagar dentro de las reglas de la empresa y pida permiso a una persona cuando algo se sale. Se evalúa **autonomía** (cuánto decide bien solo), **seguridad** (cero pagos fuera de reglas; uno solo descalifica) y **explicabilidad**.

## Decisión de diseño central: el modelo lee, el código decide
Un modelo de lenguaje puede equivocarse con total seguridad o ser engañado por el texto de una factura. Por eso:

1. **Leer** (`blinka/extract.py`) extrae cinco datos: beneficiario, monto, moneda, vencimiento y número de factura.
2. **Decidir** (`blinka/engine.py`) es código determinista, sin modelo. Pagar solo ocurre si **todas las verificaciones pasan**.
3. **Registrar** (`output/ledger.jsonl`) guarda cada decisión y cada revisión humana con su motivo, encadenadas por hash.

Así, aunque la lectura falle, lo peor que ocurre es una escalada a una persona, no un pago indebido. Hay además una invariante en el código (`assert_safe`): detiene el lote si algún pago se aprobó con una verificación fallida.

## Las verificaciones y qué pasa si fallan
| Verificación | Si falla |
|---|---|
| Lectura confiable (lectores coinciden, el documento no se contradice) | escalar |
| Datos completos | escalar |
| Moneda soportada | escalar |
| Sin duplicado | frenar |
| Límite duro por pago | frenar |
| Beneficiario permitido | escalar |
| Ruta de pago permitida (solo si la factura indica una: SPEI, Bre-B, ACH, SWIFT, USDC...) | escalar |
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
Cada factura en la pantalla muestra sus verificaciones con su detalle y el motivo en lenguaje corriente (por ejemplo: "Se acordó 4,800,000 COP y la factura cobra 7,200,000 (+50.00%)"). No hace falta abrir el código.

## Qué dejamos fuera a propósito (lo pide el reto)
Pagos reales, abrir cuentas, verificar identidad de empresas, cumplimiento y fraude, y el diseño de la app de Blinka.

## Límites conocidos
- Tipos de cambio fijos y simulados en `data/rules.json`.
- Duplicados: por número de factura normalizado; sin número, por beneficiario + monto + moneda + vencimiento. Un duplicado con número distinto y datos iguales pasa, porque se asume un cobro legítimo (por ejemplo, un cobro fijo mensual).
- Datos ficticios escritos por el mismo autor del lector: miden el motor, no la comprensión de facturas reales.

## Bordes que se probaron a propósito
USD 2000.00 paga y 2000.01 escala. +2,00 % paga y +2,02 % escala. Con la prueba de mutaciones, esto destapó un error de redondeo real que ya está corregido.

## Cómo se demuestra la seguridad (no solo se afirma)

### Atacante automático (`blinka/redteam.py`)
- Genera reglas aleatorias y, para cada una, facturas pegadas a los bordes: monto igual al límite, límite más 1 centavo, tolerancia exacta, presupuesto casi agotado, duplicados con otro formato de número, beneficiarios nuevos, monedas no configuradas, rutas de pago no permitidas, lecturas en conflicto y errores de lector.
- El **verificador independiente** (`blinka/oracle.py`) reescribe cada regla como especificación (sin importar nada del motor, con `Decimal`). Si el motor dice PAGAR y el verificador dice que no, eso es un pago indebido.
- También cuenta las **escalaciones de más** (el motor se niega a lo que el verificador permitiría): hoy 0, lo que indica que ambos coinciden en los dos sentidos.
- **Texto hostil**: se agregan órdenes («ignora las reglas...») y datos falsos al final de una factura; la decisión nunca puede volverse más permisiva.
- **Prueba de la prueba (mutantes)**: se copia el motor con 10 errores inyectados a propósito y se exige que el atacante los detecte todos. Si no los detectara, su «0 pagos indebidos» no valdría nada. Esto ya sirvió: la primera versión del atacante dejaba pasar 3 mutantes (los de «+1 USD» y «+1 centavo»), porque sus facturas no llegaban a esos bordes; se rediseñó el generador para fijar lo acordado de un proveedor justo en el borde.
- Es determinista para una semilla: `python scripts/redteam.py 5000 2026` repite exactamente lo mismo.

### Explicación contrafactual (`blinka/counterfactual.py`)
Para cada factura no pagada calcula los cambios de reglas que destrabarían cada verificación fallida, y **comprueba cada uno volviendo a correr el motor** con la regla modificada. También calcula el monto máximo con el que se pagaría hoy. Los duplicados, las lecturas dudosas y los datos faltantes no tienen cambio de regla posible y se explican como tales.

### Registro encadenado y reproducible (`blinka/ledger.py`)
- Cada entrada incluye `prev` (hash de la anterior) y `hash = SHA-256(prev + contenido)`. Lleva el hash del documento, las reglas completas del lote, lo leído y la decisión.
- `verify` recalcula la cadena: detecta ediciones, borrados e inserciones en el medio.
- `replay` repite cada decisión con el motor y compara. Detecta incluso a quien recalcule toda la cadena (la decisión falsificada no se reproduce) y avisa si un documento cambió desde que se decidió.
- No relee documentos (eso podría requerir un modelo): reproduce la **decisión** a partir de lo leído, que queda registrado.
- Límite: borrar las últimas líneas no rompe la cadena; el sello final de cada lote sirve para cotejar.

### Simulador (`/api/simulate`)
Vuelve a decidir con lo ya leído usando las reglas propuestas, sin releer ni registrar, y lista qué decisiones cambiarían.
