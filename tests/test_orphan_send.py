import json
import os
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt5.QtWidgets", exc_type=ImportError)
from PyQt5.QtWidgets import QDialog

import dte
import facturacion_tab
from db import DB
from tests.conftest import make_jws
from tests.test_envio_documentos import create_sale

import utils.docs as docs_utils
import utils.stable_json as stable_json
from utils.snapshot import Snapshot


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
    def _mark_sanitize(payload):
        called["san"] = True
        return payload

    def _mark_patch(payload):
        called["patch"] = True
        return payload

    monkeypatch.setattr(dte, "sanitize_dte_payload", _mark_sanitize)
    monkeypatch.setattr(dte, "apply_schema_patch", _mark_patch)
    monkeypatch.setattr(dte, "validate_dte_json", lambda d: called.setdefault("val", True))
    def _sign_json(_payload):
        called["sign"] = True
        return "SIGNED"
    monkeypatch.setattr(dte.jws, "sign_json", _sign_json)
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
    man = SimpleNamespace(db=db, _clientes=[], _Distribuidores=[], refresh_data=lambda: None)
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
    monkeypatch.setattr(facturacion_tab, "loading_dialog", lambda *a, **k: nullcontext())

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
    assert called.get("path")
    assert called["path"].lower().endswith(".json")
    assert os.path.exists(called["path"])


