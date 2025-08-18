import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import json
import pytest

import inventory_manager as im
import ui_mainwindow
from PyQt5.QtWidgets import QApplication, QMessageBox


class MemoryDB(im.DB):
    def __init__(self):
        super().__init__(db_name=":memory:")


@pytest.fixture(scope="module")
def qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    return app


def test_inventory_reset_removes_dependencies(qt_app, monkeypatch, tmp_path):
    monkeypatch.setattr(im, "DB", MemoryDB)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(ui_mainwindow, "LAST_INVENTORY_PATH", tmp_path / "last.json")
    monkeypatch.setattr(im, "DATOS_NEGOCIO_PATH", tmp_path / "datos_negocio.json")
    monkeypatch.setattr(ui_mainwindow, "DATOS_NEGOCIO_PATH", tmp_path / "datos_negocio_ui.json")

    window = ui_mainwindow.MainWindow()
    db = window.manager.db

    # create product
    prod_id = db.add_producto("P1", "C1", None, None, 1, 2, 3, 5)
    # create sale and detail
    venta_id = db.add_venta("2024-01-01", 10)
    db.add_detalle_venta(venta_id, prod_id, 1, 10)
    # create purchase and detail
    compra_id = db.add_compra_detallada({
        "fecha": "2024-01-02",
        "producto_id": prod_id,
        "cantidad": 2,
        "precio_unitario": 1,
        "total": 2,
    })
    db.add_detalle_compra(compra_id, prod_id, 2, 1)

    # ensure data inserted
    db.cursor.execute("SELECT COUNT(*) FROM productos")
    assert db.cursor.fetchone()[0] == 1

    # reset inventory using DB import with empty data
    empty = {
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
    path = tmp_path / "empty.json"
    path.write_text(json.dumps(empty))
    window.manager.importar_inventario_json(str(path))

    for table in ["productos", "ventas", "detalles_venta", "compras", "detalles_compra"]:
        db.cursor.execute(f"SELECT COUNT(*) FROM {table}")
        assert db.cursor.fetchone()[0] == 0


def test_import_inventory_creates_relations(tmp_path, monkeypatch):
    monkeypatch.setattr(im, "DB", MemoryDB)
    manager = im.InventoryManager()

    data = {
        "Distribuidores": [],
        "vendedores": [],
        "productos": [
            {
                "id": 1,
                "nombre": "Prod",
                "codigo": "C1",
                "precio_compra": 1,
                "precio_venta_minorista": 2,
                "precio_venta_mayorista": 3,
                "stock": 5,
            }
        ],
        "clientes": [],
        "ventas": [{"id": 1, "fecha": "2024-01-01", "total": 2}],
        "compras": [{"id": 1, "fecha": "2024-01-02", "total": 5}],
        "movimientos": [],
        "detalles_venta": [
            {"venta_id": 1, "producto_id": 1, "cantidad": 1, "precio_unitario": 2}
        ],
        "detalles_compra": [
            {"compra_id": 1, "producto_id": 1, "cantidad": 5, "precio_unitario": 1}
        ],
        "trabajadores": [],
        "datos_negocio": None,
        "ventas_credito_fiscal": [],
    }
    path = tmp_path / "inv.json"
    path.write_text(json.dumps(data))

    manager.importar_inventario_json(str(path))
    productos = manager.db.get_productos()
    assert len(productos) == 1
    prod = productos[0]

    manager.db.cursor.execute("SELECT producto_id FROM detalles_venta")
    assert manager.db.cursor.fetchone()[0] == prod["id"]

    manager.db.cursor.execute("SELECT producto_id FROM detalles_compra")
    assert manager.db.cursor.fetchone()[0] == prod["id"]

    manager.db.cursor.execute("SELECT COUNT(*) FROM ventas")
    assert manager.db.cursor.fetchone()[0] == 1

    manager.db.cursor.execute("SELECT COUNT(*) FROM compras")
    assert manager.db.cursor.fetchone()[0] == 1
