from db import DB
import pytest

def create_db():
    return DB(":memory:")

def test_add_cliente_duplicate_nit():
    db = create_db()
    db.add_cliente("Juan", "", "nit1", "", "", "", "", "", "", "")
    with pytest.raises(ValueError):
        db.add_cliente("Ana", "", "nit1", "", "", "", "", "", "", "")

def test_update_cliente_duplicate_nit():
    db = create_db()
    db.add_cliente("Juan", "", "nit1", "", "", "", "", "", "", "")
    db.add_cliente("Ana", "", "nit2", "", "", "", "", "", "", "")
    cid2 = db.cursor.lastrowid
    with pytest.raises(ValueError):
        db.update_cliente(cid2, "C-002", "Ana", "", "nit1", "", "", "", "", "", "", "")
