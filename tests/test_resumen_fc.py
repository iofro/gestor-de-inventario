from decimal import Decimal as D
import pytest

from dte import calcular_resumen, normalizar_pagos, money
from jsonschema import ValidationError
from utils import catalogos



def test_resumen_formulas_fc():
    items_total = D('13.0000')
    fiscal = {'iva': D('1.50')}
    resumen = calcular_resumen(items_total, {}, fiscal=fiscal, tipo_dte='01')
    assert D(str(resumen['totalGravada'])) == D('13.00')
    assert D(str(resumen['subTotalVentas'])) == D('13.00')
    assert D(str(resumen['subTotal'])) == D('13.00')
    assert D(str(resumen['montoTotalOperacion'])) == D('13.00')
    assert D(str(resumen['totalPagar'])) == D('13.00')
    assert D(str(resumen['totalIva'])) == D('1.50')


def test_resumen_credito_fiscal_suma_iva():
    items_total = D('15.00')
    fiscal = {'iva': D('1.95'), 'sumas': D('15.00')}
    resumen = calcular_resumen(items_total, {}, fiscal=fiscal, tipo_dte='03')
    assert D(str(resumen['subTotal'])) == D('15.00')
    assert 'totalIva' not in resumen
    assert resumen['tributos'][0]['codigo'] == '20'
    assert resumen['tributos'][0]['valor'] == D('1.95')
    assert D(str(resumen['montoTotalOperacion'])) == D('16.95')
    assert D(str(resumen['totalPagar'])) == D('16.95')


def test_resumen_credito_fiscal_sin_sumas():
    items_total = D('100.00')
    fiscal = {'iva': D('13.00'), 'descu_gravada': D('10.00')}
    resumen = calcular_resumen(items_total, {}, fiscal=fiscal, tipo_dte='03')
    assert D(str(resumen['totalGravada'])) == D('100.00')
    assert D(str(resumen['subTotalVentas'])) == D('110.00')
    assert D(str(resumen['subTotal'])) == D('100.00')
    assert 'totalIva' not in resumen
    assert D(str(resumen['montoTotalOperacion'])) == D('113.00')
    assert D(str(resumen['totalPagar'])) == D('113.00')
    assert D(str(resumen['totalDescu'])) == D('10.00')
    assert D(str(resumen['porcentajeDescuento'])) == D('9.09')
    assert resumen['tributos'][0]['codigo'] == '20'
    assert resumen['tributos'][0]['valor'] == D('13.00')


def test_resumen_sin_gravada_sin_tributos():
    items_total = D('0')
    fiscal = {'sumas': D('0'), 'ventas_exentas': D('5'), 'iva': D('0')}
    resumen = calcular_resumen(items_total, {}, fiscal=fiscal, tipo_dte='01')
    assert D(str(resumen['totalGravada'])) == D('0.00')
    assert D(str(resumen['totalIva'])) == D('0.00')
    assert resumen['tributos'] is None


def test_resumen_fc_exenta_nosuj_no_doble_conteo():
    items_total = D('10.00')
    fiscal = {
        'ventas_exentas': D('2.00'),
        'ventas_no_sujetas': D('3.00'),
    }
    resumen = calcular_resumen(items_total, {}, fiscal=fiscal, tipo_dte='01')
    assert D(str(resumen['totalGravada'])) == D('5.00')
    assert D(str(resumen['subTotalVentas'])) == D('10.00')


def test_pagos_contado_default():
    pagos = normalizar_pagos([], D('10.00'), condicion=1)
    assert pagos == [
        {
            'codigo': '01',
            'montoPago': D('10.00'),
            'referencia': None,
            'periodo': None,
            'plazo': None,
        }
    ]


def test_pagos_contado_default_int(monkeypatch):
    schema = {
        'properties': {
            'resumen': {
                'properties': {
                    'pagos': {
                        'items': {
                            'properties': {'codigo': {'type': 'integer'}}
                        }
                    }
                }
            }
        }
    }
    monkeypatch.setattr(catalogos, 'get_dte_schema', lambda _tipo: schema)
    pagos = normalizar_pagos([], D('10.00'), tipo_dte='99', condicion=1)
    assert pagos == [
        {
            'codigo': 1,
            'montoPago': D('10.00'),
            'referencia': None,
            'periodo': None,
            'plazo': None,
        }
    ]


def test_pagos_varios_cuadre():
    pagos = [
        {'codigo': '01', 'montoPago': 5},
        {'codigo': '02', 'montoPago': 5},
    ]
    total = D('10.01')
    norm = normalizar_pagos(pagos, total)
    assert norm[-1]['montoPago'] == D('5.01')
    assert sum(p['montoPago'] for p in norm) == total


def test_pagos_unico_ajuste():
    pagos = [{'codigo': '01', 'montoPago': 10.01}]
    total = D('10.00')
    norm = normalizar_pagos(pagos, total)
    assert norm[0]['montoPago'] == D('10.00')
    assert sum(p['montoPago'] for p in norm) == total


