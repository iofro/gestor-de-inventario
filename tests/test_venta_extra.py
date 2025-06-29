import json
from db import DB


def create_db():
    return DB(":memory:")


def test_add_venta_with_extra_dict():
    db = create_db()
    venta_id = db.add_venta("2024-01-01", 100, extra={"note": "test", "flag": True})
    ventas = db.get_ventas()
    assert len(ventas) == 1
    venta = ventas[0]
    assert venta["id"] == venta_id
    stored = json.loads(venta["extra"])
    assert stored == {"note": "test", "flag": True}
