import pytest
from db import DB


class MemoryDB(DB):
    def __init__(self):
        super().__init__(db_name=":memory:")


def test_limpiar_inventario_handles_missing_tables():
    db = MemoryDB()
    # setup sample data
    prod_id = db.add_producto("P1", "C1", None,  None, None, 1, 2, 3, 5)
    venta_id = db.add_venta("2024-01-01", 10)
    db.add_detalle_venta(venta_id, prod_id, 1, 10)
    cliente_id = db.add_cliente("Cliente", "", "", "", "", "", "", "", "", "")
    db.cursor.execute(
        "INSERT INTO pagos (cliente_id, monto, fecha) VALUES (?, ?, ?)",
        (cliente_id, 5, "2024-01-02"),
    )
    db.conn.commit()

    # drop one optional table to ensure missing tables do not cause errors
    db.cursor.execute("DROP TABLE notas")
    db.conn.commit()

    # should not raise
    db.limpiar_inventario()

    for table in ["detalles_venta", "ventas", "pagos"]:
        db.cursor.execute(f"SELECT COUNT(*) FROM {table}")
        assert db.cursor.fetchone()[0] == 0


def test_limpiar_inventario_rollback(monkeypatch):
    db = MemoryDB()
    prod_id = db.add_producto("P1", "C1", None,  None, None, 1, 2, 3, 5)
    venta_id = db.add_venta("2024-01-01", 10)
    db.add_detalle_venta(venta_id, prod_id, 1, 10)
    cliente_id = db.add_cliente("Cliente", "", "", "", "", "", "", "", "", "")
    db.cursor.execute(
        "INSERT INTO pagos (cliente_id, monto, fecha) VALUES (?, ?, ?)",
        (cliente_id, 5, "2024-01-02"),
    )
    db.conn.commit()

    class FailingCursor:
        def __init__(self, cursor):
            self._cursor = cursor

        def execute(self, sql, *args, **kwargs):
            if sql.startswith("DELETE FROM ventas"):
                raise RuntimeError("Boom")
            return self._cursor.execute(sql, *args, **kwargs)

        def __getattr__(self, name):
            return getattr(self._cursor, name)

    db.cursor = FailingCursor(db.cursor)

    with pytest.raises(RuntimeError):
        db.limpiar_inventario()

    for table in ["detalles_venta", "ventas", "pagos"]:
        db.cursor.execute(f"SELECT COUNT(*) FROM {table}")
        assert db.cursor.fetchone()[0] == 1
