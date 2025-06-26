import pytest
from db import DB


def create_db():
    return DB(":memory:")


def test_detalle_venta_con_vendedor():
    db = create_db()
    db.add_vendedor("Luis")
    vendedor_id = db.cursor.lastrowid
    db.add_producto("Prod", "P1", vendedor_id, None, 0, 0, 0, 10)
    producto_id = db.cursor.lastrowid
    venta_id = db.add_venta("2024-01-01", 10)
    db.add_detalle_venta(venta_id, producto_id, 1, 10, vendedor_id=vendedor_id)
    detalles = db.get_detalles_venta(venta_id)
    assert detalles[0]["vendedor_id"] == vendedor_id
