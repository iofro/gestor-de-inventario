import json
import inventory_manager as im


class MemoryDB(im.DB):
    def __init__(self):
        super().__init__(db_name=":memory:")


def _inventory_with_duplicate(path):
    data = {
        "Distribuidores": [],
        "vendedores": [
            {"id": 1, "nombre": "Vend", "codigo": "T1", "dui": "", "descripcion": ""}
        ],
        "productos": [],
        "clientes": [],
        "ventas": [],
        "compras": [],
        "movimientos": [],
        "detalles_venta": [],
        "detalles_compra": [],
        "trabajadores": [
            {"id": 1, "nombre": "Vend", "codigo": "T1", "dui": "", "es_vendedor": True},
            {"id": 2, "nombre": "Trab", "codigo": "T2", "dui": ""},
        ],
        "datos_negocio": None,
        "ventas_credito_fiscal": [],
    }
    p = path / "inv.json"
    p.write_text(json.dumps(data))
    return p


def test_import_trabajador_duplicate_codigo(tmp_path):
    manager = im.InventoryManager(MemoryDB())
    path = _inventory_with_duplicate(tmp_path)

    manager.importar_inventario_json(str(path))

    trabajadores = manager.db.get_trabajadores()
    codigos = {t["codigo"] for t in trabajadores}
    assert codigos == {"T1", "T2"}
    assert len(trabajadores) == 2

    vendedores = manager.db.get_vendedores()
    assert len(vendedores) == 1
    assert vendedores[0]["codigo"] == "T1"
