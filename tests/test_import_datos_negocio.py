import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import json
import inventory_manager as im

class MemoryDB(im.DB):
    def __init__(self):
        super().__init__(db_name=":memory:")

def test_import_without_datos_negocio_keeps_existing(tmp_path, monkeypatch):
    datos_path = tmp_path / "datos_negocio.json"
    datos_path.write_text(json.dumps({"nombre": "Original"}))
    monkeypatch.setattr(im, "DATOS_NEGOCIO_PATH", datos_path)
    manager = im.InventoryManager(MemoryDB())
    data = {
        "Distribuidores": [],
        "vendedores": [],
        "productos": [],
        "clientes": [],
        "ventas": [],
        "compras": [],
        "movimientos": [],
        "detalles_venta": [],
        "detalles_compra": [],
        "trabajadores": [],
        "ventas_credito_fiscal": [],
    }
    inv_path = tmp_path / "inv.json"
    inv_path.write_text(json.dumps(data))
    manager.importar_inventario_json(str(inv_path))
    assert json.loads(datos_path.read_text()) == {"nombre": "Original"}
