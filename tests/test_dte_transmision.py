from db import DB
from dte import transmitir_dte, _post_dte
import dte
import json
from datetime import datetime
from pathlib import Path
import os
import pytest
import auth
from utils import versioned_dte
from tests.conftest import make_jws


def create_sale(db):
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("P1", "X", None,  vid, None, 0, 0, 0, 1)
    pid = db.cursor.lastrowid
    venta_id = db.add_venta("2024-01-01", 10)
    db.add_detalle_venta(venta_id, pid, 1, 10, vendedor_id=vid)
    return venta_id


def test_transmitir_dte_contingencia(monkeypatch, tmp_path):
    db = DB(":memory:")
    venta = create_sale(db)
    monkeypatch.setattr(dte, "__file__", str(tmp_path / "dte.py"))
    data = {"identificacion": {"tipoDte": "01", "codigoGeneracion": "ABC"}, "resumen": {"totalLetras": "X"}}
    pend_path = dte.save_dte_json(data)
    version_dir = os.path.dirname(pend_path)
    db.update_venta_extra(venta, {"dteJsonPath": pend_path})
    monkeypatch.setattr(dte, "apply_schema_patch", lambda d: d)
    monkeypatch.setattr(dte.catalogos, "get_dte_schema", lambda t: {})
    monkeypatch.setattr(dte, "_load_dte_api_config", lambda: {"url": "http://example"})
    monkeypatch.setattr(auth, "get_token", lambda: "T")
    monkeypatch.setattr(auth, "get_last_auth_host", lambda: None)
    res = transmitir_dte(db, venta, modo="contingencia")
    assert res["estado"] == "Pendiente"
    row = db.cursor.execute(
        "SELECT estado FROM dte_envios WHERE venta_id=?", (venta,)
    ).fetchone()
    assert row["estado"] == "Pendiente"


def test_transmitir_dte_default_contingencia(monkeypatch, tmp_path):
    db = DB(":memory:")
    venta = create_sale(db)
    monkeypatch.setattr(dte, "__file__", str(tmp_path / "dte.py"))
    data = {"identificacion": {"tipoDte": "01", "codigoGeneracion": "DEF"}, "resumen": {"totalLetras": "X"}}
    pend_path = dte.save_dte_json(data)
    version_dir = os.path.dirname(pend_path)
    db.update_venta_extra(venta, {"dteJsonPath": pend_path})
    monkeypatch.setattr(dte, "get_default_modo_transmision", lambda: "contingencia")
    monkeypatch.setattr(dte, "apply_schema_patch", lambda d: d)
    monkeypatch.setattr(dte.catalogos, "get_dte_schema", lambda t: {})
    monkeypatch.setattr(dte, "_load_dte_api_config", lambda: {"url": "http://example"})
    monkeypatch.setattr(auth, "get_token", lambda: "T")
    monkeypatch.setattr(auth, "get_last_auth_host", lambda: None)
    monkeypatch.setattr(
        "dte.requests.post",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not post")),
    )
    res = transmitir_dte(db, venta)
    assert res["estado"] == "Pendiente"
    row = db.cursor.execute(
        "SELECT estado, modo FROM dte_envios WHERE venta_id=?", (venta,)
    ).fetchone()
    assert row["estado"] == "Pendiente"
    assert row["modo"] == "contingencia"



