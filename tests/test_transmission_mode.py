import os
import pytest
from sales_tab import SalesTab
from utils.docs import build_invoice_json

class FakeDB:
    def __init__(self):
        self._ventas = []
        self.detalles = {}
        self.pending = []
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
    def add_dte_pendiente(self, vid, data, modo):
        self.pending.append((vid, modo))

class Manager:
    def __init__(self, db):
        self.db = db
        self._Distribuidores = []
        self._clientes = []
        self._vendedores = []

@pytest.fixture(scope="module")
def qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt5.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])

def test_build_json_includes_transmission(tmp_path):
    template = tmp_path / "t.json"
    template.write_text('{"identificacion": {}, "receptor": {}, "cuerpoDocumento": [], "resumen": {}}')
    venta = {
        "numero_control": "NC",
        "codigo_generacion": "CG",
        "fecha": "2024-01-01",
        "modelo_facturacion": "1 - Facturación previo",
        "tipo_transmision": "2 - Contingencia",
    }
    data = build_invoice_json(venta, {}, [], template_path=str(template))
    assert data["identificacion"]["tipoTransmision"] == "2 - Contingencia"


def test_generate_invoice_registers_pending(qt_app, tmp_path, monkeypatch):
    db = FakeDB()
    venta = {"id": 1, "fecha": "2024-01-01", "total": 10, "tipo_transmision": "2 - Contingencia"}
    db._ventas.append(venta)
    db.detalles[1] = [{"cantidad": 1, "precio_unitario": 10}]
    man = Manager(db)
    tab = SalesTab(man, check_smtp=False)
    pdf = tmp_path / "fact.pdf"
    js = tmp_path / "fact.json"
    def fake_paths(date, cliente, identifier, doc_type, root=None):
        pdf.parent.mkdir(parents=True, exist_ok=True)
        return str(pdf), str(js)
    monkeypatch.setattr("sales_tab.get_document_paths", fake_paths)
    tab._generate_invoice_pdf(1)
    assert db.pending

