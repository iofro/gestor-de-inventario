import json
import time
import os
import logging
import pytest
import requests
import auth
import sqlite3

LONG_TOKEN = "t" * 400


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

    def fake_request(nit, pwd, url):
        calls["n"] += 1
        return f"{LONG_TOKEN}{calls['n']}", 120, "Bearer"

    monkeypatch.setattr(auth, "_request_new_token", fake_request)
    t1 = auth.get_token(refresh=True)
    assert t1 == f"{LONG_TOKEN}1"
    t2 = auth.get_token()
    assert t2 == f"{LONG_TOKEN}1"
    assert calls["n"] == 1
    t3 = auth.get_token(refresh=True)
    assert t3 == f"{LONG_TOKEN}2"
    assert calls["n"] == 2


def test_get_token_expired(monkeypatch, tmp_path):
    setup_paths(monkeypatch, tmp_path)

    def fake_request(nit, pwd, url):
        return f"{LONG_TOKEN}x", 1, "Bearer"

    monkeypatch.setattr(auth, "_request_new_token", fake_request)
    auth.get_token(refresh=True)
    auth._expires_at = time.time() - 1
    calls = {"n": 0}

    def fake_request2(nit, pwd, url):
        calls["n"] += 1
        return f"{LONG_TOKEN}{calls['n']}", 1, "Bearer"

    monkeypatch.setattr(auth, "_request_new_token", fake_request2)
    token2 = auth.get_token()
    assert token2 == f"{LONG_TOKEN}1"
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

    def fake_request(nit, pwd, url):
        calls["n"] += 1
        return f"{LONG_TOKEN}{calls['n']}", 120, "Bearer"

    monkeypatch.setattr(auth, "_request_new_token", fake_request)
    monkeypatch.setattr(auth, "_get_config_nit_and_url", lambda: (None, None))
    t1 = auth.get_token(refresh=True, nit="u", pwd="p")
    assert t1 == f"{LONG_TOKEN}1"
    t2 = auth.get_token(nit="u", pwd="p")
    assert t2 == f"{LONG_TOKEN}1"
    assert calls["n"] == 1
    auth.get_token(nit="u2", pwd="p2")
    assert calls["n"] == 2


def test_delete_token(monkeypatch, tmp_path):
    setup_paths(monkeypatch, tmp_path)
    calls = {"n": 0}

    def fake_request(nit, pwd, url):
        calls["n"] += 1
        return f"{LONG_TOKEN}{calls['n']}", 120, "Bearer"

    monkeypatch.setattr(auth, "_request_new_token", fake_request)
    auth.get_token(refresh=True)
    auth.delete_token()
    with sqlite3.connect(auth.DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT value FROM tokens WHERE key='access_token'")
        assert cur.fetchone() is None
    t2 = auth.get_token()
    assert t2 == f"{LONG_TOKEN}2"
    assert calls["n"] == 2


def test_reauth_logs_nit_and_url(monkeypatch, tmp_path, caplog):
    data = {
        "ambiente": "pruebas",
        "pruebas": {
            "auth_url": "http://auth.example",
            "auth": {"nitUsuario": "123", "pwd": "pwd"},
        },
    }
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps(data))
    monkeypatch.setattr(auth, "CONFIG_PATH", str(cfg))
    monkeypatch.setattr(auth, "DB_PATH", str(tmp_path / "db.sqlite"))
    caplog.set_level(logging.INFO)

    def fake_request(nit, pwd, url):
        assert nit == "123"
        assert url == "http://auth.example"
        return f"{LONG_TOKEN}1", 120, "Bearer"

    monkeypatch.setattr(auth, "_request_new_token", fake_request)
    token = auth.get_token(refresh=True)
    assert token == f"{LONG_TOKEN}1"
    assert "Reautenticando con NIT 123 y URL http://auth.example" in caplog.text


def test_reauth_mismatch_nit(monkeypatch, tmp_path):
    data = {
        "ambiente": "pruebas",
        "pruebas": {
            "auth_url": "http://auth.example",
            "auth": {"nitUsuario": "123", "pwd": "pwd"},
        },
    }
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps(data))
    monkeypatch.setattr(auth, "CONFIG_PATH", str(cfg))
    monkeypatch.setattr(auth, "DB_PATH", str(tmp_path / "db.sqlite"))

    def fake_request(nit, pwd, url):
        return f"{LONG_TOKEN}1", 120, "Bearer"

    monkeypatch.setattr(auth, "_request_new_token", fake_request)
    with pytest.raises(ValueError):
        auth.get_token(refresh=True, nit="999", pwd="pwd")


def test_records_last_auth_host(monkeypatch, tmp_path):
    data = {"ambiente": "pruebas", "pruebas": {"auth_url": "http://auth.example"}}
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps(data))
    monkeypatch.setattr(auth, "CONFIG_PATH", str(cfg))
    monkeypatch.setattr(auth, "DB_PATH", str(tmp_path / "db.sqlite"))
    monkeypatch.setattr(
        auth, "_request_new_token", lambda nit, pwd, url: (f"{LONG_TOKEN}1", 120, "Bearer")
    )
    auth.get_token(refresh=True, nit="user", pwd="pwd")
    assert auth.get_last_auth_host() == "auth.example"
