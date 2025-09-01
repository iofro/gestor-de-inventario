import dte
import auth


def test_enviar_dte_a_hacienda_strips_newline(monkeypatch):
    captured = {}

    def fake_decode(token):
        captured["decoded"] = token
        return {
            "identificacion": {
                "ambiente": "00",
                "version": 1,
                "tipoDte": "01",
                "codigoGeneracion": "X",
            }
        }

    def fake_post(url, token, jws_token, meta):
        captured["posted"] = jws_token
        return {"estado": "Transmitido"}

    monkeypatch.setattr(dte, "_decode_jws_payload", fake_decode)
    monkeypatch.setattr(dte, "_post_dte", fake_post)
    monkeypatch.setattr(dte, "_load_dte_api_config", lambda: {"url": "http://example.com"})
    monkeypatch.setattr(auth, "get_token", lambda: "Bearer TOKEN")

    token = "AAA.BBB.CCC\n"
    resp = dte.enviar_dte_a_hacienda(token)

    assert captured["decoded"] == "AAA.BBB.CCC"
    assert captured["posted"] == "AAA.BBB.CCC"
    assert resp["estado"] == "Transmitido"


def test_construir_sobre_recepcion_strips_newline(monkeypatch):
    captured = {}

    def fake_decode(token):
        captured["decoded"] = token
        return {
            "identificacion": {
                "ambiente": "00",
                "version": 1,
                "tipoDte": "01",
                "codigoGeneracion": "X",
            }
        }

    monkeypatch.setattr(dte, "_decode_jws_payload", fake_decode)

    token = "AAA.BBB.CCC\n"
    sobre = dte.construir_sobre_recepcion(token)

    assert captured["decoded"] == "AAA.BBB.CCC"
    assert sobre["documento"] == "AAA.BBB.CCC"
    assert sobre["ambiente"] == "00"
    assert sobre["version"] == 1
    assert sobre["tipoDte"] == "01"
    assert sobre["codigoGeneracion"] == "X"