def test_transmitir_dte_normal(monkeypatch, tmp_path):
    ambiente = "pruebas"
    db = DB(":memory:")
    venta = create_sale(db)
    monkeypatch.setattr(dte, "__file__", str(tmp_path / "dte.py"))
    data = {
        "receptor": {"nombre": "Cliente"},
        "cuerpoDocumento": [{"cantidad": 1, "precioUni": 10}],
        "resumen": {"totalGravada": 10, "totalPagar": 10, "totalLetras": "DIEZ"},
        "identificacion": {
            "tipoDte": "01",
            "version": 2,
            "ambiente": "00",
            "codigoGeneracion": "ABC",
        },
    }
    pend_path = dte.save_dte_json(data)
    version_dir = os.path.dirname(pend_path)
    db.update_venta_extra(venta, {"dteJsonPath": pend_path})
    token = make_jws(data)
    token_calls = {"count": 0}
    def fake_sign_json(payload):
        token_calls["count"] += 1
        return token
    monkeypatch.setattr("utils.jws.sign_json", fake_sign_json)
    monkeypatch.setattr(auth, "get_token", lambda: "Bearer JWT")
    monkeypatch.setattr(auth, "get_last_auth_host", lambda: "apitest.dtes.mh.gob.sv")
    monkeypatch.setattr("dte.validate_dte_json", lambda data, db=None: None)
    calls = []
    def fake_post(url, json=None, headers=None, timeout=20):
        calls.append((url, headers, json))
        class R:
            status_code = 200
            def json(self):
                return {"estado": "Transmitido", "sello": "ABC123"}
            def raise_for_status(self):
                pass
        return R()
    monkeypatch.setattr("dte.requests.post", fake_post)
    datos = {"dte_api": {"url": dte.DEFAULT_RECEPCION_URL, "ambiente": ambiente}}
    cfg_path = tmp_path / "datos_negocio.json"
    with open(cfg_path, "w", encoding="utf-8") as fh:
        json.dump(datos, fh)
    monkeypatch.setattr("dte.DATOS_NEGOCIO_PATH", str(cfg_path))
    res = transmitir_dte(db, venta)
    assert res["estado"] == "Transmitido"
    assert token_calls["count"] == 1
    assert len(calls) == 1
    url, headers, body = calls[0]
    assert url == dte.DEFAULT_RECEPCION_URL
    assert headers["Authorization"] == "Bearer JWT"
    assert headers["Content-Type"] == "application/json"
    assert headers["Accept"] == "application/json"
    assert headers["User-Agent"] == "Vertex-DTE/1.0"
    assert body["documento"] == token
    row = db.cursor.execute(
        "SELECT estado, sello FROM dte_envios WHERE venta_id=?", (venta,)
    ).fetchone()
    assert row["estado"] == "Transmitido"
    assert row["sello"] == "ABC123"

def test_post_dte_normalizes_bearer(monkeypatch):
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=20):
        captured["headers"] = headers
        captured["url"] = url
        captured["body"] = json

        class R:
            status_code = 200
            text = ""

            def json(self):
                return {}

            def raise_for_status(self):
                pass

        return R()

    monkeypatch.setattr("dte.requests.post", fake_post)
    meta = {"ambiente": "00", "version": 2, "tipoDte": "01", "codigoGeneracion": "ABC"}
    token = make_jws({"identificacion": meta})
    _post_dte(dte.DEFAULT_RECEPCION_URL, "TOKEN", token, meta)
    assert captured["headers"]["Authorization"] == "Bearer TOKEN"
    assert captured["headers"]["Content-Type"] == "application/json"
    assert captured["headers"]["Accept"] == "application/json"
    assert captured["headers"]["User-Agent"] == "Vertex-DTE/1.0"
    assert captured["url"] == dte.DEFAULT_RECEPCION_URL
    assert captured["body"]["documento"] == token
    assert captured["body"]["documento"].count(".") >= 2


def test_post_dte_handles_prefixed_token(monkeypatch):
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=20):
        captured["headers"] = headers
        captured["url"] = url
        captured["body"] = json

        class R:
            status_code = 200
            text = ""

            def json(self):
                return {}

            def raise_for_status(self):
                pass

        return R()

    monkeypatch.setattr("dte.requests.post", fake_post)
    meta = {"ambiente": "00", "version": 2, "tipoDte": "01", "codigoGeneracion": "ABC"}
    token = make_jws({"identificacion": meta})
    _post_dte(dte.DEFAULT_RECEPCION_URL, "Bearer TOKEN", token, meta)
    assert captured["headers"]["Authorization"] == "Bearer TOKEN"
    assert captured["headers"]["Content-Type"] == "application/json"
    assert captured["headers"]["Accept"] == "application/json"
    assert captured["headers"]["User-Agent"] == "Vertex-DTE/1.0"
    assert captured["url"] == dte.DEFAULT_RECEPCION_URL
    assert captured["body"]["documento"] == token
    assert captured["body"]["documento"].count(".") >= 2


