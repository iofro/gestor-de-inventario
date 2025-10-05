import logging

import pytest

import json
from pathlib import Path

import json
from pathlib import Path

try:
    from dialogs import (
        validar_nit,
        validar_dui,
        validar_nrc,
        validar_email,
        validar_telefono,
    )
except Exception:  # pragma: no cover - missing UI deps
    validar_nit = validar_dui = validar_nrc = validar_email = validar_telefono = None
    _dialog_import_error = True
else:  # pragma: no cover
    _dialog_import_error = False

from dte import validate_dte_json, _build_receptor_direccion
from db import DB
from tests.test_dte_validation import _patch_datos_negocio
from jsonschema import ValidationError
from utils import catalogos


@pytest.mark.parametrize(
    "nit, expected",
    [
        ("", True),
        ("123456789", True),
        ("12341234561234", True),
        ("1234-123456-123-1", False),
        ("123456789012345", False),
        ("abcd", False),
    ],
)
@pytest.mark.skipif(_dialog_import_error, reason="UI dependencies not available")
def test_validar_nit(nit, expected):
    assert validar_nit(nit) is expected


@pytest.mark.parametrize(
    "dui, expected",
    [
        ("123456789", True),
        ("12345678-9", False),
        ("1234567890", False),
        ("abcd", False),
    ],
)
@pytest.mark.skipif(_dialog_import_error, reason="UI dependencies not available")
def test_validar_dui(dui, expected):
    assert validar_dui(dui) is expected


@pytest.mark.parametrize("nrc, expected", [
    ("1234567", True),
    ("0000010", True),
    ("123456789", False),
    ("123456a", False),
])
@pytest.mark.skipif(_dialog_import_error, reason="UI dependencies not available")
def test_validar_nrc(nrc, expected):
    assert validar_nrc(nrc) is expected


@pytest.mark.parametrize("email, expected", [
    ("", True),
    ("user@example.com", True),
    ("test@domain.co", True),
    ("invalid@domain", False),
    ("userexample.com", False),
])
@pytest.mark.skipif(_dialog_import_error, reason="UI dependencies not available")
def test_validar_email(email, expected):
    assert validar_email(email) is expected


@pytest.mark.parametrize("telefono, expected", [
    ("1234-5678", True),
    ("(503) 1234-5678", True),
    ("1234567", False),
    ("5031234567", False),
])
@pytest.mark.skipif(_dialog_import_error, reason="UI dependencies not available")
def test_validar_telefono(telefono, expected):
    assert validar_telefono(telefono) is expected


def _load_fc():
    path = Path(__file__).resolve().parent / "goldens" / "fc.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def db_fixture(tmp_path, monkeypatch):
    _patch_datos_negocio(tmp_path, monkeypatch)
    monkeypatch.setenv("HOME", str(tmp_path))
    db = DB()
    yield db


def test_receptor_documentos(monkeypatch, db_fixture, caplog):
    original_get_schema = catalogos.get_dte_schema
    monkeypatch.setattr(catalogos, "get_dte_schema", lambda *_: None)
    data = _load_fc()
    data["receptor"]["tipoDocumento"] = 36
    data["receptor"]["numDocumento"] = "06141990011019"
    data["receptor"]["nrc"] = "123456"
    validate_dte_json(data, db=db_fixture)

    data["receptor"]["numDocumento"] = "123"
    with pytest.raises(ValueError):
        validate_dte_json(data, db=db_fixture)

    monkeypatch.setattr(catalogos, "get_dte_schema", original_get_schema)
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        data = _load_fc()
        data["receptor"]["tipoDocumento"] = 13
        data["receptor"]["numDocumento"] = "123456789"
        validate_dte_json(data, db=db_fixture)
        data["receptor"]["numDocumento"] = "12345678"
        validate_dte_json(data, db=db_fixture)
    assert any("DUI no normalizable" in record.message for record in caplog.records)


def test_receptor_direccion(monkeypatch, db_fixture):
    monkeypatch.setattr(catalogos, "get_dte_schema", lambda *_: None)
    data = _load_fc()
    data["receptor"]["nrc"] = "123456"
    data["receptor"]["direccion"] = {
        "departamento": "05",
        "municipio": "23",
        "complemento": "C",
    }
    validate_dte_json(data, db=db_fixture)

    data["receptor"]["direccion"]["municipio"] = "Municipio Inexistente"
    with pytest.raises(ValidationError):
        validate_dte_json(data, db=db_fixture)

    data["receptor"]["direccion"] = None
    with pytest.raises(ValidationError):
        validate_dte_json(data, db=db_fixture)


def test_direccion_normaliza_por_nombre():
    out = _build_receptor_direccion(
        {"departamento": "San Salvador", "municipio": "San Salvador Centro"}
    )
    assert out == {"departamento": "06", "municipio": "23", "complemento": None}


def test_direccion_normaliza_por_codigo():
    out = _build_receptor_direccion({"departamento": 6, "municipio": 23})
    assert out["departamento"] == "06"
    assert out["municipio"] == "23"


def test_infiere_departamento():
    out = _build_receptor_direccion({"municipio": "San Salvador Centro"})
    assert out["departamento"] == "06"
    assert out["municipio"] == "23"


def test_municipio_fuera_depto():
    out = _build_receptor_direccion(
        {"departamento": "06", "municipio": "Santa Ana Centro"}
    )
    assert out["departamento"] == "06"
    assert out["municipio"] == "15"


def test_receptor_direccion_municipio_nombre_fuera_depto(monkeypatch):
    monkeypatch.setattr(catalogos, "get_dte_schema", lambda *_: None)
    out = _build_receptor_direccion(
        {
            "departamento": "06",
            "municipio": "Santa Ana Centro",
            "complemento": "C",
        }
    )
    assert out == {
        "departamento": "06",
        "municipio": "15",
        "complemento": "C",
    }


def test_complemento_opcional():
    out = _build_receptor_direccion(
        {
            "departamento": "06",
            "municipio": "San Salvador Centro",
            "complemento": "",
        }
    )
    assert out["complemento"] is None
