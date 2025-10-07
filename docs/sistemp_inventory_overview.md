# Resumen del inventario de Sistemp

## Vendedores registrados
- **Archivo origen:** `sistemp/Integrasistemp/temporal/vendedores_temp.DBF`
- **Total de registros:** 1
- **Detalle:** Código `0022` corresponde a `EDWIN ALVAREZ` (ID interno 62).

| ID_VENDEDO | COD_VENDE | FULLNAME      |
|-----------:|-----------|---------------|
|        62  | 0022      | EDWIN ALVAREZ |

## Ventas relacionadas con vendedores
- **Archivo origen:** `sistemp/Integrasistemp/temporal/ventas_temp.DBF`
- **Total de movimientos:** 600
- **Campos relevantes:** `COD_VENDE`, `FULLNAME`, `ID_VENDEDO` muestran la relación entre ventas y el vendedor `0022 - EDWIN ALVAREZ`.

| COMPRO_NO | F_MOV      | COD_VENDE | FULLNAME      | COD_FICHA | NOM_FICHA                                              | COD_ITEM           | ITEM                                         |
|-----------|------------|-----------|---------------|-----------|--------------------------------------------------------|--------------------|----------------------------------------------|
| CF-000620 | 2025-03-11 | 0022      | EDWIN ALVAREZ | 2767270   | FARMACIA BETANIA, SOCIEDAD ANONIMA DE CAPITAL VARIABLE | BROMURODEIPATROPIO | BROMURO DE IPATROPIO 200 DOSIS  PHAR-INTER   |

## Categorías de catálogo y posibles distribuidores
- **Archivo origen:** `sistemp/Integrasistemp/temporal/catalogoTemp.DBF`
- **Total de categorías únicas:** 77
- **Indicios de distribuidores:** Se identifica al menos una categoría con el término "Distribuidora": `DISZASA DISTRIBUIDORA`.
