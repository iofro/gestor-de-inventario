from decimal import Decimal as D
import pytest

from dte import calcular_resumen, normalizar_pagos, money
from jsonschema import ValidationError
from utils import catalogos



def test_resumen_formulas_fc():
    items_total = D('23.85000000')
    fiscal = {
        'sumas': D('23.85000000'),
        'ventas_exentas': D('1.22222222'),
        'ventas_no_sujetas': D('2.33333333'),
        'no_gravado': D('0.44444444'),
        'descu_exenta': D('0.11111111'),
        'descu_no_suj': D('0.22222222'),
        'descu_gravada': D('0.33333333'),
        'iva': D('3.10444444'),
    }
    resumen = calcular_resumen(items_total, {}, fiscal=fiscal, extra={})
    assert D(str(resumen['totalNoSuj'])) == D('2.33')
    assert D(str(resumen['totalExenta'])) == D('1.22')
    assert D(str(resumen['totalGravada'])) == D('23.85')
    assert D(str(resumen['subTotalVentas'])) == D('27.40')
    assert D(str(resumen['totalDescu'])) == D('0.66')
    assert D(str(resumen['subTotal'])) == D('26.74')
    assert D(str(resumen['totalNoGravado'])) == D('0.44')
    assert D(str(resumen['montoTotalOperacion'])) == D('30.28')
    assert D(str(resumen['totalPagar'])) == D('30.28')
    assert D(str(resumen['totalIva'])) == D('3.10')


def test_resumen_sin_gravada_sin_tributos():
    items_total = D('0')
    fiscal = {'sumas': D('0'), 'ventas_exentas': D('5'), 'iva': D('0')}
    resumen = calcular_resumen(items_total, {}, fiscal=fiscal, extra={})
    assert D(str(resumen['totalGravada'])) == D('0.00')
    assert D(str(resumen['totalIva'])) == D('0.00')
    assert resumen['tributos'] is None


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
