import json
import os
import uuid
import pytest
from PyQt5.QtWidgets import QTableWidgetItem, QMessageBox

import dte
from sales_tab import SalesTab
from utils.doc_generation import generate_invoice_pdf
import facturacion_tab

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

def test_generate_invoice_creates_json(tmp_path):
    db = FakeDB()
    venta = {"id": 1, "fecha": "2024-01-01", "total": 10}
    db._ventas.append(venta)
    db.detalles[1] = [{"cantidad": 1, "precio_unitario": 10}]
    man = Manager(db)

    pdf_path = tmp_path / "fact.pdf"
    json_path = tmp_path / "fact.json"
    def fake_paths(date, cliente, identifier, doc_type, root=None):
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        return str(pdf_path), str(json_path)
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("utils.doc_generation.get_document_paths", fake_paths)

    generate_invoice_pdf(man, 1)
    monkeypatch.undo()

    assert pdf_path.exists()
    assert json_path.exists()

    data = json.load(open(json_path))
    ident = data.get("identificacion", {})
    assert ident.get("codigoGeneracion")
    assert ident.get("numeroControl")
    assert data.get("cuerpoDocumento")
    assert data.get("resumen", {}).get("totalPagar") == 10


def test_facturacion_tab_generate_invoice_creates_json(tmp_path):
    db = FakeDB()
    venta = {"id": 1, "fecha": "2024-01-01", "total": 10}
    db._ventas.append(venta)
    db.detalles[1] = [{"cantidad": 1, "precio_unitario": 10}]
    man = Manager(db)
    tab = facturacion_tab.FacturacionTab.__new__(facturacion_tab.FacturacionTab)
    tab.manager = man

    pdf_path = tmp_path / "fact.pdf"
    json_path = tmp_path / "fact.json"

    def fake_paths(date, cliente, identifier, doc_type, root=None):
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        return str(pdf_path), str(json_path)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("utils.doc_generation.get_document_paths", fake_paths)

    tab._generate_invoice_pdf(1)
    monkeypatch.undo()

    assert pdf_path.exists()
    assert json_path.exists()

    data = json.load(open(json_path))
    ident = data.get("identificacion", {})
    assert ident.get("codigoGeneracion")
    assert ident.get("numeroControl")
    assert data.get("cuerpoDocumento")
    assert data.get("resumen", {}).get("totalPagar") == 10


def test_generate_invoice_pdf_saves_sobre(tmp_path, monkeypatch):
    db = FakeDB()
    venta = {"id": 1, "fecha": "2024-01-01", "total": 10}
    db._ventas.append(venta)
    db.detalles[1] = [{"cantidad": 1, "precio_unitario": 10}]
    man = Manager(db)

    pdf_path = tmp_path / "fact.pdf"
    json_path = tmp_path / "fact.json"

    def fake_paths(date, cliente, identifier, doc_type, root=None):
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        return str(pdf_path), str(json_path)

    monkeypatch.setattr("utils.doc_generation.get_document_paths", fake_paths)
    monkeypatch.setattr("utils.jws.sign_json", lambda *a, **k: "TOKEN")
    monkeypatch.setattr(dte, "construir_sobre_recepcion", lambda *a, **k: {"estado": "OK"})

    created = {}

    def fake_save(dte_data, jws_token):
        fecha = dte_data.get("identificacion", {}).get("fecEmi") or dte.fecha_emision_hoy_str()
        year = str(fecha)[:4]
        base_dir = tmp_path / "dtes" / year
        os.makedirs(base_dir, exist_ok=True)
        nombre = dte_data.get("identificacion", {}).get("numeroControl") or uuid.uuid4().hex
        json_dest = base_dir / f"{nombre}.json"
        dte._write_json(str(json_dest), dte_data)
        jws_dest = base_dir / f"{nombre}.jws"
        dte._write_json(str(jws_dest), jws_token)
        sobre = dte.construir_sobre_recepcion(jws_token, dte_data)
        if sobre.get("estado") != "Error":
            sobre_dest = base_dir / f"{nombre}_sobre_hacienda.json"
            dte._write_json(str(sobre_dest), sobre)
        created["dir"] = base_dir

    monkeypatch.setattr(dte, "_save_signed_dte", fake_save)

    generate_invoice_pdf(man, 1)

    base_dir = created["dir"]
    files = list(base_dir.iterdir())
    sobre = [f for f in files if f.name.endswith("_sobre_hacienda.json")]
    assert sobre, "sobre no creado"
    base = sobre[0].name.replace("_sobre_hacienda.json", "")
    assert (base_dir / f"{base}.json").exists()
    assert (base_dir / f"{base}.jws").exists()


def test_save_ticket_creates_json(qt_app, tmp_path):
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(SalesTab, "show_sale", lambda self, clear=False: None)
    db = FakeDB()
    venta = {"id": 1, "fecha": "2024-01-01", "total": 10}
    db._ventas.append(venta)
    db.detalles[1] = [{"cantidad": 1, "precio_unitario": 10}]
    man = Manager(db)
    tab = SalesTab(man, check_smtp=False)
    tab.sales_table.setRowCount(1)
    tab.sales_table.setItem(0, 0, QTableWidgetItem("1"))
    tab.sales_table.selectRow(0)

    pdf_path = tmp_path / "ticket.pdf"
    json_path = tmp_path / "ticket.json"
    def fake_paths(date, cliente, identifier, doc_type, root=None):
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        return str(pdf_path), str(json_path)
    monkeypatch.setattr("utils.doc_generation.get_document_paths", fake_paths)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)

    tab.save_ticket()
    monkeypatch.undo()

    assert pdf_path.exists()
    assert json_path.exists()

    data = json.load(open(json_path))
    ident = data.get("identificacion", {})
    assert ident.get("codigoGeneracion")
    assert ident.get("numeroControl")
    assert data.get("cuerpoDocumento")
    assert data.get("resumen", {}).get("totalPagar") == 10
