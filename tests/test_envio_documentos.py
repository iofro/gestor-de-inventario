import copy
import json
import logging
import os
import sqlite3
from typing import Any

import pytest
import requests

from pathlib import Path
from db import DB
from dte import (
    enviar_factura,
    enviar_nota_credito,
    enviar_nota_debito,
    enviar_nota_remision,
    enviar_evento_contingencia,
    enviar_evento_anulacion,
    _post_dte,
    DTEValidationError,
)
import dte
import auth
from tests.conftest import make_jws
from utils import docs
from utils.snapshot import Snapshot


@pytest.fixture(autouse=True)
def _stub_auth_headers(monkeypatch):
    def fake_auth_headers(extra=None, *, ambiente=None):
        headers = {"Authorization": "Bearer JWT"}
        if isinstance(extra, dict):
            headers.update(extra)
        return headers

    monkeypatch.setattr(dte, "auth_headers", fake_auth_headers)


@pytest.fixture(autouse=True)
def _freeze_nota_fecemi(monkeypatch):
    monkeypatch.setattr(dte, "fecha_emision_hoy_str", lambda now=None: "2024-01-02")


class DummyResponse:
    def __init__(self, url, headers, payload, *, status_code=200, response_headers=None):
        self.status_code = status_code
        self._payload = payload
        self.headers = dict(response_headers or {})
        self.request = type(
            "Req",
            (),
            {
                "url": url,
                "headers": headers or {},
                "method": "POST",
            },
        )()
        self.elapsed = None
        self.history = []
        if isinstance(payload, (dict, list)):
            self.text = json.dumps(payload)
        else:
            self.text = str(payload)
        self.content = self.text.encode("utf-8")

    def json(self):
        return self._payload

    def raise_for_status(self):
        if 400 <= int(self.status_code) < 600:
            raise requests.HTTPError(f"HTTP {self.status_code}")


def create_sale(db):
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("P1", "X", None,  vid, None, 0, 0, 0, 1)
    pid = db.cursor.lastrowid
    venta_id = db.add_venta("2024-01-01", 10)
    db.add_detalle_venta(venta_id, pid, 1, 10, vendedor_id=vid)
    return venta_id


def test_enviar_factura_rechazo_y_reenvio(monkeypatch, caplog, tmp_path):
    db = DB(":memory:")
    venta = create_sale(db)

    sign_calls = {"count": 0, "tokens": []}

    def fake_sign(data):
        sign_calls["count"] += 1
        token = make_jws(data)
        sign_calls["tokens"].append(token)
        return token

    monkeypatch.setattr("utils.jws.sign_json", fake_sign)
    monkeypatch.setattr(auth, "get_token", lambda: "Bearer JWT")
    monkeypatch.setattr(auth, "get_last_auth_host", lambda: "apitest.dtes.mh.gob.sv")
    monkeypatch.setattr("dte.validate_dte_json", lambda data, db=None: None)
    monkeypatch.setattr(
        "dte.generar_dte_json",
        lambda db_obj, vid, **kwargs: {
            "receptor": {"nombre": "Cliente"},
            "cuerpoDocumento": [{"cantidad": 1, "precioUni": 10}],
            "resumen": {
                "totalNoSuj": 0,
                "totalExenta": 0,
                "totalGravada": 10,
                "subTotalVentas": 10,
                "descuNoSuj": 0,
                "descuExenta": 0,
                "descuGravada": 0,
                "porcentajeDescuento": 0,
                "totalDescu": 0,
                "tributos": [],
                "subTotal": 10,
                "ivaRete1": 0,
                "reteRenta": 0,
                "montoTotalOperacion": 10,
                "totalNoGravado": 0,
                "totalPagar": 10,
                "totalLetras": "DIEZ",
                "saldoFavor": 0,
                "condicionOperacion": 1,
                "pagos": None,
                "numPagoElectronico": None,
            },
            "identificacion": {
                "tipoDte": "01",
                "version": 2,
                "ambiente": "00",
                "codigoGeneracion": "ABC",
                "numeroControl": "DTE-01-S001P001-000000000000123",
            },
        },
    )

    responses = [
        {"estado": "Rechazado", "descripcionMsg": "Error", "observaciones": ["campo"]},
        {"estado": "PROCESADO", "sello": "ABC"},
    ]

    calls = []

    def fake_post(url, json=None, headers=None, timeout=20, **kwargs):
        calls.append((url, headers, json))
        data = responses.pop(0)
        return DummyResponse(url, headers, data)

    monkeypatch.setattr("dte.requests.post", fake_post)

    orig_load = dte._load_datos_negocio

    def fake_load():
        data = orig_load()
        data.setdefault("dte_api", {})["url"] = dte.DEFAULT_RECEPCION_URL
        data["dte_api"]["ambiente"] = "pruebas"
        return data

    monkeypatch.setattr(dte, "_load_datos_negocio", fake_load)

    caplog.set_level(logging.ERROR)
    res = enviar_factura(db, venta)
    assert res["estado"] == "Rechazado"
    assert "Error" in caplog.text and "campo" in caplog.text
    row = db.cursor.execute("SELECT count(*) c FROM dte_envios WHERE venta_id=?", (venta,)).fetchone()
    assert row["c"] == 1

    caplog.clear()
    res = enviar_factura(db, venta)
    assert res["estado"] == "PROCESADO"
    row = db.cursor.execute("SELECT count(*) c FROM dte_envios WHERE venta_id=?", (venta,)).fetchone()
    assert row["c"] == 2

    # Verifica que se hayan almacenado los campos clave
    row = db.cursor.execute(
        """
        SELECT codigo_generacion, numero_control, estado, sello
          FROM dte_envios WHERE venta_id=? ORDER BY id DESC LIMIT 1
        """,
        (venta,),
    ).fetchone()
    assert row["codigo_generacion"] == "ABC"
    assert row["numero_control"] == "DTE-01-S001P001-000000000000123"
    assert row["estado"] == "PROCESADO"
    assert row["sello"] == "ABC"

    assert sign_calls["count"] == 2
    assert len(calls) == 2
    for url, headers, body in calls:
        assert url == dte.DEFAULT_RECEPCION_URL
        assert body["documento"] in sign_calls["tokens"]
        assert headers["Authorization"] == "Bearer JWT"
        assert headers["Content-Type"] == "application/json"
        assert headers["Accept"] == "application/json"
        assert headers["User-Agent"] == "Vertex-DTE/1.0"


def test_ensure_nota_snapshot_rehydrates_from_saved_json(tmp_path, monkeypatch):
    base_code = "ABC123XYZ789"
    origen_payload = {
        "identificacion": {
            "codigoGeneracion": base_code,
            "numeroControl": "DTE-03-001",
        }
    }
    source_dir = tmp_path / "facturas_credito_fiscal"
    source_dir.mkdir()
    (source_dir / "origen.json").write_text(json.dumps(origen_payload), encoding="utf-8")

    dtes_dir = tmp_path / "dtes"
    fcf_dir = tmp_path / "fcf"
    consumidor_dir = tmp_path / "consumidor"
    tickets_dir = tmp_path / "tickets"
    notas_credito_dir = tmp_path / "notas_credito"
    notas_debito_dir = tmp_path / "notas_debito"
    archive_cf_dir = tmp_path / "archive_cf"
    archive_credito_dir = tmp_path / "archive_credito"

    for directory in (
        dtes_dir,
        fcf_dir,
        consumidor_dir,
        tickets_dir,
        notas_credito_dir,
        notas_debito_dir,
        archive_cf_dir,
        archive_credito_dir,
    ):
        directory.mkdir()

    monkeypatch.setattr(dte, "DTES_DIR", str(dtes_dir))
    monkeypatch.setattr(dte, "FACTURAS_CONSUMIDOR_FINAL_DIR", str(consumidor_dir))
    monkeypatch.setattr(dte, "FACTURAS_CREDITO_FISCAL_DIR", str(source_dir))
    monkeypatch.setattr(dte, "TICKETS_OUTPUT_DIR", str(tickets_dir))
    monkeypatch.setattr(dte, "NOTAS_CREDITO_DIR", str(notas_credito_dir))
    monkeypatch.setattr(dte, "NOTAS_DEBITO_DIR", str(notas_debito_dir))
    monkeypatch.setattr(dte, "FACTURAS_ARCHIVE_CF_DIR", str(archive_cf_dir))
    monkeypatch.setattr(dte, "FACTURAS_ARCHIVE_CREDITO_DIR", str(archive_credito_dir))

    venta_id = 42
    nota_id = 99

    class DummyCursor:
        def __init__(self, nota_row, envio_row, detalles_row=None):
            self._nota_row = nota_row
            self._envio_row = envio_row
            self._detalles_row = detalles_row if detalles_row is not None else nota_row
            self._last_query = ""

        def execute(self, *_args, **_kwargs):
            query = _args[0] if _args else ""
            if isinstance(query, str):
                self._last_query = query
            return self

        def fetchone(self):
            if "FROM notas" in self._last_query:
                if "detalles" in self._last_query.lower():
                    return self._detalles_row
                return self._nota_row
            if "FROM dte_envios" in self._last_query:
                return self._envio_row
            return None

    class DummyDB:
        def __init__(self):
            nota_row = {"venta_id": venta_id, "tipo": "credito"}
            detalles_row = {"detalles": json.dumps({"documentoRelacionado": [{"codigoGeneracion": base_code}]})}
            envio_row = {"codigo_generacion": base_code, "numero_control": "NC-001"}
            self.cursor = DummyCursor(nota_row, envio_row, detalles_row)
            self._snapshots = {}
            self.set_calls: list[tuple[int, str]] = []

        def get_snapshot_by_venta(self, venta_ref):
            return self._snapshots.get(venta_ref)

        def set_snapshot_path(self, venta_ref, path):
            self._snapshots[venta_ref] = path
            self.set_calls.append((venta_ref, path))

    db = DummyDB()
    assert db.get_snapshot_by_venta(venta_id) is None

    dte._ensure_nota_snapshot(db, nota_id, expected_tipo="credito")

    stored_path = dtes_dir / base_code / "documento.json"
    assert stored_path.exists()
    with stored_path.open("r", encoding="utf-8") as fh:
        persisted = json.load(fh)
    assert persisted["identificacion"]["codigoGeneracion"] == base_code
    assert db.get_snapshot_by_venta(venta_id) == str(stored_path)
    assert db.set_calls == [(venta_id, str(stored_path))]


