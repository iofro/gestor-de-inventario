import pytest

from dte import sanitize_dte_payload
from svfe.prevalidate import prevalidate
from tests.conftest import make_jws


def _make_valid_payload(dte_metadata_factory):
    payload = dte_metadata_factory()
    payload["identificacion"]["version"] = 1
    payload = sanitize_dte_payload(payload)
    return payload


def test_prevalidate_success(dte_metadata_factory):
    payload = _make_valid_payload(dte_metadata_factory)
    token = make_jws(payload)
    sobre = {
        "tipoDte": int(payload["identificacion"]["tipoDte"]),
        "codigoGeneracion": payload["identificacion"]["codigoGeneracion"],
        "documento": token,
    }
    assert prevalidate(sobre) is True


def test_prevalidate_tipo_mismatch(dte_metadata_factory):
    payload = _make_valid_payload(dte_metadata_factory)
    token = make_jws(payload)
    sobre = {
        "tipoDte": 3,  # diferente al del payload
        "codigoGeneracion": payload["identificacion"]["codigoGeneracion"],
        "documento": token,
    }
    with pytest.raises(AssertionError):
        prevalidate(sobre)

