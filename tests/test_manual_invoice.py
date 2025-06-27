import os
import pytest
from PyQt5.QtWidgets import QApplication, QDialog

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

def test_manual_invoice_button_opens_dialog(qt_app, monkeypatch):
    db = DB(":memory:")
    man = Manager(db)
    tab = SalesTab(man)

    opened = {}
    def fake_exec(self):
        opened['called'] = True
        return QDialog.Rejected
    monkeypatch.setattr(ManualInvoiceDialog, 'exec_', fake_exec)

    tab.new_invoice_btn.click()
    assert opened.get('called') is True
