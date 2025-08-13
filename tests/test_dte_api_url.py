import json
import dte


def test_load_datos_negocio_appends_recepcion_path(tmp_path, monkeypatch):
    datos_path = tmp_path / "datos_negocio.json"
    datos_path.write_text(json.dumps({"dte_api": {"url": "https://apitest.dtes.mh.gob.sv"}}))
    monkeypatch.setattr(dte, "DATOS_NEGOCIO_PATH", str(datos_path))
    data = dte._load_datos_negocio()
    assert data["dte_api"]["url"].endswith("/fesv/recepciondte")
