import pytest
from jsonschema import ValidationError

# Alias existing function names to align with test descriptions
from dte import (
    _parse_condicion_operacion as normalize_condicion_operacion,
    validate_dte_json as validate_pagos_basico,
)


def test_normalize_condicion_operacion_variants():
    """normalize_condicion_operacion should accept multiple representations."""
    assert normalize_condicion_operacion(1) == 1
    assert normalize_condicion_operacion("1") == 1
    assert normalize_condicion_operacion("contado") == 1
    assert normalize_condicion_operacion("Crédito") == 2
    assert normalize_condicion_operacion("credito") == 2
    assert normalize_condicion_operacion("OTRO") == 3
    assert normalize_condicion_operacion("3") == 3


def test_normalize_condicion_operacion_invalid():
    """Invalid values outside {1,2,3} should raise ValueError."""
    with pytest.raises(ValueError):
        normalize_condicion_operacion(4)
    with pytest.raises(ValueError):
        normalize_condicion_operacion("invalida")


def test_validate_pagos_basico_condicion1(dte_metadata_factory):
    """validate_pagos_basico should not fail for contado with valid pagos."""
    dte = dte_metadata_factory()
    dte["resumen"]["condicionOperacion"] = 1
    dte["identificacion"]["version"] = 1
    # pagos fixture already contains required keys
    validate_pagos_basico(dte)


def test_validate_pagos_basico_requires_plazo_periodo(dte_metadata_factory):
    """When condicionOperacion=2, plazo and periodo are required."""
    dte = dte_metadata_factory()
    dte["resumen"]["condicionOperacion"] = 2
    dte["identificacion"]["version"] = 1
    # Remove plazo/periodo so validation should fail
    dte["resumen"]["pagos"] = [
        {"codigo": "01", "montoPago": 10.0, "referencia": "ref"}
    ]
    with pytest.raises(ValidationError):
        validate_pagos_basico(dte)
