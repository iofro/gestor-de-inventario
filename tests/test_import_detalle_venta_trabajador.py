import json
import inventory_manager as im


class MemoryDB(im.DB):
    def __init__(self):
        super().__init__(db_name=":memory:")


def test_import_maps_detalle_trabajador(tmp_path):
    manager = im.InventoryManager(MemoryDB())

    data = {
        "Distribuidores": [],
        "vendedores": [],
        "productos": [
            {
                "id": 1,
                "nombre": "Prod",
                "codigo": "P1",
                "sku": "S1",
                "precio_compra": 0,
                "precio_venta_minorista": 0,
                "precio_venta_mayorista": 0,
                "stock": 1,
            }
        ],
        "clientes": [],
        "trabajadores": [
            {"id": 5, "nombre": "Trab Vend", "codigo": "T1", "es_vendedor": True}
        ],
        "ventas": [{"id": 1, "fecha": "2024-01-01", "total": 10}],
        "detalles_venta": [
            {
                "venta_id": 1,
                "producto_id": 1,
                "cantidad": 1,
                "precio_unitario": 10,
                "descuento": 0,
                "descuento_tipo": "",
                "iva": 0,
                "comision": 0,
                "iva_tipo": "",
                "tipo_fiscal": "Gravada",
                "extra": None,
                "precio_con_iva": 10,
                "vendedor_id": 5,
            }
        ],
        "compras": [],
        "movimientos": [],
        "detalles_compra": [],
        "datos_negocio": None,
        "ventas_credito_fiscal": [],
    }

    path = tmp_path / "inv.json"
    path.write_text(json.dumps(data))

    manager.importar_inventario_json(str(path))

    ventas = manager.db.get_ventas()
    assert len(ventas) == 1
    venta_id = ventas[0]["id"]
    detalles = manager.db.get_detalles_venta(venta_id)
    vend_id = manager.db.get_vendedores()[0]["id"]
    assert detalles[0]["vendedor_id"] == vend_id