def test_ensure_nota_snapshot_fallbacks_to_nota_detalles(tmp_path, monkeypatch):
    base_code = "FALLBACK123456"
    origen_payload = {
        "identificacion": {
            "codigoGeneracion": base_code,
            "numeroControl": "DTE-07-001",
        }
    }

    source_dir = tmp_path / "facturas_credito_fiscal"
    source_dir.mkdir()
    (source_dir / "legacy.json").write_text(json.dumps(origen_payload), encoding="utf-8")

    dtes_dir = tmp_path / "dtes"
    consumidor_dir = tmp_path / "consumidor"
    notas_credito_dir = tmp_path / "notas_credito"
    for directory in (dtes_dir, consumidor_dir, notas_credito_dir):
        directory.mkdir()

    monkeypatch.setattr(dte, "DTES_DIR", str(dtes_dir))
    monkeypatch.setattr(dte, "FACTURAS_CONSUMIDOR_FINAL_DIR", str(consumidor_dir))
    monkeypatch.setattr(dte, "FACTURAS_CREDITO_FISCAL_DIR", str(source_dir))
    monkeypatch.setattr(dte, "TICKETS_OUTPUT_DIR", "")
    monkeypatch.setattr(dte, "NOTAS_CREDITO_DIR", str(notas_credito_dir))
    monkeypatch.setattr(dte, "NOTAS_DEBITO_DIR", "")
    monkeypatch.setattr(dte, "FACTURAS_ARCHIVE_CF_DIR", "")
    monkeypatch.setattr(dte, "FACTURAS_ARCHIVE_CREDITO_DIR", "")

    venta_id = 2112
    nota_id = 1225

    class DummyCursor:
        def __init__(self, nota_row, envio_row, detalles_row=None):
            self._nota_row = nota_row
            self._envio_row = envio_row
            self._detalles_row = detalles_row if detalles_row is not None else nota_row
            self._last_query = ""

        def execute(self, *_args, **_kwargs):
            query = _args[0] if _args else ""
            if isinstance(query, str):
                self._last_query = query
            return self

        def fetchone(self):
            if "FROM notas" in self._last_query:
                if "detalles" in self._last_query.lower():
                    return self._detalles_row
                return self._nota_row
            if "FROM dte_envios" in self._last_query:
                return self._envio_row
            return None

    class DummyDB:
        def __init__(self):
            nota_row = {"venta_id": venta_id, "tipo": "credito"}
            detalles_row = {
                "detalles": json.dumps(
                    {
                        "documentoRelacionado": [
                            {
                                "codigoGeneracion": base_code,
                                "numeroControl": "FALL-001",
                            }
                        ]
                    }
                )
            }
            envio_row = None
            self.cursor = DummyCursor(nota_row, envio_row, detalles_row)
            self._snapshots = {}
            self.set_calls: list[tuple[int, str]] = []

        def get_snapshot_by_venta(self, venta_ref):
            return self._snapshots.get(venta_ref)

        def set_snapshot_path(self, venta_ref, path):
            self._snapshots[venta_ref] = path
            self.set_calls.append((venta_ref, path))

    db = DummyDB()
    assert db.get_snapshot_by_venta(venta_id) is None

    dte._ensure_nota_snapshot(db, nota_id, expected_tipo="credito")

    stored_path = dtes_dir / base_code / "documento.json"
    assert stored_path.exists()
    assert db.get_snapshot_by_venta(venta_id) == str(stored_path)
    assert db.set_calls == [(venta_id, str(stored_path))]


def test_ensure_nota_snapshot_rehydrates_from_typed_subdir(tmp_path, monkeypatch, caplog):
    base_code = "TIPEDIR123"
    payload = {
        "identificacion": {
            "codigoGeneracion": base_code,
            "numeroControl": "DTE-04-001",
        }
    }

    dtes_dir = tmp_path / "dtes"
    source_path = dtes_dir / "fcf" / base_code / "documento.json"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr(dte, "DTES_DIR", str(dtes_dir))
    monkeypatch.setattr(dte, "FACTURAS_CONSUMIDOR_FINAL_DIR", "")
    monkeypatch.setattr(dte, "FACTURAS_CREDITO_FISCAL_DIR", "")
    monkeypatch.setattr(dte, "TICKETS_OUTPUT_DIR", "")
    monkeypatch.setattr(dte, "NOTAS_CREDITO_DIR", "")
    monkeypatch.setattr(dte, "NOTAS_DEBITO_DIR", "")
    monkeypatch.setattr(dte, "FACTURAS_ARCHIVE_CF_DIR", "")
    monkeypatch.setattr(dte, "FACTURAS_ARCHIVE_CREDITO_DIR", "")

    venta_id = 314
    nota_id = 2718

    class DummyCursor:
        def __init__(self, nota_row, envio_row, detalles_row=None):
            self._nota_row = nota_row
            self._envio_row = envio_row
            self._detalles_row = detalles_row if detalles_row is not None else nota_row
            self._last_query = ""

        def execute(self, *_args, **_kwargs):
            query = _args[0] if _args else ""
            if isinstance(query, str):
                self._last_query = query
            return self

        def fetchone(self):
            if "FROM notas" in self._last_query:
                if "detalles" in self._last_query.lower():
                    return self._detalles_row
                return self._nota_row
            if "FROM dte_envios" in self._last_query:
                return self._envio_row
            return None

    class DummyDB:
        def __init__(self):
            nota_row = {"venta_id": venta_id, "tipo": "credito"}
            detalles_row = {"detalles": json.dumps({"documentoRelacionado": [{"codigoGeneracion": base_code}]})}
            envio_row = {"codigo_generacion": base_code, "numero_control": "NC-002"}
            self.cursor = DummyCursor(nota_row, envio_row, detalles_row)
            self._snapshots = {}
            self.set_calls: list[tuple[int, str]] = []

        def get_snapshot_by_venta(self, venta_ref):
            return self._snapshots.get(venta_ref)

        def set_snapshot_path(self, venta_ref, path):
            self._snapshots[venta_ref] = path
            self.set_calls.append((venta_ref, path))

    db = DummyDB()
    assert db.get_snapshot_by_venta(venta_id) is None

    caplog.set_level(logging.INFO)
    dte._ensure_nota_snapshot(db, nota_id, expected_tipo="credito")

    stored_path = dtes_dir / base_code / "documento.json"
    assert stored_path.exists()
    assert db.get_snapshot_by_venta(venta_id) == str(stored_path)
    assert any("SNAPSHOT: rehidratado" in rec.getMessage() for rec in caplog.records)
    assert db.set_calls == [(venta_id, str(stored_path))]


