import json
from pathlib import Path

import fitz

import dte
from ticket_pdf import generar_ticket_fe_pdf
from utils.doc_generation import generate_ticket_pdf


def test_ticket_fe_pdf_clean(tmp_path):
    venta = {
        "fecha": "2025-01-01",
        "total": 2.0,
        "cliente": "Cliente Demo",
        "documento": "00000000-0",
    }
    detalles = [{"descripcion": "Acetaminofen 500mg", "cantidad": 1, "precio_unitario": 2.0}]
    dte_json = {
        "identificacion": {
            "tipoDte": "01",
            "codigoGeneracion": "12345678-1234-1234-1234-123456789012",
            "numeroControl": "DTE-01-0001",
            "tipoModelo": 1,
            "tipoOperacion": 1,
            "fecEmi": "2025-01-01",
            "horEmi": "12:00:00",
        },
        "emisor": {
            "nombreComercial": "Farmacia X",
            "nit": "0614-290389-102-1",
            "nrc": "123456-7",
            "descActividad": "Farmacia",
            "direccion": {"complemento": "Av. Siempre Viva"},
        },
        "receptor": {"tipoDocumento": "37", "direccion": {"complemento": "Calle 1"}},
        "cuerpoDocumento": [
            {
                "cantidad": 1,
                "uniMedida": "59",
                "descripcion": "Acetaminofen 500mg",
                "precioUni": 2.0,
                "montoTotal": 2.0,
            }
        ],
        "resumen": {
            "totalGravada": 2.0,
            "montoTotalOperacion": 2.0,
            "totalPagar": 2.0,
            "condicionOperacion": 1,
            "pagos": [{"codigo": "01", "montoPago": 2.0}],
        },
    }
    dte_data = {"dteJson": dte_json}
    out = tmp_path / "ticket.pdf"
    generar_ticket_fe_pdf(venta, detalles, archivo=str(out), dte_data=dte_data)

    with fitz.open(out) as doc:
        text = "\n".join(page.get_text() for page in doc)
    normalized = " ".join(text.split())

    for bad in ("apendice", "cuerpoDocumento", "falta", "None"):
        assert bad not in text

    assert "DOCUMENTO TRIBUTARIO ELECTRÓNICO" in normalized
    assert "CONSUMIDOR FINAL" in normalized
    assert "TOTAL A PAGAR" in normalized or "Total a pagar" in text
    lower_text = text.lower()
    assert "condición de pago" in lower_text
    assert "contado" in lower_text


def test_generate_ticket_pdf_defaults_and_persists_es_ticket(tmp_path, monkeypatch):
    venta = {
        "id": 1,
        "fecha": "2025-02-01",
        "total": 2.0,
        "cliente": "Cliente Demo",
        "documento": "00000000-0",
    }
    detalles = [
        {"cantidad": 1, "precio_unitario": 2.0, "descripcion": "Acetaminofen 500mg"}
    ]

    class FakeDB:
        def __init__(self):
            self._ventas = [venta]
            self.detalles = {1: detalles}
            self.extra = {}
            self.ticket_pdf = {}
            self.cursor = object()

        def get_ventas(self):
            return self._ventas

        def get_detalles_venta(self, vid):
            return self.detalles.get(vid, [])

        def add_ticket_pdf(self, vid, filename):
            self.ticket_pdf[vid] = filename

        def update_venta_extra(self, venta_id, extra_dict):
            current = self.extra.setdefault(venta_id, {})
            current.update(extra_dict)
            sale = next(v for v in self._ventas if v["id"] == venta_id)
            sale["extra"] = json.dumps(current)

        def add_dte_pendiente(self, *a):
            pass

    class Manager:
        def __init__(self):
            self.db = FakeDB()
            self._clientes = []

    manager = Manager()

    pdf_path = tmp_path / "ticket.pdf"
    json_path = tmp_path / "ticket.json"

    def fake_paths(date, cliente, identifier, doc_type, root=None):
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        return str(pdf_path), str(json_path)

    sample_dte = {
        "identificacion": {
            "tipoDte": "01",
            "codigoGeneracion": "12345678-1234-1234-1234-123456789012",
            "numeroControl": "DTE-01-0001",
            "tipoModelo": 1,
            "tipoOperacion": 1,
            "fecEmi": "2025-02-01",
            "horEmi": "12:00:00",
        },
        "emisor": {
            "nombreComercial": "Farmacia X",
            "nit": "0614-290389-102-1",
            "nrc": "123456-7",
            "descActividad": "Farmacia",
            "direccion": {"complemento": "Av. Siempre Viva"},
        },
        "receptor": {"tipoDocumento": "37", "direccion": {"complemento": "Calle 1"}},
        "cuerpoDocumento": [
            {
                "cantidad": 1,
                "uniMedida": "59",
                "descripcion": "Acetaminofen 500mg",
                "precioUni": 2.0,
                "montoTotal": 2.0,
            }
        ],
        "resumen": {
            "totalGravada": 2.0,
            "montoTotalOperacion": 2.0,
            "totalPagar": 2.0,
            "condicionOperacion": 1,
            "pagos": [{"codigo": "01", "montoPago": 2.0}],
        },
    }

    def fake_ticket_json(*a, **k):
        return sample_dte

    def fake_sign_and_save(payload, path, return_token=False):
        Path(path).write_text(json.dumps(payload))
        if return_token:
            return path, "token"
        return path

    def fake_save_dte_json(data, filename=None):
        pend = tmp_path / (filename or "pending.json")
        pend.write_text(json.dumps(data))
        return str(pend)

    monkeypatch.setattr("utils.doc_generation.get_document_paths", fake_paths)
    monkeypatch.setattr("utils.doc_generation.generar_ticket_json", fake_ticket_json)
    monkeypatch.setattr("utils.doc_generation.sign_and_save", fake_sign_and_save)
    monkeypatch.setattr(dte, "save_dte_json", fake_save_dte_json)
    monkeypatch.setattr(dte, "construir_sobre_recepcion", lambda *a, **k: {"estado": "Error"})
    monkeypatch.setattr("utils.doc_generation.versioned_dte.save_estado", lambda *a, **k: None)
    monkeypatch.setattr(dte, "get_default_modo_transmision", lambda: "normal")

    generated = generate_ticket_pdf(manager, 1)

    assert manager.db.extra[1]["es_ticket"] is True
    assert Path(generated) == pdf_path
    assert json_path.exists()

    with fitz.open(pdf_path) as doc:
        text = "\n".join(page.get_text() for page in doc)
    normalized = " ".join(text.split())

    assert "DOCUMENTO TRIBUTARIO ELECTRÓNICO" in normalized
    assert "CONSUMIDOR FINAL" in normalized
    lower_text = text.lower()
    assert "condición de pago" in lower_text
    assert "contado" in lower_text
