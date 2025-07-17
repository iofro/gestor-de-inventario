import os
import pytest
from PyQt5.QtWidgets import QApplication

from sales_tab import SalesTab
from utils import docs

class FakeDB:
    def __init__(self):
        self._ventas = []
        self.detalles = {}
        self.pdfs = {}
    def get_ventas(self):
        return self._ventas
    def get_venta_credito_fiscal(self, vid):
        return None
    def get_detalles_venta(self, vid):
        return self.detalles.get(vid, [])
    def get_trabajador(self, vid):
        return None
    def add_factura_pdf(self, venta_id, tipo, ruta):
        self.pdfs[venta_id] = ruta
    def add_ticket_pdf(self, *a, **k):
        pass
    def get_ticket_pdf(self, vid):
        return None
    def get_factura_pdf(self, vid):
        return self.pdfs.get(vid)

class Manager:
    def __init__(self, db):
        self.db = db
        self._Distribuidores = []
        self._clientes = []
        self._vendedores = []

@pytest.fixture(scope="module")
def qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def test_preview_keeps_pdfs(qt_app, tmp_path, monkeypatch):
    db = FakeDB()
    man = Manager(db)

    db._ventas = [
        {"id": 1, "fecha": "2024-01-01", "total": 5},
        {"id": 2, "fecha": "2024-01-02", "total": 10},
    ]
    db.detalles = {
        1: [{"cantidad": 1, "precio_unitario": 5}],
        2: [{"cantidad": 2, "precio_unitario": 5}],
    }

    def fake_paths(date, cliente, identifier, doc_type, root=None):
        return docs.get_document_paths(date, cliente, identifier, doc_type, root=tmp_path)

    monkeypatch.setattr("sales_tab.get_document_paths", fake_paths)

    tab = SalesTab(man)

    pdf1 = tab._generate_invoice_pdf(1)
    pdf2 = tab._generate_invoice_pdf(2)

    tab.load_sales()
    tab.sales_table.selectRow(0)
    tab.show_sale()
    tab.sales_table.selectRow(1)
    tab.show_sale()

    assert os.path.exists(pdf1)
    assert os.path.exists(pdf2)