def test_ensure_nota_snapshot_handles_sqlite_row_metadata(tmp_path, monkeypatch):
    base_code = "ROWMETA321"
    payload = {
        "identificacion": {
            "codigoGeneracion": base_code,
            "numeroControl": "DTE-05-009",
        }
    }

    source_dir = tmp_path / "facturas_credito_fiscal"
    source_dir.mkdir()
    (source_dir / "legacy.json").write_text(json.dumps(payload), encoding="utf-8")

    dtes_dir = tmp_path / "dtes"
    dtes_dir.mkdir()

    monkeypatch.setattr(dte, "DTES_DIR", str(dtes_dir))
    monkeypatch.setattr(dte, "FACTURAS_CONSUMIDOR_FINAL_DIR", "")
    monkeypatch.setattr(dte, "FACTURAS_CREDITO_FISCAL_DIR", str(source_dir))
    monkeypatch.setattr(dte, "TICKETS_OUTPUT_DIR", "")
    monkeypatch.setattr(dte, "NOTAS_CREDITO_DIR", "")
    monkeypatch.setattr(dte, "NOTAS_DEBITO_DIR", "")
    monkeypatch.setattr(dte, "FACTURAS_ARCHIVE_CF_DIR", "")
    monkeypatch.setattr(dte, "FACTURAS_ARCHIVE_CREDITO_DIR", "")

    venta_id = 918
    nota_id = 273

    sql_conn = sqlite3.connect(":memory:")
    sql_conn.row_factory = sqlite3.Row
    sql_cur = sql_conn.cursor()
    sql_cur.execute(
        "select ? as codigo_generacion, ? as numero_control",
        (base_code, "NC-ROW-001"),
    )
    envio_row = sql_cur.fetchone()

    sql_cur.execute(
        "select ? as detalles",
        (
            json.dumps(
                {
                    "documentoRelacionado": [
                        {
                            "codigoGeneracion": base_code,
                            "numeroControl": "ROW-CTRL-1",
                        }
                    ]
                }
            ),
        ),
    )
    detalles_row = sql_cur.fetchone()
    sql_conn.close()

    class DummyCursor:
        def __init__(self, nota_row, envio_row_obj, detalles_row_obj):
            self._nota_row = nota_row
            self._envio_row = envio_row_obj
            self._detalles_row = detalles_row_obj
            self._last_query = ""

        def execute(self, *_args, **_kwargs):
            query = _args[0] if _args else ""
            if isinstance(query, str):
                self._last_query = query
            return self

        def fetchone(self):
            if "FROM notas" in self._last_query:
                if "detalles" in self._last_query.lower():
                    return self._detalles_row
                return self._nota_row
            if "FROM dte_envios" in self._last_query:
                return self._envio_row
            return None

    class DummyDB:
        def __init__(self):
            nota_row = {"venta_id": venta_id, "tipo": "credito"}
            self.cursor = DummyCursor(nota_row, envio_row, detalles_row)
            self._snapshots = {}
            self.set_calls: list[tuple[int, str]] = []

        def get_snapshot_by_venta(self, venta_ref):
            return self._snapshots.get(venta_ref)

        def set_snapshot_path(self, venta_ref, path):
            self._snapshots[venta_ref] = path
            self.set_calls.append((venta_ref, path))

    db = DummyDB()
    assert db.get_snapshot_by_venta(venta_id) is None

    dte._ensure_nota_snapshot(db, nota_id, expected_tipo="credito")

    stored_path = dtes_dir / base_code / "documento.json"
    assert stored_path.exists()
    assert db.get_snapshot_by_venta(venta_id) == str(stored_path)
    assert db.set_calls == [(venta_id, str(stored_path))]


def test_ensure_nota_snapshot_when_canonical_exists(tmp_path, monkeypatch, caplog):
    base_code = "EXISTE555"
    payload = {
        "identificacion": {
            "codigoGeneracion": base_code,
            "numeroControl": "DTE-06-444",
        }
    }

    dtes_dir = tmp_path / "dtes"
    canonical_path = dtes_dir / base_code / "documento.json"
    canonical_path.parent.mkdir(parents=True, exist_ok=True)
    canonical_path.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr(dte, "DTES_DIR", str(dtes_dir))
    monkeypatch.setattr(dte, "FACTURAS_CONSUMIDOR_FINAL_DIR", str(dtes_dir))
    monkeypatch.setattr(dte, "FACTURAS_CREDITO_FISCAL_DIR", "")
    monkeypatch.setattr(dte, "TICKETS_OUTPUT_DIR", "")
    monkeypatch.setattr(dte, "NOTAS_CREDITO_DIR", "")
    monkeypatch.setattr(dte, "NOTAS_DEBITO_DIR", "")
    monkeypatch.setattr(dte, "FACTURAS_ARCHIVE_CF_DIR", "")
    monkeypatch.setattr(dte, "FACTURAS_ARCHIVE_CREDITO_DIR", "")

    venta_id = 551
    nota_id = 552

    class DummyCursor:
        def __init__(self, nota_row, envio_row):
            self._nota_row = nota_row
            self._envio_row = envio_row
            self._last_query = ""

        def execute(self, *_args, **_kwargs):
            query = _args[0] if _args else ""
            if isinstance(query, str):
                self._last_query = query
            return self

        def fetchone(self):
            if "FROM notas" in self._last_query:
                return self._nota_row
            if "FROM dte_envios" in self._last_query:
                return self._envio_row
            return None

    class DummyDB:
        def __init__(self):
            nota_row = {"venta_id": venta_id, "tipo": "credito"}
            envio_row = {"codigo_generacion": base_code, "numero_control": "NC-EXISTE"}
            self.cursor = DummyCursor(nota_row, envio_row)
            self._snapshots = {}
            self.set_calls: list[tuple[int, str]] = []

        def get_snapshot_by_venta(self, venta_ref):
            return self._snapshots.get(venta_ref)

        def set_snapshot_path(self, venta_ref, path):
            self._snapshots[venta_ref] = path
            self.set_calls.append((venta_ref, path))

    db = DummyDB()
    assert db.get_snapshot_by_venta(venta_id) is None

    def fail_copy(src, dst):  # pragma: no cover - should not be called
        raise AssertionError("copyfile should not be called when canonical exists")

    monkeypatch.setattr(dte.shutil, "copyfile", fail_copy)

    caplog.set_level(logging.INFO)
    dte._ensure_nota_snapshot(db, nota_id, expected_tipo="credito")

    assert db.get_snapshot_by_venta(venta_id) == str(canonical_path)
    assert db.set_calls == [(venta_id, str(canonical_path))]
    assert any("SNAPSHOT: ya existía" in rec.getMessage() for rec in caplog.records)


def test_no_envia_si_validacion_falla(monkeypatch):
    db = DB(":memory:")
    venta = create_sale(db)

    sent = []

    def fake_post(url, json=None, headers=None, timeout=20, **kwargs):
        sent.append(True)

    monkeypatch.setattr("dte.requests.post", fake_post)
    monkeypatch.setattr(auth, "get_token", lambda: "Bearer JWT")

    sign_calls = {"count": 0}

    def fake_sign(data):
        sign_calls["count"] += 1
        return "TOKEN"

    monkeypatch.setattr("utils.jws.sign_json", fake_sign)

    monkeypatch.setattr(
        "dte.generar_dte_json",
        lambda db_obj, vid, **kwargs: {"identificacion": {"tipoDte": "01"}},
    )

    with pytest.raises(DTEValidationError):
        enviar_factura(db, venta)

    assert sent == []
    assert sign_calls["count"] == 0


def test_transmitir_dte_tipo03_preserves_tipo(monkeypatch, tmp_path):
    db = DB(":memory:")
    venta = create_sale(db)

    captured = {}

    def fake_generar(db_obj, vid, tipo_dte="01", **kwargs):
        captured["requested_tipo"] = tipo_dte
        return {
            "identificacion": {
                "tipoDte": "03",
                "version": 1,
                "ambiente": "00",
                "codigoGeneracion": "00000000-0000-4000-8000-000000000003",
                "numeroControl": "DTE-03-S001P001-000000000000123",
            },
            "resumen": {
                "totalLetras": "DIEZ",
                "totalPagar": 10,
                "condicionOperacion": 1,
                "pagos": None,
            },
            "cuerpoDocumento": [],
        }

    def fail_ticket(*args, **kwargs):
        raise AssertionError("generar_ticket_json no debe invocarse")

    def fake_enviar_documento(db_obj, doc_id, data, modo, jws_token=None):
        dest = tmp_path / data["identificacion"]["tipoDte"]
        dest.mkdir(parents=True, exist_ok=True)
        path = dest / "documento.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        captured["path"] = path
        return {"estado": "Transmitido"}

    monkeypatch.setattr("dte.generar_dte_json", fake_generar)
    monkeypatch.setattr("dte.generar_ticket_json", fail_ticket)
    monkeypatch.setattr("dte.apply_schema_patch", lambda data: data)
    monkeypatch.setattr("dte.catalogos.get_dte_schema", lambda _: {})
    monkeypatch.setattr("dte._enviar_documento", fake_enviar_documento)

    resp = dte.transmitir_dte(db, venta, tipo_dte="03")

    assert resp["estado"] == "Transmitido"
    assert captured.get("requested_tipo") == "03"
    path = captured.get("path")
    assert path and path.exists()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["identificacion"]["tipoDte"] == "03"


