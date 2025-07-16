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
    venta_id = db.add_venta_credito_fiscal(cliente_id, "2024-01-01", 10, "123", "nit1", "giro")
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
