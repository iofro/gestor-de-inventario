import os
import pytest
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QDate
from types import SimpleNamespace

import facturacion_tab
from db import DB


@pytest.fixture(scope="module")
def qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def _create_manager():
    db = DB(":memory:")
    db.add_cliente("Alice", "", "0001", "", "", "", "", "", "", "")
    db.add_cliente("Bob", "", "0002", "", "", "", "", "", "", "")
    clientes = [dict(row) for row in db.cursor.execute("SELECT id, nombre FROM clientes")]
    venta1 = db.add_venta("2024-01-01", 10, cliente_id=clientes[0]["id"])
    venta2 = db.add_venta("2024-02-01", 20, cliente_id=clientes[1]["id"])
    manager = SimpleNamespace(db=db, _clientes=clientes, _Distribuidores=[])
    return manager, [venta1, venta2]


def test_load_and_filter_documents(qt_app, tmp_path, monkeypatch):
    manager, ventas = _create_manager()
    cf_dir = tmp_path / "cf"
    credito_dir = tmp_path / "credito"
    tickets_dir = tmp_path / "tickets"
    for d in [cf_dir, credito_dir, tickets_dir]:
        d.mkdir()
    monkeypatch.setattr(facturacion_tab, "CF_DIR", str(cf_dir))
    monkeypatch.setattr(facturacion_tab, "CREDITO_DIR", str(credito_dir))
    monkeypatch.setattr(facturacion_tab, "TICKETS_DIR", str(tickets_dir))
    monkeypatch.setattr(facturacion_tab, "ADDITIONAL_DIRS", [])

    # Create dummy invoice files and register them
    for idx, venta_id in enumerate(ventas):
        pdf = cf_dir / f"invoice_{idx}.pdf"
        pdf.write_text("pdf")
        (cf_dir / f"invoice_{idx}.json").write_text("{}")
        manager.db.add_factura_pdf(venta_id, "CF", str(pdf))

    tab = facturacion_tab.FacturacionTab(manager)
    assert tab.table.rowCount() == 2

    tab.search_bar.setText("alice")
    tab.load_invoices()
    assert tab.table.rowCount() == 1

    tab.search_bar.setText("")
    tab.date_from.setDate(QDate(2024, 2, 1))
    tab.load_invoices()
    assert tab.table.rowCount() == 1