def test_enviar_nota_credito_canonicalizes_snapshot(tmp_path, monkeypatch):
    base_code = "UUID-CREDITO-BASE"
    note_code = "UUID-CREDITO-NOTA"
    dtes_dir = tmp_path / "dtes"
    typed_path = dtes_dir / "fcf" / base_code / "documento.json"
    typed_path.parent.mkdir(parents=True, exist_ok=True)
    typed_payload = {"identificacion": {"codigoGeneracion": base_code}}
    typed_path.write_text(json.dumps(typed_payload), encoding="utf-8")

    canonical_path = dtes_dir / base_code / "documento.json"
    assert not canonical_path.exists()

    monkeypatch.setattr(dte, "DTES_DIR", str(dtes_dir))

    venta_id = 123
    nota_id = 456

    class DummyCursor:
        def __init__(self):
            self._last_query = ""

        def execute(self, query, params):
            self._last_query = query
            return self

        def fetchone(self):
            if "FROM notas" in self._last_query:
                return {"venta_id": venta_id, "tipo": "credito"}
            return None

    class DummyDB:
        def __init__(self):
            self.cursor = DummyCursor()
            self.snapshot = Snapshot(
                uuid=base_code,
                path=str(typed_path),
                tipo_documento="01",
                fecha_emision="2024-01-01",
                payload=typed_payload,
            )
            self.set_calls: list[tuple[int, str]] = []

        def get_snapshot_by_venta(self, venta_ref):
            if venta_ref == venta_id:
                return self.snapshot
            return None

        def set_snapshot_path(self, venta_ref, path):
            self.set_calls.append((venta_ref, path))

        def update_venta_extra(self, *_args, **_kwargs):
            pass

    db = DummyDB()

    payload = {
        "identificacion": {
            "codigoGeneracion": note_code,
            "numeroControl": "NC-001",
        },
        "receptor": {"nombre": "Cliente"},
        "resumen": {
            "totalLetras": "DIEZ",
            "documentoRelacionado": [
                {"codigoGeneracion": base_code, "numeroControl": "DTE-BASE-001"}
            ],
        },
    }

    monkeypatch.setattr(
        "dte.generar_nota_credito_json", lambda _db, _nid, **_kwargs: payload
    )
    monkeypatch.setattr("dte.apply_schema_patch", lambda data: data)
    monkeypatch.setattr("dte.catalogos.get_dte_schema", lambda _codigo: {})

    out_dir = tmp_path / "out_nc"

    def fake_paths(fecha, empresa, numero_control, doc_type, root=None):
        out_dir.mkdir(parents=True, exist_ok=True)
        return out_dir, str(out_dir / "documento.json")

    monkeypatch.setattr(docs, "get_dte_document_paths", fake_paths)
    monkeypatch.setattr("utils.jws.sign_json", lambda data: "TOKEN")

    def fake_save_file(path, content, **kwargs):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, str):
            Path(path).write_text(content, encoding="utf-8")
        else:
            Path(path).write_text(str(content), encoding="utf-8")

    monkeypatch.setattr("utils.stable_json.save_file", fake_save_file)

    captured = {}

    def fake_enviar_documento(db_obj, doc_id, data_obj, modo, jws_token=None):
        captured["payload"] = data_obj
        return {"estado": "Transmitido"}

    monkeypatch.setattr(dte, "_enviar_documento", fake_enviar_documento)

    enviar_nota_credito(db, nota_id, modo="normal")

    assert canonical_path.exists()
    assert json.loads(canonical_path.read_text(encoding="utf-8")) == typed_payload
    assert db.set_calls == [(venta_id, str(canonical_path))]
    assert captured.get("payload") is payload


def test_enviar_nota_credito_canonicalizes_snapshot_without_metadata(
    tmp_path, monkeypatch, caplog
):
    base_code = "UUID-CREDITO-BASE-MIN"
    note_code = "UUID-CREDITO-NOTA-MIN"
    dtes_dir = tmp_path / "dtes"
    typed_path = dtes_dir / "fcf" / base_code / "documento.json"
    typed_path.parent.mkdir(parents=True, exist_ok=True)
    typed_payload = {"identificacion": {"codigoGeneracion": base_code}}
    typed_path.write_text(json.dumps(typed_payload), encoding="utf-8")

    canonical_path = dtes_dir / base_code / "documento.json"
    assert not canonical_path.exists()

    monkeypatch.setattr(dte, "DTES_DIR", str(dtes_dir))

    venta_id = 2024
    nota_id = 3030

    class DummyCursor:
        def __init__(self):
            self._last_query = ""

        def execute(self, query, params):
            self._last_query = query
            return self

        def fetchone(self):
            if "FROM notas" in self._last_query:
                return {"venta_id": venta_id, "tipo": "credito"}
            return None

    class DummyDB:
        def __init__(self):
            self.cursor = DummyCursor()
            self.snapshot = Snapshot(
                uuid=base_code,
                path=str(typed_path),
                tipo_documento="01",
                fecha_emision="2024-02-01",
                payload=typed_payload,
            )
            self.set_calls: list[tuple[int, str]] = []

        def get_snapshot_by_venta(self, venta_ref):
            if venta_ref == venta_id:
                return self.snapshot
            return None

        def set_snapshot_path(self, venta_ref, path):
            self.set_calls.append((venta_ref, path))

        def update_venta_extra(self, *_args, **_kwargs):
            pass

    db = DummyDB()

    payload = {
        "identificacion": {
            "codigoGeneracion": note_code,
            "numeroControl": "NC-002",
        },
        "receptor": {"nombre": "Cliente"},
        "cuerpoDocumento": [
            {
                "cantidad": 1,
                "precioUni": 10,
                "descripcion": "Producto",
            }
        ],
        "resumen": {"totalLetras": "DIEZ"},
    }

    monkeypatch.setattr(
        "dte.generar_nota_credito_json", lambda _db, _nid, **_kwargs: payload
    )
    monkeypatch.setattr("dte.apply_schema_patch", lambda data: data)
    monkeypatch.setattr("dte.catalogos.get_dte_schema", lambda _codigo: {})

    out_dir = tmp_path / "out_nc_sin_meta"

    def fake_paths(fecha, empresa, numero_control, doc_type, root=None):
        out_dir.mkdir(parents=True, exist_ok=True)
        return out_dir, str(out_dir / "documento.json")

    monkeypatch.setattr(docs, "get_dte_document_paths", fake_paths)
    monkeypatch.setattr("utils.jws.sign_json", lambda data: "TOKEN")

    def fake_save_file(path, content, **kwargs):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, str):
            Path(path).write_text(content, encoding="utf-8")
        else:
            Path(path).write_text(str(content), encoding="utf-8")

    monkeypatch.setattr("utils.stable_json.save_file", fake_save_file)

    captured = {}

    def fake_enviar_documento(db_obj, doc_id, data_obj, modo, jws_token=None):
        captured["payload"] = data_obj
        return {"estado": "Transmitido"}

    monkeypatch.setattr(dte, "_enviar_documento", fake_enviar_documento)

    caplog.set_level(logging.INFO)

    enviar_nota_credito(db, nota_id, modo="normal")

    assert canonical_path.exists()
    assert json.loads(canonical_path.read_text(encoding="utf-8")) == typed_payload
    assert db.set_calls == [(venta_id, str(canonical_path))]
    assert any(
        "source_path.parent" in record.getMessage()
        and base_code in record.getMessage()
        for record in caplog.records
    )
    assert captured.get("payload") is payload


