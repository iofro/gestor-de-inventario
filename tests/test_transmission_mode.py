import pytest
from pathlib import Path
import json
import dte
from utils.docs import build_invoice_json
from utils.doc_generation import generate_invoice_pdf, generate_ticket_pdf

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

def test_build_json_includes_transmission(tmp_path):
    template = tmp_path / "t.json"
    template.write_text('{"identificacion": {}, "receptor": {}, "cuerpoDocumento": [], "resumen": {}}')
    venta = {
        "numero_control": "NC",
        "codigo_generacion": "CG",
        "fecha": "2024-01-01",
        "tipo_operacion": 2,
    }
    data = build_invoice_json(venta, {}, [], template_path=str(template))
    assert data["identificacion"]["tipoOperacion"] == 2


def test_generate_invoice_registers_pending(tmp_path, monkeypatch):
    db = FakeDB()
    venta = {"id": 1, "fecha": "2024-01-01", "total": 10, "tipo_operacion": 2}
    db._ventas.append(venta)
    db.detalles[1] = [{"cantidad": 1, "precio_unitario": 10}]
    man = Manager(db)
    pdf = tmp_path / "fact.pdf"
    js = tmp_path / "fact.json"
    def fake_paths(date, cliente, identifier, doc_type, root=None):
        pdf.parent.mkdir(parents=True, exist_ok=True)
        return str(pdf), str(js)
    monkeypatch.setattr("utils.doc_generation.get_document_paths", fake_paths)
    generate_invoice_pdf(man, 1)
    assert db.pending


def test_generate_ticket_registers_pending(tmp_path, monkeypatch):
    db = FakeDB()
    venta = {"id": 1, "fecha": "2024-01-01", "total": 5}
    db._ventas.append(venta)
    db.detalles[1] = [{"cantidad": 1, "precio_unitario": 5, "descripcion": "P"}]
    man = Manager(db)
    pdf = tmp_path / "ticket.pdf"
    js = tmp_path / "ticket.json"

    def fake_paths(date, cliente, identifier, doc_type, root=None):
        pdf.parent.mkdir(parents=True, exist_ok=True)
        return str(pdf), str(js)

    def fake_gen(venta, detalles, fname, dte_data=None):
        Path(fname).write_text("PDF")

    monkeypatch.setattr("utils.doc_generation.get_document_paths", fake_paths)
    monkeypatch.setattr("utils.doc_generation.generar_ticket_personalizado", fake_gen)
    monkeypatch.setattr(dte, "get_default_modo_transmision", lambda: "contingencia")

    generate_ticket_pdf(man, 1)
    assert db.pending == [(1, "2")]


def test_get_default_modo_transmision_reads_file(tmp_path, monkeypatch):
    datos = {"dte_api": {"modo_transmision": "contingencia"}}
    cfg = tmp_path / "datos_negocio.json"
    cfg.write_text(json.dumps(datos), encoding="utf-8")
    monkeypatch.setattr(dte, "DATOS_NEGOCIO_PATH", str(cfg))
    assert dte.get_default_modo_transmision() == "contingencia"
    datos["dte_api"]["modo_transmision"] = "normal"
    cfg.write_text(json.dumps(datos), encoding="utf-8")
    assert dte.get_default_modo_transmision() == "normal"


def test_generate_ticket_pdf_applies_contingency_flags(tmp_path, monkeypatch):
    db = FakeDB()
    venta = {"id": 1, "fecha": "2024-01-01", "total": 5}
    db._ventas.append(venta)
    db.detalles[1] = [{"cantidad": 1, "precio_unitario": 5, "descripcion": "P"}]
    db.cursor = object()
    man = Manager(db)
    pdf = tmp_path / "ticket.pdf"
    js = tmp_path / "ticket.json"

    def fake_paths(date, cliente, identifier, doc_type, root=None):
        pdf.parent.mkdir(parents=True, exist_ok=True)
        return str(pdf), str(js)

    def fake_gen(venta, detalles, fname, dte_data=None):
        Path(fname).write_text("PDF")

    called = {}

    def fake_dte_json(db_obj, vid, *, tipo_dte, tipo_operacion, tipo_contingencia=None, motivo_contin=None, extra=None, **k):
        called["args"] = (
            tipo_dte,
            tipo_operacion,
            tipo_contingencia,
            motivo_contin,
            extra,
        )
        return {"resumen": {"totalLetras": "X"}}

    monkeypatch.setattr("utils.doc_generation.get_document_paths", fake_paths)
    monkeypatch.setattr("utils.doc_generation.generar_ticket_personalizado", fake_gen)
    monkeypatch.setattr("utils.doc_generation.generar_dte_json", fake_dte_json)
    monkeypatch.setattr(dte, "get_default_modo_transmision", lambda: "contingencia")
    monkeypatch.setattr(
        dte, "_load_datos_negocio", lambda: {"dte_api": {"tipo_contingencia": 3, "motivo_contin": "fallo"}}
    )

    generate_ticket_pdf(man, 1)

    tipo_dte, tipo_op, tipo_cont, motivo, extra = called["args"]
    assert tipo_dte == "01"
    assert tipo_op == 2
    assert tipo_cont == 3
    assert motivo == "fallo"
    assert extra.get("es_ticket")

