import pytest
from dte import sanitize_dte_payload, validate_dte_json


def test_dte_valido_pasa(dte_metadata_factory):
    dte = dte_metadata_factory()
    validate_dte_json(dte)


def test_codigo_invalido_rechazado(dte_metadata_factory):
    dte = dte_metadata_factory()
    dte["identificacion"]["tipoDte"] = "99"
    with pytest.raises(ValueError):
        validate_dte_json(dte)


def test_longitud_nit_invalida(dte_metadata_factory):
    dte = dte_metadata_factory()
    dte["emisor"]["nit"] = "123"
    with pytest.raises(ValueError):
        validate_dte_json(dte)


def test_longitud_num_documento_invalida(dte_metadata_factory):
    dte = dte_metadata_factory()
    dte["receptor"]["numDocumento"] = "123"
    with pytest.raises(ValueError):
        validate_dte_json(dte)


def test_estructura_invalida(dte_metadata_factory, monkeypatch):
    dte = dte_metadata_factory()
    del dte["emisor"]["nit"]
    monkeypatch.setattr("dte._load_datos_negocio", lambda: {})
    with pytest.raises(ValueError) as exc:
        validate_dte_json(dte)
    assert "nit" in str(exc.value)


def test_strips_additional_properties(dte_metadata_factory):
    dte = dte_metadata_factory()
    dte["firmaElectronica"] = "XYZ"
    dte["selloRecibido"] = "ABC"
    dte["identificacion"]["firmaElectronica"] = "XYZ"
    clean = sanitize_dte_payload(dte)
    assert "firmaElectronica" not in clean
    assert "selloRecibido" not in clean
    assert "firmaElectronica" not in clean["identificacion"]
    validate_dte_json(clean)


def test_missing_top_level_fields_listed():
    with pytest.raises(ValueError) as exc:
        validate_dte_json({})
    msg = str(exc.value)
    for key in [
        "identificacion",
        "emisor",
        "receptor",
        "cuerpoDocumento",
        "resumen",
    ]:
        assert key in msg


def test_missing_emisor_fields_listed(dte_metadata_factory, monkeypatch):
    dte = dte_metadata_factory()
    dte["emisor"] = {}
    monkeypatch.setattr("dte._load_datos_negocio", lambda: {})
    with pytest.raises(ValueError) as exc:
        validate_dte_json(dte)
    msg = str(exc.value)
    for key in [
        "nit",
        "nrc",
        "nombre",
        "nombreComercial",
        "codActividad",
        "descActividad",
        "direccion.complemento",
        "telefono",
        "correo",
    ]:
        assert key in msg


def test_schema_reports_multiple_errors(dte_metadata_factory):
    from jsonschema import ValidationError

    dte = dte_metadata_factory()
    del dte["cuerpoDocumento"][0]["descripcion"]
    del dte["cuerpoDocumento"][0]["cantidad"]
    with pytest.raises(ValidationError) as exc:
        validate_dte_json(dte)
    msg = str(exc.value)
    assert "cuerpoDocumento.0: 'descripcion' is a required property" in msg
    assert "cuerpoDocumento.0.cantidad" in msg
    assert hasattr(exc.value, "errors")
    assert len(exc.value.errors) == 2
    paths = [e["path"] for e in exc.value.errors]
    assert ["cuerpoDocumento", 0] in paths
    assert ["cuerpoDocumento", 0, "cantidad"] in paths
    messages = {e["message"] for e in exc.value.errors}
    assert "'descripcion' is a required property" in messages
    assert "0.0 is less than or equal to the minimum of 0" in messages
