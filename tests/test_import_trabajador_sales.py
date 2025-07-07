import json
import inventory_manager as im
import pytest

class MemoryDB(im.DB):
    def __init__(self):
        super().__init__(db_name=":memory:")

def test_import_maps_trabajador_sales(tmp_path, monkeypatch):
    monkeypatch.setattr(im, "DB", MemoryDB)
    manager = im.InventoryManager()

    data = {
        "Distribuidores": [],
        "vendedores": [],
        "clientes": [{"id": 1, "nombre": "C"}],
        "trabajadores": [{"id": 2, "nombre": "Vend", "codigo": "T1", "es_vendedor": True}],
        "ventas": [{"id": 1, "fecha": "2024-01-01", "total": 5, "cliente_id": 1, "vendedor_id": 2}],
        "compras": [],
        "movimientos": [],
        "detalles_venta": [],
        "detalles_compra": [],
        "datos_negocio": None,
        "ventas_credito_fiscal": [],
    }
    path = tmp_path / "inv.json"
    path.write_text(json.dumps(data))

    manager.importar_inventario_json(str(path))

    ventas = manager.db.get_ventas()
    assert len(ventas) == 1
    venta = ventas[0]
    trab_id = manager.db.get_trabajadores()[0]["id"]
    assert venta["vendedor_id"] == trab_id
