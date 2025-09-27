from types import SimpleNamespace

import pytest

import auth
import dte

def test_get_token_returns_manual(monkeypatch):
    monkeypatch.setattr(auth, "get_manual_token", lambda: "Bearer TOKEN")
    monkeypatch.setattr("mh_auth.get_manual_token", lambda: "Bearer TOKEN")
    assert auth.get_token() == "Bearer TOKEN"


def test_get_token_missing_raises(monkeypatch):
    monkeypatch.setattr(auth, "get_manual_token", lambda: None)
    monkeypatch.setattr("mh_auth.get_manual_token", lambda: None)
    with pytest.raises(RuntimeError):
        auth.get_token()


def test_post_dte_uses_manual_token(monkeypatch):
    captured = {}

    def fake_post(url, headers, json=None, timeout=None):
        captured["headers"] = headers
        return SimpleNamespace(status_code=200, json=lambda: {"estado": "Recibido"}, text="OK")

    monkeypatch.setattr("dte.requests.post", fake_post)
    monkeypatch.setattr(auth, "get_manual_token", lambda: "Bearer TOKEN")
    monkeypatch.setattr("mh_auth.get_manual_token", lambda: "Bearer TOKEN")
    meta = {"ambiente": "00", "version": 1, "tipoDte": "01", "codigoGeneracion": "A" * 36}
    response = dte._post_dte(dte.DEFAULT_RECEPCION_URL, "payload", meta)
    assert response["estado"] == "Recibido"
    assert captured["headers"]["Authorization"] == "Bearer TOKEN"


def test_post_dte_401_returns_manual_message(monkeypatch):
    def fake_post(url, headers, json=None, timeout=None):
        return SimpleNamespace(status_code=401, json=lambda: {"detalle": "Unauthorized"}, text="Unauthorized")

    monkeypatch.setattr("dte.requests.post", fake_post)
    monkeypatch.setattr(auth, "get_manual_token", lambda: "Bearer TOKEN")
    monkeypatch.setattr("mh_auth.get_manual_token", lambda: "Bearer TOKEN")
    meta = {"ambiente": "00", "version": 1, "tipoDte": "01", "codigoGeneracion": "A" * 36}
    result = dte._post_dte(dte.DEFAULT_RECEPCION_URL, "payload", meta)
    assert result["estado"] == "Rechazado"
    assert result["http_status"] == 401
    assert "Token inválido" in result["detalle"]
