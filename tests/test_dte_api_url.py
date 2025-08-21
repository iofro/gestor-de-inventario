import json
import pytest

import dte
from tests.conftest import make_jws


class DummyResp:
    status_code = 200
    text = ""

    def json(self):
        return {}

    def raise_for_status(self):
        pass


def _ok_post(*args, **kwargs):
    return DummyResp()


def _make_meta():
    return {
        "ambiente": "00",
        "version": 1,
        "tipoDte": "01",
        "codigoGeneracion": "X",
    }


def _make_token():
    return make_jws({"identificacion": _make_meta()})


def test_host_desnudo_pruebas(monkeypatch, tmp_path):
    datos = {"dte_api": {"url": "https://apitest.dtes.mh.gob.sv"}}
    datos_path = tmp_path / "datos.json"
    datos_path.write_text(json.dumps(datos))
    monkeypatch.setattr(dte, "DATOS_NEGOCIO_PATH", str(datos_path))
    monkeypatch.setattr(dte.requests, "post", _ok_post)
    cfg = dte._load_dte_api_config()
    assert cfg["url"] == "https://apitest.dtes.mh.gob.sv/fesv/recepciondte"
    _ = dte._post_dte(cfg["url"], "Bearer T", _make_token(), _make_meta())


def test_host_desnudo_produccion(monkeypatch, tmp_path):
    datos = {"dte_api": {"url": "https://api.dtes.mh.gob.sv"}}
    datos_path = tmp_path / "datos.json"
    datos_path.write_text(json.dumps(datos))
    monkeypatch.setattr(dte, "DATOS_NEGOCIO_PATH", str(datos_path))
    monkeypatch.setattr(dte.requests, "post", _ok_post)
    cfg = dte._load_dte_api_config()
    assert cfg["url"] == "https://api.dtes.mh.gob.sv/fesv/recepciondte"
    _ = dte._post_dte(cfg["url"], "Bearer T", _make_token(), _make_meta())


def test_path_presente_trailing_slash(monkeypatch, tmp_path):
    datos = {
        "dte_api": {"url": "https://apitest.dtes.mh.gob.sv/fesv/recepciondte/"}
    }
    datos_path = tmp_path / "datos.json"
    datos_path.write_text(json.dumps(datos))
    monkeypatch.setattr(dte, "DATOS_NEGOCIO_PATH", str(datos_path))
    monkeypatch.setattr(dte.requests, "post", _ok_post)
    cfg = dte._load_dte_api_config()
    assert cfg["url"].rstrip("/") == "https://apitest.dtes.mh.gob.sv/fesv/recepciondte"
    assert cfg["url"].split("://", 1)[1].count("//") == 0
    _ = dte._post_dte(cfg["url"], "Bearer T", _make_token(), _make_meta())


def test_datos_negocio_tiene_prioridad(monkeypatch, tmp_path):
    datos = {"dte_api": {"url": "https://apitest.dtes.mh.gob.sv"}}
    datos_path = tmp_path / "datos.json"
    datos_path.write_text(json.dumps(datos))
    monkeypatch.setattr(dte, "DATOS_NEGOCIO_PATH", str(datos_path))
    cfg_path = tmp_path / "config.json"
    cfg = {
        "ambiente": "pruebas",
        "pruebas": {"recepcion_url": "https://api.dtes.mh.gob.sv"},
    }
    cfg_path.write_text(json.dumps(cfg))
    monkeypatch.setattr(dte, "CONFIG_NEGOCIO_PATH", str(cfg_path))
    monkeypatch.setattr(dte.requests, "post", _ok_post)
    cfg = dte._load_dte_api_config()
    assert cfg["url"].startswith("https://apitest.dtes.mh.gob.sv")


def test_fallback_default(monkeypatch, tmp_path):
    datos_path = tmp_path / "datos.json"
    datos_path.write_text("{}")
    monkeypatch.setattr(dte, "DATOS_NEGOCIO_PATH", str(datos_path))
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({"ambiente": "pruebas", "pruebas": {}}))
    monkeypatch.setattr(dte, "CONFIG_NEGOCIO_PATH", str(cfg_path))
    cfg = dte._load_dte_api_config()
    assert cfg["url"] == dte.DEFAULT_RECEPCION_URL


def test_normalize_adds_scheme():
    assert (
        dte._normalize_recepcion_url("api.dtes.mh.gob.sv")
        == "https://api.dtes.mh.gob.sv/fesv/recepciondte"
    )


def test_post_dte_sets_required_headers(monkeypatch):
    captured = {}

    def fake_post(url, data=None, headers=None, timeout=20):
        captured["headers"] = headers
        return DummyResp()

    monkeypatch.setattr(dte.requests, "post", fake_post)
    _ = dte._post_dte(dte.DEFAULT_RECEPCION_URL, "Bearer T", _make_token(), _make_meta())
    assert captured["headers"]["Content-Type"] == "application/jose"
    assert captured["headers"]["Accept"] == "application/json"


def test_normalize_rejects_sandbox():
    with pytest.raises(ValueError):
        dte._normalize_recepcion_url("https://sandbox.dtes.mh.gob.sv")


def test_logging_final_url(monkeypatch, tmp_path, caplog):
    datos = {"dte_api": {"url": "https://apitest.dtes.mh.gob.sv"}}
    datos_path = tmp_path / "datos.json"
    datos_path.write_text(json.dumps(datos))
    monkeypatch.setattr(dte, "DATOS_NEGOCIO_PATH", str(datos_path))
    caplog.set_level("INFO")
    dte._load_dte_api_config()
    assert any("Recepción configurada" in r.message for r in caplog.records)
