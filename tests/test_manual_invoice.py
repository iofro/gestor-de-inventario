import os
import pytest
from PyQt5.QtWidgets import QApplication, QDialog, QTableWidgetItem, QMessageBox

from sales_tab import SalesTab
from dialogs import ManualInvoiceDialog
from db import DB

class Manager:
    def __init__(self, db):
        self.db = db
        self._Distribuidores = []
        self._vendedores = []
        self._clientes = []

@pytest.fixture(scope="module")
def qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    return app

def test_manual_invoice_requires_selection(qt_app, monkeypatch):
    db = DB(":memory:")
    man = Manager(db)
    tab = SalesTab(man)

    opened = {}
    def fake_exec(self):
        opened['called'] = True
        return QDialog.Rejected
    monkeypatch.setattr(ManualInvoiceDialog, 'exec_', fake_exec)

    warnings = {}
    def fake_warning(parent, title, message):
        warnings['title'] = title
        warnings['message'] = message
    monkeypatch.setattr(QMessageBox, 'warning', fake_warning)

    # Without selecting a sale, should show warning and not open dialog
    tab.new_invoice_btn.click()
    assert opened.get('called') is None
    assert warnings.get('message') == "No has seleccionado ninguna venta"

    # Add a fake sale and select it
    tab.sales_table.setRowCount(1)
    tab.sales_table.setItem(0, 0, QTableWidgetItem("1"))
    tab.sales_table.selectRow(0)
    opened.clear()
    warnings.clear()
    tab.new_invoice_btn.click()
    assert opened.get('called') is True
