import sqlite3
import pytest


def test_ventas_cliente_fk_and_index(db_conn):
    """Existing ``ventas`` tables are migrated to add missing constraints."""
    conn = db_conn.conn
    # Replace the automatically created table with one missing the cliente FK
    conn.execute("DROP TABLE ventas")
    conn.execute(
        """
        CREATE TABLE ventas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT,
            total REAL,
            estado TEXT DEFAULT 'Pagada',
            cliente_id INTEGER,
            Distribuidor_id INTEGER,
            vendedor_id INTEGER,
            extra TEXT,
            FOREIGN KEY (Distribuidor_id) REFERENCES Distribuidores(id) ON DELETE RESTRICT,
            FOREIGN KEY (vendedor_id) REFERENCES vendedores(id) ON DELETE RESTRICT
        )
        """
    )
    conn.execute(
        "INSERT INTO ventas (fecha, total, cliente_id) VALUES ('2024-01-01', 100, 1)"
    )
    conn.commit()

    # Run migration on the fixture-provided DB instance
    db_conn.migrate_ventas_cliente_fk()

    db_conn.cursor.execute("PRAGMA foreign_key_list(ventas)")
    fks = db_conn.cursor.fetchall()
    assert any(row[2] == "clientes" and row[3] == "cliente_id" for row in fks)

    db_conn.cursor.execute("PRAGMA index_list(ventas)")
    idxs = [row[1] for row in db_conn.cursor.fetchall()]
    assert "idx_ventas_cliente_id" in idxs

    with pytest.raises(sqlite3.IntegrityError):
        db_conn.add_venta("2024-02-01", 50, cliente_id=999)

