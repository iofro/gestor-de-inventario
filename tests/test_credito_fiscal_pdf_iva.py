import json
import uuid
from decimal import Decimal

import pytest

from utils.monto import to_base_iva, iva_item

from utils.doc_generation import generate_invoice_pdf
from utils.docs import build_invoice_json


class FakeDB:
    def __init__(self):
        self._ventas = []
        self.detalles = {}
        self.credito = {}
        self.clientes = {}
        self.cursor = self.FakeCursor(self)

    class FakeCursor:
        def __init__(self, db):
            self.db = db

        def execute(self, _query, params):
            vid = params[0]
            row = next((v for v in self.db._ventas if v["id"] == vid), None)

            class Result:
                def __init__(self, row):
                    self.row = row

                def fetchone(self):
                    return self.row

            return Result(row)

    def get_ventas(self):
        return self._ventas

    def get_venta_credito_fiscal(self, vid):
        return self.credito.get(vid)

    def get_detalles_venta(self, vid):
        return self.detalles.get(vid, [])

    def get_cliente(self, cid):
        return self.clientes.get(cid)

    def get_trabajador(self, vid):
        return None

    def add_factura_pdf(self, *a):
        pass

    def next_dte_correlativo(self, *a, **k):
        return 1


class Manager:
    def __init__(self, db):
        self.db = db
        self._Distribuidores = []
        self._clientes = []
        self._vendedores = []


def test_credito_fiscal_pdf_calcula_iva(tmp_path, monkeypatch):
    db = FakeDB()
    venta = {"id": 1, "fecha": "2024-01-01", "total": 11.3}
    db._ventas.append(venta)
    db.detalles[1] = [{"cantidad": 1, "precio_unitario": 10, "iva": 1.3}]
    db.credito[1] = {"sumas": 10, "descuentos": 0, "iva": 0, "subtotal": 0, "ventas_exentas": 0, "ventas_no_sujetas": 0}
    man = Manager(db)

    pdf_path = tmp_path / "fact.pdf"
    json_path = tmp_path / "fact.json"

    def fake_paths(date, cliente, identifier, doc_type, root=None):
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        return str(pdf_path), str(json_path)

    def fake_generar(db_, vid, **_):
        venta = next(v for v in db_.get_ventas() if v["id"] == vid)
        detalles = db_.get_detalles_venta(vid)
        data = build_invoice_json(venta, {}, detalles)
        ident = data.setdefault("identificacion", {})
        ident["codigoGeneracion"] = uuid.uuid4().hex
        ident["numeroControl"] = uuid.uuid4().hex[:8].upper()
        resumen = {
            "sumas": 10,
            "descuentos": 0,
            "iva": 1.3,
            "subtotal": 11.3,
            "ventasExentas": 0,
            "ventasNoSujetas": 0,
            "totalPagar": venta.get("total"),
        }
        data["resumen"] = resumen
        return data

    captured = {}

    def fake_pdf(venta_d, detalles_d, cliente, distribuidor, tipo_doc, archivo="", **_):
        captured["venta"] = venta_d
        captured["detalles"] = detalles_d
        with open(archivo, "wb") as fh:
            fh.write(b"pdf")

    monkeypatch.setattr("utils.doc_generation.get_document_paths", fake_paths)
    monkeypatch.setattr("utils.doc_generation.generar_dte_json", fake_generar)
    monkeypatch.setattr("utils.doc_generation.generar_factura_electronica_pdf", fake_pdf)

    generate_invoice_pdf(man, 1)

    assert pytest.approx(captured["venta"]["iva"], 0.01) == 1.3
    assert pytest.approx(captured["detalles"][0]["iva"], 0.01) == 1.3
    assert pytest.approx(captured["detalles"][0]["ventas_gravadas"], 0.01) == 10


def test_pdf_total_precios_incluyen_iva(tmp_path, monkeypatch):
    db = FakeDB()
    venta = {
        "id": 1,
        "fecha": "2024-01-01",
        "total": 15,
        "extra": json.dumps({"precios_incluyen_iva": True}),
    }
    db._ventas.append(venta)
    db.detalles[1] = [{"cantidad": 1, "precio_unitario": 15, "iva": 1.72566372}]
    man = Manager(db)

    pdf_path = tmp_path / "fact.pdf"
    json_path = tmp_path / "fact.json"

    def fake_paths(date, cliente, identifier, doc_type, root=None):
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        return str(pdf_path), str(json_path)

    def fake_generar(db_, vid, **_):
        venta = next(v for v in db_.get_ventas() if v["id"] == vid)
        detalles = db_.get_detalles_venta(vid)
        data = build_invoice_json(venta, {}, detalles)
        ident = data.setdefault("identificacion", {})
        ident["codigoGeneracion"] = uuid.uuid4().hex
        ident["numeroControl"] = uuid.uuid4().hex[:8].upper()
        base = 13.27433628
        iva = 1.72566372
        resumen = {
            "sumas": base,
            "descuentos": 0,
            "iva": iva,
            "subtotal": base + iva,
            "ventasExentas": 0,
            "ventasNoSujetas": 0,
            "totalPagar": venta.get("total"),
        }
        data["resumen"] = resumen
        return data

    captured = {}

    def fake_pdf(venta_d, detalles_d, cliente, distribuidor, tipo_doc, archivo="", **_):
        captured["venta"] = venta_d
        captured["detalles"] = detalles_d
        with open(archivo, "wb") as fh:
            fh.write(b"pdf")

    monkeypatch.setattr("utils.doc_generation.get_document_paths", fake_paths)
    monkeypatch.setattr("utils.doc_generation.generar_dte_json", fake_generar)
    monkeypatch.setattr("utils.doc_generation.generar_factura_electronica_pdf", fake_pdf)

    generate_invoice_pdf(man, 1)

    base, iva = 13.27433628, 1.72566372
    assert pytest.approx(captured["venta"]["subtotal"], 0.01) == 15
    assert pytest.approx(captured["venta"]["iva"], 0.01) == float(iva)
    assert pytest.approx(captured["venta"]["total"], 0.01) == 15
    assert pytest.approx(captured["detalles"][0]["iva"], 0.01) == float(iva)
    assert pytest.approx(captured["detalles"][0]["ventas_gravadas"], 0.01) == float(base)


