import json
import inventory_manager
from db import DB


def create_manager(monkeypatch):
    monkeypatch.setattr(inventory_manager, "DB", lambda: DB(":memory:"))
    man = inventory_manager.InventoryManager()
    db = man.db
    db.add_Distribuidor("D1")
    dist1 = db.cursor.lastrowid
    db.add_Distribuidor("D2")
    dist2 = db.cursor.lastrowid
    db.add_vendedor("V1", Distribuidor_id=dist1)
    vend1 = db.cursor.lastrowid
    db.add_vendedor("V2", Distribuidor_id=dist2)
    vend2 = db.cursor.lastrowid
    db.add_producto("P1", "C1", None,  vend1, dist1, 1, 2, 3, 10)
    db.add_producto("P2", "C2", None,  vend2, dist2, 1, 2, 3, 10)
    man.refresh_data()
    return man, db, vend1, vend2, dist1, dist2


def test_filters_modify_product_set(monkeypatch):
    man, db, vend1, vend2, dist1, dist2 = create_manager(monkeypatch)

    assert {p["codigo"] for p in man._products} == {"C1", "C2"}

    man.filter_products(vendedor_id=vend1)
    assert [p["codigo"] for p in man._products] == ["C1"]

    man.filter_vendedor_id = vend2
    assert [p["codigo"] for p in man._products] == ["C2"]

    man.filter_vendedor_id = None
    man.filter_Distribuidor_id = dist1
    assert [p["codigo"] for p in man._products] == ["C1"]

    man.filter_Distribuidor_id = None
    man.filter_search = "P2"
    assert [p["codigo"] for p in man._products] == ["C2"]


def test_export_json_contains_sections(monkeypatch, tmp_path):
    man, db, vend1, vend2, dist1, dist2 = create_manager(monkeypatch)
    db.add_cliente("Cliente", "", "", "", "", "", "", "", "", "")
    cliente_id = db.cursor.lastrowid
    db.add_venta("2024-01-01", 10, cliente_id=cliente_id, vendedor_id=vend1, Distribuidor_id=dist1)
    man.refresh_data()

    export_file = tmp_path / "export.json"
    man.exportar_inventario_json(str(export_file))

    with open(export_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert isinstance(data.get("productos"), list)
    assert isinstance(data.get("clientes"), list)
    assert isinstance(data.get("ventas"), list)
    assert isinstance(data.get("trabajadores"), list)
