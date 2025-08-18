import pytest
import inventory_manager
from db import DB


def create_manager(monkeypatch):
    monkeypatch.setattr(inventory_manager, "DB", lambda: DB(":memory:"))
    man = inventory_manager.InventoryManager()
    return man


def test_add_vendedor_duplicate_codigo_db():
    db = DB(":memory:")
    db.add_vendedor("V1", codigo="V001")
    with pytest.raises(ValueError):
        db.add_vendedor("V2", codigo="V001")


def test_add_vendedor_duplicate_codigo_manager(monkeypatch):
    man = create_manager(monkeypatch)
    man.add_vendedor("V1", codigo="V001")
    with pytest.raises(ValueError):
        man.add_vendedor("V2", codigo="V001")
