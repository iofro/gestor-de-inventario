import json
import auth
import dte


def test_auth_url_is_stripped(monkeypatch, tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "ambiente": "pruebas",
        "pruebas": {"auth_url": " http://auth.example \n"}
    }))
    monkeypatch.setattr(auth, "CONFIG_PATH", str(cfg))
    called = {}

    def fake_post(url, data, headers, timeout):
        called["url"] = url
        class Resp:
            status_code = 200
            def json(self):
                return {"status": "OK", "body": {"token": "t", "tokenType": "Bearer", "expiresIn": 1}}
            def raise_for_status(self):
                pass
        return Resp()

    monkeypatch.setattr(auth.requests, "post", fake_post)
    auth._request_new_token("user", "pwd")
    assert called["url"] == "http://auth.example"
    assert called["url"].strip() == called["url"]


def test_recepcion_url_is_stripped(monkeypatch, tmp_path):
    cfg = tmp_path / "config_negocio.json"
    cfg.write_text(json.dumps({
        "ambiente": "pruebas",
        "pruebas": {"recepcion_url": " http://recepcion.example/path \n"}
    }))
    monkeypatch.setattr(dte, "CONFIG_NEGOCIO_PATH", str(cfg))
    monkeypatch.setattr(dte.jws, "sign_json", lambda data: "SIGNED")
    monkeypatch.setattr(dte.auth, "get_token", lambda: "JWT")
    called = {}

    def fake_post_dte(url, token, jws_token):
        called["url"] = url
        return {"estado": "Transmitido"}

    monkeypatch.setattr(dte, "_post_dte", fake_post_dte)

    class DummyDB:
        def registrar_envio_dte(self, *args, **kwargs):
            pass

    dte._enviar_documento(DummyDB(), 1, {}, "normal")
    assert called["url"] == "http://recepcion.example/path"
    assert called["url"].strip() == called["url"]
