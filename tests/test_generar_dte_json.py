import pytest

import json
from pathlib import Path
from decimal import Decimal

from db import DB
from dte import generar_dte_json, _write_json


def create_db():
    return DB(":memory:")


def test_generar_dte_json_basic(tmp_path):
    import dte as dte_module

    datos = {
        "nit": "06141990011019",
        "nrc": "1234567-8",
        "nombre": "Mi Negocio",
        "nombreComercial": "Mi Negocio",
        "cod_giro": "123456",
        "descActividad": "Comercio",
        "telefono": "2222-2222",
        "correo": "test@example.com",
    }
    tmp_file = tmp_path / "datos_negocio.json"
    tmp_file.write_text(json.dumps(datos))
    dte_module.DATOS_NEGOCIO_PATH = str(tmp_file)

    db = create_db()
    db.add_vendedor("V1")
    vend_id = db.cursor.lastrowid
    db.add_producto("Prod", "P1", vend_id, None, 0, 0, 0, 10)
    prod_id = db.cursor.lastrowid
    db.add_cliente("Cliente", "123", "06141990011019", "", "giro", "7000-0001", "", "", "", "")
    cliente_id = db.cursor.lastrowid
    venta_id = db.add_venta("2024-01-01", 11.3, cliente_id=cliente_id)
    db.add_detalle_venta(venta_id, prod_id, 1, 10, vendedor_id=vend_id)

    data = generar_dte_json(db, venta_id)

    idf = data["identificacion"]
    res = data["resumen"]

    assert idf["tipoDte"] == "01"
    assert idf["ambiente"] in ("00", "01")

    def q2(x):
        return Decimal(str(x)).quantize(Decimal("0.01"))

    assert q2(res["totalPagar"]) == sum(
        q2(p["montoPago"]) for p in (res.get("pagos") or [])
    )

    expected = {
        "identificacion",
        "emisor",
        "receptor",
        "cuerpoDocumento",
        "resumen",
        "documentoRelacionado",
        "otrosDocumentos",
        "apendice",
        "ventaTercero",
        "extension",
    }
    assert set(data.keys()) == expected


def test_dte_rounding_and_validation(capsys):
    db = create_db()
    db.add_vendedor("V1")
    vend_id = db.cursor.lastrowid
    db.add_producto("Prod", "P1", vend_id, None, 0, 0, 0, 10)
    prod_id = db.cursor.lastrowid
    db.add_cliente("Cliente", "123", "nit1", "", "giro", "", "", "", "", "")
    cliente_id = db.cursor.lastrowid
    precio = 1.123456789
    venta_id = db.add_venta_credito_fiscal(
        cliente_id,
        "2024-01-01",
        precio * 2,
        "123",
        "nit1",
        "giro",
        sumas=precio * 2,
        descuentos=0,
        iva=0,
    )
    db.add_detalle_venta(venta_id, prod_id, 2, precio, vendedor_id=vend_id)

    data = generar_dte_json(db, venta_id)
    out = capsys.readouterr().out
    # Values rounded
    assert data["cuerpoDocumento"][0]["precioUni"] == 1.12345679
    assert data["resumen"]["totalGravada"] == 2.25
    # No warnings printed
    assert out.strip() == ""


def test_dte_sum_mismatch_warning(capsys):
    db = create_db()
    db.add_vendedor("V1")
    vend_id = db.cursor.lastrowid
    db.add_producto("Prod", "P1", vend_id, None, 0, 0, 0, 10)
    prod_id = db.cursor.lastrowid
    db.add_cliente("Cliente", "123", "nit1", "", "giro", "", "", "", "", "")
    cliente_id = db.cursor.lastrowid
    venta_id = db.add_venta_credito_fiscal(
        cliente_id,
        "2024-01-01",
        10,
        "123",
        "nit1",
        "giro",
        sumas=10,
        descuentos=0,
        iva=0,
    )
    db.add_detalle_venta(venta_id, prod_id, 1, 5, vendedor_id=vend_id)

    generar_dte_json(db, venta_id)
    out = capsys.readouterr().out
    assert "Advertencia" in out


def test_generar_ticket_json_tipo():
    db = create_db()
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("Prod", "P1", vid, None, 0, 0, 0, 10)
    pid = db.cursor.lastrowid
    venta_id = db.add_venta("2024-01-01", 5)
    db.add_detalle_venta(venta_id, pid, 1, 5, vendedor_id=vid)

    data = generar_dte_json(db, venta_id, tipo_dte="03")
    assert data["identificacion"]["tipoDte"] == "03"


def test_dte_comision_sin_advertencia_total(capsys):
    db = create_db()
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("Prod", "P1", vid, None, 0, 0, 0, 10)
    pid = db.cursor.lastrowid
    db.add_cliente("Cliente", "123", "nit1", "", "giro", "", "", "", "", "")
    cliente_id = db.cursor.lastrowid
    venta_id = db.add_venta_credito_fiscal(
        cliente_id,
        "2024-01-01",
        12,
        "123",
        "nit1",
        "giro",
        sumas=10,
        descuentos=0,
        iva=0,
    )
    db.add_detalle_venta(venta_id, pid, 1, 10, comision=2, vendedor_id=vid)
    generar_dte_json(db, venta_id)
    out = capsys.readouterr().out.lower()
    assert out.strip() == "" and "total a pagar" not in out


def test_generar_dte_json_condicion_operacion_invalida():
    db = create_db()
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("Prod", "P1", vid, None, 0, 0, 0, 10)
    pid = db.cursor.lastrowid
    db.add_cliente("Cliente", "123", "nit1", "", "giro", "", "", "", "", "")
    cliente_id = db.cursor.lastrowid
    venta_id = db.add_venta_credito_fiscal(
        cliente_id,
        "2024-01-01",
        10,
        "123",
        "nit1",
        "giro",
        condicion_pago="Invalida",
    )
    db.add_detalle_venta(venta_id, pid, 1, 10, vendedor_id=vid)

    with pytest.raises(ValueError):
        generar_dte_json(db, venta_id)


def test_write_json_guard(tmp_path):
    path = tmp_path / "facturas_consumidor_final" / "ejemplo.json"
    path.parent.mkdir(parents=True)
    with pytest.raises(AssertionError):
        _write_json(str(path), {})
