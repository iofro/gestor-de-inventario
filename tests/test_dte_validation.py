import pytest
from dte import validate_dte_json


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


def test_estructura_invalida(dte_metadata_factory):
    from jsonschema import ValidationError

    dte = dte_metadata_factory()
    del dte["emisor"]["nit"]
    with pytest.raises(ValidationError):
        validate_dte_json(dte)
