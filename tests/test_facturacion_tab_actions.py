import os
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PyQt5.QtWidgets import QApplication, QDialog

import facturacion_tab
from db import DB


@pytest.fixture(scope="module")
def qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def _create_sale(db):
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("P1", "C1", None,  vid, None, 0, 10, 10, 1)
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


def test_create_ticket_saves_files(qt_app, tmp_path, monkeypatch):
    db = DB(":memory:")
    venta_id, cid = _create_sale(db)
    tab = _make_tab(db, cid)
    monkeypatch.setattr(
        tab, "_selected_entry", lambda: {"row_type": "venta", "id": venta_id}
    )

    save_path = tmp_path / "ticket.pdf"

    def fake_gen(venta, detalles, fname, dte_data=None):
        Path(fname).write_text("PDF")
        Path(fname).with_suffix(".json").write_text("{}")
    monkeypatch.setattr(facturacion_tab, "generar_ticket_personalizado", fake_gen)
    monkeypatch.setattr(facturacion_tab.QFileDialog, "getSaveFileName", lambda *a, **k: (str(save_path), None))
    monkeypatch.setattr(facturacion_tab.QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(facturacion_tab.QMessageBox, "warning", lambda *a, **k: None)

    tab.create_ticket()
    assert save_path.exists()
    assert save_path.with_suffix(".json").exists()


def test_send_selected_invoice(monkeypatch, qt_app, tmp_path):
    db = DB(":memory:")
    venta_id, cid = _create_sale(db)
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_text("pdf")
    json_path = pdf_path.with_suffix(".json")
    json_path.write_text("{}")
    db.add_factura_pdf(venta_id, "Consumidor Final", str(pdf_path))

    creds_path = tmp_path / "creds.json"
    creds_path.write_text(
        json.dumps(
            {
                "smtp_server": "s",
                "smtp_port": 25,
                "email_usuario": "u",
                "email_contrasena": "pw",
            }
        )
    )
    monkeypatch.setattr(facturacion_tab, "DATOS_NEGOCIO_PATH", str(creds_path))

    tab = _make_tab(db, cid)
    monkeypatch.setattr(
        tab, "_selected_entry", lambda: {"row_type": "venta", "id": venta_id}
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
            self.hacienda_cb.setChecked(True)
        def exec_(self):
            return QDialog.Accepted
    monkeypatch.setattr(facturacion_tab, "SendOptionsDialog", DummyDlg)

    captured_email = {}
    class FakeSender:
        def __init__(self, server, port, user, pw, dest, subj, body, attach):
            captured_email["args"] = (server, port, user, pw, dest, subj, body, attach)
            self.finished = SimpleNamespace(connect=lambda fn: setattr(self, "_fn", fn))
        def start(self):
            if hasattr(self, "_fn"):
                self._fn(True, "ok")
    monkeypatch.setattr(facturacion_tab, "EmailSender", FakeSender)

    captured_post = {}
    def fake_post(url, token, jws, data):
        captured_post["args"] = (url, token, jws)
        return {"estado": "Transmitido"}
    monkeypatch.setattr("dte._post_dte", fake_post)
    def fake_transmitir(db_, vid, modo="normal", tipo_dte="01"):
        fake_post("http://example.com", "TOKEN", "SIGNED", {})
        return {"estado": "Transmitido"}
    monkeypatch.setattr(facturacion_tab, "transmitir_dte", fake_transmitir)

    monkeypatch.setattr(facturacion_tab.QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(facturacion_tab.QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(facturacion_tab.QMessageBox, "critical", lambda *a, **k: None)

    tab.send_selected_invoice()
    assert pdf_path in map(Path, captured_email["args"][7])
    assert json_path in map(Path, captured_email["args"][7])
    assert captured_post["args"] == ("http://example.com", "TOKEN", "SIGNED")


def test_delete_invoice_removes_all(qt_app, tmp_path, monkeypatch):
    db = DB(":memory:")
    venta_id, cid = _create_sale(db)

    pdf = tmp_path / "f.pdf"
    pdf.write_text("p")
    js = pdf.with_suffix(".json")
    js.write_text(
        json.dumps({"identificacion": {"numeroControl": "DTE-01-S001P001-000000000000005"}})
    )
    jws = pdf.with_suffix(".jws")
    jws.write_text("TOKEN")
    db.add_factura_pdf(venta_id, "Consumidor Final", str(pdf))

    base_dte = Path(facturacion_tab.__file__).with_name("dtes")
    dte_dir = base_dte / "tmp_test" / "abc"
    dte_dir.mkdir(parents=True, exist_ok=True)
    dte_json = dte_dir / js.name
    dte_json.write_text(
        json.dumps({"identificacion": {"numeroControl": "DTE-01-S001P001-000000000000005"}})
    )
    (dte_dir / f"{js.stem}_estado.json").write_text(json.dumps({"estado": "aceptado"}))

    db.set_dte_correlativo("01", "001", "001", 5)
    monkeypatch.setattr(facturacion_tab.FacturacionTab, "load_invoices", lambda self: None)
    tab = _make_tab(db, cid)
    monkeypatch.setattr(
        tab,
        "_selected_entry",
        lambda: {"row_type": "venta", "id": venta_id, "json": str(dte_json)},
    )

    monkeypatch.setattr(
        facturacion_tab.QMessageBox,
        "question",
        lambda *a, **k: facturacion_tab.QMessageBox.Yes,
    )
    monkeypatch.setattr(facturacion_tab.QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(facturacion_tab.QMessageBox, "information", lambda *a, **k: None)

    tab.delete_invoice()

    assert not pdf.exists()
    assert not js.exists()
    assert not jws.exists()
    assert not dte_dir.exists()
    assert db.get_venta_by_id(venta_id) is None
    assert db.get_dte_correlativo("01", "001", "001") == 4
