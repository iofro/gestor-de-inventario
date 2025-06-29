import pytest
import json
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


def test_extra_is_json_string():
    db = create_db()
    db.add_cliente("Maria", "456", "nit2", "", "giro2", "", "", "", "", "")
    cliente_id = db.cursor.lastrowid

    extra = {"foo": "bar", "num": 1}
    venta_id = db.add_venta_credito_fiscal(
        cliente_id,
        "2024-02-01",
        50.0,
        "456",
        "nit2",
        "giro2",
        extra=extra,
    )

    db.cursor.execute(
        "SELECT extra FROM ventas_credito_fiscal WHERE venta_id=?",
        (venta_id,),
    )
    stored = db.cursor.fetchone()["extra"]
    assert stored == json.dumps(extra)

   
