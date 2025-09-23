import os
from types import SimpleNamespace

import pytest
from PyQt5.QtWidgets import QApplication, QDialog

import dte
import auth
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
    original_get = facturacion_tab.FacturacionTab._get_invoices_from_db
    original_load = facturacion_tab.FacturacionTab.load_invoices
    try:
        facturacion_tab.FacturacionTab._get_invoices_from_db = lambda self: []
        facturacion_tab.FacturacionTab.load_invoices = lambda self: None
        tab = facturacion_tab.FacturacionTab(man)
    finally:
        facturacion_tab.FacturacionTab._get_invoices_from_db = original_get
        facturacion_tab.FacturacionTab.load_invoices = original_load
    if tab.table.rowCount() == 0:
        tab.table.setRowCount(1)
    tab.table.selectRow(0)
    return tab


def test_post_dte_token_invalid(monkeypatch):
    monkeypatch.setattr(dte, "construir_sobre_recepcion", lambda doc, data: {})
    monkeypatch.setattr(dte, "format_cliente_id_from_dui", lambda dui: "cid")
    monkeypatch.setattr(dte, "detect_user_agent", lambda ua, opts, app_version, client_id: "UA")
    monkeypatch.setattr(dte, "build_auth_header", lambda auth, app_version, client_id: {})

    class Resp:
        status_code = 401
        text = "Unauthorized"
        def json(self):
            return {"detalle": "Token expirado en Hacienda"}
    monkeypatch.setattr(dte.requests, "post", lambda *a, **k: Resp())
    resp = dte._post_dte("https://apitest.dtes.mh.gob.sv/fesv/recepciondte", "tok", "doc")
    assert resp == {
        "estado": "Rechazado",
        "http_status": 401,
        "detalle": "Token expirado en Hacienda",
    }


def test_post_dte_token_invalid_without_detail(monkeypatch):
    monkeypatch.setattr(dte, "construir_sobre_recepcion", lambda doc, data: {})
    monkeypatch.setattr(dte, "format_cliente_id_from_dui", lambda dui: "cid")
    monkeypatch.setattr(dte, "detect_user_agent", lambda ua, opts, app_version, client_id: "UA")
    monkeypatch.setattr(dte, "build_auth_header", lambda auth, app_version, client_id: {})

    class Resp:
        status_code = 403
        text = "Forbidden"
        def json(self):
            return {}

    monkeypatch.setattr(dte.requests, "post", lambda *a, **k: Resp())
    resp = dte._post_dte("https://apitest.dtes.mh.gob.sv/fesv/recepciondte", "tok", "doc")
    assert resp == {
        "estado": "Rechazado",
        "http_status": 403,
        "detalle": "Token inválido o caducado",
    }


def test_request_new_token_raises_runtimeerror(monkeypatch):
    class Resp:
        status_code = 401
        text = "Unauthorized"
        def raise_for_status(self):
            raise requests.HTTPError(response=self)
        def json(self):
            return {}
    import requests
    monkeypatch.setattr(auth.requests, "post", lambda url, data, headers, timeout: Resp())
    monkeypatch.setattr(auth, "_get_auth_url", lambda: "http://fake")
    with pytest.raises(RuntimeError):
        auth._request_new_token("nit", "pwd")


