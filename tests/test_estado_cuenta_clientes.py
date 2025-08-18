import pytest
from db import DB


def create_db():
    return DB(":memory:")


def test_estado_cuenta_clientes_summary_and_detail():
    db = create_db()
    db.add_cliente("Juan", "", "", "", "", "", "", "", "", "")
    cid1 = db.cursor.lastrowid
    db.add_cliente("Ana", "", "", "", "", "", "", "", "", "")
    cid2 = db.cursor.lastrowid

    db.add_venta("2024-01-01", 100, cliente_id=cid1)
    db.add_venta("2024-01-02", 50, cliente_id=cid2)
    db.add_venta("2024-01-03", 150, cliente_id=cid1)

    resumen = db.get_estado_cuenta_clientes()
    resumen_dict = {r["cliente_id"]: r["total_compras"] for r in resumen}
    assert resumen_dict[cid1] == 250
    assert resumen_dict[cid2] == 50

    detalle = db.get_estado_cuenta_clientes(cliente_id=cid1)
    assert len(detalle) == 2
    assert sum(d["total"] for d in detalle) == 250

    detalle_rango = db.get_estado_cuenta_clientes(
        cliente_id=cid1, fecha_inicio="2024-01-03", fecha_fin="2024-01-03"
    )
    assert len(detalle_rango) == 1
    assert detalle_rango[0]["total"] == 150
