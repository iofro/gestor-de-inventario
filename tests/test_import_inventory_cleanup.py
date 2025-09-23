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


def test_import_inventory_clears_related_tables(tmp_path):
    manager = im.InventoryManager(MemoryDB())
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


def test_inventory_reimport_does_not_expand_credit_extra(tmp_path):
    manager = im.InventoryManager(MemoryDB())
    db = manager.db

    cliente_id = db.add_cliente(
        "Cliente",
        "123456-7",
        "06141407100012",
        "12345678-9",
        "Comercio",
        "", "", "Direccion", "06", "23",
    )

    extra_payload = {"foo": "bar", "nested": {"value": 1}}

    db.add_venta_credito_fiscal(
        cliente_id,
        "2024-01-01 00:00:00",
        100,
        "123456-7",
        "06141407100012",
        "Comercio",
        extra=extra_payload,
    )

    export_path = tmp_path / "export.json"
    manager.exportar_inventario_json(str(export_path))
    data_before = json.loads(export_path.read_text())
    extra_before = data_before["ventas_credito_fiscal"][0]["extra"]
    assert isinstance(extra_before, str)
    original_size = len(extra_before)

    manager.importar_inventario_json(str(export_path))

    export_path2 = tmp_path / "export2.json"
    manager.exportar_inventario_json(str(export_path2))
    data_after = json.loads(export_path2.read_text())
    extra_after = data_after["ventas_credito_fiscal"][0]["extra"]
    assert isinstance(extra_after, str)
    assert len(extra_after) == original_size
    assert extra_after == extra_before
