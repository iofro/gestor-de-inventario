from decimal import Decimal as D

from dte import recalcular_totales
from utils.stable_json import stable_stringify


def _build_payload(precio, *, precios_incluyen_iva=None):
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
    if precios_incluyen_iva is None:
        recalcular_totales(payload)
    else:
        recalcular_totales(payload, precios_incluyen_iva=precios_incluyen_iva)
    return payload


def test_calculo_iva_precios_excluyen_iva():
    payload = _build_payload("13.00", precios_incluyen_iva=False)
    item = payload["cuerpoDocumento"][0]
    resumen = payload["resumen"]
    assert D(str(item["ventaGravada"])) == D("13.00")
    assert D(str(item["ivaItem"])) == D("1.69")
    assert D(str(resumen["montoTotalOperacion"])) == D("14.69")
    assert D(str(resumen["totalIva"])) == D("1.69")


def test_calculo_iva_precios_incluyen_iva():
    payload = _build_payload("14.69", precios_incluyen_iva=True)
    item = payload["cuerpoDocumento"][0]
    resumen = payload["resumen"]
    assert D(str(item["ventaGravada"])) == D("13.00")
    assert D(str(item["ivaItem"])) == D("1.69")
    assert D(str(resumen["totalIva"])) == D("1.69")


def test_serializacion_sin_tributos():
    payload = _build_payload("13.00", precios_incluyen_iva=False)
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
    assert D(str(item["ventaGravada"])) == D("11.50")
    assert D(str(item["ivaItem"])) == D("1.50")
    assert D(str(resumen["totalGravada"])) == D("11.50")
    assert D(str(resumen["totalIva"])) == D("1.50")
    assert D(str(resumen["totalPagar"])) == D("13.00")
    assert item.get("codTributo") is None
    assert item.get("tributos") is None
    assert resumen.get("tributos") is None
