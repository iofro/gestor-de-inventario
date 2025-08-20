import pytest

from dte import _parse_condicion_operacion as normalize_condicion_operacion
from utils.resumen import validate_pagos_basico


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
    """Values outside the catalog should normalize to 1 (contado)."""
    assert normalize_condicion_operacion(4) == 1
    assert normalize_condicion_operacion("invalida") == 1


def test_validate_pagos_basico_condicion1():
    """validate_pagos_basico should not fail for contado with valid pagos."""
    resumen = {"totalPagar": 10.0, "pagos": [{"codigo": "01", "montoPago": 10.0}]}
    validate_pagos_basico(resumen, 1)


def test_validate_pagos_basico_requires_plazo_periodo():
    """When condicionOperacion=2, plazo and periodo are required."""
    resumen = {"totalPagar": 10.0, "pagos": [{"codigo": "01", "montoPago": 10.0}]}
    with pytest.raises(ValueError):
        validate_pagos_basico(resumen, 2)

