import pytest

from dialogs import (
    validar_nit,
    validar_nrc,
    validar_email,
    validar_telefono,
)


@pytest.mark.parametrize("nit, expected", [
    ("1234-123456-123-1", True),
    ("0000-000000-000-0", True),
    ("1234-123456-123-12", False),
    ("1234-123456-123", False),
])
def test_validar_nit(nit, expected):
    assert validar_nit(nit) is expected


@pytest.mark.parametrize("nrc, expected", [
    ("123456-7", True),
    ("000001-0", True),
    ("12345-7", False),
    ("123456-78", False),
])
def test_validar_nrc(nrc, expected):
    assert validar_nrc(nrc) is expected


@pytest.mark.parametrize("email, expected", [
    ("user@example.com", True),
    ("test@domain.co", True),
    ("invalid@domain", False),
    ("userexample.com", False),
])
def test_validar_email(email, expected):
    assert validar_email(email) is expected


@pytest.mark.parametrize("telefono, expected", [
    ("1234-5678", True),
    ("(503) 1234-5678", True),
    ("1234567", False),
    ("5031234567", False),
])
def test_validar_telefono(telefono, expected):
    assert validar_telefono(telefono) is expected
