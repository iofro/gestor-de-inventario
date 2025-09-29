import base64
import json
import time

import mh_auth


class _DummyResponse:
    def __init__(self, payload: dict | None = None, *, status_code: int = 200):
        self._payload = payload or {}
        self.status_code = status_code
        self.headers: dict[str, str] = {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("HTTP error")

    def json(self):
        return self._payload


def _make_token(sub: str, ttl: int = 3600) -> str:
    header = base64.urlsafe_b64encode(json.dumps({"alg": "none"}).encode("utf-8")).rstrip(b"=")
    now = int(time.time())
    payload = {"sub": sub, "iat": now, "exp": now + ttl}
    body = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).rstrip(b"=")
    return f"Bearer {header.decode()}" + "." + body.decode() + "."


def test_get_manual_token_per_environment(tmp_path, monkeypatch):
    datos_path = tmp_path / "datos_negocio.json"
    datos_path.write_text(
        json.dumps(
            {
                "dte_api": {
                    "token_pruebas": "AAA",
                    "token_produccion": "bbb",
                }
            }
        )
    )
    monkeypatch.setattr(mh_auth, "DATOS_NEGOCIO_PATH", str(datos_path))
    mh_auth.invalidate_token_cache()

    assert mh_auth.get_manual_token("pruebas") == "AAA"
    assert mh_auth.get_manual_token("produccion") == "bbb"
    assert mh_auth.get_manual_token("apitest") == "AAA"


def test_get_manual_token_uses_cache(tmp_path, monkeypatch):
    datos_path = tmp_path / "datos_negocio.json"
    datos_path.write_text(json.dumps({"dte_api": {"token_pruebas": "AAA"}}))
    monkeypatch.setattr(mh_auth, "DATOS_NEGOCIO_PATH", str(datos_path))
    calls = []

    def fake_loader():
        calls.append(1)
        return {"apitest": "AAA"}

    monkeypatch.setattr(mh_auth, "_load_tokens_from_file", fake_loader)
    mh_auth.invalidate_token_cache()

    mh_auth.get_manual_token("pruebas")
    mh_auth.get_manual_token("pruebas")
    assert len(calls) == 1


def test_auth_headers_uses_environment_token(tmp_path, monkeypatch):
    datos_path = tmp_path / "datos_negocio.json"
    prod_token = _make_token("PROD")
    test_token = _make_token("TEST")
    datos_path.write_text(
        json.dumps(
            {
                "dte_api": {
                    "token_pruebas": test_token,
                    "token_produccion": prod_token,
                }
            }
        )
    )
    monkeypatch.setattr(mh_auth, "DATOS_NEGOCIO_PATH", str(datos_path))
    monkeypatch.setenv("DTE_AUTH_WARMUP", "0")
    mh_auth.invalidate_token_cache()

    headers_prod = mh_auth.auth_headers(ambiente="produccion")
    assert headers_prod["Authorization"] == prod_token

    headers_test = mh_auth.auth_headers({"X": "1"}, ambiente="pruebas")
    assert headers_test["Authorization"] == test_token
    assert headers_test["X"] == "1"


def test_acquire_token_uses_form_and_user_agent(monkeypatch):
    captured: dict[str, object] = {}

    def fake_resolver(env):
        return "https://api.dtes.mh.gob.sv/seguridad/auth", "user", "pwd"

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return _DummyResponse({"token": "TOKEN"})

    monkeypatch.setattr(mh_auth, "_resolve_auth_params", fake_resolver)
    monkeypatch.setattr(mh_auth, "_default_user_agent", lambda: "Vertex-DTE/1.0")
    monkeypatch.setattr(mh_auth.requests, "post", fake_post)

    token = mh_auth.acquire_token("apitest")

    assert token == "Bearer TOKEN"
    assert captured["url"] == "https://api.dtes.mh.gob.sv/seguridad/auth"
    kwargs = captured["kwargs"]
    assert kwargs.get("timeout") == 20
    assert kwargs.get("json") is None
    assert kwargs.get("data") == {"user": "user", "pwd": "pwd"}
    headers = kwargs.get("headers")
    assert headers == {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "User-Agent": "Vertex-DTE/1.0",
    }
