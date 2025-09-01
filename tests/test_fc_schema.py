import pytest
from svfe.generators import (
    generar_consumidor_final as generar_fc_ejemplo,
    strip_extras,
    validar_contra_schema as validate_against_schema,
)

def test_fc_min_valido():
    dte = generar_fc_ejemplo()
    payload = strip_extras(dte)
    validate_against_schema(payload, "fc")
    item = payload["cuerpoDocumento"][0]
    assert str(item["ventaGravada"]) == "26.95000000"
    assert str(item["ivaItem"]) == "3.10"
    assert str(payload["resumen"]["totalGravada"]) == "26.9500"
    assert str(payload["resumen"]["totalIva"]) == "3.10"
    assert str(payload["resumen"]["totalPagar"]) == "26.95"