def test_post_dte_rejects_invalid_path(monkeypatch):
    def fake_post(url, json=None, headers=None, timeout=20):
        class R:
            status_code = 200

            def json(self):
                return {}

            def raise_for_status(self):
                pass

        return R()

    monkeypatch.setattr("dte.requests.post", fake_post)
    meta = {"ambiente": "00", "version": 2, "tipoDte": "01", "codigoGeneracion": "ABC"}
    token = make_jws({"identificacion": meta})
    bad_url = "https://apitest.dtes.mh.gob.sv/recepciondte/api/recepciondte"
    with pytest.raises(AssertionError):
        _post_dte(bad_url, "Bearer TOKEN", token, meta)


def test_post_dte_handles_non_json(monkeypatch):
    def fake_post(url, json=None, headers=None, timeout=20):
        class R:
            status_code = 200
            text = "error"

            def json(self):
                raise ValueError("no json")

            def raise_for_status(self):
                pass

        return R()

    monkeypatch.setattr("dte.requests.post", fake_post)
    meta = {"ambiente": "00", "version": 2, "tipoDte": "01", "codigoGeneracion": "ABC"}
    token = make_jws({"identificacion": meta})
    res = _post_dte(dte.DEFAULT_RECEPCION_URL, "", token, meta)
    assert res == {"estado": "Recibido", "detalle": "error"}


def test_post_dte_ignores_mismatch(monkeypatch):
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=20):
        captured["body"] = json

        class R:
            status_code = 200
            text = ""

            def json(self):
                return {}

            def raise_for_status(self):
                pass

        return R()

    monkeypatch.setattr("dte.requests.post", fake_post)
    meta = {"ambiente": "00", "version": 2, "tipoDte": "01", "codigoGeneracion": "ABC"}
    token = make_jws({"identificacion": meta})
    _post_dte(
        dte.DEFAULT_RECEPCION_URL,
        "Bearer TOKEN",
        token,
        {**meta, "codigoGeneracion": "XYZ"},
    )
    assert captured["body"]["codigoGeneracion"] == "ABC"


def test_post_dte_missing_fields(monkeypatch):
    calls = {"count": 0}

    def fake_post(url, json=None, headers=None, timeout=20):
        calls["count"] += 1
        class R:
            status_code = 200
            text = ""

            def json(self):
                return {}

            def raise_for_status(self):
                pass

        return R()

    monkeypatch.setattr("dte.requests.post", fake_post)
    token = make_jws({})
    res = _post_dte(dte.DEFAULT_RECEPCION_URL, "Bearer TOKEN", token, {})
    assert res["estado"] == "Error"
    assert calls["count"] == 0


def test_post_dte_invalid_tipo(monkeypatch):
    def fake_post(url, json=None, headers=None, timeout=20):
        class R:
            status_code = 200
            text = ""

            def json(self):
                return {}

            def raise_for_status(self):
                pass

        return R()

    monkeypatch.setattr("dte.requests.post", fake_post)
    meta = {"ambiente": "00", "version": 2, "tipoDte": "99", "codigoGeneracion": "ABC"}
    token = make_jws({"identificacion": meta})
    with pytest.raises(AssertionError):
        _post_dte(dte.DEFAULT_RECEPCION_URL, "Bearer TOKEN", token, meta)


def test_consultar_envio_dte():
    db = DB(":memory:")
    venta = create_sale(db)
    db.registrar_envio_dte(venta, "normal", "Transmitido", "S", '{"ok": true}')
    assert db.consultar_envio_dte(venta) == {"ok": True}


