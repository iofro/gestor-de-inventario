import json
import inventory_manager as im

class MemoryDB(im.DB):
    def __init__(self):
        super().__init__(db_name=":memory:")


def make_inv(path):
    data = {
        "Distribuidores": [],
        "vendedores": [],
        "productos": [],
        "clientes": [{"id": 1, "nombre": "C1", "codigo": "C001"}],
        "ventas": [{"id": 1, "fecha": "2024-01-01", "total": 5, "cliente_id": 1}],
        "compras": [],
        "movimientos": [],
        "detalles_venta": [],
        "detalles_compra": [],
        "trabajadores": [],
        "datos_negocio": None,
        "ventas_credito_fiscal": [
            {"venta_id": 1, "cliente_id": 1, "nrc": "123", "nit": "n1", "giro": "g"}
        ],
    }
    p = path / "inv.json"
    p.write_text(json.dumps(data))
    return p


def test_import_resets_fiscal_sales(tmp_path, monkeypatch):
    monkeypatch.setattr(im, "DB", MemoryDB)
    man = im.InventoryManager()
    path = make_inv(tmp_path)

    man.importar_inventario_json(str(path))
    count1 = man.db.cursor.execute(
        "SELECT COUNT(*) FROM ventas_credito_fiscal"
    ).fetchone()[0]

    man.importar_inventario_json(str(path))
    count2 = man.db.cursor.execute(
        "SELECT COUNT(*) FROM ventas_credito_fiscal"
    ).fetchone()[0]

    assert count1 == 1
    assert count2 == 1
