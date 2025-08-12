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


def test_estructura_invalida(dte_metadata_factory):
    from jsonschema import ValidationError

    dte = dte_metadata_factory()
    del dte["emisor"]["nit"]
    with pytest.raises(ValidationError):
        validate_dte_json(dte)


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
