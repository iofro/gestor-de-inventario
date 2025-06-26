import pytest
from db import DB


def create_db():
    return DB(":memory:")


def test_estado_cuenta_vendedores_summary_and_detail():
    db = create_db()
    db.add_vendedor("Juan")
    vid1 = db.cursor.lastrowid
    db.add_vendedor("Ana")
    vid2 = db.cursor.lastrowid

    db.add_venta("2024-01-01", 100, vendedor_id=vid1)
    db.add_venta("2024-01-02", 50, vendedor_id=vid2)
    db.add_venta("2024-01-03", 150, vendedor_id=vid1)

    resumen = db.get_estado_cuenta_vendedores()
    resumen_dict = {r["vendedor_id"]: r["total_ventas"] for r in resumen}
    assert resumen_dict[vid1] == 250
    assert resumen_dict[vid2] == 50

    detalle = db.get_estado_cuenta_vendedores(vendedor_id=vid1)
    assert len(detalle) == 2
    assert sum(d["total"] for d in detalle) == 250

    detalle_rango = db.get_estado_cuenta_vendedores(
        vendedor_id=vid1, fecha_inicio="2024-01-03", fecha_fin="2024-01-03"
    )
    assert len(detalle_rango) == 1
    assert detalle_rango[0]["total"] == 150