def test_enviar_documento_detecta_json_desincronizado(monkeypatch, tmp_path):
    monkeypatch.setattr(dte, "DTES_DIR", str(tmp_path / "dtes"))
    monkeypatch.setattr(dte, "DTE_FALLIDOS_DIR", str(tmp_path / "dte_fallidos"))
    monkeypatch.setattr(versioned_dte, "DTES_DIR", str(tmp_path / "dtes"))

    db = DB(":memory:")
    venta = create_sale(db)
    codigo = "00000000-0000-4000-8000-000000000123"
    data = {
        "identificacion": {
            "tipoDte": "01",
            "version": 2,
            "ambiente": "00",
            "codigoGeneracion": codigo,
            "numeroControl": "DTE-01-S001P001-000000000000001",
            "fecEmi": "2024-01-01",
            "horEmi": "12:00:00",
        },
        "resumen": {
            "totalGravada": 10,
            "totalPagar": 10,
            "totalLetras": "DIEZ",
            "condicionOperacion": 1,
        },
        "cuerpoDocumento": [],
    }

    base_dir = dte._dte_base_dir(data)
    versioned_dte.ensure_version(data, base_dir=base_dir)

    data_mod = json.loads(json.dumps(data))
    data_mod["resumen"]["totalPagar"] = 11

    monkeypatch.setattr(dte, "_load_dte_api_config", lambda: {"url": "http://example"})
    monkeypatch.setattr(auth, "get_last_auth_host", lambda: None)
    monkeypatch.setattr("utils.jws.sign_json", lambda payload: pytest.fail("No debe firmar"))

    with pytest.raises(RuntimeError) as exc:
        dte._enviar_documento(db, venta, data_mod, "normal")

    assert codigo in str(exc.value)


def test_consultar_envio_dte_texto():
    db = DB(":memory:")
    venta = create_sale(db)
    db.registrar_envio_dte(venta, "normal", "Rechazado", "", "error")
    assert db.consultar_envio_dte(venta) == {}


def test_transmitir_dte_fails_if_already_sent():
    db = DB(":memory:")
    venta = create_sale(db)
    db.registrar_envio_dte(venta, "normal", "Transmitido", "S")
    with pytest.raises(ValueError):
        transmitir_dte(db, venta)


def test_listar_dtes():
    db = DB(":memory:")
    v1 = create_sale(db)
    v2 = create_sale(db)
    db.registrar_envio_dte(v1, "normal", "Transmitido", "S", '{"ok": true}')
    db.registrar_envio_dte(v2, "normal", "Rechazado", "", "error")
    today = datetime.now().date().isoformat()
    rows = db.listar_dtes(today, today, "Transmitido")
    assert len(rows) == 1
    assert rows[0]["estado"] == "Transmitido"


def test_finalize_pendiente_cleans_versions(monkeypatch, tmp_path):
    monkeypatch.setattr(dte, "__file__", str(tmp_path / "dte.py"))
    codigo = "CGTEST"
    data1 = {"identificacion": {"tipoDte": "01", "codigoGeneracion": codigo, "numeroControl": "1"}}
    data2 = {"identificacion": {"tipoDte": "01", "codigoGeneracion": codigo, "numeroControl": "2"}}
    path1 = dte.save_dte_json(data1)
    path2 = dte.save_dte_json(data2)
    base_dest = dte._dte_base_dir(data1)
    versioned_dte.ensure_version(data1, base_dir=base_dest)
    final_path = dte._finalize_pendiente(path2, data2, "TOK", "Aceptado")
    codigo_dir = os.path.dirname(os.path.dirname(final_path))
    assert os.listdir(codigo_dir) == [os.path.basename(os.path.dirname(final_path))]
    assert not os.path.exists(os.path.dirname(os.path.dirname(path1)))


def test_transmitir_dte_blocks_when_json_in_final_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(dte, "__file__", str(tmp_path / "dte.py"))
    db = DB(":memory:")
    venta = create_sale(db)
    codigo = "CGTEST2"
    data = {"identificacion": {"tipoDte": "01", "codigoGeneracion": codigo}}
    pend_path = dte.save_dte_json(data)
    final_path = dte._finalize_pendiente(pend_path, data, "TOK", "Rechazado")
    db.update_venta_extra(venta, {"dteJsonPath": final_path, "codigoGeneracion": codigo})
    with pytest.raises(ValueError):
        transmitir_dte(db, venta)


def test_transmitir_dte_blocks_if_final_json_exists_without_path(monkeypatch, tmp_path):
    monkeypatch.setattr(dte, "__file__", str(tmp_path / "dte.py"))
    db = DB(":memory:")
    venta = create_sale(db)
    codigo = "CGTEST3"
    data = {"identificacion": {"tipoDte": "01", "codigoGeneracion": codigo}}
    base_dest = dte._dte_base_dir(data)
    versioned_dte.ensure_version(data, base_dir=base_dest)
    db.update_venta_extra(venta, {"codigoGeneracion": codigo})
    with pytest.raises(ValueError):
        transmitir_dte(db, venta)
