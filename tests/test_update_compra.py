import pytest

from db import DB


def create_db():
    return DB(":memory:")


def test_update_compra_detallada_updates_totals_and_stock():
    db = create_db()
    db.add_Distribuidor("D1")
    dist_id = db.cursor.lastrowid
    db.add_vendedor("V1")
    vend_id = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None, vend_id, dist_id, 0, 0, 0, 0)
    prod_id = db.cursor.lastrowid

    compra_id = db.add_compra_detallada(
        {
            "fecha": "2024-01-01",
            "producto_id": None,
            "cantidad": 0,
            "precio_unitario": 0,
            "total": 100,
            "Distribuidor_id": dist_id,
            "comision_pct": 0,
            "comision_monto": 0,
            "vendedor_id": vend_id,
        }
    )

    db.add_detalle_compra(
        compra_id,
        prod_id,
        10,
        10,
        "",
        0,
        "%",
        0,
        "",
        0,
        0,
        "Añadida al total",
    )
    db.aumentar_stock(prod_id, 10)

    db.update_compra_detallada(
        compra_id,
        {
            "fecha": "2024-01-02",
            "producto_id": None,
            "cantidad": 0,
            "precio_unitario": 0,
            "total": 50,
            "Distribuidor_id": dist_id,
            "comision_pct": 0,
            "comision_monto": 5,
            "vendedor_id": vend_id,
        },
        [
            {
                "producto_id": prod_id,
                "cantidad": 5,
                "precio": 8,
                "fecha_vencimiento": "2024-12-31",
                "descuento_monto": 0,
                "descuento_tipo": "%",
                "iva": 0,
                "iva_tipo": "ninguno",
                "comision_pct": 0,
                "comision_monto": 5,
                "comision_tipo": "Añadida al total",
            }
        ],
    )

    compra = db.get_compras()[0]
    assert compra["total"] == 50
    assert compra["comision_monto"] == 5

    detalles = db.get_detalles_compra(compra_id)
    assert len(detalles) == 1
    detalle = detalles[0]
    assert detalle["cantidad"] == 5
    assert detalle["precio_unitario"] == 8
    assert detalle["comision_monto"] == 5

    db.cursor.execute("SELECT stock FROM productos WHERE id=?", (prod_id,))
    stock = db.cursor.fetchone()["stock"]
    assert stock == 5


def test_update_detalle_compra_cantidad_updates_stock():
    db = create_db()
    db.add_Distribuidor("D1")
    dist_id = db.cursor.lastrowid
    db.add_vendedor("V1")
    vend_id = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None, vend_id, dist_id, 0, 0, 0, 0)
    prod_id = db.cursor.lastrowid

    compra_id = db.add_compra_detallada(
        {
            "fecha": "2024-01-01",
            "producto_id": None,
            "cantidad": 0,
            "precio_unitario": 0,
            "total": 0,
            "Distribuidor_id": dist_id,
            "comision_pct": 0,
            "comision_monto": 0,
            "vendedor_id": vend_id,
        }
    )

    db.add_detalle_compra(compra_id, prod_id, 10, 5)
    detalle_id = db.cursor.lastrowid

    db.update_detalle_compra_cantidad(detalle_id, 6)

    detalle = db.get_detalles_compra(compra_id)[0]
    assert detalle["cantidad"] == 6

    db.cursor.execute("SELECT stock FROM productos WHERE id=?", (prod_id,))
    stock = db.cursor.fetchone()["stock"]
    assert stock == 6


def test_update_detalle_compra_cantidad_validates_input():
    db = create_db()
    db.add_Distribuidor("D1")
    dist_id = db.cursor.lastrowid
    db.add_vendedor("V1")
    vend_id = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None, vend_id, dist_id, 0, 0, 0, 0)
    prod_id = db.cursor.lastrowid

    compra_id = db.add_compra_detallada(
        {
            "fecha": "2024-01-01",
            "producto_id": None,
            "cantidad": 0,
            "precio_unitario": 0,
            "total": 0,
            "Distribuidor_id": dist_id,
            "comision_pct": 0,
            "comision_monto": 0,
            "vendedor_id": vend_id,
        }
    )

    db.add_detalle_compra(compra_id, prod_id, 10, 5)
    detalle_id = db.cursor.lastrowid

    with pytest.raises(ValueError):
        db.update_detalle_compra_cantidad(detalle_id, -1)

    with pytest.raises(ValueError):
        db.update_detalle_compra_cantidad(None, 1)

