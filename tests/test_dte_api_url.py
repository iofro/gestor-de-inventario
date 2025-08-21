import json
from urllib.parse import urlparse
import dte


def test_load_datos_negocio_appends_recepcion_path(tmp_path, monkeypatch):
    datos_path = tmp_path / "datos_negocio.json"
    datos_path.write_text(json.dumps({"dte_api": {"url": "https://apitest.dtes.mh.gob.sv"}}))
    monkeypatch.setattr(dte, "DATOS_NEGOCIO_PATH", str(datos_path))
    data = dte._load_datos_negocio()
    pu = urlparse(data["dte_api"]["url"])
    assert pu.path.rstrip("/") == "/fesv/recepciondte"


def test_load_dte_api_config_uses_default(monkeypatch, tmp_path):
    datos_path = tmp_path / "datos_negocio.json"
    datos_path.write_text(json.dumps({"dte_api": {"url": ""}}))
    monkeypatch.setattr(dte, "DATOS_NEGOCIO_PATH", str(datos_path))
    cfg = dte._load_dte_api_config()
    assert cfg["url"] == dte.DEFAULT_RECEPCION_URL
