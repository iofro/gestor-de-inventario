import json
import inventory_manager as im


class MemoryDB(im.DB):
    def __init__(self):
        super().__init__(db_name=":memory:")


def make_valid_data():
    return {
        "schemaVersion": 1,
        "generatedAt": "2024-01-01T00:00:00",
        "appVersion": "test",
        "Distribuidores": [{"id": 1, "nombre": "D"}],
        "vendedores": [{"id": 1, "nombre": "V", "Distribuidor_id": 1}],
        "productos": [
            {
                "id": 1,
                "nombre": "P",
                "codigo": "P1",
                "sku": "S1",
                "vendedor_id": 1,
                "Distribuidor_id": 1,
                "precio_compra": 1,
                "precio_venta_minorista": 2,
                "precio_venta_mayorista": 2,
                "stock": 0,
            }
        ],
        "clientes": [{"id": 1, "nombre": "C"}],
        "ventas": [
            {
                "id": 1,
                "fecha": "2024-01-01",
                "total": 2,
                "cliente_id": 1,
                "vendedor_id": 1,
                "Distribuidor_id": 1,
            }
        ],
        "detalles_venta": [
            {
                "venta_id": 1,
                "producto_id": 1,
                "cantidad": 1,
                "precio_unitario": 2,
            }
        ],
    }


def test_happy_path_import(tmp_path):
    manager = im.InventoryManager(MemoryDB())
    data = make_valid_data()
    path = tmp_path / "inv.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    manager.importar_inventario_json(str(path))
    assert manager.db.get_productos()


def test_invalid_producto_id(tmp_path):
    manager = im.InventoryManager(MemoryDB())
    data = make_valid_data()
    data["detalles_venta"][0]["producto_id"] = 99
    path = tmp_path / "inv.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    summary = manager.importar_inventario_json(str(path), dry_run=True, strict=False)
    assert len(summary["errors"]) == 1
    assert summary["errors"][0]["path"] == "detalles_venta[0].producto_id"
    assert not manager.db.get_productos()


def test_non_numeric_stock(tmp_path):
    manager = im.InventoryManager(MemoryDB())
    data = make_valid_data()
    data["productos"][0]["stock"] = "invalid"
    path = tmp_path / "inv.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    summary = manager.importar_inventario_json(str(path), dry_run=True, strict=False)
    assert any(issue["path"] == "productos[0].stock" for issue in summary["errors"])


def test_missing_section_is_error(tmp_path):
    manager = im.InventoryManager(MemoryDB())
    data = make_valid_data()
    data.pop("productos")
    path = tmp_path / "inv.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    summary = manager.importar_inventario_json(str(path), dry_run=True, strict=False)
    assert any(issue["path"] == "productos" and issue["severity"] == "error" for issue in summary["errors"])


def test_migration_applied(tmp_path):
    manager = im.InventoryManager(MemoryDB())
    data = make_valid_data()
    path = tmp_path / "inv.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    summary = manager.importar_inventario_json(str(path), dry_run=True)
    assert not summary["errors"]
    assert any("Distribuidores" in m for m in summary["migrations_applied"])


def test_vendedor_id_optional(tmp_path):
    manager = im.InventoryManager(MemoryDB())
    data = make_valid_data()
    data["ventas"][0]["vendedor_id"] = None
    path = tmp_path / "inv.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    summary = manager.importar_inventario_json(str(path), dry_run=True, strict=False)
    assert not any(issue["path"] == "ventas[0].vendedor_id" for issue in summary["errors"])
