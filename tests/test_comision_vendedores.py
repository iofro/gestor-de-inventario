import pytest
from db import DB


def create_db():
    return DB(":memory:")


def test_get_comision_vendedores():
    db = create_db()
    db.add_vendedor("V1")
    vid1 = db.cursor.lastrowid
    db.add_vendedor("V2")
    vid2 = db.cursor.lastrowid
    db.add_producto("P1", "C1", None,  vid1, None, 0, 0, 0, 10)
    pid1 = db.cursor.lastrowid
    db.add_producto("P2", "C2", None,  vid2, None, 0, 0, 0, 10)
    pid2 = db.cursor.lastrowid

    v1 = db.add_venta("2024-01-01", 100, vendedor_id=vid1)
    db.add_detalle_venta(v1, pid1, 1, 100, comision=10, vendedor_id=vid1)
    v2 = db.add_venta("2024-01-02", 50, vendedor_id=vid2)
    db.add_detalle_venta(v2, pid2, 1, 50, comision=5, vendedor_id=vid2)
    v3 = db.add_venta("2024-01-03", 150, vendedor_id=vid1)
    db.add_detalle_venta(v3, pid1, 1, 150, comision=15, vendedor_id=vid1)

    resumen = db.get_comision_vendedores()
    resumen_dict = {r["vendedor_id"]: r["total_comision"] for r in resumen}
    assert resumen_dict[vid1] == 25
    assert resumen_dict[vid2] == 5

    rango = db.get_comision_vendedores(fecha_inicio="2024-01-03", fecha_fin="2024-01-03")
    assert len(rango) == 1
    assert rango[0]["vendedor_id"] == vid1
    assert rango[0]["total_comision"] == 15
