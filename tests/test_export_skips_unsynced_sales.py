import json
import inventory_manager as im


class MemoryDB(im.DB):
    def __init__(self):
        super().__init__(db_name=":memory:")


def test_export_skips_unsynced_sales(monkeypatch, tmp_path):
    monkeypatch.setattr(im, "DB", MemoryDB)
    man = im.InventoryManager()
    db = man.db

    db.add_cliente("Cliente", "", "", "", "", "", "", "", "", "")
    venta1 = db.add_venta("2024-01-01", 10, cliente_id=1)
    venta2 = db.add_venta("2024-01-02", 20, cliente_id=1)
    db.cursor.execute("UPDATE ventas SET sincronizada=0 WHERE id=?", (venta2,))
    db.conn.commit()
    man.refresh_data()

    export_file = tmp_path / "export.json"
    man.exportar_inventario_json(str(export_file))

    data = json.loads(export_file.read_text())
    assert [v["id"] for v in data.get("ventas", [])] == [venta1]
