import pytest
from db import DB


def create_db():
    return DB(":memory:")



def test_get_venta_credito_fiscal_basic():
    db = create_db()
    db.add_cliente("Juan", "123", "nit1", "", "giro", "", "", "", "", "")
    cliente_id = db.cursor.lastrowid

    venta_id = db.add_venta_credito_fiscal(
        cliente_id,
        "2024-01-01",
        100.0,
        "123",
        "nit1",
        "giro",
    )

    record = db.get_venta_credito_fiscal(venta_id)
    assert record is not None
    assert record["venta_id"] == venta_id
    assert record["cliente_id"] == cliente_id
    assert record["nrc"] == "123"

   
