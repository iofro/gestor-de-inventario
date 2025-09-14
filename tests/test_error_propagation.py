import dte
import auth
from dte import _post_dte, enviar_dte_a_hacienda
from db import DB
from tests.conftest import make_jws


def test_post_dte_populates_error_fields(monkeypatch):
    meta = {"ambiente": "00", "version": 1, "tipoDte": "01", "codigoGeneracion": "CG"}
    token = make_jws({"identificacion": meta})
    monkeypatch.setattr(dte, "construir_sobre_recepcion", lambda doc, data: {})

    def fake_post(url, headers=None, json=None, timeout=20):
        class R:
            status_code = 400
            text = ""

            def json(self):
                return {"detalle": {"descripcionMsg": "Bad", "observaciones": {"foo": "bar"}}}

        return R()

    monkeypatch.setattr("dte.requests.post", fake_post)
    resp = _post_dte(dte.DEFAULT_RECEPCION_URL, "TOKEN", token, meta)
    assert resp["http_status"] == 400
    assert resp["descripcionMsg"] == "Bad"
    assert resp["observaciones"] == {"foo": "bar"}
    assert resp["errores"] == "Bad; foo: bar"


def test_enviar_dte_a_hacienda_returns_errores(monkeypatch):
    jws_token = make_jws({"identificacion": {"tipoDte": "01", "codigoGeneracion": "1", "ambiente": "00", "version": 1}})

    def fake_post_dte(url, token, jws, meta):
        return {"estado": "Rechazado", "descripcionMsg": "Mal", "observaciones": {"a": "b"}}

    monkeypatch.setattr(dte, "_post_dte", fake_post_dte)
    monkeypatch.setattr(dte, "_load_dte_api_config", lambda: {"url": dte.DEFAULT_RECEPCION_URL})
    monkeypatch.setattr(auth, "get_token", lambda: "T")
    resp = enviar_dte_a_hacienda(jws_token)
    assert resp["errores"] == "Mal; a: b"


def test_enviar_evento_propagates_errores(monkeypatch):
    db = DB(":memory:")
    monkeypatch.setattr(dte, "_load_dte_api_config", lambda: {"url": dte.DEFAULT_RECEPCION_URL})
    monkeypatch.setattr(dte.jws, "sign_json", lambda data: "TOKEN")
    monkeypatch.setattr(auth, "get_token", lambda: "T")

    def fake_post_evento(url, token, evento, evento_data):
        return {"estado": "Rechazado", "descripcionMsg": "Oops", "observaciones": {"x": "y"}}

    monkeypatch.setattr(dte, "_post_evento", fake_post_evento)
    monkeypatch.setattr(db, "registrar_envio_dte", lambda *a, **k: None)
    res = dte.enviar_evento_contingencia(db, 1, {"id": 1})
    assert res["errores"] == "Oops; x: y"
