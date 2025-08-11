from db import DB
from dte import generar_dte_json


def create_db():
    return DB(":memory:")


def test_generar_dte_json_basic():
    db = create_db()
    db.add_vendedor("V1")
    vend_id = db.cursor.lastrowid
    db.add_producto("Prod", "P1", vend_id, None, 0, 0, 0, 10)
    prod_id = db.cursor.lastrowid
    db.add_cliente("Cliente", "123", "nit1", "", "giro", "", "", "", "", "")
    cliente_id = db.cursor.lastrowid
    venta_id = db.add_venta_credito_fiscal(cliente_id, "2024-01-01", 10, "123", "nit1", "giro", descuentos=0)
    db.add_detalle_venta(venta_id, prod_id, 1, 10, vendedor_id=vend_id)

    data = generar_dte_json(db, venta_id)

    required = [
        "identificacion",
        "emisor",
        "receptor",
        "cuerpoDocumento",
        "resumen",
        "firmaElectronica",
        "selloRecibido",
        "condicionPago",
    ]
    for key in required:
        assert key in data
    assert data["firmaElectronica"] is None
    assert data["selloRecibido"] is None
    assert data["identificacion"].get("codigoGeneracion")
    assert data["receptor"].get("noRemision") is None
    assert data["receptor"].get("ordenNo") is None


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
    assert data["cuerpoDocumento"][0]["precioUnitario"] == 1.12345679
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
