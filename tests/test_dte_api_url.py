import json
import logging
from urllib.parse import urlparse
import dte
from tests.conftest import make_jws


def test_load_dte_api_config_normalizes_endpoint(tmp_path, monkeypatch, caplog):
    datos_path = tmp_path / "datos_negocio.json"
    datos_path.write_text(json.dumps({"dte_api": {"endpoint": "https://apitest.dtes.mh.gob.sv"}}))
    monkeypatch.setattr(dte, "DATOS_NEGOCIO_PATH", str(datos_path))
    with caplog.at_level(logging.INFO):
        cfg = dte._load_dte_api_config()
    assert cfg["url"] == dte.DEFAULT_RECEPCION_URL
    assert any(
        f"Recepción configurada → {dte.DEFAULT_RECEPCION_URL}" in m for m in caplog.messages
    )
    pu = urlparse(cfg["url"])
    assert pu.path.rstrip("/") == "/fesv/recepciondte"


def test_load_dte_api_config_prefers_recepcion_url(tmp_path, monkeypatch):
    datos_path = tmp_path / "datos_negocio.json"
    datos_path.write_text(
        json.dumps(
            {
                "dte_api": {
                    "recepcion_url": dte.DEFAULT_RECEPCION_URL,
                    "endpoint": "https://example.com",
                }
            }
        )
    )
    monkeypatch.setattr(dte, "DATOS_NEGOCIO_PATH", str(datos_path))
    cfg = dte._load_dte_api_config()
    assert cfg["url"] == dte.DEFAULT_RECEPCION_URL


def test_load_dte_api_config_normalizes_prod_url(tmp_path, monkeypatch):
    datos_path = tmp_path / "datos_negocio.json"
    datos_path.write_text(
        json.dumps({"dte_api": {"recepcion_url": "https://api.dtes.mh.gob.sv"}})
    )
    monkeypatch.setattr(dte, "DATOS_NEGOCIO_PATH", str(datos_path))
    cfg = dte._load_dte_api_config()
    assert cfg["url"] == "https://api.dtes.mh.gob.sv/fesv/recepciondte"
    meta = {"ambiente": "00", "version": 1, "tipoDte": "01", "codigoGeneracion": "XYZ"}
    token = make_jws({"identificacion": meta})
    called = {}

    def fake_post(url, data=None, headers=None, timeout=20):
        called["url"] = url
        class R:
            status_code = 200
            def json(self):
                return {}
            def raise_for_status(self):
                pass
        return R()

    monkeypatch.setattr("dte.requests.post", fake_post)
    dte._post_dte(cfg["url"], "Bearer T", token, meta)
    assert called["url"] == cfg["url"]

