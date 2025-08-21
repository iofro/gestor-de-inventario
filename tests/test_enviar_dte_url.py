import json
from urllib.parse import urlparse
import dte
import auth
from tests.conftest import make_jws


def test_enviar_dte_a_hacienda_uses_default_url_and_jws(monkeypatch, tmp_path):
    datos = {"dte_api": {"url": "", "ambiente": "pruebas"}}
    datos_path = tmp_path / "datos_negocio.json"
    datos_path.write_text(json.dumps(datos))
    monkeypatch.setattr(dte, "DATOS_NEGOCIO_PATH", str(datos_path))

    captured = {}

    def fake_post(url, token, jws_token, meta):
        captured["url"] = url
        captured["body"] = jws_token
        return {"estado": "Transmitido"}

    monkeypatch.setattr(dte, "_post_dte", fake_post)
    monkeypatch.setattr(auth, "get_token", lambda: "Bearer TOKEN")

    meta = {"ambiente": "00", "version": 1, "tipoDte": "01", "codigoGeneracion": "X"}
    token = make_jws({"identificacion": meta})
    dte.enviar_dte_a_hacienda(token)

    assert captured["url"] == dte.DEFAULT_RECEPCION_URL
    pu = urlparse(captured["url"])
    assert pu.netloc == "apitest.dtes.mh.gob.sv"
    assert pu.path.rstrip("/") == "/fesv/recepciondte"
    assert captured["body"].count(".") >= 2
