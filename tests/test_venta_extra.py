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


def test_credito_fiscal_extra_persisted_in_ventas(db_conn):
    db_conn.add_cliente(
        nombre="Cliente",
        nrc="",
        nit="",
        dui="",
        giro="",
        telefono="",
        email="cli@example.com",
        direccion="San Salvador",
        departamento="06",
        municipio="23",
    )
    cliente_id = db_conn.cursor.lastrowid

    extra = {
        "sumas": 100,
        "descuentos": 5,
        "iva": 13,
        "subtotal": 108,
        "ventas_exentas": 10,
        "ventas_no_sujetas": 2,
    }

    venta_id = db_conn.add_venta_credito_fiscal(
        cliente_id=cliente_id,
        fecha="2024-01-01",
        total=120,
        nrc="",
        nit="",
        giro="",
        sumas=extra["sumas"],
        descuentos=extra["descuentos"],
        iva=extra["iva"],
        subtotal=extra["subtotal"],
        ventas_exentas=extra["ventas_exentas"],
        ventas_no_sujetas=extra["ventas_no_sujetas"],
        total_letras="CIENTO VEINTE",
        extra=extra,
    )

    row = db_conn.cursor.execute(
        "SELECT extra FROM ventas WHERE id=?", (venta_id,)
    ).fetchone()
    assert row is not None and row["extra"]
    stored = json.loads(row["extra"])
    assert stored == extra
