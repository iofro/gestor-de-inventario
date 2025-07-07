import os
import json
import pytest

import inventory_manager as im
import ui_mainwindow
from PyQt5.QtWidgets import QApplication

class MemoryDB(im.DB):
    def __init__(self):
        super().__init__(db_name=":memory:")

def make_inv(path):
    data = {
        "Distribuidores": [],
        "vendedores": [],
        "productos": [],
        "clientes": [{"id": 1, "nombre": "C"}],
        "ventas": [{"id": 1, "fecha": "2024-01-01", "total": 5, "cliente_id": 1}],
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
    return str(p)

@pytest.fixture(scope="module")
def qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    return app

def test_sales_table_populated_after_import(qt_app, tmp_path, monkeypatch):
    monkeypatch.setattr(im, "DB", MemoryDB)
    inv = make_inv(tmp_path)
    monkeypatch.setattr(ui_mainwindow, "LAST_INVENTORY_PATH", tmp_path / "last.json")
    monkeypatch.setattr(ui_mainwindow.QFileDialog, "getOpenFileName", lambda *a, **k: (inv, ""))
    monkeypatch.setattr(ui_mainwindow.QMessageBox, "information", lambda *a, **k: None)
    window = ui_mainwindow.MainWindow()
    assert window.sales_tab.sales_table.rowCount() == 0
    window.cargar_inventario()
    assert window.sales_tab.sales_table.rowCount() == 1
