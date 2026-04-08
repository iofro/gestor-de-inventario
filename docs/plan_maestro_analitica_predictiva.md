# Plan maestro funcional y tecnico
## Modulo de analitica predictiva de compras y ventas (IA basica y liviana)

## 1. Objetivo de negocio y alcance
### 1.1 Objetivo general
Implementar un modulo de analitica predictiva que permita al dueno del negocio tomar decisiones de compra e inventario con base en datos historicos reales, usando metodos estadisticos simples, explicables y de bajo consumo de recursos.

### 1.2 Objetivos especificos
1. Predecir demanda por producto para horizontes de 7, 15 y 30 dias.
2. Recomendar cantidades de compra por producto con explicacion legible.
3. Detectar riesgo de quiebre, sobrestock y baja rotacion.
4. Priorizar productos por impacto (ventas, margen, criticidad).
5. Presentar resultados en una pestana nueva sin alterar flujos actuales.

### 1.3 Alcance funcional
Incluye:
1. Extraccion read-only de ventas, compras, inventario y catalogos auxiliares.
2. Normalizacion de datos para analitica diaria por producto.
3. Motor predictivo basico y liviano.
4. Reglas de negocio para recomendaciones de compra.
5. UI en pestana nueva con resumen ejecutivo y tablas accionables.
6. Parametrizacion de horizontes, umbrales y nivel de servicio.

No incluye en esta fase:
1. Auto-compra o ejecucion automatica de ordenes.
2. Modelos de ML pesados o dependencias complejas.
3. Cambios en estructura transaccional de ventas/facturacion.
4. Cambios en flujos de envio DTE o correo.

## 2. No alcance
1. No se modificara la logica de registro de ventas, compras, facturacion ni inventario.
2. No se reemplazaran reportes actuales de estados de cuenta.
3. No se creara integracion con ERP externo o proveedores en linea.
4. No se implementaran pronosticos por clima, eventos externos o web scraping.
5. No se forzaran cambios de base de datos que pongan en riesgo compatibilidad.

## 3. KPIs exactos
Todos los KPIs deben calcularse por periodo y permitir filtro por horizonte.

### 3.1 KPI de demanda y precision
1. Demanda diaria promedio por producto:
   Demanda_promedio = suma(unidades vendidas en ventana) / dias de ventana
2. Pronostico por horizonte H:
   Pronostico_H = unidades estimadas para H dias
3. Error absoluto medio (MAE):
   MAE = promedio(|real - pronosticado|)
4. Error porcentual absoluto medio (MAPE, con proteccion de cero):
   MAPE = promedio(|real - pronosticado| / max(real, 1)) * 100

### 3.2 KPI de inventario
1. Cobertura en dias:
   Cobertura_dias = stock_actual / max(demanda_promedio_diaria, epsilon)
2. Punto de reorden (ROP):
   ROP = demanda_promedio_diaria * lead_time_dias + stock_seguridad
3. Stock de seguridad:
   Stock_seguridad = z * desviacion_demanda_diaria * raiz(lead_time_dias)
4. Riesgo de quiebre en dias:
   Dias_quiebre = stock_actual / max(demanda_promedio_diaria, epsilon)

### 3.3 KPI de compra sugerida
1. Demanda esperada al horizonte H:
   Demanda_H = demanda_promedio_diaria * H
2. Compra sugerida:
   Compra_sugerida = max(0, Demanda_H + stock_seguridad - stock_actual - stock_en_transito)
3. Inversion sugerida:
   Inversion_sugerida = Compra_sugerida * costo_unitario_referencia

### 3.4 KPI de rentabilidad y prioridad
1. Margen unitario:
   Margen_unitario = precio_venta_referencia - costo_unitario_referencia
2. Contribucion total:
   Contribucion = unidades_vendidas_periodo * margen_unitario
3. Clasificacion ABC por contribucion acumulada:
   A: hasta 80%
   B: 80% a 95%
   C: 95% a 100%

## 4. Formulas exactas de pronostico y reposicion
## 4.1 Preparacion de serie
1. Granularidad diaria por producto.
2. Dias sin venta se imputan con 0 (no se eliminan).
3. Ventana base recomendada: 28 dias.
4. Si historial < 7 dias, usar fallback simple.

## 4.2 Metodo 1: Promedio movil ponderado (WMA)
Para n dias y pesos w_i, con suma(w_i)=1:
Pronostico_dia_siguiente = suma(w_i * demanda_t-i)
Pronostico_H = Pronostico_dia_siguiente * H
Pesos por defecto (n=7): [0.30, 0.22, 0.16, 0.12, 0.09, 0.06, 0.05]

