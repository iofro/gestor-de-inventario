import os
from types import SimpleNamespace

import pytest
import requests
from PyQt5.QtWidgets import QApplication, QDialog

import dte
import facturacion_tab
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
    return venta_id, cid


def _make_tab(db, cid):
    man = SimpleNamespace(db=db, _clientes=[{"id": cid, "nombre": "C", "email": "c@x.com"}], _Distribuidores=[])
    tab = facturacion_tab.FacturacionTab(man)
    tab.table.selectRow(0)
    return tab


def test_post_dte_connection_error(monkeypatch):
    monkeypatch.setattr(dte, "construir_sobre_recepcion", lambda *a, **k: {})

    def fake_post(*a, **k):
        raise requests.ConnectionError("boom")

    monkeypatch.setattr(dte.requests, "post", fake_post)

    res = dte._post_dte(
        "https://apitest.dtes.mh.gob.sv/fesv/recepciondte", "T", "DOC"
    )
    assert res == {"estado": "Error", "detalle": "Sin conexión a Internet"}


def test_send_selected_invoice_no_connection(monkeypatch, qt_app):
    db = DB(":memory:")
    venta_id, cid = _create_sale(db)
    tab = _make_tab(db, cid)

    monkeypatch.setattr(
        tab, "_selected_entry", lambda: {"row_type": "venta", "id": venta_id}
    )
    monkeypatch.setattr(
        tab,
        "_selected_factura",
        lambda: {"venta_id": venta_id, "json": "", "control": "X"},
    )

    class DummyCheck:
        def __init__(self):
            self._checked = False

        def setChecked(self, v):
            self._checked = v

        def isChecked(self):
            return self._checked

    class DummyDlg:
        def __init__(self, parent=None):
            self.email_cb = DummyCheck()
            self.hacienda_cb = DummyCheck()
            self.hacienda_cb.setChecked(True)

        def exec_(self):
            # Desactivar envío por correo
            self.email_cb.setChecked(False)
            return QDialog.Accepted

    monkeypatch.setattr(facturacion_tab, "SendOptionsDialog", DummyDlg)

    def fake_transmitir(db_, vid, tipo_dte="01", modo="normal"):
        return {"estado": "Error", "detalle": "Sin conexión a Internet"}

    monkeypatch.setattr(facturacion_tab, "transmitir_dte", fake_transmitir)

    captured = {}

    def fake_critical(parent, title, msg):
        captured["title"] = title
        captured["msg"] = msg

    monkeypatch.setattr(facturacion_tab.QMessageBox, "critical", fake_critical)
    monkeypatch.setattr(facturacion_tab.QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(facturacion_tab.QMessageBox, "warning", lambda *a, **k: None)

    tab.send_selected_invoice()

    assert (
        captured["msg"]
        == "No hay conexión a Internet. Active la conexión antes de reenviar."
    )
