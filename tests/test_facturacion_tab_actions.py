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
    db.add_producto("P1", "C1", vid, None, 0, 10, 10, 1)
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

    save_path = tmp_path / "ticket.pdf"

    def fake_gen(venta, detalles, fname, dte_data=None):
        Path(fname).write_text("PDF")
        Path(fname).with_suffix(".json").write_text("{}")
    monkeypatch.setattr(facturacion_tab, "generar_ticket_personalizado", fake_gen)
    monkeypatch.setattr(facturacion_tab.QFileDialog, "getSaveFileName", lambda *a, **k: (str(save_path), None))
    monkeypatch.setattr(facturacion_tab.QMessageBox, "information", lambda *a, **k: None)

    tab.create_ticket()
    assert save_path.exists()
    assert save_path.with_suffix(".json").exists()


def test_change_estado_updates_table(qt_app, monkeypatch):
    db = DB(":memory:")
    venta_id, cid = _create_sale(db)
    tab = _make_tab(db, cid)

    class DummyDlg:
        def __init__(self, estado, parent=None):
            pass
        def exec_(self):
            return QDialog.Accepted
        def get_estado(self):
            return "Anulada"
    monkeypatch.setattr("dialogs.EstadoVentaDialog", DummyDlg)
    monkeypatch.setattr(facturacion_tab.QMessageBox, "warning", lambda *a, **k: None)

    tab.change_estado()
    assert tab.table.item(0, 4).text() == "Anulada"
    row = db.cursor.execute("SELECT estado FROM ventas WHERE id=?", (venta_id,)).fetchone()
    assert row["estado"] == "Anulada"


def test_send_selected_invoice(monkeypatch, qt_app, tmp_path):
    db = DB(":memory:")
    venta_id, cid = _create_sale(db)
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_text("pdf")
    json_path = pdf_path.with_suffix(".json")
    json_path.write_text("{}")
    db.add_factura_pdf(venta_id, "Consumidor Final", str(pdf_path))

    creds_path = tmp_path / "creds.json"
    creds_path.write_text(json.dumps({"smtp_server": "s", "smtp_port": 25, "email_usuario": "u"}))
    monkeypatch.setattr(facturacion_tab, "DATOS_NEGOCIO_PATH", str(creds_path))
    monkeypatch.setenv("INVENTARIO_EMAIL_PASSWORD", "pw")

    tab = _make_tab(db, cid)

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
    def fake_post(url, token, jws):
        captured_post["args"] = (url, token, jws)
        return {"estado": "Transmitido"}
    monkeypatch.setattr("dte._post_dte", fake_post)
    def fake_transmitir(db_, vid, modo="normal", tipo_dte="01"):
        fake_post("http://example.com", "TOKEN", "SIGNED")
        return {"estado": "Transmitido"}
    monkeypatch.setattr(facturacion_tab, "transmitir_dte", fake_transmitir)

    monkeypatch.setattr(facturacion_tab.QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(facturacion_tab.QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(facturacion_tab.QMessageBox, "critical", lambda *a, **k: None)

    tab.send_selected_invoice()
    assert pdf_path in map(Path, captured_email["args"][7])
    assert json_path in map(Path, captured_email["args"][7])
    assert captured_post["args"] == ("http://example.com", "TOKEN", "SIGNED")


def test_delete_files_removes(qt_app, tmp_path, monkeypatch):
    db = DB(":memory:")
    venta_id, cid = _create_sale(db)
    pdf = tmp_path / "f.pdf"
    pdf.write_text("p")
    js = pdf.with_suffix(".json")
    js.write_text("{}")
    db.add_factura_pdf(venta_id, "Consumidor Final", str(pdf))
    tab = _make_tab(db, cid)

    monkeypatch.setattr(facturacion_tab.QMessageBox, "question", lambda *a, **k: facturacion_tab.QMessageBox.Yes)
    monkeypatch.setattr(facturacion_tab.QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(facturacion_tab.QMessageBox, "information", lambda *a, **k: None)

    tab.delete_files()
    assert not pdf.exists()
    assert not js.exists()
