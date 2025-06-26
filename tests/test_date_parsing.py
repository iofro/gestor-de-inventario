import os
import pytest
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QDate

from purchases_tab import PurchasesTab
from sales_tab import SalesTab
from db import DB

class Manager:
    def __init__(self, db):
        self.db = db
        self._Distribuidores = db.get_Distribuidores()
        self._vendedores = db.get_vendedores()
        self._clientes = db.get_clientes()

def setup_db():
    db = DB(":memory:")
    db.add_Distribuidor("D1")
    db.add_vendedor("V1")
    db.add_producto("P", "c1", 1, 1, 0, 0, 0, 10)
    db.add_compra_detallada({
        "fecha": "2024-01-01 10:00:00",
        "producto_id": 1,
        "cantidad": 1,
        "precio_unitario": 10,
        "total": 10,
        "Distribuidor_id": 1,
        "comision_pct": 0,
        "comision_monto": 0,
        "vendedor_id": 1,
    })
    db.add_compra_detallada({
        "fecha": "2024-01-02",
        "producto_id": 1,
        "cantidad": 1,
        "precio_unitario": 10,
        "total": 10,
        "Distribuidor_id": 1,
        "comision_pct": 0,
        "comision_monto": 0,
        "vendedor_id": 1,
    })
    db.add_venta("2024-01-01 12:00:00", 10)
    db.add_venta("2024-01-02", 20)
    return db

@pytest.fixture(scope="module")
def qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    return app

def test_load_purchases_date_formats(qt_app):
    db = setup_db()
    man = Manager(db)
    tab = PurchasesTab(man)
    tab.date_from.setDate(QDate(2024, 1, 1))
    tab.date_to.setDate(QDate(2024, 1, 31))
    tab.load_purchases()
    assert tab.table.rowCount() == 2

    tab.date_from.setDate(QDate(2024, 1, 2))
    tab.load_purchases()
    assert tab.table.rowCount() == 1

def test_load_sales_date_formats(qt_app):
    db = setup_db()
    man = Manager(db)
    tab = SalesTab(man)
    tab.date_from.setDate(QDate(2024, 1, 1))
    tab.date_to.setDate(QDate(2024, 1, 31))
    tab.load_sales()
    assert tab.sales_table.rowCount() == 2

    tab.date_from.setDate(QDate(2024, 1, 2))
    tab.load_sales()
    assert tab.sales_table.rowCount() == 1
