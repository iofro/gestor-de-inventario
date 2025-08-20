import base64
import pytest

from dte import sanitize_dte_payload
from svfe.prevalidate import prevalidate
from tests.conftest import make_jws


def _make_valid_payload(dte_metadata_factory):
    payload = dte_metadata_factory()
    payload["identificacion"]["version"] = 1
    # Ajustar municipios a valores válidos del catálogo
    payload["emisor"]["direccion"]["municipio"] = "01"
    payload["receptor"]["direccion"]["municipio"] = "01"
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


def test_prevalidate_schema_error(dte_metadata_factory):
    payload = _make_valid_payload(dte_metadata_factory)
    payload.pop("emisor")
    token = make_jws(payload)
    sobre = {
        "tipoDte": int(payload["identificacion"]["tipoDte"]),
        "codigoGeneracion": payload["identificacion"]["codigoGeneracion"],
        "documento": token,
    }
    with pytest.raises(ValueError):
        prevalidate(sobre)


def test_prevalidate_operacion_contingencia(dte_metadata_factory):
    payload = _make_valid_payload(dte_metadata_factory)
    ident = payload["identificacion"]
    ident["tipoOperacion"] = 2
    # faltan tipoContingencia y tipoModelo adecuado
    token = make_jws(payload)
    sobre = {
        "tipoDte": int(ident["tipoDte"]),
        "codigoGeneracion": ident["codigoGeneracion"],
        "documento": token,
    }
    with pytest.raises(AssertionError):
        prevalidate(sobre)


def test_prevalidate_credito_requiere_plazo_periodo(dte_metadata_factory):
    payload = _make_valid_payload(dte_metadata_factory)
    resumen = payload["resumen"]
    resumen["condicionOperacion"] = 2
    # pagos actuales carecen de plazo/periodo
    token = make_jws(payload)
    sobre = {
        "tipoDte": int(payload["identificacion"]["tipoDte"]),
        "codigoGeneracion": payload["identificacion"]["codigoGeneracion"],
        "documento": token,
    }
    with pytest.raises(ValueError):
        prevalidate(sobre)


def test_prevalidate_firma_en_produccion(dte_metadata_factory):
    payload = _make_valid_payload(dte_metadata_factory)
    ident = payload["identificacion"]
    ident["ambiente"] = "01"
    payload["firmaElectronica"] = base64.b64encode(b"sig").decode()
    token = make_jws(payload)
    sobre = {
        "tipoDte": int(ident["tipoDte"]),
        "codigoGeneracion": ident["codigoGeneracion"],
        "documento": token,
    }
    assert prevalidate(sobre) is True

    # quitar firma -> falla
    payload.pop("firmaElectronica")
    token = make_jws(payload)
    sobre["documento"] = token
    with pytest.raises(AssertionError):
        prevalidate(sobre)

