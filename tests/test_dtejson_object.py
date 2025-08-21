import os

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

    monkeypatch.setattr(jws.requests, "post", fake_post)

    payload = '{"identificacion":{"version":"1","tipoDte":"01"}}'
    token = jws.sign_json(payload, nit="X", passwordPri="Y")

    assert token == "<JWS>"
    assert isinstance(captured["json"]["dteJson"], dict)
