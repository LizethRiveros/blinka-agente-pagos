# Especificación en lenguaje normal: cuándo se puede pagar una factura

Este texto está escrito para que **otra IA (Gemini) o una persona** programe un verificador sin ver el código del motor. Si el verificador de Gemini y el motor discrepan, hay un malentendido de la regla (o un hueco en este texto) y se corrige aquí.

## Datos de entrada
**Reglas de la empresa** (`rules`, un diccionario):
- `fx_to_usd`: tasa para convertir cada moneda a USD (`{"COP": 0.00025, "USD": 1, ...}`).
- `max_per_payment_usd`, `approval_threshold_usd`, `period_budget_usd`: números en USD.
- `amount_tolerance_pct`: porcentaje de tolerancia sobre lo acordado.
- `max_days_overdue`: días de atraso tolerados.
- `as_of`: fecha de hoy (`"AAAA-MM-DD"`).
- `allowed_beneficiaries`: lista de `{name, currency, agreed_amount, rails}` (`rails` puede venir vacía).

**Factura leída** (`ex`, un diccionario; cualquier campo puede ser `None`):
`beneficiary`, `amount` (número), `currency` (ej. `"USD"`), `due_date` (`"AAAA-MM-DD"`), `invoice_number`, `payment_rail` (ej. `"SPEI"`, `"SWIFT"`, `"USDC on Base"`).

**Calidad de la lectura** (`meta`, un diccionario): `conflicts` (lista, no vacía si dos lectores leyeron distinto), `ambiguous` (lista, no vacía si el documento trae totales contradictorios), `error` (texto o `None`).

## Cuándo una factura se puede pagar
Se puede pagar **solo si ninguna** de estas condiciones se cumple. Cada una que se cumpla es una «razón para no pagar»:

1. **Lectura no confiable:** `conflicts`, `ambiguous` o `error` traen algo.
2. **Datos incompletos:** falta beneficiario, monto, moneda o vencimiento.
3. **Duplicado:** ya se vio antes una factura del mismo beneficiario con el mismo número (ignorando mayúsculas, tildes, espacios, guiones y ceros a la izquierda: `PX-0231` = `px 231`); o, si no tiene número, con el mismo beneficiario, monto, moneda y vencimiento. El nombre del beneficiario se compara ignorando mayúsculas, tildes y signos (`Estudio Pixel S.A.S.` = `estudio pixel sas`). Toda factura que se evalúa cuenta como «vista» desde ese momento, se pague o no.
4. **Moneda no configurada:** la moneda no está en `fx_to_usd`.
5. **Sobre el límite duro:** monto en USD **mayor que** `max_per_payment_usd` (igual al límite sí pasa).
6. **Sobre el umbral de aprobación humana:** monto en USD **mayor que** `approval_threshold_usd` (igual sí pasa: 2000.00 paga, 2000.01 no).
7. **Sin presupuesto:** monto en USD **mayor que** lo que queda del presupuesto, es decir `period_budget_usd` menos lo ya pagado en este periodo (igual a lo que queda sí pasa).
8. **Beneficiario no permitido:** el nombre (comparado como en el punto 3) no está en `allowed_beneficiaries`.
9. **Distinto de lo acordado:** el beneficiario existe pero la moneda de la factura no es la acordada, o el monto se aparta de `agreed_amount` en **más** de `amount_tolerance_pct` por ciento (diferencia absoluta dividida entre lo acordado). Justo en la tolerancia sí pasa (+2,00 % con tolerancia 2 paga; +2,02 % no).
10. **Ruta de pago no permitida:** la factura indica una `payment_rail`, el beneficiario tiene `rails` no vacía y la ruta (comparada ignorando mayúsculas y signos; `USDC`, `USDT` y `stablecoin` cuentan como la misma ruta «USDC»; `Bre-B` = `BREB`) no está entre las del beneficiario. Si la factura no indica ruta, no aplica.
11. **Vencida:** `as_of` menos `due_date` (en días) es **mayor que** `max_days_overdue`.

## Convertir a USD
`monto × fx_to_usd[moneda]`, redondeado a centavos (2 decimales, mitad al par). Usar aritmética decimal exacta, no `float`.

## Lo ya pagado
Cuando se paga una factura, su monto en USD se suma a lo gastado del periodo y reduce el presupuesto disponible para las siguientes. Las facturas no pagadas no gastan presupuesto.

## Qué debe hacer el verificador
Dar, para cada factura, la lista de razones para no pagar (vacía = pagar está permitido). No decide pagar ni escalar: solo dice si pagar **estaría permitido**.
