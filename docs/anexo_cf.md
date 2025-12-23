## Anexo II – Consumidor Final (F-07 v14)

- **Agrupación**: 1 fila por día y tipo de DTE (01/02/10/11). Ordena los DTE del día por `fecEmi` + `horEmi` (si falta hora se usa 00:00) y usa el **primer** y **último** `codigoGeneracion` como Del/Al.
- **Campos fijos para DTE (clase 4)**: Resolución/Serie/Control Interno → `N/A`. Máquina registradora → vacío.
- **Rangos Del/Al**: se generan a partir de los códigos ordenados; no dependen del orden de lectura de archivos.
- **Renta (U/V)**:
  - Periodos `< 2025-01`: siempre `0`.
  - Periodos `>= 2025-01`: no se permiten `0`. Si el DTE no trae valores, se aplican defaults configurables en `datos_negocio.json` → `anexos_cf`:  
    - `renta_tipo_operacion_default` (default `1`, usar `2` si todas las ventas del día son exentas/no sujetas).  
    - `renta_tipo_ingreso_default` (default `3`).  
    - `strict_renta_fields` (default `false`): si es `true` y faltan valores válidos se bloquea la exportación.
- **Delimitador CSV**: por defecto `;`. Se puede ajustar con `anexos_cf.csv_delimiter`.
- **Validaciones previas**: 23 columnas exactas, longitudes <= 100, campos obligatorios no vacíos, `N/A` en campos fijos de DTE y máquina vacía.
- **Previsualización**: usa las filas ya agregadas del anexo (1 por día/tipo). Muestra el rango `Del–Al`, cantidad de DTE y rango de hora (inicio–fin) derivado de los códigos ordenados.
