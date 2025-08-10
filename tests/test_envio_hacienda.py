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


def test_transmision_exitosa(monkeypatch, tmp_path):
    db = DB(":memory:")
    monkeypatch.setattr(
        "dte._load_datos_negocio",
        lambda: {
            "razon_social": "ACME",
            "nit": "0614-123456-102-3",
            "nrc": "123456-7",
            "giro": "Giro",
            "direccion": "Calle 1",
        },
    )
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("P1", "X", vid, None, 0, 0, 0, 1)
    pid = db.cursor.lastrowid
    db.add_cliente("Cliente", "", "0614-987654-321-0", "", "Giro", "", "", "Dir", "", "")
    cid = db.cursor.lastrowid
    venta = db.add_venta("2024-01-01", 10, cliente_id=cid)
    db.add_detalle_venta(venta, pid, 1, 10, vendedor_id=vid)

    monkeypatch.setattr("utils.jws.get_cert_config", lambda: (None, None, None))

    captured = {}

    def fake_sign(data, c, p, k):
        captured["data"] = data
        captured["count"] = captured.get("count", 0) + 1
        return "JWS_SIGNED"

    monkeypatch.setattr("utils.jws.sign_json", fake_sign)

    tokens = {"count": 0}

    def fake_token():
        tokens["count"] += 1
        return "JWT"

    monkeypatch.setattr("auth.get_token", fake_token)
    monkeypatch.setattr("dte.validate_dte_json", lambda d: None)

    auth_url = "http://auth.test"
    recepcion_url = "http://recepcion.test"
    calls = []

    class Resp:
        def __init__(self, data):
            self.data = data
            self.status_code = 200
            self.text = json.dumps(data)

        def json(self):
            return self.data

        def raise_for_status(self):
            pass

    def fake_post(url, *a, **k):
        headers = k.get("headers", {})
        calls.append((url, headers, k.get("json")))
        if url == auth_url:
            return Resp({"access_token": "JWT"})
        if url == recepcion_url:
            return Resp({"estado": "Transmitido", "sello": "ABC123"})
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr("requests.post", fake_post)

    cfg = {"ambiente": "pruebas", "pruebas": {"recepcion_url": recepcion_url}}
    config_path = tmp_path / "cfg.json"
    config_path.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setattr("dte.CONFIG_NEGOCIO_PATH", str(config_path))

    transmitir_dte(db, venta)

    assert captured.get("count") == 1
    payload = captured["data"]
    assert payload["receptor"]["nombre"] == "Cliente"
    assert payload["receptor"]["nit"] == "0614-987654-321-0"
    assert payload["cuerpoDocumento"][0]["cantidad"] == 1

    items_total = sum(
        i["cantidad"] * i.get("precioUnitario", i.get("precioUni", 0))
        for i in payload["cuerpoDocumento"]
    )
    assert payload["resumen"]["sumas"] == pytest.approx(items_total)
    assert payload["resumen"]["iva"] == pytest.approx(0)
    assert payload["resumen"]["totalPagar"] == pytest.approx(items_total)
    assert payload["identificacion"]["tipoDte"] == "01"

    assert tokens["count"] == 1
    recep = [c for c in calls if c[0] == recepcion_url]
    assert recep[0][1]["Authorization"] == "Bearer JWT"

    row = db.cursor.execute(
        "SELECT estado, sello FROM dte_envios WHERE venta_id=?", (venta,)
    ).fetchone()
    assert row["estado"] == "Transmitido"
    assert row["sello"] == "ABC123"


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
