# analytics_predictive

Estructura base aislada para analitica predictiva de compras y ventas.

Principios de esta fase:
1. Sin modificar flujos transaccionales existentes.
2. Solo lectura de datos para analitica.
3. Sin dependencias pesadas.
4. Integracion minima y controlada en fases posteriores.

Capas:
1. data: repositorio read-only y modelos.
2. forecast: metodos predictivos livianos.
3. recommendations: reglas de compra y alertas.
4. presentation: base de UI para futura pestana.
5. config: parametros simples del modulo.
