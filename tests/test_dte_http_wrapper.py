import base64
import json
import logging
from datetime import timedelta
from typing import Any
from types import SimpleNamespace
from unittest import mock

import pytest
import requests

from dte import _post_json


@pytest.fixture(autouse=True)
def _clear_http_env(monkeypatch):
    for name in [
        "DTE_RATE_LIMIT_MS",
        "DTE_BACKOFF_MS",
        "DTE_RETRY_401_EMPTY",
        "DTE_DEBUG_NO_REDIRECTS",
        "DTE_DEBUG_DUMP_REQ_BODY",
    ]:
        monkeypatch.delenv(name, raising=False)


def _base_headers(token: str = "Bearer token"):
    return {
        "Authorization": token,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "pytest",
        "app-version": "test",
    }


class _SimpleRequestsMock:
    def __init__(self, monkeypatch):
        self._registry: dict[str, list[dict]] = {}
        self.request_history: list[SimpleNamespace] = []
        monkeypatch.setattr(requests, "post", self._dispatch)

    def post(self, url: str, *args, **kwargs):
        if args:
            specs = args[0]
            if not isinstance(specs, list):
                raise TypeError("Expected list of response specs")
            self._registry.setdefault(url, []).extend(dict(item) for item in specs)
        else:
            self._registry.setdefault(url, []).append(dict(kwargs))

    def _dispatch(self, url: str, **kwargs):
        queue = self._registry.get(url) or []
        if not queue:
            raise AssertionError(f"No mock registered for POST {url}")
        spec = queue.pop(0)
        status_code = spec.pop("status_code", 200)
        headers_spec = dict(spec.pop("headers", {}) or {})
        body_json = spec.pop("json", None)
        body_text = spec.pop("text", None)

        response = requests.Response()
        response.status_code = status_code
        response.headers = headers_spec
        response.url = url

        if body_json is not None:
            response._content = json.dumps(body_json).encode("utf-8")
            response.encoding = "utf-8"
            response.headers.setdefault("Content-Type", "application/json")
        elif body_text is not None:
            response._content = body_text.encode("utf-8")
            response.encoding = "utf-8"
        else:
            response._content = b""

        req_headers = dict(kwargs.get("headers") or {})
        request = requests.Request(
            "POST",
            url,
            headers=req_headers,
            json=kwargs.get("json"),
        ).prepare()
        if req_headers:
            request.headers.update(req_headers)
        response.request = request

        record = SimpleNamespace(
            method="POST",
            url=url,
            headers=dict(request.headers),
            json=kwargs.get("json"),
            body=request.body,
        )
        self.request_history.append(record)
        return response


@pytest.fixture
def requests_mock(monkeypatch):
    return _SimpleRequestsMock(monkeypatch)


def _build_bearer(payload: dict) -> str:
    header = base64.urlsafe_b64encode(json.dumps({"alg": "none"}).encode("utf-8")).rstrip(b"=")
    body = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).rstrip(b"=")
    return f"Bearer {header.decode()}" + "." + body.decode() + "."


def test_post_json_success_parses_response(requests_mock, caplog):
    url = "https://apitest.dtes.mh.gob.sv/fesv/recepciondte"
    headers = _base_headers()
    body = {"ambiente": "00"}
    requests_mock.post(
        url,
        json={"estado": "OK"},
        headers={"Date": "Wed, 01 Jan 2020 00:00:01 GMT"},
    )

    caplog.set_level(logging.INFO, logger="dte")

    resp, data, text = _post_json(url, headers, body, tag="test_success")

    assert resp.status_code == 200
    assert data == {"estado": "OK"}
    assert json.loads(text) == {"estado": "OK"}
    assert any("HTTP: RESP_SKEW" in rec.message for rec in caplog.records)


def test_post_json_retry_on_empty_401(requests_mock, monkeypatch, caplog):
    url = "https://apitest.dtes.mh.gob.sv/fesv/recepciondte"
    headers = _base_headers()
    body = {"ambiente": "00"}
    monkeypatch.setenv("DTE_BACKOFF_MS", "0")
    caplog.set_level(logging.INFO, logger="dte")
    requests_mock.post(
        url,
        [
            {"status_code": 401, "text": "", "headers": {}},
            {"status_code": 200, "json": {"estado": "RECIBIDO"}},
        ],
    )

    resp, data, _ = _post_json(url, headers, body, tag="test_retry")

    assert resp.status_code == 200
    assert data == {"estado": "RECIBIDO"}
    assert len(requests_mock.request_history) == 2
    second_request = requests_mock.request_history[1]
    assert second_request.headers.get("Connection") == "close"
    retry_msgs = [rec.message for rec in caplog.records if "401 vacío" in rec.message]
    assert len(retry_msgs) >= 2