def test_send_orphan_invoice_warns_with_token_detail(monkeypatch, qt_app, tmp_path):
    pdf_path = tmp_path / "20240101_Test_ConsumidorFinal.pdf"
    pdf_path.write_text("PDF")
    json_path = pdf_path.with_suffix(".json")
    json_path.write_text("{}")

    db = DB(":memory:")
    man = SimpleNamespace(db=db, _clientes=[], _Distribuidores=[], refresh_data=lambda: None)
    monkeypatch.setattr(facturacion_tab, "CF_DIR", str(tmp_path))
    monkeypatch.setattr(facturacion_tab, "CREDITO_DIR", str(tmp_path / "cf"))
    monkeypatch.setattr(facturacion_tab, "ADDITIONAL_DIRS", [])

    tab = facturacion_tab.FacturacionTab(man)
    tab.table.selectRow(0)

    class DummyCheck:
        def __init__(self):
            self._checked = False
        def setChecked(self, value):
            self._checked = value
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
    monkeypatch.setattr(facturacion_tab, "loading_dialog", lambda *a, **k: nullcontext())

    warnings = {}
    monkeypatch.setattr(facturacion_tab.QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(facturacion_tab.QMessageBox, "critical", lambda *a, **k: None)
    def fake_warning(parent, title, message):
        warnings["msg"] = message
    monkeypatch.setattr(facturacion_tab.QMessageBox, "warning", fake_warning)
    monkeypatch.setattr(
        facturacion_tab.FacturacionTab,
        "_show_send_error_dialog",
        lambda self, summary, title, details_payload=None: warnings.__setitem__("msg", str(summary)),
    )

    def fake_transmit(db_, path):
        return {"http_status": 401, "detalle": "Credenciales revocadas"}

    monkeypatch.setattr(facturacion_tab.dte, "transmitir_dte_orphan", fake_transmit)

    tab.send_selected_invoice()
    assert warnings["msg"] == "Credenciales revocadas"


def test_resend_credit_note_regenerates_codigo(monkeypatch, qt_app, tmp_path):
    db = DB(":memory:")
    venta_id = create_sale(db)
    nota_id = db.add_nota(venta_id, "credito", "2024-01-02", 10, "motivo")
    dummy_snapshot = Snapshot(
        uuid="SNAPSHOT",
        path=str(tmp_path / "snapshot.json"),
        tipo_documento="01",
        fecha_emision="2024-01-01",
        payload={},
    )
    monkeypatch.setattr(
        db,
        "get_snapshot_by_venta",
        lambda vid: dummy_snapshot if (vid == venta_id or str(vid) == str(venta_id)) else None,
    )
    old_code = "00000000-0000-4000-8000-OLDNC000000"
    numero_control = "DTE-05-S001P001-000000000000123"
    db.registrar_envio_dte(
        nota_id,
        "normal",
        "Rechazado",
        "",
        codigo_generacion=old_code,
        numero_control=numero_control,
    )

    nota_dir = tmp_path / "notas_credito"
    nota_dir.mkdir()
    base = "20240102_Test_DTE-05-S001P001-000000000000123_NotaCredito"
    pdf_path = nota_dir / f"{base}.pdf"
    pdf_path.write_text("PDF", encoding="utf-8")
    json_path = nota_dir / f"{base}.json"
    json_path.write_text(
        json.dumps(
            {
                "identificacion": {
                    "tipoDte": "05",
                    "version": 1,
                    "ambiente": "00",
                    "codigoGeneracion": old_code,
                    "numeroControl": numero_control,
                    "fecEmi": "2024-01-02",
                },
                "receptor": {"nombre": "Cliente"},
                "resumen": {
                    "montoTotalOperacion": 10,
                    "totalLetras": "DIEZ",
                    "condicionOperacion": 1,
                    "pagos": None,
                },
            }
        ),
        encoding="utf-8",
    )

    other_dirs = {
        "CF_DIR": tmp_path / "cf",
        "CREDITO_DIR": tmp_path / "cf2",
        "TICKETS_DIR": tmp_path / "tickets",
        "NOTAS_DEBITO_DIR": tmp_path / "notas_debito",
        "NOTAS_REMISION_DIR": tmp_path / "notas_remision",
    }
    for attr, path in other_dirs.items():
        path.mkdir(exist_ok=True)
        monkeypatch.setattr(facturacion_tab, attr, str(path))
    monkeypatch.setattr(facturacion_tab, "NOTAS_CREDITO_DIR", str(nota_dir))
    monkeypatch.setattr(facturacion_tab, "ADDITIONAL_DIRS", [])

    monkeypatch.setattr(facturacion_tab, "loading_dialog", lambda *a, **k: nullcontext())
    monkeypatch.setattr(facturacion_tab.QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(facturacion_tab.QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(facturacion_tab.QMessageBox, "critical", lambda *a, **k: None)

    new_code = "11111111-2222-4333-8444-999999999999"
    new_control = "DTE-05-S001P001-000000000000999"

    def fake_generar_nota_credito_json(db_obj, note_id, **kwargs):
        assert note_id == nota_id
        return {
            "identificacion": {
                "tipoDte": "05",
                "version": 1,
                "ambiente": "00",
                "codigoGeneracion": new_code,
                "numeroControl": new_control,
                "fecEmi": "2024-01-03",
            },
            "receptor": {"nombre": "Cliente"},
            "resumen": {
                "montoTotalOperacion": 10,
                "totalLetras": "DIEZ",
                "condicionOperacion": 1,
                "pagos": None,
            },
            "cuerpoDocumento": [],
        }

    monkeypatch.setattr(dte, "generar_nota_credito_json", fake_generar_nota_credito_json)
    monkeypatch.setattr(dte, "apply_schema_patch", lambda data: data)
    monkeypatch.setattr(dte.catalogos, "get_dte_schema", lambda _: {})

    def fake_get_paths(fecha, nombre, numero, doc_type):
        return pdf_path, json_path

    monkeypatch.setattr(docs_utils, "get_dte_document_paths", fake_get_paths)

    def fake_save_file(path, content, add_final_newline=True):
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, str):
            text = content
        else:
            text = json.dumps(content)
        if add_final_newline and not text.endswith("\n"):
            text += "\n"
        target.write_text(text, encoding="utf-8")

    monkeypatch.setattr(stable_json, "save_file", fake_save_file)
    monkeypatch.setattr(dte.jws, "sign_json", make_jws)
    monkeypatch.setattr(dte, "_save_signed_dte", lambda *a, **k: None)
    monkeypatch.setattr(
        dte,
        "_load_dte_api_config",
        lambda: {"url": "https://apitest.dtes.mh.gob.sv/fesv/recepciondte", "ambiente": "pruebas"},
    )
    monkeypatch.setattr(dte.auth, "get_last_auth_host", lambda: "apitest.dtes.mh.gob.sv")
    monkeypatch.setattr(dte, "auth_headers", lambda headers: {**headers, "Authorization": "Bearer T"})

    captured = {}

    def fake_post(url, documento, meta, *args, **kwargs):
        captured["meta"] = dict(meta)
        return {"estado": "PROCESADO", "sello": "SELLO"}

    monkeypatch.setattr(dte, "_post_dte", fake_post)

    man = SimpleNamespace(
        db=db,
        refresh_data=lambda: None,
        _clientes=[],
        _Distribuidores=[],
    )

    tab = facturacion_tab.FacturacionTab(man)
    monkeypatch.setattr(tab, "load_invoices", lambda: None)
    resp = tab._reenviar_nota_credito(
        {"row_type": "orphan", "tipo": "Nota de crédito"},
        {"json": str(json_path)},
    )
    assert resp["estado"] == "PROCESADO"

    assert captured["meta"]["codigoGeneracion"] == new_code
    assert captured["meta"]["codigoGeneracion"] != old_code

    row = db.cursor.execute(
        "SELECT codigo_generacion, estado FROM dte_envios WHERE venta_id=? ORDER BY id DESC LIMIT 1",
        (nota_id,),
    ).fetchone()
    assert row["codigo_generacion"] == new_code
    assert row["estado"].upper() == "PROCESADO"

    with open(json_path, "r", encoding="utf-8") as fh:
        refreshed = json.load(fh)
    assert refreshed["identificacion"]["codigoGeneracion"] == new_code


def test_resend_credit_note_without_db_entry_transmits_orphan(
    monkeypatch, qt_app, tmp_path
):
    monkeypatch.setattr(facturacion_tab.FacturacionTab, "load_invoices", lambda self: None)

    db = DB(":memory:")
    man = SimpleNamespace(db=db, _clientes=[], _Distribuidores=[], refresh_data=lambda: None)
    tab = facturacion_tab.FacturacionTab(man)

    json_path = tmp_path / "nota_credito.json"
    json_path.write_text("{}", encoding="utf-8")

    def fake_buscar(self, factura, expected):
        raise ValueError("No se encontró la nota asociada al documento seleccionado")

    monkeypatch.setattr(facturacion_tab.FacturacionTab, "_buscar_nota_id", fake_buscar)

    def fail_enviar(*args, **kwargs):  # pragma: no cover - guard against regressions
        pytest.fail("enviar_nota_credito no debe llamarse cuando falta la nota")

    monkeypatch.setattr(facturacion_tab.dte, "enviar_nota_credito", fail_enviar)

    called = {}

    def fake_transmit(db_obj, path):
        called["path"] = path
        return {"estado": "Transmitido"}

    monkeypatch.setattr(facturacion_tab.dte, "transmitir_dte_orphan", fake_transmit)

    entry = {"row_type": "orphan", "tipo": "Nota de crédito"}
    factura = {"json": str(json_path)}

    resp = tab._reenviar_nota_credito(entry, factura)

    assert called["path"] == str(json_path)
    assert resp["estado"] == "Transmitido"
