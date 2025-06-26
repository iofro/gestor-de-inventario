import pytest
from db import DB


def create_db():
    return DB(":memory:")


def test_get_venta_credito_fiscal_return():
    db = create_db()
    db.add_cliente("Cli", "", "", "", "", "", "", "", "", "")
    cid = db.cursor.lastrowid
    venta_id = db.add_venta_credito_fiscal(cid, "2024-01-01", 100, "123", "456", "giro")
    data = db.get_venta_credito_fiscal(venta_id)
    assert data is not None
    assert data["venta_id"] == venta_id
    assert data["cliente_id"] == cid
    assert data["nrc"] == "123"


def test_get_venta_credito_fiscal_none():
    db = create_db()
    assert db.get_venta_credito_fiscal(1) is None
