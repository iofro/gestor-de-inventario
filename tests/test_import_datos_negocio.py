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


def test_import_preserves_manual_tokens(tmp_path, monkeypatch):
    datos_path = tmp_path / "datos_negocio.json"
    existing = {
        "nombre": "Farmacia",
        "dte_api": {
            "token_pruebas": "Bearer viejo-test",
            "token_produccion": "Bearer viejo-prod",
            "url": "https://apitest.example",
        },
    }
    datos_path.write_text(json.dumps(existing))
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
        "datos_negocio": {
            "nombre": "Actualizado",
            "dte_api": {
                "token_pruebas": "Bearer nuevo-test",
                "token_produccion": "Bearer nuevo-prod",
                "url": "https://api.dtes.mh.gob.sv",
            },
        },
    }
    inv_path = tmp_path / "inv.json"
    inv_path.write_text(json.dumps(data))
    manager.importar_inventario_json(str(inv_path))
    guardados = json.loads(datos_path.read_text())
    assert guardados["nombre"] == "Actualizado"
    dte_api = guardados["dte_api"]
    assert dte_api["token_pruebas"] == "Bearer viejo-test"
    assert dte_api["token_produccion"] == "Bearer viejo-prod"
    assert "token" not in dte_api
    assert dte_api["url"] == "https://api.dtes.mh.gob.sv"


def test_export_redacts_manual_tokens(tmp_path, monkeypatch):
    datos_path = tmp_path / "datos_negocio.json"
    existing = {
        "nombre": "Farmacia",
        "dte_api": {
            "token_pruebas": "Bearer viejo-test",
            "token_produccion": "Bearer viejo-prod",
            "prefijo_control": "DTE-01",
        },
    }
    datos_path.write_text(json.dumps(existing))
    monkeypatch.setattr(im, "DATOS_NEGOCIO_PATH", datos_path)
    manager = im.InventoryManager(MemoryDB())
    export_path = tmp_path / "export.json"
    manager.exportar_inventario_json(str(export_path))
    contenido = json.loads(export_path.read_text())
    dte_api = (contenido.get("datos_negocio") or {}).get("dte_api", {})
    assert "token" not in dte_api
    assert "token_pruebas" not in dte_api
    assert "token_produccion" not in dte_api
    assert dte_api.get("prefijo_control") == "DTE-01"
