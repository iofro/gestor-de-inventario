import json
from pathlib import Path
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PyQt5.QtWidgets import QDialog

import dte
import facturacion_tab
from db import DB
from tests.conftest import make_jws


def test_transmitir_dte_orphan_signs(monkeypatch, tmp_path):
    db = DB(":memory:")
    data = {
        "identificacion": {
            "ambiente": "00",
            "version": "1",
            "tipoDte": "01",
            "codigoGeneracion": "ABC",
        },
        "resumen": {"totalLetras": "c"},
    }
    json_path = tmp_path / "dte.json"
    json_path.write_text(json.dumps(data))
    called = {}
    monkeypatch.setattr(dte, "sanitize_dte_payload", lambda d: called.setdefault("san", True) or d)
    monkeypatch.setattr(dte, "apply_schema_patch", lambda d: called.setdefault("patch", True) or d)
    monkeypatch.setattr(dte, "validate_dte_json", lambda d: called.setdefault("val", True))
    monkeypatch.setattr(dte.jws, "sign_json", lambda d: called.setdefault("sign", True) or "SIGNED")
    monkeypatch.setattr(dte.auth, "get_token", lambda: "T")
    monkeypatch.setattr(dte.auth, "get_last_auth_host", lambda: "example.com")
    monkeypatch.setattr(dte, "_load_dte_api_config", lambda: {"url": "http://example.com"})
    captured = {}
    def fake_post(url, token, jws_token, meta):
        captured.update({"jws": jws_token, "meta": meta})
        return {"estado": "Transmitido", "sello": "S"}
    monkeypatch.setattr(dte, "_post_dte", fake_post)
    resp = dte.transmitir_dte_orphan(db, str(json_path))
    assert called["sign"]
    assert captured["jws"] == "SIGNED"
    row = db.cursor.execute("SELECT estado, sello FROM dte_envios").fetchone()
    assert row["estado"] == "Transmitido" and row["sello"] == "S"
    assert resp["estado"] == "Transmitido"


def test_transmitir_dte_orphan_uses_jws(monkeypatch, tmp_path):
    db = DB(":memory:")
    token = make_jws({"identificacion": {"ambiente": "00", "version": "1", "tipoDte": "01", "codigoGeneracion": "ABC"}})
    json_path = tmp_path / "signed.json"
    json_path.write_text(json.dumps(token))
    monkeypatch.setattr(dte.jws, "sign_json", lambda d: (_ for _ in ()).throw(RuntimeError("no sign")))
    monkeypatch.setattr(dte.auth, "get_token", lambda: "T")
    monkeypatch.setattr(dte.auth, "get_last_auth_host", lambda: "example.com")
    monkeypatch.setattr(dte, "_load_dte_api_config", lambda: {"url": "http://example.com"})
    captured = {}
    def fake_post(url, token, jws_token, meta):
        captured["jws"] = jws_token
        return {"estado": "Transmitido", "sello": "S"}
    monkeypatch.setattr(dte, "_post_dte", fake_post)
    resp = dte.transmitir_dte_orphan(db, str(json_path))
    assert captured["jws"] == token
    row = db.cursor.execute("SELECT estado FROM dte_envios").fetchone()
    assert row["estado"] == "Transmitido"
    assert resp["estado"] == "Transmitido"


def test_send_orphan_invoice(monkeypatch, qt_app, tmp_path):
    pdf_path = tmp_path / "20240101_Test_ConsumidorFinal.pdf"
    pdf_path.write_text("PDF")
    json_path = pdf_path.with_suffix(".json")
    json_path.write_text("{}")

    db = DB(":memory:")
    man = SimpleNamespace(db=db, _clientes=[], _Distribuidores=[])
    monkeypatch.setattr(facturacion_tab, "CF_DIR", str(tmp_path))
    monkeypatch.setattr(facturacion_tab, "CREDITO_DIR", str(tmp_path / "cf"))
    monkeypatch.setattr(facturacion_tab, "ADDITIONAL_DIRS", [])
    tab = facturacion_tab.FacturacionTab(man)
    tab.table.selectRow(0)
    assert tab.btn_enviar.isEnabled()

    class DummyCheck:
        def __init__(self): self._checked = True
        def setChecked(self, v): self._checked = v
        def isChecked(self): return self._checked
    class DummyDlg:
        def __init__(self, parent=None):
            self.email_cb = DummyCheck()
            self.hacienda_cb = DummyCheck()
        def exec_(self):
            return QDialog.Accepted
    monkeypatch.setattr(facturacion_tab, "SendOptionsDialog", DummyDlg)

    creds_path = tmp_path / "creds.json"
    creds_path.write_text(json.dumps({
        "smtp_server": "s",
        "smtp_port": 25,
        "email_usuario": "u",
        "email_contrasena": "p",
    }))
    monkeypatch.setattr(facturacion_tab, "DATOS_NEGOCIO_PATH", str(creds_path))

    monkeypatch.setattr(facturacion_tab.QInputDialog, "getText", lambda *a, **k: ("dest@example.com", True))

    sent = {}
    class FakeSender:
        def __init__(self, *args):
            sent["attachments"] = args[-1]
            self.finished = SimpleNamespace(connect=lambda fn: setattr(self, "_fn", fn))
        def start(self):
            self._fn(True, "ok")
    monkeypatch.setattr(facturacion_tab, "EmailSender", FakeSender)

    called = {}
    def fake_transmit(db_, path):
        called["path"] = path
        return {"estado": "Transmitido"}
    monkeypatch.setattr(facturacion_tab.dte, "transmitir_dte_orphan", fake_transmit)

    monkeypatch.setattr(facturacion_tab.QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(facturacion_tab.QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(facturacion_tab.QMessageBox, "critical", lambda *a, **k: None)

    tab.send_selected_invoice()
    assert json_path in map(Path, sent["attachments"])
    assert called["path"] == str(json_path)
