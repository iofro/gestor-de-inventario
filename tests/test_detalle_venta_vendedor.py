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


def test_import_detalles_venta_uses_vendedor_map(tmp_path, monkeypatch):
    import inventory_manager
    monkeypatch.setattr(inventory_manager, 'DB', lambda: DB(":memory:"))
    man = inventory_manager.InventoryManager()

    data = {
        "vendedores": [{"id": 1, "nombre": "Luis"}],
        "Distribuidores": [],
        "productos": [
            {
                "id": 1,
                "nombre": "Prod",
                "codigo": "P1",
                "precio_compra": 0,
                "precio_venta_minorista": 0,
                "precio_venta_mayorista": 0,
                "stock": 10,
            }
        ],
        "clientes": [],
        "ventas": [{"id": 1, "fecha": "2024-01-01", "total": 10}],
        "compras": [],
        "movimientos": [],
        "detalles_compra": [],
        "detalles_venta": [
            {
                "venta_id": 1,
                "producto_id": 1,
                "cantidad": 1,
                "precio_unitario": 10,
                "descuento": 0,
                "descuento_tipo": "",
                "iva": 0,
                "comision": 0,
                "iva_tipo": "",
                "tipo_fiscal": "Gravada",
                "extra": None,
                "precio_con_iva": 10,
                "vendedor_id": 1,
            }
        ],
        "trabajadores": [],
        "datos_negocio": None,
        "ventas_credito_fiscal": [],
    }

    file_path = tmp_path / "inv.json"
    with open(file_path, "w", encoding="utf-8") as f:
        import json
        json.dump(data, f)

    man.importar_inventario_json(str(file_path))

    ventas = man.db.get_ventas()
    assert len(ventas) == 1
    venta_id = ventas[0]["id"]
    detalles = man.db.get_detalles_venta(venta_id)
    vend_id = man.db.get_vendedores()[0]["id"]
    assert detalles[0]["vendedor_id"] == vend_id
