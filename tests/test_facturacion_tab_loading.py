import os
import json
import pytest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QDate

import facturacion_tab
from db import DB


@pytest.fixture(scope="module")
def qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def _create_tab(tmp_path, monkeypatch):
    invoice_dir = tmp_path / "invoices"
    invoice_dir.mkdir()
    pdf_path = invoice_dir / "20240101_Test_1_ConsumidorFinal.pdf"
    pdf_path.write_text("pdf")
    (invoice_dir / "20240101_Test_1_ConsumidorFinal.json").write_text("{}")

    db = DB(":memory:")
    db.cursor.execute("INSERT INTO clientes (id, nombre) VALUES (1, 'Alice')")
    db.conn.commit()
    venta_id = db.add_venta("2024-01-01", 10, cliente_id=1)
    db.add_factura_pdf(venta_id, "ConsumidorFinal", str(pdf_path))
    manager = SimpleNamespace(db=db, _clientes=[{"id": 1, "nombre": "Alice"}])

    monkeypatch.setattr(facturacion_tab, "CF_DIR", str(invoice_dir))
    monkeypatch.setattr(facturacion_tab, "CREDITO_DIR", str(invoice_dir))
    monkeypatch.setattr(facturacion_tab, "TICKETS_DIR", str(invoice_dir))
    monkeypatch.setattr(facturacion_tab, "NOTAS_DEBITO_DIR", str(invoice_dir))
    monkeypatch.setattr(facturacion_tab, "NOTAS_CREDITO_DIR", str(invoice_dir))
    monkeypatch.setattr(facturacion_tab, "NOTAS_REMISION_DIR", str(invoice_dir))
    monkeypatch.setattr(facturacion_tab, "ADDITIONAL_DIRS", [])

    return facturacion_tab.FacturacionTab(manager)


def test_loads_documents(qt_app, tmp_path, monkeypatch):
    tab = _create_tab(tmp_path, monkeypatch)
    assert tab.table.rowCount() == 1


def test_filters_documents(qt_app, tmp_path, monkeypatch):
    tab = _create_tab(tmp_path, monkeypatch)

    tab.search_bar.setText("nope")
    tab.load_invoices()
    assert tab.table.rowCount() == 0

    tab.search_bar.setText("")
    tab.load_invoices()
    assert tab.table.rowCount() == 1


def test_ticket_rows_loaded_from_db(qt_app, tmp_path, monkeypatch):
    ticket_dir = tmp_path / "tickets"
    ticket_dir.mkdir()
    pdf_path = ticket_dir / "20240103_Test_1_Ticket.pdf"
    pdf_path.write_text("pdf")
    json_data = {
        "identificacion": {
            "numeroControl": "DTE-01-S001P001-000000000000123",
            "tipoDte": "01",
        }
    }
    (ticket_dir / "20240103_Test_1_Ticket.json").write_text(json.dumps(json_data))

    db = DB(":memory:")
    venta_id = db.add_venta("2024-01-03", 5)
    db.add_ticket_pdf(venta_id, str(pdf_path))

    manager = SimpleNamespace(db=db, _clientes=[], _Distribuidores=[])

    monkeypatch.setattr(facturacion_tab, "CF_DIR", str(tmp_path / "cf"))
    monkeypatch.setattr(facturacion_tab, "CREDITO_DIR", str(tmp_path / "cfiscal"))
    monkeypatch.setattr(facturacion_tab, "TICKETS_DIR", str(ticket_dir))
    monkeypatch.setattr(facturacion_tab, "NOTAS_DEBITO_DIR", str(tmp_path / "nd"))
    monkeypatch.setattr(facturacion_tab, "NOTAS_CREDITO_DIR", str(tmp_path / "nc"))
    monkeypatch.setattr(facturacion_tab, "NOTAS_REMISION_DIR", str(tmp_path / "nr"))
    monkeypatch.setattr(facturacion_tab, "ADDITIONAL_DIRS", [])

    tab = facturacion_tab.FacturacionTab(manager)
    rows = tab._get_invoices_from_db()
    ticket_rows = [r for r in rows if r.get("venta_id") == venta_id]
    assert ticket_rows, "expected ticket entry from database"
    ticket_entry = ticket_rows[0]
    assert ticket_entry["row_type"] == "ticket"
    assert ticket_entry["tipo"] == "Ticket"

    docs = tab._scan_documents()
    names = [r.get("name") for r in docs if r.get("venta_id") == venta_id]
    assert ticket_entry["name"] in names
    assert not any(
        r.get("row_type") == "orphan" and r.get("name") == ticket_entry["name"]
        for r in docs
    )