@pytest.mark.parametrize("host", ["apitest.dtes.mh.gob.sv", "api.dtes.mh.gob.sv"])
def test_post_json_refreshes_token_on_persistent_empty_401(requests_mock, monkeypatch, caplog, host):
    url = f"https://{host}/fesv/recepciondte"
    headers = _base_headers()
    body = {"ambiente": "00"}
    monkeypatch.setenv("DTE_BACKOFF_MS", "0")
    caplog.set_level(logging.INFO, logger="dte")

    ensure_calls: dict[str, Any] = {}

    def fake_ensure(env, current, *, min_ttl_s=300, force):
        ensure_calls.setdefault("count", 0)
        ensure_calls["count"] += 1
        ensure_calls["env"] = env
        ensure_calls["current"] = current
        ensure_calls["min_ttl_s"] = min_ttl_s
        ensure_calls["force"] = force
        return "Bearer REFRESHED"

    monkeypatch.setattr("mh_auth.ensure_valid_bearer", fake_ensure)

    requests_mock.post(
        url,
        [
            {"status_code": 401, "text": "", "headers": {}},
            {"status_code": 401, "text": "", "headers": {}},
            {"status_code": 200, "json": {"estado": "RECIBIDO"}},
        ],
    )

    resp, data, _ = _post_json(url, headers, body, tag="test_retry_refresh")

    assert resp.status_code == 200
    assert data == {"estado": "RECIBIDO"}
    assert len(requests_mock.request_history) == 3
    assert requests_mock.request_history[2].headers.get("Authorization") == "Bearer REFRESHED"
    expected_env = "apitest" if "apitest" in host else "produccion"
    assert ensure_calls["env"] == expected_env
    assert ensure_calls["current"] == "Bearer token"
    assert ensure_calls["force"] is True
    assert ensure_calls["min_ttl_s"] == 300
    assert ensure_calls["count"] == 1
    assert any("AUTH: refreshed token for retry" in rec.message for rec in caplog.records)


def test_post_json_normalizes_authorization(requests_mock, caplog):
    url = "https://apitest.dtes.mh.gob.sv/fesv/recepciondte"
    headers = _base_headers("  Bearer \u200bBearer\tSECRETO\n")
    body = {"ambiente": "00"}
    requests_mock.post(url, json={"ok": True})
    caplog.set_level(logging.INFO, logger="dte")

    _post_json(url, headers, body, tag="test_auth_norm")

    sent_header = requests_mock.request_history[0].headers.get("Authorization")
    assert sent_header == "Bearer SECRETO"
    assert any("AUTH: header corregido" in rec.message for rec in caplog.records)


def test_post_json_respects_no_redirect_flag(monkeypatch):
    url = "https://apitest.dtes.mh.gob.sv/fesv/recepciondte"
    headers = _base_headers()
    body = {"ambiente": "00"}
    monkeypatch.setenv("DTE_DEBUG_NO_REDIRECTS", "1")

    response = requests.Response()
    response.status_code = 200
    response._content = b"{}"
    response.headers = {}
    prepared = requests.Request("POST", url, headers={"Content-Type": "application/json"}).prepare()
    prepared.headers["Content-Type"] = "application/json"
    response.request = prepared
    response.history = []
    response.elapsed = timedelta(milliseconds=10)

    with mock.patch("requests.post", return_value=response) as mock_post:
        result = _post_json(url, headers, body, tag="test_no_redirect")

    assert mock_post.call_args.kwargs.get("allow_redirects") is False
    resp, data, text = result
    assert resp is response
    assert data == {}
    assert text == "{}"


def test_post_json_does_not_retry_on_403(requests_mock):
    url = "https://apitest.dtes.mh.gob.sv/fesv/recepciondte"
    headers = _base_headers()
    body = {"ambiente": "00"}
    requests_mock.post(url, status_code=403, json={"error": "forbidden"})

    resp, data, text = _post_json(url, headers, body, tag="test_forbidden")

    assert resp.status_code == 403
    assert data == {"error": "forbidden"}
    assert json.loads(text) == {"error": "forbidden"}
    assert len(requests_mock.request_history) == 1