def test_send_selected_invoice_warns_on_token(monkeypatch, qt_app, tmp_path):
    db = DB(":memory:")
    venta_id, cid = _create_sale(db)
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_text("pdf")
    json_path = pdf_path.with_suffix(".json")
    json_path.write_text("{}")
    db.add_factura_pdf(venta_id, "Consumidor Final", str(pdf_path))

    tab = _make_tab(db, cid)
    monkeypatch.setattr(
        tab,
        "_selected_entry",
        lambda: {"row_type": "venta", "id": 1, "venta_id": venta_id},
    )
    monkeypatch.setattr(
        tab,
        "_selected_factura",
        lambda: {"venta_id": venta_id, "json": str(json_path), "control": "X"},
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
        def exec_(self):
            self.email_cb.setChecked(False)
            self.hacienda_cb.setChecked(True)
            return QDialog.Accepted
    monkeypatch.setattr(facturacion_tab, "SendOptionsDialog", DummyDlg)

    warnings = {}
    monkeypatch.setattr(facturacion_tab.QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(facturacion_tab.QMessageBox, "critical", lambda *a, **k: None)
    def fake_warning(parent, title, message):
        warnings["msg"] = message
    monkeypatch.setattr(facturacion_tab.QMessageBox, "warning", fake_warning)

    def fake_transmitir(db_, vid, tipo_dte="01"):
        return {"http_status": 401, "detalle": "Token rechazado por Hacienda"}
    monkeypatch.setattr(facturacion_tab, "transmitir_dte", fake_transmitir)

    tab.send_selected_invoice()
    assert warnings["msg"] == "Token rechazado por Hacienda"


def test_send_selected_invoice_warns_on_token_generic(monkeypatch, qt_app, tmp_path):
    db = DB(":memory:")
    venta_id, cid = _create_sale(db)
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_text("pdf")
    json_path = pdf_path.with_suffix(".json")
    json_path.write_text("{}")
    db.add_factura_pdf(venta_id, "Consumidor Final", str(pdf_path))

    tab = _make_tab(db, cid)
    monkeypatch.setattr(
        tab,
        "_selected_entry",
        lambda: {"row_type": "venta", "id": 1, "venta_id": venta_id},
    )
    monkeypatch.setattr(
        tab,
        "_selected_factura",
        lambda: {"venta_id": venta_id, "json": str(json_path), "control": "X"},
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
        def exec_(self):
            self.email_cb.setChecked(False)
            self.hacienda_cb.setChecked(True)
            return QDialog.Accepted
    monkeypatch.setattr(facturacion_tab, "SendOptionsDialog", DummyDlg)

    warnings = {}
    monkeypatch.setattr(facturacion_tab.QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(facturacion_tab.QMessageBox, "critical", lambda *a, **k: None)
    def fake_warning(parent, title, message):
        warnings["msg"] = message
    monkeypatch.setattr(facturacion_tab.QMessageBox, "warning", fake_warning)

    def fake_transmitir(db_, vid, tipo_dte="01"):
        return {"http_status": 401}
    monkeypatch.setattr(facturacion_tab, "transmitir_dte", fake_transmitir)

    tab.send_selected_invoice()
    assert "token" in warnings["msg"].lower()


def test_send_selected_invoice_warns_on_exception(monkeypatch, qt_app, tmp_path):
    db = DB(":memory:")
    venta_id, cid = _create_sale(db)
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_text("pdf")
    json_path = pdf_path.with_suffix(".json")
    json_path.write_text("{}")
    db.add_factura_pdf(venta_id, "Consumidor Final", str(pdf_path))

    tab = _make_tab(db, cid)
    monkeypatch.setattr(
        tab,
        "_selected_entry",
        lambda: {"row_type": "venta", "id": 1, "venta_id": venta_id},
    )
    monkeypatch.setattr(
        tab,
        "_selected_factura",
        lambda: {"venta_id": venta_id, "json": str(json_path), "control": "X"},
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
        def exec_(self):
            self.email_cb.setChecked(False)
            self.hacienda_cb.setChecked(True)
            return QDialog.Accepted
    monkeypatch.setattr(facturacion_tab, "SendOptionsDialog", DummyDlg)

    warnings = {}
    monkeypatch.setattr(facturacion_tab.QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(facturacion_tab.QMessageBox, "critical", lambda *a, **k: None)
    def fake_warning(parent, title, message):
        warnings["msg"] = message
    monkeypatch.setattr(facturacion_tab.QMessageBox, "warning", fake_warning)

    def fake_transmitir(db_, vid, tipo_dte="01"):
        raise RuntimeError("Token inválido o caducado")
    monkeypatch.setattr(facturacion_tab, "transmitir_dte", fake_transmitir)

    tab.send_selected_invoice()
    assert "token" in warnings["msg"].lower()


def test_send_selected_invoice_cert_access(monkeypatch, qt_app, tmp_path):
    db = DB(":memory:")
    venta_id, cid = _create_sale(db)
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_text("pdf")
    json_path = pdf_path.with_suffix(".json")
    json_path.write_text("{}")
    db.add_factura_pdf(venta_id, "Consumidor Final", str(pdf_path))

    tab = _make_tab(db, cid)
    monkeypatch.setattr(
        tab,
        "_selected_entry",
        lambda: {"row_type": "venta", "id": 1, "venta_id": venta_id},
    )
    monkeypatch.setattr(
        tab,
        "_selected_factura",
        lambda: {"venta_id": venta_id, "json": str(json_path), "control": "X"},
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

        def exec_(self):
            self.email_cb.setChecked(False)
            self.hacienda_cb.setChecked(True)
            return QDialog.Accepted

    monkeypatch.setattr(facturacion_tab, "SendOptionsDialog", DummyDlg)

    warnings = {}
    criticals = {}
    monkeypatch.setattr(facturacion_tab.QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(facturacion_tab.QMessageBox, "warning", lambda *a, **k: warnings.setdefault("msg", a[2]))

    def fake_critical(parent, title, message):
        criticals["title"] = title
        criticals["message"] = message

    monkeypatch.setattr(facturacion_tab.QMessageBox, "critical", fake_critical)

    def fake_transmitir(db_, vid, tipo_dte="01"):
        raise RuntimeError("CERT_ACCESS")

    monkeypatch.setattr(facturacion_tab, "transmitir_dte", fake_transmitir)

    tab.send_selected_invoice()

    assert criticals == {
        "title": "Firma",
        "message": "Error de firma: no se pudo acceder al certificado.",
    }
    assert "msg" not in warnings