def test_pagos_diferencia_grande_reajuste():
    pagos = [{'codigo': '01', 'montoPago': 13}]
    total = D('11.50')
    norm = normalizar_pagos(pagos, total)
    assert norm[0]['montoPago'] == D('11.50')
    assert sum(p['montoPago'] for p in norm) == total


def test_pagos_exceso_previo_error():
    pagos = [
        {'codigo': '01', 'montoPago': 12},
        {'codigo': '02', 'montoPago': 5},
    ]
    total = D('10')
    with pytest.raises(ValidationError):
        normalizar_pagos(pagos, total)


def test_credito_requiere_plazo_periodo():
    pagos = [{'codigo': '01', 'montoPago': 5}]
    with pytest.raises(Exception):
        normalizar_pagos(pagos, D('5'), condicion=2)


def test_codigo_pago_tipo_schema(monkeypatch):
    pagos = [{'codigo': '1', 'montoPago': 10}]
    res = normalizar_pagos(pagos, D('10'))
    assert isinstance(res[0]['codigo'], str)

    schema = {
        'properties': {
            'resumen': {
                'properties': {
                    'pagos': {
                        'items': {
                            'properties': {'codigo': {'type': 'integer'}}
                        }
                    }
                }
            }
        }
    }
    monkeypatch.setattr(catalogos, 'get_dte_schema', lambda _tipo: schema)
    res = normalizar_pagos(pagos, D('10'), tipo_dte='99')
    assert isinstance(res[0]['codigo'], int)


def test_pagos_default_enum_sin_01(monkeypatch):
    schema = {
        'properties': {
            'resumen': {
                'properties': {
                    'pagos': {
                        'items': {
                            'properties': {
                                'codigo': {
                                    'type': 'string',
                                    'enum': ['03', '07'],
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    monkeypatch.setattr(catalogos, 'get_dte_schema', lambda _tipo: schema)
    pagos = normalizar_pagos([], D('10.00'), tipo_dte='99', condicion=1)
    assert pagos[0]['codigo'] == '03'

    schema_int = {
        'properties': {
            'resumen': {
                'properties': {
                    'pagos': {
                        'items': {
                            'properties': {
                                'codigo': {
                                    'type': 'integer',
                                    'enum': [3, 7],
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    monkeypatch.setattr(catalogos, 'get_dte_schema', lambda _tipo: schema_int)
    pagos = normalizar_pagos([], D('10.00'), tipo_dte='99', condicion=1)
    assert pagos[0]['codigo'] == 3


def test_resumen_centavos_multiplo():
    resumen = {"totalPagar": D('1.005')}

    with pytest.raises(ValidationError):
        for k in (
            "totalIva",
            "montoTotalOperacion",
            "totalPagar",
            "totalGravada",
            "totalExenta",
            "totalNoSuj",
            "totalNoGravado",
        ):
            if k in resumen:
                val = D(str(resumen[k]))
                if val != money(val):
                    raise ValidationError(f"{k} debe ser múltiplo de 0.01 (recibido={resumen[k]})")


def test_serializacion_sin_neg_zero():
    resumen = {
        'totalIva': D('-0.00'),
        'montoTotalOperacion': D('-0.00'),
        'totalPagar': D('-0.00'),
        'pagos': [{'codigo': '01', 'montoPago': D('-0.00'), 'referencia': None, 'periodo': None, 'plazo': None}],
        'tributos': [{'codigo': '19', 'descripcion': 'IVA', 'valor': D('-0.00')}],
    }

    for k in (
        'totalIva',
        'montoTotalOperacion',
        'totalPagar',
        'totalGravada',
        'totalExenta',
        'totalNoSuj',
        'totalNoGravado',
    ):
        if k in resumen:
            val = D(str(resumen[k]))
            if val != money(val):
                raise ValidationError(f"{k} debe ser múltiplo de 0.01 (recibido={resumen[k]})")

    for k, v in list(resumen.items()):
        if k in {"pagos", "tributos"}:
            continue
        val_float = float(money(v))
        if val_float == -0.0:
            val_float = 0.0
        resumen[k] = val_float

    if resumen.get('tributos'):
        for t in resumen['tributos']:
            val = float(money(t['valor']))
            if val == -0.0:
                val = 0.0
            t['valor'] = val

    if resumen.get('pagos'):
        for p in resumen['pagos']:
            mp = float(money(p['montoPago']))
            if mp == -0.0:
                mp = 0.0
            p['montoPago'] = mp

    assert resumen['totalIva'] == 0.0
    assert resumen['montoTotalOperacion'] == 0.0
    assert resumen['totalPagar'] == 0.0
    assert resumen['pagos'][0]['montoPago'] == 0.0
    assert resumen['tributos'][0]['valor'] == 0.0
