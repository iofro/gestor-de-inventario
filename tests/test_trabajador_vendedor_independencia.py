from db import DB


def test_add_trabajador_es_vendedor_no_crea_vendedor(tmp_path):
    db = DB(str(tmp_path / "db.sqlite"))
    db.add_trabajador({"codigo": "T1", "nombre": "Juan", "es_vendedor": True})
    db.cursor.execute("SELECT COUNT(*) FROM vendedores")
    assert db.cursor.fetchone()[0] == 0


def test_update_trabajador_es_vendedor_no_crea_vendedor(tmp_path):
    db = DB(str(tmp_path / "db.sqlite"))
    db.add_trabajador({"codigo": "T1", "nombre": "Ana"})
    tid = db.get_trabajadores()[0]["id"]
    db.update_trabajador(tid, {"codigo": "T1", "nombre": "Ana", "es_vendedor": True})
    db.cursor.execute("SELECT COUNT(*) FROM vendedores")
    assert db.cursor.fetchone()[0] == 0
