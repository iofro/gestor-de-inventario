import os
from decimal import Decimal

import utils.jws as jws


def test_sign_json_sends_dtejson_as_object(monkeypatch):
    monkeypatch.setenv("SEND_DTEJSON_AS_OBJECT", "1")
    monkeypatch.setattr(jws, "SEND_DTEJSON_AS_OBJECT", True)
    monkeypatch.setattr(jws, "_ensure_cert_file", lambda nit: None)

    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["json"] = json
        class R:
            status_code = 200
            text = "OK"
            def raise_for_status(self):
                pass
            def json(self):
                return {"status": "OK", "body": "<JWS>"}
        return R()

    def fake_get(url, timeout=None):
        captured["health"] = {"url": url, "timeout": timeout}

        class R:
            status_code = 200
            text = "OK"

            def raise_for_status(self):
                pass

        return R()

    monkeypatch.setattr(jws.requests, "get", fake_get)
    monkeypatch.setattr(jws.requests, "post", fake_post)

    payload = '{"identificacion":{"version":"1","tipoDte":"01"}}'
    token = jws.sign_json(payload, nit="X", passwordPri="Y")

    assert token == "<JWS>"
    assert isinstance(captured["json"]["dteJson"], dict)


def test_sign_json_converts_decimal_values(monkeypatch):
    monkeypatch.setenv("SEND_DTEJSON_AS_OBJECT", "1")
    monkeypatch.setattr(jws, "SEND_DTEJSON_AS_OBJECT", True)
    monkeypatch.setattr(jws, "_ensure_cert_file", lambda nit: None)

    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["json"] = json
        class R:
            status_code = 200
            text = "OK"
            def raise_for_status(self):
                pass
            def json(self):
                return {"status": "OK", "body": "<JWS>"}
        return R()

    def fake_get(url, timeout=None):
        captured["health"] = {"url": url, "timeout": timeout}

        class R:
            status_code = 200
            text = "OK"

            def raise_for_status(self):
                pass

        return R()

    monkeypatch.setattr(jws.requests, "get", fake_get)
    monkeypatch.setattr(jws.requests, "post", fake_post)

    payload = {"identificacion": {"version": "1", "tipoDte": "01"}, "monto": Decimal("1.50")}
    jws.sign_json(payload, nit="X", passwordPri="Y")

    assert isinstance(captured["json"]["dteJson"], dict)
    assert isinstance(captured["json"]["dteJson"]["monto"], float)


def test_sign_json_health_check_allows_missing_endpoint(monkeypatch):
    monkeypatch.setattr(jws, "_ensure_cert_file", lambda nit: None)

    def fake_get(url, timeout=None):

        class R:
            status_code = 404
            text = "Not Found"

            def raise_for_status(self):
                raise AssertionError("raise_for_status should not be called")

        return R()

    def fake_post(url, json=None, timeout=None):

        class R:
            status_code = 200
            text = "OK"

            def raise_for_status(self):
                pass

            def json(self):
                return {"status": "OK", "body": "<JWS>"}

        return R()

    monkeypatch.setattr(jws.requests, "get", fake_get)
    monkeypatch.setattr(jws.requests, "post", fake_post)

    payload = {"identificacion": {"version": "1", "tipoDte": "01"}}

    token = jws.sign_json(payload, nit="X", passwordPri="Y")

    assert token == "<JWS>"
