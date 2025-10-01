from decimal import Decimal

from db import DB


def test_add_dte_pendiente_handles_decimal(tmp_path):
    db_path = tmp_path / "inventario.db"
    database = DB(db_path)

    payload = {"resumen": {"totalPagar": Decimal("10.50")}}

    row_id = database.add_dte_pendiente(venta_id=1, dte_json=payload, modo="2")

    pendientes = database.get_dte_pendientes()

    match = next(p for p in pendientes if p["id"] == row_id)

    assert match["dte_json"]["resumen"]["totalPagar"] == Decimal("10.50")
    assert match["modo"] == "2"
