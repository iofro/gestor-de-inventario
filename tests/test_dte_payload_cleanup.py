import dte


def _has_none(data):
    if data is None:
        return True
    if isinstance(data, dict):
        return any(_has_none(v) for v in data.values())
    if isinstance(data, list):
        return any(_has_none(v) for v in data)
    return False


def test_sanitize_dte_payload_removes_none_recursively(dte_metadata_factory):
    dte_payload = dte_metadata_factory()
    dte_payload["emisor"]["codActividad"] = None
    dte_payload["documentoRelacionado"] = None
    clean = dte.sanitize_dte_payload(dte_payload)
    assert "codActividad" not in clean["emisor"]
    assert "documentoRelacionado" not in clean
    assert not _has_none(clean)


def test_enviar_documento_uses_clean_payload(monkeypatch, dte_metadata_factory):
    payload = dte_metadata_factory()
    payload["emisor"]["codActividad"] = None
    payload["documentoRelacionado"] = None

    captured = {}

    from tests.conftest import make_jws

    def fake_sign(data):
        captured["data"] = data
        return make_jws(data)

    monkeypatch.setattr(dte.jws, "sign_json", fake_sign)
    monkeypatch.setattr(dte.auth, "get_token", lambda: "Bearer JWT")
    monkeypatch.setattr(dte, "_post_dte", lambda url, token, jws, meta: {"estado": "Transmitido"})
    monkeypatch.setattr(dte.auth, "get_last_auth_host", lambda: None)
    monkeypatch.setattr(dte, "_load_dte_api_config", lambda: {})

    class DummyDB:
        def registrar_envio_dte(self, *args, **kwargs):
            pass

    dte._enviar_documento(DummyDB(), 1, payload, "normal")

    assert "codActividad" not in captured["data"]["emisor"]
    assert "documentoRelacionado" not in captured["data"]
    assert not _has_none(captured["data"])
