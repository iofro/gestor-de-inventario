from db import DB


def test_add_cliente_defaults_to_san_salvador(tmp_path):
    db = DB(tmp_path / "test.db")
    db.add_cliente("Juan", "", "", "", "", "", "", "", None, None)
    row = db.cursor.execute(
        "SELECT direccion, departamento, municipio FROM clientes WHERE nombre=?",
        ("Juan",),
    ).fetchone()
    assert row["direccion"] == "San Salvador"
    assert row["departamento"] == "06"
    assert row["municipio"] == "23"


def test_update_cliente_defaults_to_san_salvador(tmp_path):
    db = DB(tmp_path / "test.db")
    db.add_cliente("Ana", "", "", "", "", "", "", "Calle 1", "01", "02")
    row = db.cursor.execute(
        "SELECT id, codigo FROM clientes WHERE nombre=?",
        ("Ana",),
    ).fetchone()
    cliente_id, codigo = row["id"], row["codigo"]
    db.update_cliente(
        cliente_id,
        codigo,
        "Ana",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        None,
        None,
    )
    row = db.cursor.execute(
        "SELECT direccion, departamento, municipio FROM clientes WHERE id=?",
        (cliente_id,),
    ).fetchone()
    assert row["direccion"] == "San Salvador"
    assert row["departamento"] == "06"
    assert row["municipio"] == "23"
