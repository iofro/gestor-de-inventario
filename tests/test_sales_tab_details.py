import os
from types import SimpleNamespace

import pytest
from PyQt5.QtWidgets import QApplication, QDialog

from sales_tab import SalesTab
from db import DB


@pytest.fixture(scope="module")
def qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def _create_sale(db):
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("P1", "C1", None, vid, None, 0, 10, 10, 1)
    pid = db.cursor.lastrowid
    db.add_cliente("C", "", "", "", "", "", "c@x.com", "", "", "")
    cid = db.cursor.lastrowid
    venta_id = db.add_venta("2024-01-01", 10, cliente_id=cid, vendedor_id=vid)
    db.add_detalle_venta(venta_id, pid, 1, 10, vendedor_id=vid)
    return venta_id, cid, vid


def _make_tab(db, cid, vid):
    man = SimpleNamespace(
        db=db,
        _clientes=[{"id": cid, "nombre": "C"}],
        _vendedores=[{"id": vid, "nombre": "V1"}],
        _products=[],
    )
    tab = SalesTab(man, check_smtp=False)
    tab.load_sales()
    return tab


def test_show_sale_details_opens_dialog(qt_app, monkeypatch):
    db = DB(":memory:")
    venta_id, cid, vid = _create_sale(db)
    tab = _make_tab(db, cid, vid)
    tab.sales_table.selectRow(0)

    captured = {}

    class DummyDlg:
        def __init__(self, venta, detalles, parent=None):
            captured["venta"] = venta
            captured["detalles"] = detalles
            captured["exec"] = False
        def exec_(self):
            captured["exec"] = True
            return QDialog.Accepted

    monkeypatch.setattr("dialogs.VentaDetalleDialog", DummyDlg)

    tab.show_sale_details()
    assert captured.get("exec")
    assert captured["venta"]["id"] == venta_id
    assert captured["detalles"]
