import pytest
import inventory_manager
from db import DB


def create_manager():
    db = DB(":memory:")
    man = inventory_manager.InventoryManager(db)
    return man


def test_add_vendedor_duplicate_codigo_db():
    db = DB(":memory:")
    db.add_vendedor("V1", codigo="V001")
    with pytest.raises(ValueError):
        db.add_vendedor("V2", codigo="V001")


def test_add_vendedor_duplicate_codigo_manager():
    man = create_manager()
    man.add_vendedor("V1", codigo="V001")
    with pytest.raises(ValueError):
        man.add_vendedor("V2", codigo="V001")
