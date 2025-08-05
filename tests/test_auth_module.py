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
        return f"tok{calls['n']}", 120, time.time()

    monkeypatch.setattr(auth, "_request_new_token", fake_request)
    t1 = auth.get_token(refresh=True)
    assert t1 == "tok1"
    t2 = auth.get_token()
    assert t2 == "tok1"
    assert calls["n"] == 1
    t3 = auth.get_token(refresh=True)
    assert t3 == "tok2"
    assert calls["n"] == 2


def test_get_token_expired(monkeypatch, tmp_path):
    setup_paths(monkeypatch, tmp_path)

    def fake_request(nit, pwd):
        return "tok", 1, time.time() - 100

    monkeypatch.setattr(auth, "_request_new_token", fake_request)
    auth.get_token(refresh=True)
    calls = {"n": 0}

    def fake_request2(nit, pwd):
        calls["n"] += 1
        return "new", 1, time.time()

    monkeypatch.setattr(auth, "_request_new_token", fake_request2)
    token2 = auth.get_token()
    assert token2 == "new"
    assert calls["n"] == 1


def test_request_error(monkeypatch, tmp_path):
    setup_paths(monkeypatch, tmp_path)

    def fake_post(url, data, headers, timeout):
        raise requests.HTTPError("boom")

    monkeypatch.setattr(auth.requests, "post", fake_post)
    with pytest.raises(requests.HTTPError):
        auth.get_token(refresh=True)
