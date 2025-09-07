from decimal import Decimal as D
import pytest

from dte import recalcular_totales


def _build_payload(tipo):
    return {
        "identificacion": {"tipoDte": tipo},
        "receptor": {"nit": "06141990011019"},
        "cuerpoDocumento": [
            {
                "numItem": 1,
                "descripcion": "A",
                "cantidad": D("1"),
                "precioUni": D("10"),
                "montoDescu": D("0"),
            }
        ],
        "resumen": {},
    }


@pytest.mark.parametrize("tipo", ["05", "06"])
def test_nota_base_iva(tipo):
    payload = _build_payload(tipo)
    recalcular_totales(payload)
    item = payload["cuerpoDocumento"][0]
    resumen = payload["resumen"]
    assert item["ventaGravada"] == D("8.85")
    assert resumen["totalGravada"] == D("8.85")
    iva = resumen["tributos"][0]["valor"]
    assert iva == D("1.15")
    assert resumen["montoTotalOperacion"] == D("10.00")
