import os
import pytest
from types import SimpleNamespace
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
    tab.date_from.setDate(QDate(2024, 2, 1))
    tab.load_invoices()
    assert tab.table.rowCount() == 0
