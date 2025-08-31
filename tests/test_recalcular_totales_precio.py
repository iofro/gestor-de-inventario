from decimal import Decimal as D
import json
from pathlib import Path

from dte import recalcular_totales, money
from utils.stable_json import stable_stringify


def _build_payload(precio, cantidad="1"):
    total = money(D(str(precio)) * D(str(cantidad)))
    iva = money(total - total / D("1.13"))
    return {
        "identificacion": {"tipoDte": "01"},
        "cuerpoDocumento": [
            {
                "numItem": 1,
                "descripcion": "Test",
                "cantidad": D(str(cantidad)),
                "precioUni": D(str(precio)),
                "montoDescu": D("0"),
                "ventaGravada": total,
                "ivaItem": iva,
            }
        ],
        "resumen": {},
    }


def test_precio_cero_todos_ceros():
    payload = _build_payload("0")
    recalcular_totales(payload, precios_incluyen_iva=True)
    item = payload["cuerpoDocumento"][0]
    resumen = payload["resumen"]
    assert D(str(item["ventaGravada"])) == D("0.0")
    assert D(str(item["ivaItem"])) == D("0.0")
    assert D(str(resumen["totalPagar"])) == D("0.00")
    json_str = stable_stringify(payload)
    assert '"precioUni":"0.0"' in json_str
    assert '"ventaGravada":"0.0"' in json_str
    assert '"ivaItem":"0.0"' in json_str
    assert '"totalPagar":"0.00"' in json_str


def test_precio_uno_cantidad_uno():
    payload = _build_payload("1.00")
    recalcular_totales(payload, precios_incluyen_iva=True)
    item = payload["cuerpoDocumento"][0]
    resumen = payload["resumen"]
    assert D(str(item["ventaGravada"])) == D("1.00")
    assert D(str(item["ivaItem"])) == D("0.12")
    assert D(str(resumen["totalPagar"])) == D("1.00")


def test_precio_diez_cantidad_uno():
    payload = _build_payload("10.00")
    recalcular_totales(payload, precios_incluyen_iva=True)
    item = payload["cuerpoDocumento"][0]
    resumen = payload["resumen"]
    assert D(str(item["ventaGravada"])) == D("10.00")
    assert D(str(item["ivaItem"])) == D("1.15")
    assert D(str(resumen["totalPagar"])) == D("10.00")


def test_precio_requiere_cuatro_decimales():
    payload = _build_payload("3.3333", cantidad="3")
    recalcular_totales(payload, precios_incluyen_iva=True)
    item = payload["cuerpoDocumento"][0]
    resumen = payload["resumen"]
    assert D(str(item["precioUni"])) == D("3.3333")
    assert D(str(item["ventaGravada"])) == D("10.00")
    assert D(str(resumen["totalPagar"])) == D("10.00")
    item_json = stable_stringify(item)
    assert '"precioUni":"3.3333"' in item_json
    assert '"ventaGravada":"10.0000"' in item_json


def test_rechazado_vs_aceptado():
    base = Path(__file__).resolve().parents[1] / "dte rechazado y aceptado"
    rej_path = base / "20250825_ariel_DTE-01-S001P001-000000000000075_ConsumidorFinal.json"
    acc_path = base / "20250828_ariel_DTE-01-S001P001-000000000000078_ConsumidorFinal.json"
    with rej_path.open("r", encoding="utf-8") as fh:
        rej = json.load(fh)
    with acc_path.open("r", encoding="utf-8") as fh:
        acc = json.load(fh, parse_float=D)

    item_rej = rej["cuerpoDocumento"][0]
    payload = {
        "identificacion": {"tipoDte": "01"},
        "cuerpoDocumento": [
            {
                "numItem": 1,
                "tipoItem": item_rej["tipoItem"],
                "numeroDocumento": None,
                "codigo": item_rej["codigo"],
                "descripcion": item_rej["descripcion"],
                "cantidad": D(str(item_rej["cantidad"])),
                "uniMedida": item_rej["uniMedida"],
                "precioUni": D(str(item_rej["precioUni"])),
                "montoDescu": D("0"),
                "ventaNoSuj": D("0"),
                "ventaExenta": D("0"),
                "ventaGravada": money(D(str(item_rej["precioUni"])) * D(str(item_rej["cantidad"]))),
                "ivaItem": money(D(str(item_rej["precioUni"])) - D(str(item_rej["precioUni"])) / D("1.13")),
                "psv": D("0"),
                "noGravado": D("0"),
            }
        ],
        "resumen": {},
    }
    recalcular_totales(payload, precios_incluyen_iva=True)
    item = payload["cuerpoDocumento"][0]
    resumen_raw = payload["resumen"].copy()
    acc_item = acc["cuerpoDocumento"][0]
    acc_resumen_raw = acc["resumen"].copy()
    keys = ["subTotal","subTotalVentas","totalGravada","totalIva","montoTotalOperacion","totalPagar"]
    resumen = {k: resumen_raw[k] for k in keys}
    acc_resumen = {k: acc_resumen_raw[k] for k in keys}
    assert stable_stringify(item) == stable_stringify(acc_item)
    assert stable_stringify(resumen) == stable_stringify(acc_resumen)
