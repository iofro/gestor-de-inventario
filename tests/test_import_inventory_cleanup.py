import json
import inventory_manager as im


class MemoryDB(im.DB):
    def __init__(self):
        super().__init__(db_name=":memory:")


def _empty_inventory(path):
    data = {
        "Distribuidores": [],
        "vendedores": [],
        "productos": [],
        "clientes": [],
        "ventas": [],
        "compras": [],
        "movimientos": [],
        "detalles_venta": [],
        "detalles_compra": [],
        "trabajadores": [],
        "datos_negocio": None,
        "ventas_credito_fiscal": [],
    }
    p = path / "inv.json"
    p.write_text(json.dumps(data))
    return p


def test_import_inventory_clears_related_tables(tmp_path, monkeypatch):
    monkeypatch.setattr(im, "DB", MemoryDB)
    manager = im.InventoryManager()
    db = manager.db

    cliente_id = db.add_cliente("Cliente", "", "", "", "", "", "", "", "", "")
    prod_id = db.add_producto("Prod", "C1", None,  None, None, 1, 2, 3, 5)
    venta_id = db.add_venta("2024-01-01", 10, cliente_id=cliente_id)
    db.add_detalle_venta(venta_id, prod_id, 1, 10)

    db.cursor.execute(
        "INSERT INTO pagos (cliente_id, monto, fecha) VALUES (?, ?, ?)",
        (cliente_id, 5, "2024-01-02"),
    )
    db.cursor.execute(
        "INSERT INTO facturas_pdf (venta_id, tipo, ruta, fecha_creacion) VALUES (?, ?, ?, ?)",
        (venta_id, "F", "ruta", "2024-01-01"),
    )
    db.cursor.execute(
        "INSERT INTO tickets_pdf (venta_id, ruta, fecha_creacion) VALUES (?, ?, ?)",
        (venta_id, "ruta", "2024-01-01"),
    )
    db.conn.commit()

    path = _empty_inventory(tmp_path)
    manager.importar_inventario_json(str(path))

    for table in ["pagos", "facturas_pdf", "tickets_pdf", "ventas", "clientes"]:
        db.cursor.execute(f"SELECT COUNT(*) FROM {table}")
        assert db.cursor.fetchone()[0] == 0
