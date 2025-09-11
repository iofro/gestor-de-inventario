import json
import inventory_manager as im


class MemoryDB(im.DB):
    def __init__(self):
        super().__init__(db_name=":memory:")


def test_import_product_vendor_mapping(tmp_path, producto_factory):
    manager = im.InventoryManager(MemoryDB())

    producto = producto_factory(
        id=10,
        nombre="P1",
        codigo="C1",
        vendedor_id=5,
        Distribuidor_id=1,
        precio_compra=0,
        precio_venta_minorista=0,
        precio_venta_mayorista=0,
        stock=3,
    )
    data = {
        "Distribuidores": [{"id": 1, "nombre": "D1"}],
        "vendedores": [{"id": 5, "nombre": "V1", "Distribuidor_id": 1, "codigo": "V001"}],
        "productos": [producto],
    }
    path = tmp_path / "inv.json"
    path.write_text(json.dumps(data))

    manager.importar_inventario_json(str(path))

    productos = manager.db.get_productos()
    assert len(productos) == 1
    prod = productos[0]
    vend_id = manager.db.get_vendedores()[0]["id"]
    dist_id = manager.db.get_Distribuidores()[0]["id"]
    assert prod["vendedor_id"] == vend_id
    assert prod["Distribuidor_id"] == dist_id
