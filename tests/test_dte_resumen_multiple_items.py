import pytest
from decimal import Decimal
from utils.monto import D, d8, iva_item
from dte import calcular_resumen, normalizar_pagos
from jsonschema import ValidationError


def test_calcular_resumen_con_iva_items_y_pagos():
    cant1 = D("2.5")
    precio1 = D("9.54")
    venta1 = d8(cant1 * precio1)
    iva1 = iva_item(venta1)

    cant2 = D("1")
    precio2 = D("4.20")
    venta2 = d8(cant2 * precio2)
    iva2 = iva_item(venta2)

    items_total = venta1 + venta2
    pagos = [
        {"codigo": "01", "montoPago": 20},
        {"codigo": "02", "montoPago": 11.70},
    ]
    extra = {"iva_items": [iva1, iva2], "pagos": pagos}

    resumen = calcular_resumen(items_total, {}, fiscal={}, extra=extra)

    assert resumen["totalIva"] == pytest.approx(3.65)
    assert resumen["montoTotalOperacion"] == pytest.approx(31.70)
    assert resumen["totalPagar"] == pytest.approx(31.70)
    assert resumen["tributos"][0]["valor"] == pytest.approx(3.65)
    assert sum(p["montoPago"] for p in resumen["pagos"]) == pytest.approx(
        resumen["totalPagar"]
    )


def test_normalizar_pagos_excede_total():
    pagos = [
        {"codigo": "01", "montoPago": 5},
        {"codigo": "02", "montoPago": 2},
    ]
    with pytest.raises(ValidationError):
        normalizar_pagos(pagos, Decimal("3"))
