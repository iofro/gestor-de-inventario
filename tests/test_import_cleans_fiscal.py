import json
import inventory_manager as im

class MemoryDB(im.DB):
    def __init__(self):
        super().__init__(db_name=":memory:")

def test_import_resets_credito_fiscal(tmp_path, monkeypatch):
    monkeypatch.setattr(im, "DB", MemoryDB)
    manager = im.InventoryManager()

    data = {
        "vendedores": [],
        "Distribuidores": [],
        "productos": [],
        "clientes": [{"id": 1, "nombre": "C"}],
        "ventas": [{"id": 1, "fecha": "2024-01-01", "total": 1, "cliente_id": 1}],
        "ventas_credito_fiscal": [
            {"venta_id": 1, "cliente_id": 1, "nrc": "1", "nit": "1", "giro": "g"}
        ],
    }
    path = tmp_path / "inv.json"
    path.write_text(json.dumps(data))

    manager.importar_inventario_json(str(path))
    assert len(manager.db.cursor.execute("SELECT * FROM ventas_credito_fiscal").fetchall()) == 1

    # Import again to check that table is cleared
    manager.importar_inventario_json(str(path))
    rows = manager.db.cursor.execute("SELECT * FROM ventas_credito_fiscal").fetchall()
    assert len(rows) == 1