def test_enviar_nota_debito_respects_existing_canonical_snapshot(tmp_path, monkeypatch):
    base_code = "UUID-DEBITO-BASE"
    note_code = "UUID-DEBITO-NOTA"
    dtes_dir = tmp_path / "dtes"
    canonical_path = dtes_dir / base_code / "documento.json"
    canonical_path.parent.mkdir(parents=True, exist_ok=True)
    canonical_payload = {"identificacion": {"codigoGeneracion": base_code, "campo": "canon"}}
    canonical_path.write_text(json.dumps(canonical_payload), encoding="utf-8")
    before_mtime = canonical_path.stat().st_mtime_ns

    typed_path = dtes_dir / "ccf" / base_code / "documento.json"
    typed_path.parent.mkdir(parents=True, exist_ok=True)
    typed_payload = {"identificacion": {"codigoGeneracion": base_code, "campo": "typed"}}
    typed_path.write_text(json.dumps(typed_payload), encoding="utf-8")

    monkeypatch.setattr(dte, "DTES_DIR", str(dtes_dir))

    venta_id = 789
    nota_id = 321

    class DummyCursor:
        def __init__(self):
            self._last_query = ""

        def execute(self, query, params):
            self._last_query = query
            return self

        def fetchone(self):
            if "FROM notas" in self._last_query:
                return {"venta_id": venta_id, "tipo": "debito"}
            return None

    class DummyDB:
        def __init__(self):
            self.cursor = DummyCursor()
            self.snapshot = Snapshot(
                uuid=base_code,
                path=str(typed_path),
                tipo_documento="01",
                fecha_emision="2024-01-02",
                payload=typed_payload,
            )
            self.set_calls: list[tuple[int, str]] = []

        def get_snapshot_by_venta(self, venta_ref):
            if venta_ref == venta_id:
                return self.snapshot
            return None

        def set_snapshot_path(self, venta_ref, path):
            self.set_calls.append((venta_ref, path))

        def update_venta_extra(self, *_args, **_kwargs):
            pass

    db = DummyDB()

    payload = {
        "identificacion": {
            "codigoGeneracion": note_code,
            "numeroControl": "ND-001",
        },
        "receptor": {"nombre": "Cliente"},
        "resumen": {
            "totalLetras": "QUINCE",
            "documentoRelacionado": [
                {"codigoGeneracion": base_code, "numeroControl": "DTE-BASE-002"}
            ],
        },
    }

    monkeypatch.setattr(
        "dte.generar_nota_debito_json", lambda _db, _nid, **_kwargs: payload
    )
    monkeypatch.setattr("dte.apply_schema_patch", lambda data: data)
    monkeypatch.setattr("dte.catalogos.get_dte_schema", lambda _codigo: {})

    out_dir = tmp_path / "out_nd"

    def fake_paths_debito(fecha, empresa, numero_control, doc_type, root=None):
        out_dir.mkdir(parents=True, exist_ok=True)
        return out_dir, str(out_dir / "documento.json")

    monkeypatch.setattr(docs, "get_dte_document_paths", fake_paths_debito)
    monkeypatch.setattr("utils.jws.sign_json", lambda data: "TOKEN")

    def fake_save_file_debito(path, content, **kwargs):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, str):
            Path(path).write_text(content, encoding="utf-8")
        else:
            Path(path).write_text(str(content), encoding="utf-8")

    monkeypatch.setattr("utils.stable_json.save_file", fake_save_file_debito)

    captured = {}

    def fake_enviar_documento(db_obj, doc_id, data_obj, modo, jws_token=None):
        captured["payload"] = data_obj
        return {"estado": "Transmitido"}

    monkeypatch.setattr(dte, "_enviar_documento", fake_enviar_documento)

    enviar_nota_debito(db, nota_id, modo="normal")

    assert canonical_path.exists()
    assert json.loads(canonical_path.read_text(encoding="utf-8")) == canonical_payload
    assert canonical_path.stat().st_mtime_ns == before_mtime
    assert db.set_calls == [(venta_id, str(canonical_path))]
    assert captured.get("payload") is payload


def test_enviar_nota_credito(monkeypatch, tmp_path):
    db = DB(":memory:")
    venta = create_sale(db)
    nota_id = db.add_nota(venta, "credito", "2024-01-02", 10, "motivo")

    forced_today = "2025-09-29"
    monkeypatch.setattr(dte, "fecha_emision_hoy_str", lambda now=None: forced_today)

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
        lambda vid: dummy_snapshot if (vid == venta or str(vid) == str(venta)) else None,
    )

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
        lambda vid: dummy_snapshot if (vid == venta or str(vid) == str(venta)) else None,
    )

    sign_calls = {"count": 0, "tokens": [], "payloads": []}

    def fake_sign(data):
        sign_calls["count"] += 1
        sign_calls["payloads"].append(json.loads(json.dumps(data)))
        token = make_jws(data)
        sign_calls["tokens"].append(token)
        return token

    monkeypatch.setattr("utils.jws.sign_json", fake_sign)
    monkeypatch.setattr(auth, "get_token", lambda: "Bearer JWT")
    monkeypatch.setattr(auth, "get_last_auth_host", lambda: "apitest.dtes.mh.gob.sv")
    monkeypatch.setattr("dte.validate_dte_json", lambda data, db=None: None)
    monkeypatch.setattr(
        "dte.generar_nota_credito_json",
        lambda db_obj, nid, **_kwargs: {
            "receptor": {"nombre": "Cliente"},
            "cuerpoDocumento": [{"cantidad": 1, "precioUni": 10}],
            "documentoRelacionado": [
                {
                    "tipoDocumento": "01",
                    "numeroDocumento": "BASE",
                    "fechaEmision": "2024-01-01",
                }
            ],
            "resumen": {
                "totalNoSuj": 0,
                "totalExenta": 0,
                "totalGravada": 10,
                "subTotalVentas": 10,
                "descuNoSuj": 0,
                "descuExenta": 0,
                "descuGravada": 0,
                "porcentajeDescuento": 0,
                "totalDescu": 0,
                "tributos": [],
                "subTotal": 10,
                "ivaRete1": 0,
                "reteRenta": 0,
                "montoTotalOperacion": 10,
                "totalNoGravado": 0,
                "totalPagar": 10,
                "totalLetras": "DIEZ",
                "saldoFavor": 0,
                "condicionOperacion": 1,
                "pagos": None,
                "numPagoElectronico": None,
            },
            "identificacion": {
                "tipoDte": "01",
                "version": 2,
                "ambiente": "00",
                "codigoGeneracion": "NC1",
            },
        },
    )

    calls = []
    orig_paths = docs.get_dte_document_paths

    def fake_paths(fecha, empresa, numero_control, doc_type, root=None):
        return orig_paths(fecha, empresa, numero_control, doc_type, root=tmp_path)

    monkeypatch.setattr(docs, "get_dte_document_paths", fake_paths)

    def fake_post(url, json=None, headers=None, timeout=20, **kwargs):
        calls.append((url, headers, json))
        return DummyResponse(
            url,
            headers,
            {"estado": "Transmitido", "sello": "XYZ"},
        )

    monkeypatch.setattr("dte.requests.post", fake_post)

    orig_load = dte._load_datos_negocio

    def fake_load():
        data = orig_load()
        data.setdefault("dte_api", {})["url"] = dte.DEFAULT_RECEPCION_URL
        data["dte_api"]["ambiente"] = "pruebas"
        return data

    monkeypatch.setattr(dte, "_load_datos_negocio", fake_load)

    res = enviar_nota_credito(db, nota_id)
    assert res["estado"] == "Transmitido"
    row = db.cursor.execute("SELECT estado FROM dte_envios WHERE venta_id=?", (nota_id,)).fetchone()
    assert row["estado"] == "Transmitido"
    assert sign_calls["count"] == 1
    assert len(calls) == 1
    url, headers, body = calls[0]
    assert url == dte.DEFAULT_RECEPCION_URL
    assert body["documento"] in sign_calls["tokens"]
    assert headers["Authorization"] == "Bearer JWT"
    assert headers["Content-Type"] == "application/json"
    assert headers["Accept"] == "application/json"
    assert headers["User-Agent"] == "Vertex-DTE/1.0"

    assert sign_calls["payloads"], "Se esperaba capturar el payload firmado"
    signed_payload = sign_calls["payloads"][0]
    assert signed_payload["identificacion"]["fecEmi"] == forced_today
    assert signed_payload["documentoRelacionado"][0]["fechaEmision"] == "2024-01-01"


def test_enviar_nota_credito_reuses_jws(monkeypatch, tmp_path):
    db = DB(":memory:")
    venta = create_sale(db)
    nota_id = db.add_nota(venta, "credito", "2024-01-02", 10, "motivo")

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
        lambda vid: dummy_snapshot if (vid == venta or str(vid) == str(venta)) else None,
    )

    data = {
        "receptor": {"nombre": "Cliente"},
        "cuerpoDocumento": [{"cantidad": 1, "precioUni": 10}],
        "resumen": {
            "totalNoSuj": 0,
            "totalExenta": 0,
            "totalGravada": 10,
            "subTotalVentas": 10,
            "descuNoSuj": 0,
            "descuExenta": 0,
            "descuGravada": 0,
            "porcentajeDescuento": 0,
            "totalDescu": 0,
            "tributos": [],
            "subTotal": 10,
            "ivaRete1": 0,
            "reteRenta": 0,
            "montoTotalOperacion": 10,
            "totalNoGravado": 0,
            "totalPagar": 10,
            "totalLetras": "DIEZ",
            "saldoFavor": 0,
            "condicionOperacion": 1,
            "pagos": None,
            "numPagoElectronico": None,
        },
        "identificacion": {
            "tipoDte": "01",
            "version": 2,
            "ambiente": "00",
            "codigoGeneracion": "NC1",
            "numeroControl": "1",
            "fecEmi": "2024-01-02",
        },
    }

    monkeypatch.setattr(
        "dte.generar_nota_credito_json",
        lambda db_obj, nid, **_kwargs: data,
    )

    sign_calls = {"count": 0}

    def fake_sign(payload):
        sign_calls["count"] += 1
        return "SIGNED"

    monkeypatch.setattr("utils.jws.sign_json", fake_sign)

    orig_paths = docs.get_dte_document_paths

    def fake_paths(fecha, empresa, numero_control, doc_type, root=None):
        return orig_paths(fecha, empresa, numero_control, doc_type, root=tmp_path)

    monkeypatch.setattr(docs, "get_dte_document_paths", fake_paths)

    _, json_path = fake_paths(
        data["identificacion"]["fecEmi"],
        data["receptor"]["nombre"],
        data["identificacion"]["numeroControl"],
        "NotaCredito",
    )

    captured = {}

    def fake_post(url, json=None, headers=None, timeout=20, **kwargs):
        captured["token"] = json["documento"]
        return DummyResponse(
            url,
            headers,
            {"estado": "Transmitido", "sello": "XYZ"},
        )

    monkeypatch.setattr("dte.requests.post", fake_post)

    monkeypatch.setattr(auth, "get_token", lambda: "Bearer JWT")
    monkeypatch.setattr(auth, "get_last_auth_host", lambda: "apitest.dtes.mh.gob.sv")

    orig_load = dte._load_datos_negocio

    def fake_load():
        cfg = orig_load()
        cfg.setdefault("dte_api", {})["url"] = dte.DEFAULT_RECEPCION_URL
        cfg["dte_api"]["ambiente"] = "pruebas"
        return cfg

    monkeypatch.setattr(dte, "_load_datos_negocio", fake_load)

    res = enviar_nota_credito(db, nota_id)
    assert res["estado"] == "Transmitido"
    assert captured["token"] == "SIGNED"
    assert sign_calls["count"] == 1