## 4.3 Metodo 2: Suavizamiento exponencial simple (SES)
S_t = alpha * X_t + (1 - alpha) * S_t-1
Pronostico_dia_siguiente = S_t
Pronostico_H = S_t * H
Alpha por defecto: 0.35
Rango permitido de ajuste: [0.10, 0.60]

## 4.4 Metodo 3 opcional: Tendencia lineal basica
Modelo lineal por minimos cuadrados sobre serie diaria reciente.
Y = a + b*t
Pronostico_H = suma_{k=1..H} max(0, a + b*(t+k))
Se usa solo si:
1. Historial >= 30 dias
2. Error historico menor que WMA y SES

## 4.5 Seleccion de metodo por producto
1. Evaluar MAE o MAPE en backtest corto (rolling de 7 dias).
2. Elegir metodo con menor error.
3. Si no hay datos suficientes: fallback demanda promedio simple.

## 4.6 Reposicion
Variables:
1. lead_time_dias (LT)
2. demanda_promedio_diaria (D)
3. desviacion_demanda_diaria (sigma)
4. nivel_servicio -> z-score

Formulas:
1. Stock_seguridad = z * sigma * raiz(LT)
2. ROP = D * LT + Stock_seguridad
3. Compra_sugerida_H = max(0, D*H + Stock_seguridad - stock_actual - stock_en_transito)

Niveles de servicio por defecto:
1. Basico: 90% (z=1.28)
2. Normal: 95% (z=1.65)
3. Conservador: 98% (z=2.05)

## 5. Reglas de alertas y semaforos
## 5.1 Alerta de quiebre
Condicion:
1. Cobertura_dias < LT o stock_actual <= 0
Semaforo:
1. Rojo: cobertura < LT
2. Amarillo: cobertura entre LT y LT+2
3. Verde: cobertura > LT+2

## 5.2 Alerta de sobrestock
Condicion:
1. Cobertura_dias > umbral_sobrestock
Umbral por defecto: 45 dias
Semaforo:
1. Rojo: > 60 dias
2. Amarillo: 45 a 60 dias
3. Verde: <= 45 dias

## 5.3 Alerta de producto lento
Condicion:
1. Sin ventas en N dias
2. Stock_actual > 0
N por defecto: 21 dias
Semaforo:
1. Rojo: > 30 dias sin venta
2. Amarillo: 21 a 30 dias
3. Verde: < 21 dias

## 5.4 Alerta de datos insuficientes
Condicion:
1. Historial < 7 dias o datos incompletos
Semaforo:
1. Gris: requiere revision manual

## 6. Entradas de datos requeridas
## 6.1 Datos obligatorios
1. Ventas por fecha, producto, cantidad, precio unitario.
2. Compras por fecha, producto, cantidad, costo unitario.
3. Stock actual por producto.
4. Catalogo de producto (id, nombre, codigo, proveedor/vendedor si aplica).

## 6.2 Datos deseables
1. Lead time por proveedor o por producto.
2. Stock en transito.
3. Criticidad de producto (esencial/no esencial).
4. Presentacion y conversion si existen empaques.

## 6.3 Reglas de calidad de datos
1. Fechas invalidas deben descartarse y registrarse en log.
2. Cantidades o precios negativos deben normalizarse o excluirse segun regla.
3. IDs faltantes deben marcarse como no analizables.
4. Nunca se debe escribir sobre tablas fuente en esta fase.

## 7. Contratos de salida esperados
## 7.1 Contrato de salida por producto (analitica)
Campos minimos:
1. producto_id
2. nombre_producto
3. metodo_pronostico
4. pronostico_7d
5. pronostico_15d
6. pronostico_30d
7. demanda_promedio_diaria
8. desviacion_demanda
9. stock_actual
10. cobertura_dias
11. lead_time_dias
12. stock_seguridad
13. punto_reorden
14. compra_sugerida_7d
15. compra_sugerida_15d
16. compra_sugerida_30d
17. nivel_alerta
18. motivo_alerta
19. explicacion_negocio
20. calidad_dato

## 7.2 Contrato de salida para UI ejecutiva
Bloques:
1. resumen_general
2. comprar_hoy
3. riesgo_quiebre
4. sobrestock
5. productos_lentos
6. top_margen
7. metricas_precision

## 7.3 Reglas de explicabilidad
Cada recomendacion debe incluir texto humano, ejemplo:
"Comprar 35 unidades: demanda 3.2/dia, cobertura 5 dias, lead time 7 dias, nivel de servicio normal."

## 8. Diseno de pestana nueva
Nombre sugerido: Analitica predictiva

## 8.1 Componentes minimos
1. Encabezado con filtros:
   - horizonte (7/15/30)
   - periodo historico (ultimos 30/60/90 dias)
   - nivel de servicio (basico/normal/conservador)
   - boton Actualizar analisis
2. Tarjetas KPI:
   - riesgo de quiebre total
   - inversion sugerida
   - productos en rojo
   - precision promedio
