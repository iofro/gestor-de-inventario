import json
import pytest
import requests

from dte import transmitir_dte


def test_transmision_exitosa(monkeypatch, venta_factory, dte_metadata_factory, temp_json, db_conn):
    db = db_conn
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
    venta = venta_factory()
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
    monkeypatch.setattr("dte.generar_dte_json", lambda db_obj, vid: dte_metadata_factory())

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
    config_path = temp_json("cfg.json", cfg)
    monkeypatch.setattr("dte.CONFIG_NEGOCIO_PATH", str(config_path))

    transmitir_dte(db, venta)

    assert len(calls) == 1
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
        "SELECT estado, sello FROM dte_envios WHERE venta_id=?", (venta,),
    ).fetchone()
    assert row["estado"] == "Transmitido"
    assert row["sello"] == "ABC123"


@pytest.mark.parametrize("status", [401, 500])
def test_http_error_negativo(monkeypatch, status, venta_factory, temp_json, db_conn):
    """Token 401 and response 500 should mark envio as Rechazado."""
    db = db_conn
    venta = venta_factory()

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
    config_path = temp_json("cfg.json", config)
    monkeypatch.setattr("dte.CONFIG_NEGOCIO_PATH", str(config_path))

    with pytest.raises(requests.HTTPError) as excinfo:
        transmitir_dte(db, venta)
    assert f"error {status}" in str(excinfo.value)
    row = db.cursor.execute(
        "SELECT estado, count(*) c FROM dte_envios WHERE venta_id=?", (venta,),
    ).fetchone()
    assert row["estado"] == "Rechazado"
    assert row["c"] == 1


def test_firma_fallida_negativo(monkeypatch, venta_factory, temp_json, db_conn):
    db = db_conn
    venta = venta_factory()

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
    config_path = temp_json("cfg.json", config)
    monkeypatch.setattr("dte.CONFIG_NEGOCIO_PATH", str(config_path))

    with pytest.raises(RuntimeError):
        transmitir_dte(db, venta)

    row = db.cursor.execute(
        "SELECT count(*) c FROM dte_envios WHERE venta_id=?", (venta,),
    ).fetchone()
    assert row["c"] == 0
    assert "called" not in called
