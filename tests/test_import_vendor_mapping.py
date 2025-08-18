import json
import pytest
import inventory_manager as im

class MemoryDB(im.DB):
    def __init__(self):
        super().__init__(db_name=":memory:")

def test_import_maps_vendors(tmp_path, monkeypatch):
    monkeypatch.setattr(im, "DB", MemoryDB)
    manager = im.InventoryManager()

    data = {
        "Distribuidores": [{"id": 1, "nombre": "D1"}],
        "vendedores": [{"id": 99, "nombre": "V1", "Distribuidor_id": 1, "codigo": "V001"}],
        "clientes": [{"id": 2, "nombre": "C1", "codigo": "C001"}],
        "ventas": [{"id": 5, "fecha": "2024-01-01", "total": 10, "cliente_id": 2, "Distribuidor_id": 1, "vendedor_id": 99}],
    }
    path = tmp_path / "inv.json"
    path.write_text(json.dumps(data))

    manager.importar_inventario_json(str(path))

    ventas = manager.db.get_ventas()
    assert len(ventas) == 1
    venta = ventas[0]
    vend = manager.db.get_vendedores()[0]
    assert venta["vendedor_id"] == vend["id"]