def test_enviar_nota_credito_resigns_after_rechazo(monkeypatch, tmp_path):
    db = DB(":memory:")
    venta = create_sale(db)
    nota_id = db.add_nota(venta, "credito", "2024-01-02", 10, "motivo")

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
        lambda vid: dummy_snapshot if (vid == venta or str(vid) == str(venta)) else None,
    )

    template = {
        "receptor": {"nombre": "Cliente"},
        "cuerpoDocumento": [{"cantidad": 1, "precioUni": 10}],
        "resumen": {
            "totalNoSuj": 0,
            "totalExenta": 0,
            "totalGravada": 10,
            "subTotalVentas": 10,
            "descuNoSuj": 0,
            "descuExenta": 0,
            "descuGravada": 0,
            "porcentajeDescuento": 0,
            "totalDescu": 0,
            "tributos": [],
            "subTotal": 10,
            "ivaRete1": 0,
            "reteRenta": 0,
            "montoTotalOperacion": 10,
            "totalNoGravado": 0,
            "totalPagar": 10,
            "totalLetras": "DIEZ",
            "saldoFavor": 0,
            "condicionOperacion": 1,
            "pagos": None,
            "numPagoElectronico": None,
        },
        "identificacion": {
            "tipoDte": "01",
            "version": 2,
            "ambiente": "00",
            "codigoGeneracion": "UUID-1",
            "numeroControl": "NC-1",
            "fecEmi": "2024-01-02",
        },
    }

    call_state = {"count": 0}

    def fake_generate(db_obj, nid, **_kwargs):
        idx = call_state["count"]
        call_state["count"] += 1
        payload = copy.deepcopy(template)
        payload["identificacion"]["codigoGeneracion"] = f"UUID-{idx + 1}"
        return payload

    monkeypatch.setattr(
        "dte.generar_nota_credito_json",
        fake_generate,
    )
    monkeypatch.setattr("utils.jws.sign_json", lambda data: make_jws(data))

    orig_paths = docs.get_dte_document_paths

    def fake_paths(fecha, empresa, numero_control, doc_type, root=None):
        return orig_paths(fecha, empresa, numero_control, doc_type, root=tmp_path)

    monkeypatch.setattr(docs, "get_dte_document_paths", fake_paths)

    _, json_path = fake_paths(
        template["identificacion"]["fecEmi"],
        template["receptor"]["nombre"],
        template["identificacion"]["numeroControl"],
        "NotaCredito",
    )
    jws_path = os.path.splitext(json_path)[0] + ".jws"

    posts = []

    def fake_post(url, documento, meta, *args, **kwargs):
        posts.append({"meta": dict(meta), "documento": documento})
        if len(posts) == 1:
            return {"estado": "Rechazado", "sello": ""}
        return {"estado": "Transmitido", "sello": "XYZ"}

    monkeypatch.setattr(dte, "_post_dte", fake_post)

    monkeypatch.setattr(auth, "get_token", lambda: "Bearer JWT")
    monkeypatch.setattr(auth, "get_last_auth_host", lambda: "apitest.dtes.mh.gob.sv")

    orig_load = dte._load_datos_negocio

    def fake_load():
        cfg = orig_load()
        cfg.setdefault("dte_api", {})["url"] = dte.DEFAULT_RECEPCION_URL
        cfg["dte_api"]["ambiente"] = "pruebas"
        return cfg

    monkeypatch.setattr(dte, "_load_datos_negocio", fake_load)

    res1 = enviar_nota_credito(db, nota_id)
    assert res1["estado"] == "Rechazado"
    assert len(posts) == 1
    assert posts[0]["meta"]["codigoGeneracion"] == "UUID-1"
    with open(jws_path, "r", encoding="utf-8") as fh:
        first_token = fh.read()

    res2 = enviar_nota_credito(db, nota_id)
    assert res2["estado"] == "Transmitido"
    assert len(posts) == 2
    assert posts[1]["meta"]["codigoGeneracion"] == "UUID-2"
    with open(jws_path, "r", encoding="utf-8") as fh:
        second_token = fh.read()

    assert first_token != second_token
    assert posts[0]["documento"] != posts[1]["documento"]


def test_post_dte_packs_jws_in_json_body(monkeypatch):
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=20, **kwargs):
        captured["body"] = json
        return DummyResponse(url, headers, {})

    monkeypatch.setattr("dte.requests.post", fake_post)

    meta = {
        "ambiente": "00",
        "version": 2,
        "tipoDte": "01",
        "codigoGeneracion": "ABC",
    }
    token = make_jws({"identificacion": meta})
    _post_dte(dte.DEFAULT_RECEPCION_URL, "Bearer TOKEN", token, meta)

    body_json = captured["body"]
    assert body_json["documento"] == token


def test_enviar_evento_contingencia(monkeypatch, caplog, tmp_path):
    db = DB(":memory:")
    venta_id = create_sale(db)

    sign_calls = {"count": 0, "token": ""}

    def fake_sign(data):
        sign_calls["count"] += 1
        token = make_jws(data)
        sign_calls["token"] = token
        return token

    monkeypatch.setattr("utils.jws.sign_json", fake_sign)
    monkeypatch.setattr(auth, "get_token", lambda: "Bearer JWT")
    monkeypatch.setattr(auth, "get_last_auth_host", lambda: "apitest.dtes.mh.gob.sv")

    calls = []

    def fake_post(url, json=None, headers=None, timeout=20, **kwargs):
        calls.append((url, headers, json))
        return DummyResponse(
            url,
            headers,
            {
                "estado": "Rechazado",
                "descripcionMsg": "Fallo",
                "observaciones": {"campo": "invalido"},
            },
        )

    monkeypatch.setattr("dte.requests.post", fake_post)

    orig_load = dte._load_datos_negocio

    def fake_load():
        data = orig_load()
        data.setdefault("dte_api", {})["url"] = dte.DEFAULT_RECEPCION_URL
        data["dte_api"]["ambiente"] = "pruebas"
        return data

    monkeypatch.setattr(dte, "_load_datos_negocio", fake_load)

    caplog.set_level(logging.ERROR)
    data = {
        "identificacion": {
            "version": 2,
            "ambiente": "00",
            "tipoDte": "CON",
            "codigoGeneracion": "EV1",
        },
        "id": venta_id,
    }
    res = enviar_evento_contingencia(db, venta_id, data)
    assert res["estado"] == "Rechazado"
    assert "Fallo" in caplog.text and "campo: invalido" in caplog.text
    row = db.cursor.execute("SELECT estado FROM dte_envios WHERE venta_id=?", (venta_id,)).fetchone()
    assert row["estado"] == "Rechazado"
    assert sign_calls["count"] == 1
    assert len(calls) == 1
    url, headers, body = calls[0]
    assert url == dte.DEFAULT_EVENTO_URL
    assert body["documento"] == sign_calls["token"]
    assert headers["Authorization"] == "Bearer JWT"
    assert headers["Content-Type"] == "application/json"
    assert headers["Accept"] == "application/json"
    assert headers["User-Agent"] == "Vertex-DTE/1.0"


