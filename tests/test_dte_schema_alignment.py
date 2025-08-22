from db import DB
from dte import generar_dte_json
from jsonschema import validate as js_validate
from utils import catalogos
import json
import os


def _load_schema(tipo):
    path = catalogos.SCHEMA_MAP[tipo]
    with open(path, 'r', encoding='utf-8') as fh:
        return json.load(fh)


def _create_basic_sale(descuento=0, tributos=None, pagos=None):
    db = DB(":memory:")
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None,  vid, None, 0, 0, 0, 10)
    pid = db.cursor.lastrowid
    db.add_cliente(
        "Cliente",
        "123",
        "0614-000000-102-5",
        "",
        "giro",
        "",
        "",
        "C",
        "06",
        "01",
    )
    cid = db.cursor.lastrowid
    venta_id = db.add_venta_credito_fiscal(
        cid,
        "2024-01-01",
        10 - descuento,
        "123",
        "0614-000000-102-5",
        "giro",
        sumas=10,
        descuentos=descuento,
        iva=0,
    )
    db.add_detalle_venta(venta_id, pid, 1, 10, vendedor_id=vid)
    extra = {}
    if tributos:
        extra["tributos"] = tributos
    if pagos:
        extra["pagos"] = pagos
    if extra:
        db.update_venta_extra(venta_id, extra)
    return db, venta_id


def test_resumen_matches_schema_keys():
    db, venta_id = _create_basic_sale()
    data = generar_dte_json(db, venta_id, tipo_dte="03")
    resumen = data["resumen"]
    schema = _load_schema("03")["properties"]["resumen"]
    js_validate(resumen, schema)
    allowed = set(schema["properties"].keys())
    assert set(resumen.keys()) == allowed
    assert "sumas" not in resumen and "iva" not in resumen and "descuentos" not in resumen


def test_resumen_with_descuentos_tributos_pagos():
    tributos = [{"codigo": "59", "descripcion": "FOVIAL", "valor": 1.0}]
    pagos = [{"codigo": "02", "montoPago": 9.0, "referencia": "ref", "periodo": None, "plazo": None}]
    db, venta_id = _create_basic_sale(descuento=1.0, tributos=tributos, pagos=pagos)
    data = generar_dte_json(db, venta_id, tipo_dte="03")
    resumen = data["resumen"]
    schema = _load_schema("03")["properties"]["resumen"]
    js_validate(resumen, schema)
    assert resumen["totalDescu"] == 1.0
    assert resumen["porcentajeDescuento"] == 10.0
    assert resumen["tributos"][0]["codigo"] == "59"
    assert resumen["pagos"][0]["codigo"] == "02"
    # ensure mapping of iva
    assert "iva" not in resumen