3. Tabla Comprar hoy:
   - producto
   - compra sugerida
   - cobertura actual
   - inversion estimada
   - explicacion
4. Tabla Riesgo de quiebre
5. Tabla Sobrestock
6. Tabla Productos lentos

## 8.2 Comportamiento UX
1. Carga bajo demanda al abrir pestana o al presionar Actualizar.
2. Mensaje claro cuando faltan datos.
3. No bloquear interfaz durante calculos.
4. Mantener consistencia visual con estilo actual.

## 9. Criterios de aceptacion
## 9.1 Funcionales
1. El modulo genera pronosticos para productos con historial minimo.
2. El modulo calcula compra sugerida y punto de reorden.
3. El modulo muestra alertas con semaforo.
4. Las recomendaciones incluyen explicacion legible.
5. La pestana nueva se abre sin afectar pestañas existentes.

## 9.2 No funcionales
1. Tiempo de respuesta objetivo:
   - hasta 10,000 lineas historicas: < 2 segundos en equipo promedio.
2. Consumo de memoria moderado y sin dependencias pesadas.
3. Tolerancia a datos incompletos sin caidas.

## 9.3 Integridad
1. No se alteran ventas, compras, inventario ni facturacion.
2. No se modifican tablas existentes en esta fase.
3. No se altera flujo de envio DTE.

## 10. Plan de pruebas
## 10.1 Pruebas unitarias
1. Formula WMA.
2. Formula SES.
3. Formula stock de seguridad y ROP.
4. Compra sugerida con casos borde.

## 10.2 Pruebas de integracion
1. Extraccion de ventas y compras con filtros de fecha.
2. Construccion de serie diaria por producto.
3. Manejo de productos sin historial.

## 10.3 Pruebas funcionales UI
1. Carga de pestana.
2. Actualizacion de analisis.
3. Visualizacion de tablas y semaforos.
4. Mensajes de error controlados.

## 10.4 Pruebas de no regresion
1. Venta normal sigue operando.
2. Compra normal sigue operando.
3. Facturacion y DTE siguen operando.
4. Navegacion de pestañas existentes sin cambios inesperados.

## 11. Riesgos y mitigaciones
## 11.1 Riesgos altos
1. Editar carpeta duplicada en lugar de ruta activa.
   Mitigacion: trabajar solo sobre la raiz activa confirmada al inicio de cada fase.
2. Desalinear indices del sidebar al agregar nueva pestana.
   Mitigacion: actualizar mapping de indices y orden canonico en el mismo cambio controlado.
3. Congelar UI por calculo en hilo principal.
   Mitigacion: calculo diferido y/o worker de fondo con timeout de UI.

## 11.2 Riesgos medios
1. Datos sin lead time explicito.
   Mitigacion: parametro manual por defecto y soporte de ajuste por producto/proveedor.
2. Consultas repetitivas con alto volumen.
   Mitigacion: agregaciones por lote y cache temporal de resultados.
3. Formatos de fecha heterogeneos.
   Mitigacion: normalizador central de fechas con log de descartes.

## 11.3 Riesgos bajos
1. Falta de datos para algunos productos.
   Mitigacion: estado "datos insuficientes" y recomendacion manual.

## 12. Plan de despliegue gradual
## 12.1 Fase A - Documentacion y arquitectura
1. Aprobacion del presente documento.
2. Definicion de parametros iniciales.

## 12.2 Fase B - Capa de datos y motor
1. Implementar extraccion read-only.
2. Implementar pronostico y reglas.
3. Validar con datos reales.

## 12.3 Fase C - UI nueva en beta interna
1. Activar pestana para pruebas internas.
2. Medir tiempos y precision.
3. Ajustar umbrales.

## 12.4 Fase D - Produccion controlada
1. Activacion para usuarios administradores.
2. Seguimiento semanal de precision y decisiones tomadas.
3. Retroalimentacion y mejora continua.

## 13. Parametros iniciales recomendados
1. Ventana historica base: 28 dias.
2. Horizonte por defecto: 15 dias.
3. Nivel de servicio por defecto: normal (95%).
4. Umbral producto lento: 21 dias.
5. Umbral sobrestock: 45 dias.
6. Epsilon para division segura: 0.01.

## 14. Definicion de listo (Definition of Done)
1. Existe pestana nueva de analitica predictiva.
2. Se muestran recomendaciones accionables con explicacion.
3. No hay regresiones en flujos existentes.
4. Se ejecutan pruebas unitarias, integracion y no regresion con resultado satisfactorio.
5. Se entrega guia de uso para dueno.

---
Documento base para implementacion controlada del modulo predictivo.
Cualquier cambio de formulas o reglas debe versionarse con fecha y justificacion de negocio.
