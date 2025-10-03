import json
from types import SimpleNamespace

import dte


def _sample_meta():
    return {
        "identificacion": {
            "ambiente": "00",
            "version": 1,
            "tipoDte": "01",
            "codigoGeneracion": "00000000-0000-4000-8000-000000000001",
        }
    }


def test_post_dte_persists_payload_even_on_rejection(monkeypatch):
    captured: dict[str, object] = {}

    def fake_save(sobre, serialized=None):
        captured["sobre"] = sobre
        captured["serialized"] = serialized

    monkeypatch.setattr(dte, "_save_hacienda_payload", fake_save)
    monkeypatch.setattr(dte, "auth_headers", lambda extra, ambiente=None: dict(extra or {}))
    monkeypatch.setattr(dte, "detect_user_agent", lambda *a, **k: "Vertex-DTE/Tests")

    class FakeResp:
        status_code = 400
        headers = {}
        text = ""
        content = b""
        request = SimpleNamespace(headers={}, body=b"{}")

        def json(self):
            return {"estado": "Error", "detalle": "fail"}

    def fake_post_json(url, headers, body, tag):
        assert "serialized" in captured, "se debe guardar antes de contactar a Hacienda"
        return FakeResp(), {"estado": "Error", "detalle": "fail"}, ""

    monkeypatch.setattr(dte, "_post_json", fake_post_json)

    result = dte._post_dte(
        dte.DEFAULT_RECEPCION_URL,
        "header.payload.signature",
        _sample_meta(),
    )

    assert result["estado"] == "Rechazado"
    assert "serialized" in captured

    serialized = captured["serialized"]
    if isinstance(serialized, (bytes, bytearray)):
        serialized = bytes(serialized).decode("utf-8")

    expected = json.dumps(captured["sobre"], ensure_ascii=False)
    assert serialized == expected