def test_orders_by_datetime(qt_app, tmp_path, monkeypatch):
    inv_dir = tmp_path / "facturas_consumidor_final"
    inv_dir.mkdir()

    base1 = "20240101_Test_1_ConsumidorFinal"
    data1 = {
        "identificacion": {
            "numeroControl": base1,
            "tipoDte": "01",
            "fecEmi": "2024-01-01",
            "horEmi": "10:00:00",
        },
        "receptor": {"nombre": "Cliente"},
        "resumen": {"totalPagar": 1},
    }
    (inv_dir / f"{base1}.json").write_text(json.dumps(data1))
    (inv_dir / f"{base1}.pdf").write_text("pdf")

    base2 = "20240101_Test_2_ConsumidorFinal"
    data2 = {
        "identificacion": {
            "numeroControl": base2,
            "tipoDte": "01",
            "fecEmi": "2024-01-01",
            "horEmi": "11:00:00",
        },
        "receptor": {"nombre": "Cliente"},
        "resumen": {"totalPagar": 1},
    }
    (inv_dir / f"{base2}.json").write_text(json.dumps(data2))
    (inv_dir / f"{base2}.pdf").write_text("pdf")

    db = DB(":memory:")
    manager = SimpleNamespace(db=db, _clientes=[], _Distribuidores=[])

    monkeypatch.setattr(facturacion_tab, "CF_DIR", str(inv_dir))
    monkeypatch.setattr(
        facturacion_tab, "CREDITO_DIR", str(tmp_path / "facturas_credito_fiscal")
    )
    monkeypatch.setattr(facturacion_tab, "TICKETS_DIR", str(tmp_path / "tickets"))
    monkeypatch.setattr(facturacion_tab, "NOTAS_DEBITO_DIR", str(tmp_path / "nd"))
    monkeypatch.setattr(facturacion_tab, "NOTAS_CREDITO_DIR", str(tmp_path / "nc"))
    monkeypatch.setattr(facturacion_tab, "NOTAS_REMISION_DIR", str(tmp_path / "nr"))
    monkeypatch.setattr(facturacion_tab, "ADDITIONAL_DIRS", [])

    tab = facturacion_tab.FacturacionTab(manager)
    tab.load_invoices()
    first = tab.table.item(0, 1).text()
    second = tab.table.item(1, 1).text()
    assert first.endswith("11:00")
    assert second.endswith("10:00")


def test_client_and_vendor_filters(qt_app, tmp_path, monkeypatch):
    inv_dir = tmp_path / "facturas_consumidor_final"
    inv_dir.mkdir()

    base1 = "20240101_Alpha_1_ConsumidorFinal"
    data1 = {
        "identificacion": {
            "numeroControl": base1,
            "tipoDte": "01",
            "fecEmi": "2024-01-01",
        },
        "receptor": {"nombre": "Alice"},
        "resumen": {"totalPagar": 10},
    }
    (inv_dir / f"{base1}.json").write_text(json.dumps(data1))
    (inv_dir / f"{base1}.pdf").write_text("pdf")

    base2 = "20240102_Beta_2_ConsumidorFinal"
    data2 = {
        "identificacion": {
            "numeroControl": base2,
            "tipoDte": "01",
            "fecEmi": "2024-01-02",
        },
        "receptor": {"nombre": "Bob"},
        "resumen": {"totalPagar": 20},
    }
    (inv_dir / f"{base2}.json").write_text(json.dumps(data2))
    (inv_dir / f"{base2}.pdf").write_text("pdf")

    db = DB(":memory:")
    db.cursor.executemany(
        "INSERT INTO clientes (id, nombre) VALUES (?, ?)",
        [(1, "Alice"), (2, "Bob")],
    )
    db.cursor.executemany(
        "INSERT INTO trabajadores (id, codigo, nombre, es_vendedor) VALUES (?, ?, ?, 1)",
        [(1, "V1", "Vend 1"), (2, "V2", "Vend 2")],
    )
    db.conn.commit()

    venta1 = db.add_venta("2024-01-01", 10, cliente_id=1, vendedor_id=1)
    venta2 = db.add_venta("2024-01-02", 20, cliente_id=2, vendedor_id=2)
    db.add_factura_pdf(venta1, "ConsumidorFinal", str(inv_dir / f"{base1}.pdf"))
    db.add_factura_pdf(venta2, "ConsumidorFinal", str(inv_dir / f"{base2}.pdf"))

    manager = SimpleNamespace(
        db=db,
        _clientes=[{"id": 1, "nombre": "Alice"}, {"id": 2, "nombre": "Bob"}],
    )

    monkeypatch.setattr(facturacion_tab, "CF_DIR", str(inv_dir))
    monkeypatch.setattr(facturacion_tab, "CREDITO_DIR", str(tmp_path / "credito"))
    monkeypatch.setattr(facturacion_tab, "TICKETS_DIR", str(tmp_path / "tickets"))
    monkeypatch.setattr(facturacion_tab, "NOTAS_DEBITO_DIR", str(tmp_path / "nd"))
    monkeypatch.setattr(facturacion_tab, "NOTAS_CREDITO_DIR", str(tmp_path / "nc"))
    monkeypatch.setattr(facturacion_tab, "NOTAS_REMISION_DIR", str(tmp_path / "nr"))
    monkeypatch.setattr(facturacion_tab, "ADDITIONAL_DIRS", [])

    tab = facturacion_tab.FacturacionTab(manager)
    tab.load_invoices()
    assert tab.table.rowCount() == 2

    idx = tab.client_filter.findData(1)
    tab.client_filter.setCurrentIndex(idx)
    tab.load_invoices()
    assert tab.table.rowCount() == 1

    tab.client_filter.setCurrentIndex(0)
    tab.load_invoices()
    assert tab.table.rowCount() == 2

    idx_v = tab.vendedor_filter.findData(2)
    tab.vendedor_filter.setCurrentIndex(idx_v)
    tab.load_invoices()
    assert tab.table.rowCount() == 1

    tab.vendedor_filter.setCurrentIndex(0)
    tab.load_invoices()
    assert tab.table.rowCount() == 2
