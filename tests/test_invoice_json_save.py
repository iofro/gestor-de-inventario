import os
import json
import pytest
from PyQt5.QtWidgets import QApplication, QTableWidgetItem, QMessageBox

from sales_tab import SalesTab
from utils import docs

class FakeDB:
    def __init__(self):
        self._ventas = []
        self.detalles = {}
    def get_ventas(self):
        return self._ventas
    def get_venta_credito_fiscal(self, vid):
        return None
    def get_detalles_venta(self, vid):
        return self.detalles.get(vid, [])
    def get_trabajador(self, vid):
        return None
    def add_factura_pdf(self, *a):
        pass
    def add_ticket_pdf(self, *a):
        pass
    def get_ticket_pdf(self, vid):
        return None
    def get_factura_pdf(self, vid):
        return None

class Manager:
    def __init__(self, db):
        self.db = db
        self._Distribuidores = []
        self._clientes = []
        self._vendedores = []

@pytest.fixture(scope="module")
def qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    return app


def test_generate_invoice_creates_json(qt_app, tmp_path):
    db = FakeDB()
    venta = {"id": 1, "fecha": "2024-01-01", "total": 10}
    db._ventas.append(venta)
    db.detalles[1] = [{"cantidad": 1, "precio_unitario": 10}]
    man = Manager(db)
    tab = SalesTab(man)

    pdf_path = tmp_path / "fact.pdf"
    json_path = tmp_path / "fact.json"
    def fake_paths(date, cliente, identifier, doc_type, root=None):
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        return str(pdf_path), str(json_path)
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("sales_tab.get_document_paths", fake_paths)

    tab._generate_invoice_pdf(1)
    monkeypatch.undo()

    assert pdf_path.exists()
    assert json_path.exists()


def test_save_ticket_creates_json(qt_app, tmp_path):
    db = FakeDB()
    venta = {"id": 1, "fecha": "2024-01-01", "total": 10}
    db._ventas.append(venta)
    db.detalles[1] = [{"cantidad": 1, "precio_unitario": 10}]
    man = Manager(db)
    tab = SalesTab(man)
    tab.sales_table.setRowCount(1)
    tab.sales_table.setItem(0, 0, QTableWidgetItem("1"))
    tab.sales_table.selectRow(0)

    pdf_path = tmp_path / "ticket.pdf"
    json_path = tmp_path / "ticket.json"
    def fake_paths(date, cliente, identifier, doc_type, root=None):
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        return str(pdf_path), str(json_path)
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("sales_tab.get_document_paths", fake_paths)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)

    tab.save_ticket()
    monkeypatch.undo()

    assert pdf_path.exists()
    assert json_path.exists()
    data = json.load(open(json_path))
    assert data.get("identificacion", {}).get("codigoGeneracion")
    assert data.get("identificacion", {}).get("numeroControl")
