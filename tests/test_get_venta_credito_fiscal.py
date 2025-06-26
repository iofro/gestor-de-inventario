import pytest
from db import DB


def create_db():
    return DB(":memory:")


def test_get_venta_credito_fiscal():
    db = create_db()
    db.add_cliente("Cliente", "", "", "", "", "", "", "", "", "")
    cid = db.cursor.lastrowid

    venta_id = db.add_venta_credito_fiscal(cid, "2024-01-01", 100, "NRC", "NIT", "GIRO")

    row = db.get_venta_credito_fiscal(venta_id)
    assert row is not None
    assert row["venta_id"] == venta_id
    assert row["cliente_id"] == cid


def test_get_venta_credito_fiscal_none():
    db = create_db()
    assert db.get_venta_credito_fiscal(1) is None

