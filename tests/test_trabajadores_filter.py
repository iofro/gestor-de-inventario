from db import DB


def _prepare_db(tmp_path):
    db = DB(str(tmp_path / "db.sqlite"))
    db.add_trabajador({"codigo": "T1", "nombre": "Carlos", "area": "Ventas"})
    db.add_trabajador({"codigo": "T2", "nombre": "Ana", "area": "ventas"})
    db.add_trabajador({"codigo": "T3", "nombre": "Luis", "area": "Atención al Cliente"})
    return db


def test_get_trabajadores_area_case_insensitive(tmp_path):
    db = _prepare_db(tmp_path)
    trabajadores = db.get_trabajadores(area="VENTAS")
    codigos = {t["codigo"] for t in trabajadores}
    assert codigos == {"T1", "T2"}


def test_get_trabajadores_area_partial_match(tmp_path):
    db = _prepare_db(tmp_path)
    trabajadores = db.get_trabajadores(area="vent")
    codigos = {t["codigo"] for t in trabajadores}
    assert codigos == {"T1", "T2"}

    trabajadores_cliente = db.get_trabajadores(area="cliente")
    codigos_cliente = {t["codigo"] for t in trabajadores_cliente}
    assert codigos_cliente == {"T3"}
