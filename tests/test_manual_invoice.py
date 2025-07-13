import os
import pytest
from PyQt5.QtWidgets import QApplication, QDialog, QTableWidgetItem, QMessageBox
from PyQt5.QtGui import QDesktopServices

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


def test_manual_invoice_consumidor_final_fields(qt_app):
    dialog = ManualInvoiceDialog()
    dialog.type_combo.setCurrentIndex(0)

    required = [
        'cf_codigo_generacion',
        'cf_numero_control',
        'cf_sello',
        'cf_condicion_pago',
        'cf_no_remision',
        'cf_orden_no',
        'cf_vendedor',
        'cf_venta_cuenta',
        'cf_total_letras',
    ]

    for name in required:
        assert hasattr(dialog, name), f"Dialog missing field {name}"


def test_preview_uses_stored_pdf(qt_app, tmp_path, monkeypatch):
    db = DB(":memory:")
    venta_id = db.add_venta("2024-01-01", 5)
    man = Manager(db)
    tab = SalesTab(man)
    tab.sales_table.setRowCount(1)
    tab.sales_table.setItem(0, 0, QTableWidgetItem(str(venta_id)))
    tab.sales_table.selectRow(0)

    pdf = tmp_path / "fact.pdf"
    pdf.write_text("x")
    db.add_factura_pdf(venta_id, "CF", str(pdf))

    called = {"gen": False}
    def fake_generate(vid):
        called["gen"] = True
        return str(pdf)
    monkeypatch.setattr(tab, "_generate_invoice_pdf", fake_generate)
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda *a, **k: None)

    tab.preview_pdf()
    assert called["gen"] is False
