from db import DB
from dte import transmitir_dte, _post_dte
import dte
import json
import os
from datetime import datetime
from pathlib import Path
import pytest
import auth
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
    monkeypatch.setattr(dte, "generar_dte_json", lambda *a, **k: {"resumen": {"totalLetras": "X"}})
    monkeypatch.setattr(dte, "apply_schema_patch", lambda d: d)
    monkeypatch.setattr(dte.catalogos, "get_dte_schema", lambda t: {})
    monkeypatch.setattr(dte, "_load_dte_api_config", lambda: {"url": "http://example"})
    monkeypatch.setattr(dte, "_save_signed_dte", lambda *a, **k: None)
    monkeypatch.setattr(auth, "get_token", lambda: "T")
    monkeypatch.setattr(auth, "get_last_auth_host", lambda: None)
    monkeypatch.setattr("utils.jws.sign_json", lambda d: make_jws(d))
    res = transmitir_dte(db, venta, modo="contingencia")
    assert res["estado"] == "Pendiente"
    row = db.cursor.execute(
        "SELECT estado FROM dte_envios WHERE venta_id=?", (venta,)
    ).fetchone()
    assert row["estado"] == "Pendiente"


def test_transmitir_dte_default_contingencia(monkeypatch):
    db = DB(":memory:")
    venta = create_sale(db)

    monkeypatch.setattr(dte, "get_default_modo_transmision", lambda: "contingencia")
    monkeypatch.setattr(dte, "generar_dte_json", lambda *a, **k: {"resumen": {"totalLetras": "X"}})
    monkeypatch.setattr(dte, "apply_schema_patch", lambda d: d)
    monkeypatch.setattr(dte.catalogos, "get_dte_schema", lambda t: {})
    monkeypatch.setattr(dte, "_load_dte_api_config", lambda: {"url": "http://example"})
    monkeypatch.setattr(dte, "_save_signed_dte", lambda *a, **k: None)
    monkeypatch.setattr(auth, "get_token", lambda: "T")
    monkeypatch.setattr(auth, "get_last_auth_host", lambda: None)
    monkeypatch.setattr(
        "dte.requests.post",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not post")),
    )
    monkeypatch.setattr("utils.jws.sign_json", lambda d: make_jws(d))

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

    sign_calls = {"count": 0, "tokens": []}

    def fake_sign(data):
        sign_calls["count"] += 1
        token = make_jws(data)
        sign_calls["tokens"].append(token)
        return token

    monkeypatch.setattr("utils.jws.sign_json", fake_sign)

    token_calls = {"count": 0}

    def fake_get_token():
        token_calls["count"] += 1
        return "Bearer JWT"

    monkeypatch.setattr(auth, "get_token", fake_get_token)
    monkeypatch.setattr(auth, "get_last_auth_host", lambda: "apitest.dtes.mh.gob.sv")
    monkeypatch.setattr("dte.validate_dte_json", lambda data, db=None: None)
    monkeypatch.setattr(
        "dte.generar_dte_json",
        lambda db_obj, vid: {
            "receptor": {
                "nombre": "Cliente",
                "tipoDocumento": "36",
                "numDocumento": "06149876543210",
                "nrc": None,
                "codActividad": None,
                "descActividad": None,
                "direccion": None,
                "telefono": None,
                "correo": None,
            },
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
            },
        },
    )

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
    assert sign_calls["count"] == 1
    assert len(calls) == 1
    url, headers, body = calls[0]
    assert url == dte.DEFAULT_RECEPCION_URL
    assert headers["Authorization"] == "Bearer JWT"
    assert headers["Content-Type"] == "application/json"
    assert headers["Accept"] == "application/json"
    assert headers["User-Agent"] == "Vertex-DTE/1.0"
    assert body["documento"] in sign_calls["tokens"]
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


def test_save_signed_dte_moves_and_cleans(monkeypatch, tmp_path):
    codigo = "ABC"
    data = {"identificacion": {"tipoDte": "01", "codigoGeneracion": codigo}}
    monkeypatch.setattr(dte, "__file__", str(tmp_path / "dte.py"))
    pending_base = tmp_path / "dtes_pendientes" / "fcf"
    version_dir, _ = dte.versioned_dte.ensure_version(data, base_dir=str(pending_base))
    json_path = os.path.join(version_dir, "documento.json")
    dest_old = tmp_path / "dtes" / "fcf" / codigo / "old"
    os.makedirs(dest_old, exist_ok=True)
    with open(dest_old / "documento.json", "w") as fh:
        fh.write("{}")
    with open(dest_old / "metadata.json", "w") as fh:
        fh.write("{}")
    monkeypatch.setattr(dte, "construir_sobre_recepcion", lambda *a, **k: {"estado": "OK"})
    dte._save_signed_dte(data, "TOKEN", json_path=json_path)
    dest_codigo_dir = tmp_path / "dtes" / "fcf" / codigo
    dirs = [p.name for p in dest_codigo_dir.iterdir() if p.is_dir()]
    assert dirs == [os.path.basename(version_dir)]
    assert not dest_old.exists()
    assert not Path(version_dir).exists()


def test_transmitir_dte_reuses_pending_json(monkeypatch, tmp_path):
    db = DB(":memory:")
    venta = create_sale(db)
    codigo = "XYZ"
    data = {
        "identificacion": {"tipoDte": "01", "codigoGeneracion": codigo},
        "resumen": {"totalLetras": "X"},
    }
    monkeypatch.setattr(dte, "__file__", str(tmp_path / "dte.py"))
    pending_base = tmp_path / "dtes_pendientes" / "fcf"
    version_dir, _ = dte.versioned_dte.ensure_version(data, base_dir=str(pending_base))
    json_path = os.path.join(version_dir, "documento.json")
    db.update_venta_extra(venta, {"codigoGeneracion": codigo, "dteJsonPath": json_path})
    called = {}

    def fake_enviar(db_, vid, data_, modo_, jws_token=None, json_path=None):
        called["json_path"] = json_path
        return {"estado": "Transmitido"}

    monkeypatch.setattr(dte, "_enviar_documento", fake_enviar)
    monkeypatch.setattr(dte, "apply_schema_patch", lambda d: d)
    monkeypatch.setattr(dte.catalogos, "get_dte_schema", lambda t: {})
    res = transmitir_dte(db, venta)
    assert called["json_path"] == json_path
    assert res["estado"] == "Transmitido"


def test_transmitir_dte_blocks_if_already_in_dtes(monkeypatch, tmp_path):
    db = DB(":memory:")
    venta = create_sale(db)
    codigo = "AAA"
    data = {"resumen": {"totalLetras": "X"}}
    monkeypatch.setattr(dte, "__file__", str(tmp_path / "dte.py"))
    dest_dir = tmp_path / "dtes" / "fcf" / codigo / "v1"
    os.makedirs(dest_dir, exist_ok=True)
    json_path = dest_dir / "documento.json"
    with open(json_path, "w") as fh:
        json.dump(data, fh)
    db.update_venta_extra(venta, {"codigoGeneracion": codigo, "dteJsonPath": str(json_path)})
    with pytest.raises(ValueError):
        transmitir_dte(db, venta)
