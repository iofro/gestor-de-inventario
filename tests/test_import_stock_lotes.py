import json
import inventory_manager as im

class MemoryDB(im.DB):
    def __init__(self):
        super().__init__(db_name=":memory:")


def test_import_creates_lote_from_stock(tmp_path, monkeypatch):
    monkeypatch.setattr(im, "DB", MemoryDB)
    manager = im.InventoryManager()

    data = {
        "productos": [
            {
                "id": 1,
                "nombre": "Prod",
                "codigo": "P1",
                "precio_compra": 2,
                "precio_venta_minorista": 0,
                "precio_venta_mayorista": 0,
                "stock": 5,
            }
        ],
        "vendedores": [],
        "Distribuidores": [],
        "clientes": [],
        "ventas": [],
        "compras": [],
        "movimientos": [],
        "detalles_venta": [],
        "detalles_compra": [],
        "trabajadores": [],
        "datos_negocio": None,
        "ventas_credito_fiscal": [],
    }

    file_path = tmp_path / "inv.json"
    file_path.write_text(json.dumps(data))

    manager.importar_inventario_json(str(file_path))

    manager.db.cursor.execute("SELECT * FROM detalles_compra")
    rows = [dict(r) for r in manager.db.cursor.fetchall()]
    assert len(rows) == 1
    lote = rows[0]
    producto_id = manager.db.get_productos()[0]["id"]
    assert lote["producto_id"] == producto_id
    assert lote["cantidad"] == 5


def test_import_lote_links_extra_info(tmp_path, monkeypatch):
    monkeypatch.setattr(im, "DB", MemoryDB)
    manager = im.InventoryManager()

    data = {
        "vendedores": [{"id": 1, "nombre": "V1"}],
        "Distribuidores": [{"id": 2, "nombre": "D1"}],
        "productos": [
            {
                "id": 1,
                "nombre": "Prod",
                "codigo": "P1",
                "vendedor_id": 1,
                "Distribuidor_id": 2,
                "precio_compra": 3,
                "precio_venta_minorista": 0,
                "precio_venta_mayorista": 0,
                "stock": 4,
            }
        ],
        "clientes": [],
        "ventas": [],
        "compras": [],
        "movimientos": [],
        "detalles_venta": [],
        "detalles_compra": [],
        "trabajadores": [],
        "datos_negocio": None,
        "ventas_credito_fiscal": [],
    }

    file_path = tmp_path / "inv.json"
    file_path.write_text(json.dumps(data))
    manager.importar_inventario_json(str(file_path))

    manager.db.cursor.execute("SELECT * FROM compras")
    compras = [dict(r) for r in manager.db.cursor.fetchall()]
    assert len(compras) == 1
    compra = compras[0]
    vend_id = manager.db.get_vendedores()[0]["id"]
    dist_id = manager.db.get_Distribuidores()[0]["id"]
    assert compra["vendedor_id"] == vend_id
    assert compra["Distribuidor_id"] == dist_id

    manager.db.cursor.execute("SELECT * FROM detalles_compra")
    detalle = dict(manager.db.cursor.fetchone())
    assert detalle["compra_id"] == compra["id"]
    assert detalle["cantidad"] == 4
