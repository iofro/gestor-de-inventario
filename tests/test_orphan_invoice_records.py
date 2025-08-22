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


def test_orphan_invoice_records_are_moved_and_removed(qt_app, tmp_path, monkeypatch):
    db = DB(":memory:")
    pdf = tmp_path / "invoice.pdf"
    js = tmp_path / "invoice.json"
    pdf.write_text("PDF")
    js.write_text("{}")
    db.cursor.execute(
        "INSERT INTO facturas_pdf (venta_id, tipo, ruta, fecha_creacion) VALUES (?, ?, ?, ?)",
        (123, "CF", str(pdf), "2024-01-01"),
    )
    db.conn.commit()

    orphan_dir = tmp_path / "orphans"
    monkeypatch.setattr(facturacion_tab, "ORPHAN_INVOICES_DIR", str(orphan_dir))

    man = SimpleNamespace(db=db, _clientes=[], _Distribuidores=[])
    tab = facturacion_tab.FacturacionTab(man)
    rows = tab._get_invoices_from_db()
    assert rows == []
    count = db.cursor.execute("SELECT COUNT(*) FROM facturas_pdf").fetchone()[0]
    assert count == 0
    assert (orphan_dir / pdf.name).exists()
    assert (orphan_dir / js.name).exists()
