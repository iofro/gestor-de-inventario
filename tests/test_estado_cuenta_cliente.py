import pytest
from db import DB


def create_db():
    return DB(":memory:")


def test_estado_cuenta_cliente_exclusive():
    db = create_db()
    db.add_cliente("Juan", "", "", "", "", "", "", "", "", "")
    cid1 = db.cursor.lastrowid
    db.add_cliente("Ana", "", "", "", "", "", "", "", "", "")
    cid2 = db.cursor.lastrowid

    db.add_venta("2024-01-01", 100, cliente_id=cid1)
    db.add_venta("2024-01-05", 150, cliente_id=cid1)
    db.add_venta("2024-01-03", 200, cliente_id=cid2)

    db.add_pago(cid1, 80, "2024-01-06")
    db.add_pago(cid2, 50, "2024-01-07")

    estado = db.get_estado_cuenta_cliente(cid1)
    assert estado["total_acumulado"] == 250
    assert estado["saldo"] == 170
    assert len(estado["historial_compras"]) == 2
    assert len(estado["pagos_aplicados"]) == 1
