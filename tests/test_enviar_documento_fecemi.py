import copy

import auth
import dte
from db import DB


def test_enviar_documento_preserva_fecemi_factura(monkeypatch):
    db = DB(":memory:")
    controlled_date = "2024-01-15"
    data = {
        "identificacion": {
            "tipoDte": "01",
            "codigoGeneracion": "UUID-123",
            "numeroControl": "DTE-01-ABC-000000000000001",
            "fecEmi": controlled_date,
        },
        "resumen": {"totalLetras": "DIEZ"},
    }

    calls = {"sign": 0, "post": 0}
    captured: dict[str, dict] = {}

    monkeypatch.setattr(auth, "get_last_auth_host", lambda: None)
    monkeypatch.setattr(
        dte,
        "_load_dte_api_config",
        lambda: {"url": "https://apitest.dtes.mh.gob.sv/fesv/recepciondte"},
    )
    monkeypatch.setattr(dte, "_save_signed_dte", lambda *args, **kwargs: None)
    monkeypatch.setattr(dte, "fecha_emision_hoy_str", lambda now=None: "2077-07-07")

    def fake_sign(payload):
        calls["sign"] += 1
        captured["payload"] = copy.deepcopy(payload)
        return "token"

    def fake_decode(token):
        assert token == "token"
        return copy.deepcopy(captured["payload"])

    def fake_post(url, documento, meta, **kwargs):
        calls["post"] += 1
        captured["meta"] = copy.deepcopy(meta)
        return {"estado": "Procesado"}

    monkeypatch.setattr("utils.jws.sign_json", fake_sign)
    monkeypatch.setattr(dte, "_decode_jws_payload", fake_decode)
    monkeypatch.setattr(dte, "_post_dte", fake_post)

    result = dte._enviar_documento(db, 1, data, "normal")

    assert result["estado"] == "Procesado"
    assert calls["sign"] == 1
    assert calls["post"] == 1
    assert captured["payload"]["identificacion"]["fecEmi"] == controlled_date
    assert data["identificacion"]["fecEmi"] == controlled_date
