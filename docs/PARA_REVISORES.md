# Para quien revise este proyecto (3 minutos de lectura)

Gracias por mirarlo. Esto es lo que pedían, lo que entregamos y dónde necesitamos tu crítica.

## Qué pedían (reto Blinka, hackathon 30X)
Un **agente que revise las facturas de una empresa y decida cuáles pagar**, dentro de reglas que la empresa define, y que **pida permiso a una persona** cuando algo se sale. El agente no mueve dinero real: solo **decide (pagar / frenar / escalar), registra y explica**.

Restricciones: ningún dato real; el agente **nunca aprueba un pago fuera de las reglas** sin aprobación humana; cada decisión debe poder explicarse **leyendo el registro, sin abrir el código**.

Cómo lo miden: **autonomía** (cuántas facturas decide bien sin ayuda), **seguridad** (cero pagos indebidos; uno solo descalifica) y **explicabilidad**.

## Qué entregamos
| Pidieron | Qué hicimos |
|---|---|
| Leer factura (a quién, cuánto, moneda, fecha) | Lee texto, PDF, chat y fotos. 40 facturas ficticias, con casos trampa (duplicados, beneficiario nuevo, monto distinto, sobre el límite, sin presupuesto, órdenes escondidas, moneda o ruta no permitida). |
| Reglas configurables | Pantalla para editar límite por pago, presupuesto, umbral de aprobación humana, tolerancia, vencimiento y beneficiarios; con **simulador** de qué cambiaría antes de guardar. |
| Registrar y explicar | Cada decisión con su motivo. Pestaña **Registro** que cuenta cada decisión en lenguaje de finanzas, con sello criptográfico por línea. |
| Seguridad | La IA solo **lee**; un motor de reglas **decide** (sin IA). Un **atacante automático** lanza miles de facturas hostiles: 0 pagos indebidos, y detecta 10 de 10 errores inyectados a propósito. |

Qué es distinto: no pedimos confiar. El agente se puede **atacar**, cada caso trae **qué tendría que cambiar para pagarse** (comprobado por el motor), y el registro se puede **auditar**: hay un botón que intenta falsificar una decisión y muestra cómo la cadena se rompe.

## Cómo probarlo (necesitas Python 3, nada más)
```
git clone https://github.com/LizethRiveros/blinka-agente-pagos
cd blinka-agente-pagos
python server.py        # abre http://localhost:8765
```
Pulsa *Procesar facturas*, abre una fila, pulsa *Atacar al agente*, *Verificar registro* y *Intentar falsificar una decisión*.

## Límites (los decimos nosotros antes que tú)
- Las facturas las escribimos nosotros: miden el motor, no la comprensión de facturas del mundo real.
- La lectura con IA (fotos, texto libre) **aún no está medida**.
- El verificador del atacante lo escribió el mismo autor del motor: cubre errores de programación, no un malentendido de la regla. Estamos pidiendo a otra IA que escriba uno desde `docs/ESPECIFICACION.md` sin ver el código.
- Quien borre las **últimas** líneas del registro no rompe la cadena; el sello final debe guardarse aparte.

## Dónde necesitamos tu feedback
1. En 30 segundos de pantalla, ¿entiendes qué hace el agente y por qué confiarías en él?
2. ¿El **Registro** se entiende sin saber programar? ¿Qué le falta a una persona de finanzas?
3. ¿Qué factura trampa o regla se nos está pasando?
4. ¿La pantalla de reglas es lo bastante simple para una empresa real?
5. Si fueras jurado: ¿qué te haría dudar de la seguridad?
6. ¿Qué quitarías? (Si algo sobra, sobra.)