def test_post_json_warns_on_missing_authorization(requests_mock, caplog):
    url = "https://apitest.dtes.mh.gob.sv/fesv/recepciondte"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "pytest",
        "app-version": "test",
    }
    body = {"ambiente": "00"}
    requests_mock.post(url, json={"ok": True})
    caplog.set_level(logging.INFO, logger="dte")

    _post_json(url, headers, body, tag="test_missing_auth")

    assert any("AUTH: header ausente" in rec.message for rec in caplog.records)


def test_post_json_cliente_id_matches_sub(requests_mock, caplog):
    url = "https://apitest.dtes.mh.gob.sv/fesv/recepciondte"
    token = _build_bearer({"sub": "12345678-9", "iat": 1, "exp": 1000})
    headers = _base_headers(token)
    headers["cliente-id"] = "12345678-9"
    body = {"ambiente": "00"}
    requests_mock.post(url, json={"ok": True})
    caplog.set_level(logging.INFO, logger="dte")

    _post_json(url, headers, body, tag="test_client_match")

    assert any("JWT: cliente-id coincide" in rec.message for rec in caplog.records)


def test_post_json_cliente_id_mismatch_warns(requests_mock, caplog):
    url = "https://apitest.dtes.mh.gob.sv/fesv/recepciondte"
    token = _build_bearer({"sub": "12345678-9", "iat": 1, "exp": 1000})
    headers = _base_headers(token)
    headers["cliente-id"] = "00000000-0"
    body = {"ambiente": "00"}
    requests_mock.post(url, json={"ok": True})
    caplog.set_level(logging.INFO, logger="dte")

    _post_json(url, headers, body, tag="test_client_mismatch")

    assert any("JWT: cliente-id mismatch" in rec.message for rec in caplog.records)


def test_post_json_dump_body_flag(monkeypatch, requests_mock, caplog):
    url = "https://apitest.dtes.mh.gob.sv/fesv/recepciondte"
    headers = _base_headers()
    body = {"ambiente": "00", "foo": "bar"}
    monkeypatch.setenv("DTE_DEBUG_DUMP_REQ_BODY", "1")
    requests_mock.post(url, json={"ok": True})

    caplog.set_level(logging.INFO, logger="dte")

    _post_json(url, headers, body, tag="test_dump")

    messages = [rec.message for rec in caplog.records]
    assert any("HTTP: REQ_BODY" in msg for msg in messages)
    assert any("sha256=" in msg for msg in messages)


def test_post_json_dump_body_flag_disabled(monkeypatch, requests_mock, caplog):
    url = "https://apitest.dtes.mh.gob.sv/fesv/recepciondte"
    headers = _base_headers()
    body = {"ambiente": "00", "foo": "bar"}
    monkeypatch.delenv("DTE_DEBUG_DUMP_REQ_BODY", raising=False)
    requests_mock.post(url, json={"ok": True})

    caplog.set_level(logging.INFO, logger="dte")

    _post_json(url, headers, body, tag="test_dump_off")

    messages = [rec.message for rec in caplog.records]
    assert not any("HTTP: REQ_BODY" in msg for msg in messages)


def test_post_json_retry_on_empty_401_with_blank_auth_header(requests_mock, monkeypatch, caplog):
    url = "https://apitest.dtes.mh.gob.sv/fesv/recepciondte"
    headers = _base_headers()
    body = {"ambiente": "00"}
    monkeypatch.setenv("DTE_BACKOFF_MS", "0")
    caplog.set_level(logging.INFO, logger="dte")
    requests_mock.post(
        url,
        [
            {"status_code": 401, "text": "", "headers": {"WWW-Authenticate": "   "}},
            {"status_code": 200, "json": {"estado": "RECIBIDO"}},
        ],
    )

    resp, data, _ = _post_json(url, headers, body, tag="test_retry_blank_www")

    assert resp.status_code == 200
    assert data == {"estado": "RECIBIDO"}
    assert len(requests_mock.request_history) == 2
    retry_msgs = [rec.message for rec in caplog.records if "401 vacío" in rec.message]
    assert retry_msgs