def test_pdf_importa_detalles_dte(tmp_path, monkeypatch):
    db = FakeDB()
    venta = {
        "id": 1,
        "fecha": "2024-01-01",
        "total": 12,
    }
    db._ventas.append(venta)
    db.detalles[1] = [
        {
            "cantidad": 1,
            "precio_unitario": 12,
            "descripcion": "Producto",
            "iva": 0,
        }
    ]
    db.credito[1] = {
        "sumas": 12,
        "descuentos": 0,
        "iva": 0,
        "subtotal": 12,
        "ventas_exentas": 0,
        "ventas_no_sujetas": 0,
    }
    man = Manager(db)

    pdf_path = tmp_path / "fact.pdf"
    json_path = tmp_path / "fact.json"

    def fake_paths(date, cliente, identifier, doc_type, root=None):
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        return str(pdf_path), str(json_path)

    base = Decimal("10.619469")
    iva = iva_item(base)

    def fake_generar(db_, vid, **_):
        venta = next(v for v in db_.get_ventas() if v["id"] == vid)
        detalles = db_.get_detalles_venta(vid)
        data = build_invoice_json(venta, {}, detalles)
        ident = data.setdefault("identificacion", {})
        ident["codigoGeneracion"] = uuid.uuid4().hex
        ident["numeroControl"] = uuid.uuid4().hex[:8].upper()
        ident["tipoDte"] = "03"
        data["cuerpoDocumento"] = [
            {
                "numItem": 1,
                "cantidad": "1.0000",
                "precioUni": str(base),
                "ventaGravada": str(base),
                "ventaExenta": "0",
                "ventaNoSuj": "0",
                "noGravado": "0",
                "montoDescu": "0",
            }
        ]
        resumen = {
            "sumas": str(base),
            "subTotalVentas": str(base),
            "subTotal": str(base),
            "totalGravada": str(base),
            "totalExenta": "0",
            "totalNoSuj": "0",
            "montoTotalOperacion": "12.0000",
            "totalPagar": "12.0000",
            "condicionOperacion": 1,
            "tributos": [
                {
                    "codigo": "20",
                    "descripcion": "IVA",
                    "valor": str(iva),
                }
            ],
        }
        data["resumen"] = resumen
        return data

    captured = {}

    def fake_pdf(venta_d, detalles_d, cliente, distribuidor, tipo_doc, archivo="", **_):
        captured["venta"] = venta_d
        captured["detalles"] = [dict(item) for item in detalles_d]
        with open(archivo, "wb") as fh:
            fh.write(b"pdf")

    monkeypatch.setattr("utils.doc_generation.get_document_paths", fake_paths)
    monkeypatch.setattr("utils.doc_generation.generar_dte_json", fake_generar)
    monkeypatch.setattr("utils.doc_generation.generar_factura_electronica_pdf", fake_pdf)

    generate_invoice_pdf(man, 1)

    detalle = captured["detalles"][0]
    expected_base = float(base)
    expected_iva = float(iva)
    assert pytest.approx(detalle["precio_unitario"], rel=1e-6) == expected_base
    assert pytest.approx(detalle["ventas_gravadas"], rel=1e-6) == expected_base
    assert pytest.approx(detalle["iva"], rel=1e-6) == expected_iva


def test_credito_fiscal_resumen_iva(tmp_path):
    from decimal import Decimal
    from dte import calcular_resumen

    resumen = calcular_resumen(
        Decimal("18"),
        {"total": 18},
        fiscal={},
        extra={"precios_incluyen_iva": True},
        tipo_dte="03",
    )
    sumas = float(resumen.get("totalGravada"))
    iva = float(resumen.get("tributos")[0]["valor"]) if resumen.get("tributos") else 0
    total = float(resumen.get("totalPagar"))
    assert pytest.approx(sumas, 0.01) == 15.93
    assert pytest.approx(iva, 0.01) == 2.07
    assert pytest.approx(total, 0.01) == 18.00
