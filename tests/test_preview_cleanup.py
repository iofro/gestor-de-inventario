import os
import pytest

import dte
from sales_tab import SalesTab
from utils import docs
from utils.doc_generation import generate_invoice_pdf

class FakeDB:
    def __init__(self):
        self._ventas = []
        self.detalles = {}
        self.pdfs = {}
    def get_ventas(self, *args, **kwargs):
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

    def fake_dte(db_, vid, **kwargs):
        return {
            "identificacion": {
                "version": 1,
                "tipoDte": "01",
                "codigoGeneracion": f"CG{vid}",
                "numeroControl": f"NC-{vid}",
                "ambiente": "00",
            },
            "resumen": {"totalPagar": 5 * vid},
            "cuerpoDocumento": [{"cantidad": vid, "precioUnitario": 5}],
        }

    def fake_sobre(token, data):
        ident = data.get("identificacion", {})
        return {
            "ambiente": ident.get("ambiente", "00"),
            "idEnvio": 1,
            "version": ident.get("version", 1),
            "tipoDte": ident.get("tipoDte", "01"),
            "codigoGeneracion": ident.get("codigoGeneracion", "CG"),
            "documento": token,
        }

    monkeypatch.setattr("utils.doc_generation.get_document_paths", fake_paths)
    monkeypatch.setattr("utils.doc_generation.generar_dte_json", fake_dte)
    monkeypatch.setattr("utils.jws.sign_json", lambda *a, **k: "TOKEN")
    monkeypatch.setattr(dte, "construir_sobre_recepcion", fake_sobre)

    tab = SalesTab(man, check_smtp=False)

    pdf1 = generate_invoice_pdf(man, 1)
    pdf2 = generate_invoice_pdf(man, 2)

    tab.load_sales()
    tab.sales_table.selectRow(0)
    tab.show_sale()
    tab.sales_table.selectRow(1)
    tab.show_sale()

    assert os.path.exists(pdf1)
    assert os.path.exists(pdf2)
