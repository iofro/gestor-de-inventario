from decimal import Decimal as D
import pytest
from dte import recalcular_totales


def _build_payload(items, nit="06141990011019"):
    return {
        "identificacion": {"tipoDte": "03"},
        "receptor": {"nit": nit},
        "cuerpoDocumento": items,
        "resumen": {"pagos": [{"codigo": "01", "montoPago": D("0")}]} ,
    }


def test_ccf_totals_with_inclusive_prices():
    items = [
        {"numItem": 1, "descripcion": "A", "cantidad": D("1"), "precioUni": D("0.05"), "montoDescu": D("0")},
        {"numItem": 2, "descripcion": "B", "cantidad": D("1"), "precioUni": D("0.05"), "montoDescu": D("0")},
    ]
    payload = _build_payload(items)
    recalcular_totales(payload)
    item1, item2 = payload["cuerpoDocumento"]
    resumen = payload["resumen"]
    assert item1["ventaGravada"] == D("0.05")
    assert item2["ventaGravada"] == D("0.04")
    assert resumen["totalGravada"] == D("0.09")
    assert resumen["montoTotalOperacion"] == D("0.10")
    assert resumen["totalPagar"] == D("0.10")
    assert resumen["tributos"][0]["codigo"] == "20"
    assert resumen["tributos"][0]["valor"] == D("0.01")
    assert "totalIva" not in resumen
    assert resumen["pagos"][0]["montoPago"] == D("0.10")


def test_ccf_nit_validation():
    items = [{"numItem": 1, "descripcion": "A", "cantidad": D("1"), "precioUni": D("1"), "montoDescu": D("0")}]
    payload = _build_payload(items, nit="123")
    with pytest.raises(ValueError):
        recalcular_totales(payload)
