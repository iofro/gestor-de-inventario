from decimal import Decimal as D

import pytest

from dte import recalcular_totales
from utils.stable_json import stable_stringify


def _build_payload(precio):
    payload = {
        "identificacion": {"tipoDte": "01"},
        "cuerpoDocumento": [
            {
                "numItem": 1,
                "descripcion": "Test",
                "cantidad": D("1"),
                "precioUni": D(str(precio)),
                "montoDescu": D("0"),
            }
        ],
        "resumen": {},
    }
    recalcular_totales(payload)
    return payload


def test_calculo_iva_item():
    payload = _build_payload("13.00")
    item = payload["cuerpoDocumento"][0]
    resumen = payload["resumen"]
    assert D(str(item["ventaGravada"])) == D("13.00")
    assert D(str(item["ivaItem"])) == D("1.4956")
    assert D(str(resumen["totalIva"])) == D("1.4956")


def test_serializacion_sin_tributos():
    payload = _build_payload("13.00")
    item = payload["cuerpoDocumento"][0]
    resumen = payload["resumen"]
    assert item.get("tributos") is None
    assert item.get("codTributo") is None
    assert resumen.get("tributos") is None
    iva_suma = sum(D(str(i["ivaItem"])) for i in payload["cuerpoDocumento"])
    assert D(str(resumen["totalIva"])) == iva_suma
    json_str = stable_stringify(payload)
    assert "-0.00" not in json_str


def test_fc_precio_incluye_iva_default():
    payload = _build_payload("13.00")
    item = payload["cuerpoDocumento"][0]
    resumen = payload["resumen"]
    assert D(str(item["ventaGravada"])) == D("13.00")
    assert D(str(item["ivaItem"])) == D("1.4956")
    assert D(str(resumen["totalGravada"])) == D("13.00")
    assert D(str(resumen["totalIva"])) == D("1.4956")
    assert D(str(resumen["totalPagar"])) == D("13.00")
    assert item.get("codTributo") is None
    assert item.get("tributos") is None
    assert resumen.get("tributos") is None


def test_valida_iva_incorrecto_warning(caplog):
    payload = {
        "identificacion": {"tipoDte": "01"},
        "cuerpoDocumento": [
            {
                "numItem": 1,
                "descripcion": "Test",
                "cantidad": D("1"),
                "precioUni": D("13.00"),
                "montoDescu": D("0"),
                "ivaItem": D("0"),
            }
        ],
        "resumen": {},
    }
    with caplog.at_level("WARNING"):
        recalcular_totales(payload)
    assert "IVA por ítem incoherente" in caplog.text
    item = payload["cuerpoDocumento"][0]
    assert D(str(item["ivaItem"])) == D("1.4956")
