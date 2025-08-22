import pytest
from utils.docs import build_invoice_json
from utils.doc_generation import generate_invoice_pdf

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

def test_build_json_includes_transmission():
    identificacion = {
        "ambiente": "00",
        "version": 1,
        "tipoDte": "01",
        "codigoGeneracion": "CG",
        "numeroControl": "NC",
        "tipoOperacion": 2,
    }
    emisor = {"nombre": "E", "direccion": {"departamento": "01", "municipio": "0101"}}
    data = build_invoice_json(
        identificacion=identificacion,
        emisor=emisor,
        receptor={},
        items=[{"descripcion": "P", "cantidad": 1, "precioUnitario": 1}],
    )
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
    monkeypatch.setattr(
        "utils.doc_generation.generar_dte_json",
        lambda *a, **k: {
            "identificacion": {
                "version": 1,
                "tipoDte": "01",
                "codigoGeneracion": "XYZ",
                "numeroControl": "NC-1",
            },
            "resumen": {"totalPagar": 10},
            "cuerpoDocumento": [{"cantidad": 1, "precioUnitario": 10}],
        },
    )
    generate_invoice_pdf(man, 1)
    assert db.pending

