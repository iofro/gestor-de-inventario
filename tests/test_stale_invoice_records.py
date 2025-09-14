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


def test_missing_invoice_records_removed(qt_app, tmp_path):
    db = DB(":memory:")
    venta_id = db.add_venta("2024-01-01", 10)
    # add reference to non existing pdf
    db.add_factura_pdf(venta_id, "CF", str(tmp_path / "missing.pdf"))

    man = SimpleNamespace(db=db, _clientes=[], _Distribuidores=[])
    tab = facturacion_tab.FacturacionTab(man)

    rows = tab._get_invoices_from_db()
    assert len(rows) == 1
    assert rows[0]["estado"] == "Incompleta"
    count = db.cursor.execute("SELECT COUNT(*) FROM facturas_pdf").fetchone()[0]
    assert count == 1
