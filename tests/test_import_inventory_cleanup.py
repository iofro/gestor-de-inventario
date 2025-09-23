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


def _deeply_nested_extra(payload, depth=3):
    value = payload
    for _ in range(depth):
        value = json.dumps(value)
    return value


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
    venta_extra_before = data_before["ventas"][0]["extra"]
    extra_before = data_before["ventas_credito_fiscal"][0]["extra"]
    assert isinstance(extra_before, str)
    assert isinstance(venta_extra_before, str)
    original_size = len(extra_before)

    manager.importar_inventario_json(str(export_path))

    export_path2 = tmp_path / "export2.json"
    manager.exportar_inventario_json(str(export_path2))
    data_after = json.loads(export_path2.read_text())
    venta_extra_after = data_after["ventas"][0]["extra"]
    extra_after = data_after["ventas_credito_fiscal"][0]["extra"]
    assert isinstance(extra_after, str)
    assert isinstance(venta_extra_after, str)
    assert len(extra_after) == original_size
    assert extra_after == extra_before
    assert venta_extra_after == venta_extra_before


def test_import_inventory_cleans_deeply_nested_extra(tmp_path):
    manager = im.InventoryManager(MemoryDB())

    payload = {
        "ventas_no_sujetas": 0,
        "descu_gravada": "5.00",
        "sub_total_ventas": 100,
        "items": [
            {
                "codigo": "SKU-1",
                "descripcion": "Producto demo",
                "cantidad": 2,
                "precio_unitario": 10,
            }
        ],
    }
    deep_extra = _deeply_nested_extra(payload, depth=9)

    data = {
        "Distribuidores": [],
        "vendedores": [],
        "productos": [],
        "clientes": [
            {
                "id": 77,
                "nombre": "Cliente Demo",
                "nrc": "",
                "nit": "",
                "dui": "",
                "giro": "",
                "telefono": "",
                "email": "",
                "direccion": "",
                "departamento": "06",
                "municipio": "23",
            }
        ],
        "ventas": [
            {
                "id": 101,
                "fecha": "2024-03-01",
                "total": 100,
                "cliente_id": 77,
                "Distribuidor_id": None,
                "vendedor_id": None,
                "extra": deep_extra,
                "estado": "Pagada",
                "sincronizada": 1,
            }
        ],
        "compras": [],
        "movimientos": [],
        "detalles_venta": [],
        "detalles_compra": [],
        "dte_envios": [],
        "notas": [],
        "facturas_pdf": [],
        "tickets_pdf": [],
        "datos_negocio": {},
        "trabajadores": [],
        "ventas_credito_fiscal": [
            {
                "venta_id": 101,
                "cliente_id": 77,
                "nrc": "",
                "nit": "",
                "giro": "",
                "no_remision": "",
                "orden_no": "",
                "condicion_pago": "",
                "venta_a_cuenta_de": "",
                "documento_venta_a_cuenta": "",
                "fecha_remision_anterior": "",
                "fecha_remision": "",
                "sumas": 100,
                "iva": 13,
                "subtotal": 113,
                "total_letras": "ciento trece",
                "descuentos": 0,
                "extra": deep_extra,
                "ventas_exentas": 0,
                "ventas_no_sujetas": 0,
            }
        ],
        "tab_order": [],
    }

    path = tmp_path / "deep.json"
    path.write_text(json.dumps(data))

    manager.importar_inventario_json(str(path))

    export_path = tmp_path / "export.json"
    manager.exportar_inventario_json(str(export_path))
    exported = json.loads(export_path.read_text())

    expected_extra = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    venta_extra = exported["ventas"][0]["extra"]
    credit_extra = exported["ventas_credito_fiscal"][0]["extra"]

    assert venta_extra == expected_extra
    assert credit_extra == expected_extra
    assert json.loads(venta_extra) == payload
    assert json.loads(credit_extra) == payload
    assert len(venta_extra) < len(deep_extra)
    assert len(credit_extra) < len(deep_extra)
