from __future__ import annotations

def _insert_sale(db):
    db.cursor.execute(
        "INSERT INTO clientes (codigo, nombre) VALUES (?, ?)",
        ("C001", "Cliente"),
    )
    cliente_id = db.cursor.lastrowid
    db.cursor.execute(
        "INSERT INTO ventas (fecha, total, cliente_id) VALUES (?, ?, ?)",
        ("2024-01-01", 10, cliente_id),
    )
    db.conn.commit()
    return db.cursor.lastrowid


def test_update_factura_pdf_path_updates_latest_entry(db_conn, tmp_path):
    venta_id = _insert_sale(db_conn)

    older = str(tmp_path / "old.pdf")
    newer = str(tmp_path / "new.pdf")
    canonical = str(tmp_path / "canonical.pdf")

    db_conn.cursor.execute(
        "INSERT INTO facturas_pdf (venta_id, tipo, ruta, fecha_creacion) VALUES (?, ?, ?, ?)",
        (venta_id, "CF", older, "2024-01-01 09:00:00"),
    )
    db_conn.cursor.execute(
        "INSERT INTO facturas_pdf (venta_id, tipo, ruta, fecha_creacion) VALUES (?, ?, ?, ?)",
        (venta_id, "CF", newer, "2024-01-01 10:00:00"),
    )
    db_conn.conn.commit()

    assert db_conn.update_factura_pdf_path(venta_id, canonical) is True

    rows = db_conn.cursor.execute(
        "SELECT ruta FROM facturas_pdf WHERE venta_id=? ORDER BY fecha_creacion",
        (venta_id,),
    ).fetchall()

    assert rows[0]["ruta"] == older
    assert rows[1]["ruta"] == canonical
    assert db_conn.update_factura_pdf_path(venta_id, canonical) is False


def test_update_factura_pdf_path_missing_entry(db_conn, tmp_path):
    missing_path = str(tmp_path / "missing.pdf")
    assert db_conn.update_factura_pdf_path(9999, missing_path) is False
