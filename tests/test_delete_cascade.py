import pytest
from db import DB


def test_delete_producto_removes_dependents(tmp_path):
    db = DB(str(tmp_path / "db.sqlite"))
    db.add_vendedor("V1")
    vendedor_id = db.get_vendedores()[0]["id"]
    db.add_producto("P1", "C1", vendedor_id, None, 1, 2, 3, 10)
    producto_id = db.get_productos()[0]["id"]
    venta_id = db.add_venta("2024-01-01", 10)
    db.add_detalle_venta(venta_id, producto_id, 1, 10)
    compra_id = db.add_compra_detallada(
        {
            "fecha": "2024-01-01",
            "producto_id": producto_id,
            "cantidad": 5,
            "precio_unitario": 2,
            "total": 10,
        }
    )
    db.add_detalle_compra(compra_id, producto_id, 5, 2)
    db.add_movimiento("2024-01-01", "entrada", producto_id, 5)
    db.delete_producto(producto_id)
    for table, column in [
        ("detalles_venta", "producto_id"),
        ("detalles_compra", "producto_id"),
        ("compras", "producto_id"),
        ("movimientos", "producto_id"),
    ]:
        db.cursor.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {column}=?", (producto_id,)
        )
        assert db.cursor.fetchone()[0] == 0
    db.cursor.execute("SELECT COUNT(*) FROM productos WHERE id=?", (producto_id,))
    assert db.cursor.fetchone()[0] == 0


def test_delete_vendedor_requires_reassignment(tmp_path):
    db = DB(str(tmp_path / "db.sqlite"))
    db.add_vendedor("V1")
    vendedor_id = db.get_vendedores()[0]["id"]
    db.add_producto("P1", "C1", vendedor_id, None, 1, 2, 3, 10)
    producto_id = db.get_productos()[0]["id"]
    venta_id = db.add_venta("2024-01-01", 10, vendedor_id=vendedor_id)
    db.add_detalle_venta(
        venta_id, producto_id, 1, 10, vendedor_id=vendedor_id
    )
    db.add_compra_detallada(
        {
            "fecha": "2024-01-01",
            "producto_id": producto_id,
            "cantidad": 5,
            "precio_unitario": 2,
            "total": 10,
            "vendedor_id": vendedor_id,
        }
    )
    with pytest.raises(ValueError):
        db.delete_vendedor(vendedor_id)
    db.add_vendedor("V2")
    nuevo_id = db.get_vendedores()[1]["id"]
    db.delete_vendedor(vendedor_id, reassign_to=nuevo_id)
    for table in ["productos", "detalles_venta", "compras", "ventas"]:
        db.cursor.execute(f"SELECT vendedor_id FROM {table}")
        assert db.cursor.fetchone()[0] == nuevo_id
    db.cursor.execute("SELECT COUNT(*) FROM vendedores WHERE id=?", (vendedor_id,))
    assert db.cursor.fetchone()[0] == 0


def test_delete_distribuidor_requires_reassignment(tmp_path):
    db = DB(str(tmp_path / "db.sqlite"))
    db.add_Distribuidor("D1")
    dist1 = db.get_Distribuidores()[0]["id"]
    db.add_vendedor("V1", Distribuidor_id=dist1)
    vend1 = db.get_vendedores()[0]["id"]
    db.add_producto("P1", "C1", vend1, dist1, 1, 2, 3, 10)
    producto_id = db.get_productos()[0]["id"]
    venta_id = db.add_venta(
        "2024-01-01",
        10,
        Distribuidor_id=dist1,
        vendedor_id=vend1,
    )
    db.add_detalle_venta(venta_id, producto_id, 1, 10, vendedor_id=vend1)
    db.add_compra_detallada(
        {
            "fecha": "2024-01-01",
            "producto_id": producto_id,
            "cantidad": 5,
            "precio_unitario": 2,
            "total": 10,
            "Distribuidor_id": dist1,
            "vendedor_id": vend1,
        }
    )
    with pytest.raises(ValueError):
        db.delete_Distribuidor(dist1)
    db.add_Distribuidor("D2")
    dist2 = db.get_Distribuidores()[1]["id"]
    db.delete_Distribuidor(dist1, reassign_to=dist2)
    for table in ["vendedores", "productos", "compras", "ventas"]:
        db.cursor.execute(f"SELECT Distribuidor_id FROM {table}")
        assert db.cursor.fetchone()[0] == dist2
    db.cursor.execute(
        "SELECT COUNT(*) FROM Distribuidores WHERE id=?", (dist1,)
    )
    assert db.cursor.fetchone()[0] == 0


def test_delete_venta_removes_detalles(tmp_path):
    db = DB(str(tmp_path / "db.sqlite"))
    db.add_vendedor("V1")
    vendedor_id = db.get_vendedores()[0]["id"]
    db.add_producto("P1", "C1", vendedor_id, None, 1, 2, 3, 10)
    producto_id = db.get_productos()[0]["id"]
    venta_id = db.add_venta("2024-01-01", 10)
    db.add_detalle_venta(venta_id, producto_id, 1, 10)
    db.delete_venta(venta_id)
    db.cursor.execute(
        "SELECT COUNT(*) FROM detalles_venta WHERE venta_id=?", (venta_id,)
    )
    assert db.cursor.fetchone()[0] == 0
    db.cursor.execute("SELECT COUNT(*) FROM ventas WHERE id=?", (venta_id,))
    assert db.cursor.fetchone()[0] == 0
