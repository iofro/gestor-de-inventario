import dte


def _has_none(data):
    if data is None:
        return True
    if isinstance(data, dict):
        return any(_has_none(v) for v in data.values())
    if isinstance(data, list):
        return any(_has_none(v) for v in data)
    return False

REQUIRED_NULL_FIELDS = {
    "documentoRelacionado",
    "otrosDocumentos",
    "ventaTercero",
    "extension",
    "apendice",
}


def test_sanitize_dte_payload_removes_none_recursively(dte_metadata_factory):
    dte_payload = dte_metadata_factory()
    dte_payload["emisor"]["codActividad"] = None
    clean = dte.sanitize_dte_payload(dte_payload)
    assert "codActividad" not in clean["emisor"]
    for key in REQUIRED_NULL_FIELDS:
        assert key in clean and clean[key] is None
    item0 = clean["cuerpoDocumento"][0]
    assert item0["codTributo"] is None
    assert item0["tributos"] is None
    assert clean["resumen"]["tributos"] is None
    clean_no_required = {k: v for k, v in clean.items() if k not in REQUIRED_NULL_FIELDS}
    for item in clean_no_required.get("cuerpoDocumento", []):
        item.pop("codTributo", None)
        item.pop("tributos", None)
    clean_no_required.get("resumen", {}).pop("tributos", None)
    assert not _has_none(clean_no_required)


def test_enviar_factura_sanitizes_payload(monkeypatch, dte_metadata_factory):
    payload = dte_metadata_factory()
    payload["emisor"]["codActividad"] = None

    captured = {}

    monkeypatch.setattr(dte, "generar_dte_json", lambda db, venta_id: payload)
    monkeypatch.setattr(dte, "apply_schema_patch", lambda data: data)
    monkeypatch.setattr(dte, "validate_dte_json", lambda data, db=None: None)

    def fake_send(db, doc_id, data, modo):
        captured["data"] = data
        return {"estado": "Transmitido"}

    monkeypatch.setattr(dte, "_enviar_documento", fake_send)

    class DummyDB:
        pass

    dte.enviar_factura(DummyDB(), 1)

    assert "codActividad" not in captured["data"]["emisor"]
    for key in REQUIRED_NULL_FIELDS:
        assert key in captured["data"] and captured["data"][key] is None
    item0 = captured["data"]["cuerpoDocumento"][0]
    assert item0["codTributo"] is None
    assert item0["tributos"] is None
    assert captured["data"]["resumen"]["tributos"] is None
    captured_no_required = {
        k: v for k, v in captured["data"].items() if k not in REQUIRED_NULL_FIELDS
    }
    for item in captured_no_required.get("cuerpoDocumento", []):
        item.pop("codTributo", None)
        item.pop("tributos", None)
    captured_no_required.get("resumen", {}).pop("tributos", None)
    assert not _has_none(captured_no_required)
