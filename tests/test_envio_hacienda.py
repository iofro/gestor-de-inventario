import json
import pytest
import requests

from db import DB
from dte import transmitir_dte


def create_sale(db):

    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("P1", "X", vid, None, 0, 0, 0, 1)
    pid = db.cursor.lastrowid
    venta_id = db.add_venta("2024-01-01", 10)
    db.add_detalle_venta(venta_id, pid, 1, 10, vendedor_id=vid)
    return venta_id


@pytest.mark.parametrize("status", [401, 500])
def test_http_error_negativo(monkeypatch, tmp_path, status):
    """Token 401 and response 500 should mark envio as Rechazado."""
    db = DB(":memory:")
    venta = create_sale(db)

    monkeypatch.setattr("utils.jws.get_cert_config", lambda: (None, None, None))
    monkeypatch.setattr("utils.jws.sign_json", lambda d, c, p, k: "SIGNED")
    monkeypatch.setattr("auth.get_token", lambda: "JWT")
    monkeypatch.setattr("dte.validate_dte_json", lambda d: None)

    class Resp:
        status_code = status
        text = f"error {status}"

        def json(self):
            return {"estado": "Rechazado", "descripcionMsg": self.text}

        def raise_for_status(self):
            raise requests.HTTPError(self.text)

    monkeypatch.setattr("dte.requests.post", lambda *a, **k: Resp())

    config = {"ambiente": "pruebas", "recepcion_url": {"pruebas": "http://example.com"}}
    with open("config_negocio.json", "w", encoding="utf-8") as fh:
        json.dump(config, fh)

    with pytest.raises(requests.HTTPError) as excinfo:
        transmitir_dte(db, venta)
    assert f"error {status}" in str(excinfo.value)
    row = db.cursor.execute(
        "SELECT estado, count(*) c FROM dte_envios WHERE venta_id=?", (venta,)
    ).fetchone()
    assert row["estado"] == "Rechazado"
    assert row["c"] == 1


def test_firma_fallida_negativo(monkeypatch, tmp_path):
    db = DB(":memory:")
    venta = create_sale(db)

    monkeypatch.setattr("utils.jws.get_cert_config", lambda: (None, None, None))
    monkeypatch.setattr("auth.get_token", lambda: "JWT")
    monkeypatch.setattr("dte.validate_dte_json", lambda d: None)

    def fail(*a, **k):
        raise RuntimeError("firma")

    monkeypatch.setattr("utils.jws.sign_json", fail)

    called = {}

    def fake_post(*a, **k):
        called["called"] = True
        raise AssertionError("should not post")

    monkeypatch.setattr("dte.requests.post", fake_post)

    config = {"ambiente": "pruebas", "recepcion_url": {"pruebas": "http://example.com"}}
    with open("config_negocio.json", "w", encoding="utf-8") as fh:
        json.dump(config, fh)

    with pytest.raises(RuntimeError):
        transmitir_dte(db, venta)

    row = db.cursor.execute(
        "SELECT count(*) c FROM dte_envios WHERE venta_id=?", (venta,)
    ).fetchone()
    assert row["c"] == 0
    assert "called" not in called

def test_transmision_token_401_en_recepcion(monkeypatch, tmp_path):
    db = DB(":memory:")
    venta = create_sale(db)

    monkeypatch.setattr("utils.jws.get_cert_config", lambda: (None, None, None))
    monkeypatch.setattr("utils.jws.sign_json", lambda d, c, p, k: "SIGNED")
    monkeypatch.setattr("dte.validate_dte_json", lambda d: None)

    token_calls = []

    def fake_get_token(refresh: bool = False):
        token_calls.append(refresh)
        return "JWT_VALIDO"

    monkeypatch.setattr("auth.get_token", fake_get_token)

    calls = {"auth": 0, "recepcion": 0}

    class RespAuth:
        status_code = 200

        def json(self):
            return {"access_token": "JWT_VALIDO"}

        def raise_for_status(self):
            pass

    class Resp401:
        status_code = 401
        text = "TOKEN_INVALIDO"

        def json(self):
            return {"estado": "Rechazado", "descripcionMsg": self.text}

        def raise_for_status(self):
            raise requests.HTTPError(self.text)

    def fake_post(url, *a, **k):
        if "auth" in url:
            calls["auth"] += 1
            return RespAuth()
        calls["recepcion"] += 1
        return Resp401()

    monkeypatch.setattr("dte.requests.post", fake_post)
    monkeypatch.setattr("auth.requests.post", fake_post)

    config = {
        "ambiente": "pruebas",
        "pruebas": {
            "auth_url": "http://auth.example",
            "recepcion_url": "http://recepcion.example",
        },
    }
    with open("config_negocio.json", "w", encoding="utf-8") as fh:
        json.dump(config, fh)

    with pytest.raises(requests.HTTPError) as excinfo:
        transmitir_dte(db, venta)

    assert "TOKEN_INVALIDO" in str(excinfo.value) or "401" in str(excinfo.value)
    assert calls["recepcion"] <= 2
    assert len(token_calls) <= 2

    row = db.cursor.execute(
        "SELECT estado, count(*) c FROM dte_envios WHERE venta_id=?", (venta,),
    ).fetchone()
    assert row["estado"] == "Rechazado"
    assert row["c"] == 1