def test_enviar_evento_anulacion(monkeypatch, tmp_path):
    db = DB(":memory:")
    venta_id = create_sale(db)

    sign_calls = {"count": 0, "token": ""}

    def fake_sign(data):
        sign_calls["count"] += 1
        token = make_jws(data)
        sign_calls["token"] = token
        return token

    monkeypatch.setattr("utils.jws.sign_json", fake_sign)
    monkeypatch.setattr(auth, "get_token", lambda: "Bearer JWT")
    monkeypatch.setattr(auth, "get_last_auth_host", lambda: "apitest.dtes.mh.gob.sv")

    calls = []

    def fake_post(url, json=None, headers=None, timeout=20, **kwargs):
        calls.append((url, headers, json))
        return DummyResponse(
            url,
            headers,
            {"estado": "Transmitido", "sello": "SSS"},
        )

    monkeypatch.setattr("dte.requests.post", fake_post)

    orig_load = dte._load_datos_negocio

    def fake_load():
        data = orig_load()
        data.setdefault("dte_api", {})["url"] = dte.DEFAULT_RECEPCION_URL
        data["dte_api"]["ambiente"] = "pruebas"
        return data

    monkeypatch.setattr(dte, "_load_datos_negocio", fake_load)

    data = {
        "identificacion": {
            "version": 2,
            "ambiente": "00",
            "tipoDte": "ANU",
            "codigoGeneracion": "EV2",
        },
        "id": venta_id,
    }
    res = enviar_evento_anulacion(db, venta_id, data)
    assert res["estado"] == "Transmitido"
    row = db.cursor.execute("SELECT estado FROM dte_envios WHERE venta_id=?", (venta_id,)).fetchone()
    assert row["estado"] == "Transmitido"
    assert sign_calls["count"] == 1
    assert len(calls) == 1
    url, headers, body = calls[0]
    assert url == dte.DEFAULT_EVENTO_URL
    assert body["documento"] == sign_calls["token"]
    assert headers["Authorization"] == "Bearer JWT"
    assert headers["Content-Type"] == "application/json"
    assert headers["Accept"] == "application/json"
    assert headers["User-Agent"] == "Vertex-DTE/1.0"


def test_enviar_factura_default_contingencia(monkeypatch):
    db = DB(":memory:")
    venta_id = create_sale(db)

    monkeypatch.setattr(dte, "get_default_modo_transmision", lambda: "contingencia")
    monkeypatch.setattr(dte, "_load_dte_api_config", lambda: {"url": "http://example"})
    monkeypatch.setattr(
        "dte.generar_dte_json",
        lambda db_obj, vid, **kwargs: {"resumen": {"totalLetras": "X"}},
    )
    monkeypatch.setattr("dte.apply_schema_patch", lambda data: data)
    monkeypatch.setattr("dte.catalogos.get_dte_schema", lambda t: {})
    monkeypatch.setattr(auth, "get_token", lambda: "T")
    monkeypatch.setattr(auth, "get_last_auth_host", lambda: None)
    monkeypatch.setattr("dte._save_signed_dte", lambda *a, **k: None)
    monkeypatch.setattr("utils.jws.sign_json", lambda data: "TOKEN")
    monkeypatch.setattr(
        "dte.requests.post",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not post")),
    )

    res = enviar_factura(db, venta_id)
    assert res["estado"] == "Pendiente"
    row = db.cursor.execute(
        "SELECT estado, modo FROM dte_envios WHERE venta_id=?", (venta_id,)
    ).fetchone()
    assert row["estado"] == "Pendiente"
    assert row["modo"] == "contingencia"


def test_enviar_nota_credito_default_contingencia(monkeypatch, tmp_path):
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

    monkeypatch.setattr(dte, "get_default_modo_transmision", lambda: "contingencia")
    monkeypatch.setattr(dte, "_load_dte_api_config", lambda: {"url": "http://example"})
    monkeypatch.setattr(
        "dte.generar_nota_credito_json",
        lambda db_obj, nid, **_kwargs: {
            "identificacion": {"fecEmi": "2024-01-02", "numeroControl": "1"},
            "receptor": {"nombre": "C"},
            "resumen": {"totalLetras": "X"},
        },
    )
    monkeypatch.setattr("dte.apply_schema_patch", lambda data: data)
    monkeypatch.setattr("dte.catalogos.get_dte_schema", lambda t: {})
    monkeypatch.setattr(auth, "get_token", lambda: "T")
    monkeypatch.setattr(auth, "get_last_auth_host", lambda: None)
    monkeypatch.setattr("dte._save_signed_dte", lambda *a, **k: None)
    monkeypatch.setattr(
        "utils.docs.get_dte_document_paths",
        lambda *a, **k: (tmp_path / "x.pdf", tmp_path / "x.json"),
    )
    monkeypatch.setattr("utils.jws.sign_json", lambda data: "TOKEN")
    monkeypatch.setattr("utils.stable_json.save_file", lambda *a, **k: None)
    monkeypatch.setattr("utils.stable_json.stable_stringify", lambda d, indent=2: "{}")
    monkeypatch.setattr(
        "dte.requests.post",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not post")),
    )

    res = enviar_nota_credito(db, nota_id)
    assert res["estado"] == "Pendiente"
    row = db.cursor.execute(
        "SELECT estado, modo FROM dte_envios WHERE venta_id=?", (nota_id,)
    ).fetchone()
    assert row["estado"] == "Pendiente"
    assert row["modo"] == "contingencia"


def test_enviar_nota_debito_default_contingencia(monkeypatch, tmp_path):
    db = DB(":memory:")
    venta_id = create_sale(db)
    nota_id = db.add_nota(venta_id, "debito", "2024-01-02", 10, "motivo")

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

    forced_today = "2025-09-29"
    monkeypatch.setattr(dte, "fecha_emision_hoy_str", lambda now=None: forced_today)

    monkeypatch.setattr(dte, "get_default_modo_transmision", lambda: "contingencia")
    monkeypatch.setattr(dte, "_load_dte_api_config", lambda: {"url": "http://example"})
    monkeypatch.setattr(
        "dte.generar_nota_debito_json",
        lambda db_obj, nid, **_kwargs: {
            "identificacion": {"fecEmi": "2024-01-02", "numeroControl": "1"},
            "receptor": {"nombre": "C"},
            "resumen": {"totalLetras": "X"},
            "documentoRelacionado": [
                {
                    "tipoDocumento": "01",
                    "numeroDocumento": "BASE",
                    "fechaEmision": "2024-01-01",
                }
            ],
        },
    )
    monkeypatch.setattr("dte.apply_schema_patch", lambda data: data)
    monkeypatch.setattr("dte.catalogos.get_dte_schema", lambda t: {})
    monkeypatch.setattr(auth, "get_token", lambda: "T")
    monkeypatch.setattr(auth, "get_last_auth_host", lambda: None)
    monkeypatch.setattr(
        "utils.docs.get_dte_document_paths",
        lambda *a, **k: (tmp_path / "x.pdf", tmp_path / "x.json"),
    )
    signed_payloads: list[dict] = []

    def fake_sign(payload):
        signed_payloads.append(json.loads(json.dumps(payload)))
        return "TOKEN"

    monkeypatch.setattr("utils.jws.sign_json", fake_sign)
    monkeypatch.setattr("utils.stable_json.save_file", lambda *a, **k: None)
    monkeypatch.setattr("utils.stable_json.stable_stringify", lambda d, indent=2: "{}")
    monkeypatch.setattr(
        "dte.requests.post",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not post")),
    )

    res = enviar_nota_debito(db, nota_id)
    assert res["estado"] == "Pendiente"
    row = db.cursor.execute(
        "SELECT estado, modo FROM dte_envios WHERE venta_id=?", (nota_id,)
    ).fetchone()
    assert row["estado"] == "Pendiente"
    assert row["modo"] == "contingencia"
    assert signed_payloads, "Se esperaba capturar el payload firmado"
    assert signed_payloads[0]["identificacion"]["fecEmi"] == forced_today
    assert signed_payloads[0]["documentoRelacionado"][0]["fechaEmision"] == "2024-01-01"


def test_enviar_nota_remision_default_contingencia(monkeypatch):
    db = DB(":memory:")
    venta_id = create_sale(db)
    nota_id = db.add_nota(venta_id, "remision", "2024-01-02", 10, "motivo")

    forced_today = "2025-09-29"
    monkeypatch.setattr(dte, "fecha_emision_hoy_str", lambda now=None: forced_today)

    monkeypatch.setattr(dte, "get_default_modo_transmision", lambda: "contingencia")
    monkeypatch.setattr(dte, "_load_dte_api_config", lambda: {"url": "http://example"})
    monkeypatch.setattr(
        "nota_remision.generar_nota_remision_desde_db",
        lambda db_obj, nid, **_kwargs: {
            "identificacion": {"numeroControl": "1"},
            "documentoRelacionado": [
                {
                    "tipoDocumento": "01",
                    "numeroDocumento": "BASE",
                    "fechaEmision": "2024-01-01",
                }
            ],
            "resumen": {"totalLetras": "X"},
        },
    )
    monkeypatch.setattr("dte.apply_schema_patch", lambda data: data)
    monkeypatch.setattr("dte.catalogos.get_dte_schema", lambda t: {})
    monkeypatch.setattr(auth, "get_token", lambda: "T")
    monkeypatch.setattr(auth, "get_last_auth_host", lambda: None)
    monkeypatch.setattr("dte._save_signed_dte", lambda *a, **k: None)

    signed_payloads: list[dict] = []

    def fake_sign(payload):
        signed_payloads.append(json.loads(json.dumps(payload)))
        return "TOKEN"

    monkeypatch.setattr("utils.jws.sign_json", fake_sign)
    monkeypatch.setattr(
        "dte.requests.post",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not post")),
    )

    res = enviar_nota_remision(db, nota_id)
    assert res["estado"] == "Pendiente"
    row = db.cursor.execute(
        "SELECT estado, modo FROM dte_envios WHERE venta_id=?", (nota_id,)
    ).fetchone()
    assert row["estado"] == "Pendiente"
    assert row["modo"] == "contingencia"
    assert signed_payloads, "Se esperaba capturar el payload firmado"
    assert signed_payloads[0]["identificacion"]["fecEmi"] == forced_today
    assert signed_payloads[0]["documentoRelacionado"][0]["fechaEmision"] == "2024-01-01"


