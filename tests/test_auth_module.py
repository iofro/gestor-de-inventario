import json
import time
import os
import pytest
import requests
import auth


def write_config(tmp_path, nit="123", pwd="pwd"):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"nit": nit, "api_pwd": pwd}))
    return cfg


def setup_paths(monkeypatch, tmp_path):
    cfg = write_config(tmp_path)
    monkeypatch.setattr(auth, "CONFIG_PATH", str(cfg))
    monkeypatch.setattr(auth, "DB_PATH", str(tmp_path / "db.sqlite"))


def test_get_credentials_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(auth, "CONFIG_PATH", str(tmp_path / "missing.json"))
    monkeypatch.setattr(auth, "DB_PATH", str(tmp_path / "missing.db"))
    with pytest.raises(RuntimeError):
        auth._get_credentials()


def test_get_token_caching_and_refresh(monkeypatch, tmp_path):
    setup_paths(monkeypatch, tmp_path)
    calls = {"n": 0}

    def fake_request(nit, pwd):
        calls["n"] += 1
        return f"Bearer tok{calls['n']}", 120, "Bearer"

    monkeypatch.setattr(auth, "_request_new_token", fake_request)
    t1 = auth.get_token(refresh=True)
    assert t1 == "Bearer tok1"
    t2 = auth.get_token()
    assert t2 == "Bearer tok1"
    assert calls["n"] == 1
    t3 = auth.get_token(refresh=True)
    assert t3 == "Bearer tok2"
    assert calls["n"] == 2


def test_get_token_expired(monkeypatch, tmp_path):
    setup_paths(monkeypatch, tmp_path)

    def fake_request(nit, pwd):
        return "Bearer tok", 1, "Bearer"

    monkeypatch.setattr(auth, "_request_new_token", fake_request)
    auth.get_token(refresh=True)
    auth._expires_at = time.time() - 1
    calls = {"n": 0}

    def fake_request2(nit, pwd):
        calls["n"] += 1
        return "Bearer new", 1, "Bearer"

    monkeypatch.setattr(auth, "_request_new_token", fake_request2)
    token2 = auth.get_token()
    assert token2 == "Bearer new"
    assert calls["n"] == 1


def test_request_error(monkeypatch, tmp_path):
    setup_paths(monkeypatch, tmp_path)

    def fake_post(url, data, headers, timeout):
        raise requests.HTTPError("boom")

    monkeypatch.setattr(auth.requests, "post", fake_post)
    with pytest.raises(requests.HTTPError):
        auth.get_token(refresh=True)


def test_missing_token_includes_response(monkeypatch):
    def fake_post(url, data, headers, timeout):
        class Resp:
            status_code = 200
            text = '{"status":"OK","body":{"mensaje":"sin token"}}'

            def raise_for_status(self):
                return None

            def json(self):
                return {"status": "OK", "body": {"mensaje": "sin token"}}

        return Resp()

    monkeypatch.setattr(auth.requests, "post", fake_post)
    monkeypatch.setattr(auth, "_get_auth_url", lambda: "http://fake")
    with pytest.raises(ValueError) as excinfo:
        auth._request_new_token("nit", "pwd")
    msg = str(excinfo.value)
    assert "sin token" in msg
    assert "Respuesta de autenticación sin token" in msg


def test_env_specific_credentials(monkeypatch, tmp_path):
    data = {
        "ambiente": "pruebas",
        "pruebas": {
            "firma_electronica": {
                "nit": "env_nit",
                "passwordPri": "env_pwd",
            }
        },
    }
    cfg = tmp_path / "config_env.json"
    cfg.write_text(json.dumps(data))
    monkeypatch.setattr(auth, "CONFIG_PATH", str(cfg))
    monkeypatch.setattr(auth, "DB_PATH", str(tmp_path / "db.sqlite"))
    nit, pwd = auth._read_config_credentials()
    assert nit == "env_nit"
    assert pwd == "env_pwd"


def test_read_config_api_user(monkeypatch, tmp_path):
    data = {"api_user": "user1", "api_pwd": "pass1"}
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps(data))
    monkeypatch.setattr(auth, "CONFIG_PATH", str(cfg))
    monkeypatch.setattr(auth, "DB_PATH", str(tmp_path / "db.sqlite"))
    nit, pwd = auth._read_config_credentials()
    assert nit == "user1"
    assert pwd == "pass1"


def test_get_token_with_explicit_credentials(monkeypatch):
    calls = {"n": 0}

    def fake_request(nit, pwd):
        calls["n"] += 1
        return "tok", 120, "Bearer"

    monkeypatch.setattr(auth, "_request_new_token", fake_request)
    t1 = auth.get_token(refresh=True, nit="u", pwd="p")
    assert t1 == "tok"
    t2 = auth.get_token(nit="u", pwd="p")
    assert t2 == "tok"
    assert calls["n"] == 1
    auth.get_token(nit="u2", pwd="p2")
    assert calls["n"] == 2
