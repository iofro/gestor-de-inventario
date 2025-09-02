import pytest
from utils.monto import D, d8, d2, iva_item
from dte import calcular_resumen, normalizar_pagos


def decimal_places(value):
    exp = D(str(value)).as_tuple().exponent
    return -exp if exp < 0 else 0


def test_item_and_total_rounding():
    cantidad = D('2.5')
    precio = D('9.54')

    venta = d8(cantidad * precio)
    assert str(venta) == '23.85000000'
    assert decimal_places(venta) <= 8

    iva = iva_item(venta)
    assert str(iva) == '3.10050000'
    assert decimal_places(iva) <= 8

    resumen = calcular_resumen(
        venta,
        {'total': venta + iva},
        fiscal={'iva': iva},
        extra={"precios_incluyen_iva": False},
        tipo_dte="03",
    )

    assert f"{d2(resumen['totalGravada']):.2f}" == '23.85'
    assert f"{d2(resumen['totalIva']):.2f}" == '3.10'
    assert f"{d2(resumen['totalPagar']):.2f}" == '26.95'

    for key in ['totalIva', 'totalPagar']:
        assert decimal_places(resumen[key]) <= 2
    assert decimal_places(resumen['totalGravada']) <= 2


def test_pagos_rounding_adjusts_last_payment():
    pagos = [
        {"codigo": "01", "montoPago": 5.005},
        {"codigo": "02", "montoPago": 5.005},
    ]
    total = D("10.01")
    norm = normalizar_pagos(pagos, total)
    suma = sum(p["montoPago"] for p in norm)
    assert suma == total
    assert norm[-1]["montoPago"] == D("5.00")
