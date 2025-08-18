import pytest
from db import DB


def test_delete_trabajador_with_sales(tmp_path):
    db = DB(str(tmp_path / "db.sqlite"))
    db.add_trabajador({"nombre": "Vend", "codigo": "T1", "es_vendedor": True})
    trabajador_id = db.get_trabajadores()[0]["id"]
    db.cursor.execute(
        "INSERT INTO vendedores (id, codigo, nombre, descripcion, Distribuidor_id, dui) VALUES (?, ?, ?, ?, ?, ?)",
        (trabajador_id, "V1", "Vend", "", None, None),
    )
    db.conn.commit()
    db.add_venta("2024-01-01", 10, vendedor_id=trabajador_id)
    with pytest.raises(ValueError):
        db.delete_trabajador(trabajador_id)
    assert db.get_trabajador(trabajador_id) is not None
