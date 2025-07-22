import os
import pytest
from PyQt5.QtWidgets import QApplication
from types import SimpleNamespace

import facturacion_tab
from db import DB

@pytest.fixture(scope="module")
def qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def test_tickets_listed_from_db(qt_app, tmp_path, monkeypatch):
    ticket_dir = tmp_path / "tickets"
    ticket_dir.mkdir()
    pdf_path = ticket_dir / "20240101_Test_1_Ticket.pdf"
    pdf_path.write_text("pdf")
    json_path = ticket_dir / "20240101_Test_1_Ticket.json"
    json_path.write_text("{}")

    db = DB(":memory:")
    venta_id = db.add_venta("2024-01-01", 5)
    db.add_ticket_pdf(venta_id, str(pdf_path))
    man = SimpleNamespace(db=db, _clientes=[], _Distribuidores=[])

    monkeypatch.setattr(facturacion_tab, "TICKETS_DIR", str(ticket_dir))

    tab = facturacion_tab.FacturacionTab(man)
    tickets = tab._get_tickets_from_db()
    assert any(t.get("pdf") == str(pdf_path) for t in tickets)


def test_orphan_ticket_found(qt_app, tmp_path, monkeypatch):
    ticket_dir = tmp_path / "tickets"
    ticket_dir.mkdir()
    pdf_path = ticket_dir / "20240102_Test_2_Ticket.pdf"
    pdf_path.write_text("pdf")
    json_path = ticket_dir / "20240102_Test_2_Ticket.json"
    json_path.write_text("{}")

    db = DB(":memory:")
    man = SimpleNamespace(db=db, _clientes=[], _Distribuidores=[])

    monkeypatch.setattr(facturacion_tab, "TICKETS_DIR", str(ticket_dir))
    monkeypatch.setattr(facturacion_tab, "CF_DIR", str(tmp_path / "cf"))
    monkeypatch.setattr(facturacion_tab, "CREDITO_DIR", str(tmp_path / "cf2"))
    monkeypatch.setattr(facturacion_tab, "ADDITIONAL_DIRS", [])

    tab = facturacion_tab.FacturacionTab(man)
    orphans = tab._find_orphan_documents()
    assert any(o.get("pdf") == str(pdf_path) for o in orphans)
