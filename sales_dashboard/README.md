# Panel de Estadísticas de Venta

Aplicación de escritorio construida con PyQt5 que resume las métricas claves de ventas,
productos y canales para que cualquier persona pueda entender el estado del negocio en
menos de cinco segundos.

## Requisitos

1. Crear (y activar) un entorno virtual de Python 3.11 o superior.
2. Instalar las dependencias:

```bash
pip install -r requirements.txt
```

> El archivo `requirements.txt` se encuentra en la raíz del repositorio y
> comparte dependencias con el resto del proyecto.

## Ejecución

Desde la raíz del repositorio:

```bash
python -m sales_dashboard.main sales_dashboard/sample_data.csv
```

Argumentos disponibles:

- `dataset` (opcional): Ruta al CSV con los datos de ventas. Por defecto se
  utiliza `sales_dashboard/sample_data.csv`.
- `--timezone`: Texto a mostrar junto a la barra de filtros.

## Contenido de la pantalla

- **Barra de filtros fija** con selección por día, mes, año o período
  personalizado y botón "Aplicar" que solo se habilita al detectar cambios.
- **Tarjetas de KPIs** con tooltips y textos de apoyo: ventas, transacciones,
  ticket promedio, margen bruto y CMV estimado.
- **Tendencia diaria** con barras de transacciones y línea de ventas. El cursor
  muestra fecha, ventas, transacciones y ticket promedio del día.
- **Top productos** con tabla ordenable y gráfico de barras horizontal.
- **Ventas por canal/vendedor** con tabla y gráfico de pastel (agrupa canales
  menores a 3% en "Otros").
- **Reporte financiero** con tabla de ingresos, gastos y resultado del período
  además de gráfico comparativo de ingresos vs gastos.
- **Stock crítico** con tabla y estado vacío cuando no hay alertas.
- **Estados vacíos y mensajes** claros ante ausencia de datos.

## Dataset de ejemplo

`sales_dashboard/sample_data.csv` es un dataset sintético reproducible. El
rango del **10/03/2025 al 16/03/2025** contiene 34 transacciones, ventas por
$122.48 y un ticket promedio de $3.60 para las pruebas de QA.

## Pruebas automatizadas

```bash
pytest sales_dashboard/tests
```

## Empaquetado

La aplicación puede generarse como ejecutable autónomo usando
[PyInstaller](https://pyinstaller.org/). Ejemplo rápido:

```bash
pyinstaller --name "estadisticas_venta" --windowed sales_dashboard/main.py
```

El binario quedará disponible en `dist/estadisticas_venta/`. Ajusta los
parámetros (icono, recursos adicionales) según tus necesidades.
