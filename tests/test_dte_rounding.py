import pytest
from utils.monto import D, d8, d2, iva_item
from dte import calcular_resumen


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

    resumen = calcular_resumen(venta, {'total': venta + iva}, fiscal={'iva': iva})

    assert f"{d2(resumen['totalGravada']):.2f}" == '23.85'
    assert f"{d2(resumen['totalIva']):.2f}" == '3.10'
    assert f"{d2(resumen['totalPagar']):.2f}" == '26.95'

    for key in ['totalGravada', 'totalIva', 'totalPagar']:
        assert decimal_places(resumen[key]) <= 2