def test_enviar_nota_credito_propagates_production_ambiente(monkeypatch, tmp_path):
    db = DB(":memory:")
    venta_id = create_sale(db)
    nota_id = db.add_nota(venta_id, "credito", "2024-01-02", 10, "motivo")

    monkeypatch.setattr(dte, "_ensure_nota_snapshot", lambda *a, **k: None)
    monkeypatch.setattr(dte, "_ensure_canonical_snapshot", lambda *a, **k: None)
    monkeypatch.setattr(dte, "_resolve_base_document_code", lambda *a, **k: (None, None))
    monkeypatch.setattr(db, "get_snapshot_by_venta", lambda *_: None)
    monkeypatch.setattr(db, "update_venta_extra", lambda *a, **k: None)
    monkeypatch.setattr(
        dte,
        "_load_dte_api_config",
        lambda: {"ambiente": "produccion", "url": "https://api.example/fesv/recepciondte"},
    )

    captured: dict[str, Any] = {}

    def fake_generate(db_obj, note_id, *, ambiente="00", **_kwargs):
        captured["ambiente_param"] = ambiente
        return {
            "identificacion": {
                "numeroControl": "NC-1",
                "codigoGeneracion": "UUID-1",
                "fecEmi": "2024-01-02",
                "ambiente": ambiente,
            },
            "receptor": {"nombre": "Cliente"},
            "resumen": {"totalLetras": "X"},
        }

    monkeypatch.setattr(dte, "generar_nota_credito_json", fake_generate)
    monkeypatch.setattr(dte, "apply_schema_patch", lambda data: data)
    monkeypatch.setattr(dte.catalogos, "get_dte_schema", lambda *_: {})
    monkeypatch.setattr("utils.jws.sign_json", lambda data: "TOKEN")
    monkeypatch.setattr("utils.stable_json.save_file", lambda *a, **k: None)
    monkeypatch.setattr("utils.stable_json.stable_stringify", lambda data, indent=2: json.dumps(data))
    monkeypatch.setattr(
        "utils.docs.get_dte_document_paths",
        lambda *a, **k: (tmp_path, str(tmp_path / "nc.json")),
    )
    monkeypatch.setattr(dte.os.path, "exists", lambda path: False)

    sent_payload: dict[str, Any] = {}

    def fake_enviar_documento(_db, _id, payload, _modo, jws_token=None):
        sent_payload["payload"] = json.loads(json.dumps(payload))
        return {"estado": "Transmitido"}

    monkeypatch.setattr(dte, "_enviar_documento", fake_enviar_documento)

    enviar_nota_credito(db, nota_id, modo="normal")

    assert captured.get("ambiente_param") == "01"
    assert sent_payload["payload"]["identificacion"]["ambiente"] == "01"


def test_enviar_nota_debito_propagates_production_ambiente(monkeypatch, tmp_path):
    db = DB(":memory:")
    venta_id = create_sale(db)
    nota_id = db.add_nota(venta_id, "debito", "2024-01-02", 10, "motivo")

    monkeypatch.setattr(dte, "_ensure_nota_snapshot", lambda *a, **k: None)
    monkeypatch.setattr(dte, "_ensure_canonical_snapshot", lambda *a, **k: None)
    monkeypatch.setattr(dte, "_resolve_base_document_code", lambda *a, **k: (None, None))
    monkeypatch.setattr(db, "get_snapshot_by_venta", lambda *_: None)
    monkeypatch.setattr(db, "update_venta_extra", lambda *a, **k: None)
    monkeypatch.setattr(
        dte,
        "_load_dte_api_config",
        lambda: {"ambiente": "produccion", "url": "https://api.example/fesv/recepciondte"},
    )

    captured: dict[str, Any] = {}

    def fake_generate(db_obj, note_id, *, ambiente="00", **_kwargs):
        captured["ambiente_param"] = ambiente
        return {
            "identificacion": {
                "numeroControl": "ND-1",
                "codigoGeneracion": "UUID-1",
                "fecEmi": "2024-01-02",
                "ambiente": ambiente,
            },
            "documentoRelacionado": [
                {
                    "tipoDocumento": "01",
                    "numeroDocumento": "BASE",
                    "fechaEmision": "2024-01-01",
                }
            ],
            "receptor": {"nombre": "Cliente"},
            "resumen": {"totalLetras": "X"},
        }

    monkeypatch.setattr(dte, "generar_nota_debito_json", fake_generate)
    monkeypatch.setattr(dte, "apply_schema_patch", lambda data: data)
    monkeypatch.setattr(dte.catalogos, "get_dte_schema", lambda *_: {})
    monkeypatch.setattr("utils.jws.sign_json", lambda data: "TOKEN")
    monkeypatch.setattr("utils.stable_json.save_file", lambda *a, **k: None)
    monkeypatch.setattr("utils.stable_json.stable_stringify", lambda data, indent=2: json.dumps(data))
    monkeypatch.setattr(
        "utils.docs.get_dte_document_paths",
        lambda *a, **k: (tmp_path, str(tmp_path / "nd.json")),
    )
    monkeypatch.setattr(dte.os.path, "exists", lambda path: False)

    sent_payload: dict[str, Any] = {}

    def fake_enviar_documento(_db, _id, payload, _modo, jws_token=None):
        sent_payload["payload"] = json.loads(json.dumps(payload))
        return {"estado": "Transmitido"}

    monkeypatch.setattr(dte, "_enviar_documento", fake_enviar_documento)

    enviar_nota_debito(db, nota_id, modo="normal")

    assert captured.get("ambiente_param") == "01"
    assert sent_payload["payload"]["identificacion"]["ambiente"] == "01"


def test_enviar_nota_remision_propagates_production_ambiente(monkeypatch, tmp_path):
    db = DB(":memory:")
    venta_id = create_sale(db)
    nota_id = db.add_nota(venta_id, "remision", "2024-01-02", 10, "motivo")

    monkeypatch.setattr(db, "update_venta_extra", lambda *a, **k: None)
    monkeypatch.setattr(
        dte,
        "_load_dte_api_config",
        lambda: {"ambiente": "produccion", "url": "https://api.example/fesv/recepciondte"},
    )

    captured: dict[str, Any] = {}

    def fake_generate(db_obj, note_id, *, ambiente="00", **_kwargs):
        captured["ambiente_param"] = ambiente
        return {
            "identificacion": {
                "numeroControl": "NR-1",
                "codigoGeneracion": "UUID-1",
                "fecEmi": "2024-01-02",
                "ambiente": ambiente,
            },
            "documentoRelacionado": [
                {
                    "tipoDocumento": "01",
                    "numeroDocumento": "BASE",
                    "fechaEmision": "2024-01-01",
                }
            ],
            "receptor": {"nombre": "Cliente"},
            "resumen": {"totalLetras": "X"},
        }

    monkeypatch.setattr("nota_remision.generar_nota_remision_desde_db", fake_generate)
    monkeypatch.setattr(dte, "apply_schema_patch", lambda data: data)
    monkeypatch.setattr(dte.catalogos, "get_dte_schema", lambda *_: {})
    monkeypatch.setattr("utils.stable_json.save_file", lambda *a, **k: None)
    monkeypatch.setattr("utils.stable_json.stable_stringify", lambda data, indent=2: json.dumps(data))
    monkeypatch.setattr(
        "utils.docs.get_dte_document_paths",
        lambda *a, **k: (tmp_path, str(tmp_path / "nr.json")),
    )

    sent_payload: dict[str, Any] = {}

    def fake_enviar_documento(_db, _id, payload, _modo):
        sent_payload["payload"] = json.loads(json.dumps(payload))
        return {"estado": "Transmitido"}

    monkeypatch.setattr(dte, "_enviar_documento", fake_enviar_documento)

    enviar_nota_remision(db, nota_id, modo="normal")

    assert captured.get("ambiente_param") == "01"
    assert sent_payload["payload"]["identificacion"]["ambiente"] == "01"

