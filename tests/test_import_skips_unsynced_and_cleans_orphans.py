import json
import inventory_manager as im


class MemoryDB(im.DB):
    def __init__(self):
        super().__init__(db_name=":memory:")


def make_inv(path):
    data = {
        "Distribuidores": [],
        "vendedores": [],
        "productos": [
            {
                "id": 1,
                "nombre": "P",
                "codigo": "P1",
                "sku": "S1",
                "vendedor_id": None,
                "Distribuidor_id": None,
                "precio_compra": 1,
                "precio_venta_minorista": 2,
                "precio_venta_mayorista": 3,
                "stock": 10,
            }
        ],
        "clientes": [{"id": 1, "nombre": "C"}],
        "ventas": [
            {
                "id": 1,
                "fecha": "2024-01-01",
                "total": 5,
                "cliente_id": 1,
                "sincronizada": 1,
            },
            {
                "id": 2,
                "fecha": "2024-01-02",
                "total": 5,
                "cliente_id": 1,
                "sincronizada": 0,
            },
            {
                "id": 3,
                "fecha": "2024-01-03",
                "total": 5,
                "cliente_id": 1,
                "sincronizada": 1,
            },
        ],
        "compras": [],
        "movimientos": [],
        "detalles_venta": [
            {
                "venta_id": 1,
                "producto_id": 1,
                "cantidad": 1,
                "precio_unitario": 5,
                "descuento": 0,
                "descuento_tipo": "",
                "iva": 0,
                "comision": 0,
                "iva_tipo": "",
                "tipo_fiscal": "Gravada",
                "extra": None,
                "precio_con_iva": 5,
                "vendedor_id": None,
            },
            {
                "venta_id": 2,
                "producto_id": 1,
                "cantidad": 1,
                "precio_unitario": 5,
                "descuento": 0,
                "descuento_tipo": "",
                "iva": 0,
                "comision": 0,
                "iva_tipo": "",
                "tipo_fiscal": "Gravada",
                "extra": None,
                "precio_con_iva": 5,
                "vendedor_id": None,
            },
        ],
        "detalles_compra": [],
        "trabajadores": [],
        "datos_negocio": None,
        "ventas_credito_fiscal": [],
        "dte_envios": [],
        "notas": [],
        "facturas_pdf": [],
        "tickets_pdf": [],
    }
    p = path / "inv.json"
    p.write_text(json.dumps(data))
    return p


def test_import_skips_unsynced_and_cleans_orphans(tmp_path):
    man = im.InventoryManager(MemoryDB())
    path = make_inv(tmp_path)
    man.importar_inventario_json(str(path))

    cur = man.db.cursor
    ventas = [row["id"] for row in cur.execute("SELECT id FROM ventas").fetchall()]
    assert ventas == [1]
    detalles = cur.execute("SELECT COUNT(*) FROM detalles_venta").fetchone()[0]
    assert detalles == 1
