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


def test_add_vendedor_distribuidor_no_crea_trabajador(tmp_path):
    db = DB(str(tmp_path / "db.sqlite"))
    db.add_Distribuidor("Dist 1")
    dist_id = db.get_Distribuidores()[0]["id"]
    db.add_vendedor("Proveedor", Distribuidor_id=dist_id)
    db.cursor.execute("SELECT COUNT(*) FROM trabajadores")
    assert db.cursor.fetchone()[0] == 0
    db.cursor.execute("SELECT COUNT(*) FROM vendedores")
    assert db.cursor.fetchone()[0] == 1
