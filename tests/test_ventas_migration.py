import sqlite3
import pytest

from db import DB


def test_ventas_cliente_fk_and_index(tmp_path):
    db_path = tmp_path / "db.sqlite"
    conn = sqlite3.connect(db_path)
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
    conn.close()

    db = DB(str(db_path))

    db.cursor.execute("PRAGMA foreign_key_list(ventas)")
    fks = db.cursor.fetchall()
    assert any(row[2] == "clientes" and row[3] == "cliente_id" for row in fks)

    db.cursor.execute("PRAGMA index_list(ventas)")
    idxs = [row[1] for row in db.cursor.fetchall()]
    assert "idx_ventas_cliente_id" in idxs

    with pytest.raises(sqlite3.IntegrityError):
        db.add_venta("2024-02-01", 50, cliente_id=999)

