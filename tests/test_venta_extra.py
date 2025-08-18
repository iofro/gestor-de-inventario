import json


def test_add_venta_with_extra_dict(db_conn):
    """Ensure ``extra`` dicts are stored as JSON strings."""
    venta_id = db_conn.add_venta(
        "2024-01-01", 100, extra={"note": "test", "flag": True}
    )
    ventas = db_conn.get_ventas()
    assert len(ventas) == 1
    venta = ventas[0]
    assert venta["id"] == venta_id
    stored = json.loads(venta["extra"])
    assert stored == {"note": "test", "flag": True}
