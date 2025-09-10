from decimal import Decimal as D
import pytest

from dte import recalcular_totales, money


def _build_payload(items, nit="06141990011019"):
    return {
        "identificacion": {"tipoDte": "03"},
        "receptor": {"nit": nit},
        "cuerpoDocumento": items,
        "resumen": {"pagos": [{"codigo": "01", "montoPago": D("0")}]} ,
    }


def test_ccf_totals_with_inclusive_prices():
    items = [
        {"numItem": 1, "descripcion": "A", "cantidad": D("1"), "precioUni": D("0.044"), "montoDescu": D("0")},
        {"numItem": 2, "descripcion": "B", "cantidad": D("1"), "precioUni": D("0.044"), "montoDescu": D("0")},
    ]
    payload = _build_payload(items)
    recalcular_totales(payload)
    item1, item2 = payload["cuerpoDocumento"]
    resumen = payload["resumen"]
    assert item1["ventaGravada"] == D("0.0440")
    assert item2["ventaGravada"] == D("0.0460")
    assert resumen["totalGravada"] == D("0.0900")
    assert resumen["montoTotalOperacion"] == D("0.10")
    assert resumen["totalPagar"] == D("0.10")
    assert resumen["tributos"][0]["codigo"] == "20"
    assert resumen["tributos"][0]["valor"] == D("0.01")
    assert "totalIva" not in resumen
    assert resumen["pagos"][0]["montoPago"] == D("0.10")
def test_ccf_descuento_no_permitido():
    items = [
        {
            "numItem": 1,
            "descripcion": "A",
            "cantidad": D("1"),
            "precioUni": D("10.00"),
            "montoDescu": D("2.00"),
        }
    ]
    payload = _build_payload(items)
    recalcular_totales(payload)
    item = payload["cuerpoDocumento"][0]
    resumen = payload["resumen"]
    assert item["precioUni"] == D("8.00")
    assert item["montoDescu"] == D("0")
    assert item["ventaGravada"] == D("8.00")
    assert resumen["subTotalVentas"] == D("8.00")
    assert resumen["subTotal"] == D("8.00")
    assert resumen["totalDescu"] == D("0")
    assert resumen["porcentajeDescuento"] == D("0")
    assert resumen["totalGravada"] == D("8.00")
    assert resumen["montoTotalOperacion"] == D("9.04")
    assert resumen["pagos"][0]["montoPago"] == D("9.04")


def test_ccf_descuento_un_por_ciento():
    items = [
        {
            "numItem": 1,
            "descripcion": "A",
            "cantidad": D("1"),
            "precioUni": D("100.00"),
            "montoDescu": D("1.00"),
        }
    ]
    payload = _build_payload(items)
    recalcular_totales(payload)
    item = payload["cuerpoDocumento"][0]
    resumen = payload["resumen"]
    assert item["precioUni"] == D("99.00")
    assert item["montoDescu"] == D("1.00")
    assert resumen["totalDescu"] == D("1.00")
    assert resumen["porcentajeDescuento"] == D("1.00")
    assert resumen["tributos"][0]["valor"] == D("12.87")
    assert resumen["totalPagar"] == D("111.87")


def test_ccf_descuento_colapsado_consistente():
    items = [
        {
            "numItem": 1,
            "descripcion": "A",
            "cantidad": D("1"),
            "precioUni": D("15.04"),
            "montoDescu": D("0.75"),
        }
    ]
    payload = _build_payload(items)
    recalcular_totales(payload)
    item = payload["cuerpoDocumento"][0]
    resumen = payload["resumen"]
    assert item["precioUni"] == D("14.29")
    assert item["montoDescu"] == D("0")
    assert item["ventaGravada"] == D("14.29")
    assert resumen["subTotalVentas"] == D("14.29")
    assert resumen["subTotal"] == D("14.29")
    assert resumen["totalGravada"] == D("14.29")
    assert resumen["totalDescu"] == D("0")
    assert resumen["porcentajeDescuento"] == D("0")
    assert resumen["montoTotalOperacion"] == D("16.15")
    assert resumen["pagos"][0]["montoPago"] == D("16.15")


def test_ccf_precio_7_96_iva_redondeo():
    items = [
        {
            "numItem": 1,
            "descripcion": "A",
            "cantidad": D("1"),
            "precioUni": D("7.96"),
            "montoDescu": D("0"),
        }
    ]
    payload = _build_payload(items)
    recalcular_totales(payload)
    resumen = payload["resumen"]
    assert resumen["tributos"][0]["valor"] == D("1.03")
    assert resumen["montoTotalOperacion"] == D("8.99")


def test_ccf_nit_validation():
    items = [{"numItem": 1, "descripcion": "A", "cantidad": D("1"), "precioUni": D("1"), "montoDescu": D("0")}]
    payload = _build_payload(items, nit="123")
    with pytest.raises(ValueError):
        recalcular_totales(payload)
