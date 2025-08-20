import pytest

import json
from pathlib import Path

import json
from pathlib import Path

try:
    from dialogs import (
        validar_nit,
        validar_nrc,
        validar_email,
        validar_telefono,
    )
except Exception:  # pragma: no cover - missing UI deps
    validar_nit = validar_nrc = validar_email = validar_telefono = None
    _dialog_import_error = True
else:  # pragma: no cover
    _dialog_import_error = False

from dte import validate_dte_json, _build_receptor_direccion
from jsonschema import ValidationError
from utils import catalogos


@pytest.mark.parametrize("nit, expected", [
    ("1234-123456-123-1", True),
    ("12341234561231", True),
    ("12345678-9", True),
    ("123456789", True),
    ("1234-123456-123", False),
    ("abcd", False),
])
@pytest.mark.skipif(_dialog_import_error, reason="UI dependencies not available")
def test_validar_nit(nit, expected):
    assert validar_nit(nit) is expected


@pytest.mark.parametrize("nrc, expected", [
    ("123456-7", True),
    ("000001-0", True),
    ("12345-7", False),
    ("123456-78", False),
])
@pytest.mark.skipif(_dialog_import_error, reason="UI dependencies not available")
def test_validar_nrc(nrc, expected):
    assert validar_nrc(nrc) is expected


@pytest.mark.parametrize("email, expected", [
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


def _load_nc():
    path = Path(__file__).resolve().parent / "goldens" / "nc.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_receptor_documentos(monkeypatch):
    monkeypatch.setattr(catalogos, "get_dte_schema", lambda *_: None)
    data = _load_fc()
    data["receptor"]["tipoDocumento"] = 36
    data["receptor"]["numDocumento"] = "06141990011019"
    validate_dte_json(data)

    data["receptor"]["numDocumento"] = "123"
    with pytest.raises(ValueError):
        validate_dte_json(data)

    data = _load_fc()
    data["receptor"]["tipoDocumento"] = 13
    data["receptor"]["numDocumento"] = "12345678-9"
    validate_dte_json(data)
    data["receptor"]["numDocumento"] = "123456789"
    with pytest.raises(ValueError):
        validate_dte_json(data)


def test_receptor_direccion(monkeypatch):
    monkeypatch.setattr(catalogos, "get_dte_schema", lambda *_: None)
    data = _load_fc()
    data["receptor"]["direccion"] = {
        "departamento": "05",
        "municipio": "23",
        "complemento": "C",
    }
    validate_dte_json(data)

    data["receptor"]["direccion"]["municipio"] = "99"
    with pytest.raises(ValidationError):
        validate_dte_json(data)

    data["receptor"]["direccion"] = None
    with pytest.raises(ValidationError):
        validate_dte_json(data)


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
    with pytest.raises(ValidationError):
        _build_receptor_direccion(
            {"departamento": "06", "municipio": "Santa Ana Centro"}
        )


def test_receptor_direccion_municipio_nombre_fuera_depto(monkeypatch):
    monkeypatch.setattr(catalogos, "get_dte_schema", lambda *_: None)
    data = _load_fc()
    data["receptor"]["direccion"] = {
        "departamento": "06",
        "municipio": "Santa Ana Centro",
        "complemento": "C",
    }
    with pytest.raises(ValidationError):
        validate_dte_json(data)


def test_complemento_opcional():
    out = _build_receptor_direccion(
        {
            "departamento": "06",
            "municipio": "San Salvador Centro",
            "complemento": "",
        }
    )
    assert out["complemento"] is None


def test_validar_documento_relacionado(monkeypatch):
    monkeypatch.setattr(catalogos, "get_dte_schema", lambda *_: None)
    data = _load_nc()
    data["identificacion"]["version"] = 1
    data["identificacion"]["tipoDte"] = "01"
    validate_dte_json(data)
    data["documentoRelacionado"][0]["tipoDocumento"] = "99"
    with pytest.raises(ValueError):
        validate_dte_json(data)


def test_validar_otros_documentos(monkeypatch):
    monkeypatch.setattr(catalogos, "get_dte_schema", lambda *_: None)
    data = _load_fc()
    data["otrosDocumentos"] = [
        {
            "codDocAsociado": 1,
            "descDocumento": "REF",
            "detalleDocumento": "DET",
            "medico": None,
        }
    ]
    validate_dte_json(data)
    data["otrosDocumentos"][0]["codDocAsociado"] = 99
    with pytest.raises(ValueError):
        validate_dte_json(data)
