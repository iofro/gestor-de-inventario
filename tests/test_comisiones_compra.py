import pytest
from db import DB


def create_db():
    return DB(":memory:")


def test_comisiones_compra_agregada_y_detallada():
    db = create_db()
    db.add_Distribuidor("D1")
    dist_id = db.cursor.lastrowid
    db.add_vendedor("V1")
    vend_id = db.cursor.lastrowid
    db.add_producto("Prod1", "P1", vend_id, dist_id, 0, 0, 0, 10)
    prod_id = db.cursor.lastrowid

    compra_id = db.add_compra_detallada({
        "fecha": "2024-01-01",
        "producto_id": None,
        "cantidad": 0,
        "precio_unitario": 0,
        "total": 230,
        "Distribuidor_id": dist_id,
        "comision_pct": 0,
        "comision_monto": 30,
        "vendedor_id": vend_id,
    })

    db.add_detalle_compra(compra_id, prod_id, 1, 100, "", 0, "", 0, "", 10, 10, "Añadida al total")
    db.add_detalle_compra(compra_id, prod_id, 1, 120, "", 0, "", 0, "", 20, 20, "Desglosada (incluida en el precio)")

    compras = db.get_compras()
    assert len(compras) == 1
    c = compras[0]
    assert c["comision_monto"] == 30
    assert c["total"] == 230

    detalles = db.get_detalles_compra(compra_id)
    assert sum(d["comision_monto"] for d in detalles) == 30
    tipos = {d["comision_tipo"] for d in detalles}
    assert "Añadida al total" in tipos
    assert "Desglosada (incluida en el precio)" in tipos
