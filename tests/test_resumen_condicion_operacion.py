import pytest

from dte import _parse_condicion_operacion as parse_condicion_operacion
from utils.doc_generation import normalize_payment_condition
from utils.resumen import (
    normalize_condicion_operacion as normalize_condicion_operacion_extra,
    sync_condicion_operacion_flags,
    validate_pagos_basico,
)


def test_normalize_condicion_operacion_variants():
    """normalize_condicion_operacion should accept multiple representations."""
    assert parse_condicion_operacion(1) == 1
    assert parse_condicion_operacion("1") == 1
    assert parse_condicion_operacion("contado") == 1
    assert parse_condicion_operacion("Crédito") == 2
    assert parse_condicion_operacion("credito") == 2
    assert parse_condicion_operacion("OTRO") == 3
    assert parse_condicion_operacion("3") == 3


def test_normalize_condicion_operacion_invalid():
    """Values outside the catalog should normalize to 1 (contado)."""
    assert parse_condicion_operacion(4) == 1
    assert parse_condicion_operacion("invalida") == 1


def test_normalize_condicion_operacion_alias_otros():
    """Both helper variants must accept the plural alias 'Otros'."""
    assert parse_condicion_operacion("otros") == 3
    assert normalize_condicion_operacion_extra("Otros") == 3


def test_validate_pagos_basico_condicion1():
    """validate_pagos_basico should not fail for contado with valid pagos."""
    resumen = {"totalPagar": 10.0, "pagos": [{"codigo": "01", "montoPago": 10.0}]}
    validate_pagos_basico(resumen, 1)


def test_validate_pagos_basico_requires_plazo_periodo():
    """When condicionOperacion=2, plazo and periodo are required."""
    resumen = {"totalPagar": 10.0, "pagos": [{"codigo": "01", "montoPago": 10.0}]}
    with pytest.raises(ValueError):
        validate_pagos_basico(resumen, 2)


def test_validate_pagos_basico_credito_acepta_periodos_largos():
    """Credit operations allow arbitrary positive periods (e.g. 12 meses)."""

    resumen = {
        "totalPagar": 10.0,
        "pagos": [
            {"codigo": "01", "montoPago": 10.0, "plazo": "02", "periodo": 12},
        ],
    }

    validate_pagos_basico(resumen, 2)


def test_validate_pagos_basico_credito_rechaza_periodo_invalido():
    """Periodo no numérico o <=0 debe generar error explícito."""

    resumen = {
        "totalPagar": 10.0,
        "pagos": [
            {"codigo": "01", "montoPago": 10.0, "plazo": "02", "periodo": "12x"},
        ],
    }

    with pytest.raises(ValueError, match="periodo debe ser entero > 0"):
        validate_pagos_basico(resumen, 2)


def test_validate_pagos_basico_credito_rechaza_plazo_fuera_catalogo():
    """Plazos distintos de 01/02/03 se rechazan con mensaje claro."""

    resumen = {
        "totalPagar": 10.0,
        "pagos": [
            {"codigo": "01", "montoPago": 10.0, "plazo": "05", "periodo": 6},
        ],
    }

    with pytest.raises(ValueError, match="Crédito: unidad inválida"):
        validate_pagos_basico(resumen, 2)


def test_sync_condicion_operacion_flags_sets_both_keys():
    """sync helper should write both camelCase and snake_case keys."""
    extra = {}
    code = sync_condicion_operacion_flags(extra, "Crédito")
    assert code == 2
    assert extra["condicion_operacion"] == 2
    assert extra["condicionOperacion"] == 2


def test_normalize_payment_condition_credit_variants():
    """Credit operations normalize plazo/periodo while keeping integers."""
    payload = {
        "condicion_operacion": 2,
        "pago_plazo": "M",
        "pago_periodo": "3",
    }
    result = normalize_payment_condition(payload)
    assert result["pago_plazo"] == "02"
    assert result["pago_periodo"] == 3


def test_normalize_payment_condition_non_credit_blanks_fields():
    """Non credit operations must drop plazo/periodo content."""
    payload = {
        "condicion_operacion": 1,
        "pago_plazo": "02",
        "pago_periodo": "5",
    }
    result = normalize_payment_condition(payload)
    assert result["pago_plazo"] is None
    assert result["pago_periodo"] is None


def test_normalize_payment_condition_credit_errors_on_invalid_periodo():
    """Invalid periodo raises before reaching the generator layer."""
    payload = {
        "condicion_operacion": 2,
        "pago_plazo": "M",
        "pago_periodo": 0,
    }
    with pytest.raises(ValueError):
        normalize_payment_condition(payload)


def test_normalize_payment_condition_credit_errors_on_invalid_plazo():
    """Invalid plazo catalog value should be rejected."""
    payload = {
        "condicion_operacion": 2,
        "pago_plazo": "ZZ",
        "pago_periodo": 5,
    }
    with pytest.raises(ValueError):
        normalize_payment_condition(payload)


@pytest.mark.parametrize(
    "condicion, plazo, periodo, esperado_plazo, esperado_periodo",
    [
        (2, "M", "3", "02", 3),
        (2, "02", 7, "02", 7),
        (1, "A", 12, None, None),
        (3, "01", "9", None, None),
    ],
)
def test_normalize_payment_condition_matches_schema_examples(
    condicion, plazo, periodo, esperado_plazo, esperado_periodo
):
    """La normalización respeta los casos representativos del esquema DTE."""

    payload = {
        "condicion_operacion": condicion,
        "pago_plazo": plazo,
        "pago_periodo": periodo,
        "pago_referencia": "OC-1234",
        "otros": "no tocar",
    }

    result = normalize_payment_condition(payload)

    assert result["condicion_operacion"] in {1, 2, 3}
    assert result["pago_plazo"] == esperado_plazo
    assert result["pago_periodo"] == esperado_periodo
    assert result["pago_referencia"] == "OC-1234"
    assert result["otros"] == "no tocar"


def test_normalize_payment_condition_is_idempotent():
    """Invocar la función varias veces no altera un resultado ya normalizado."""

    payload = {
        "condicion_operacion": 2,
        "pago_plazo": "d",
        "pago_periodo": "15",
    }

    first = normalize_payment_condition(payload)
    second = normalize_payment_condition(first)

    assert second is first
    assert second["pago_plazo"] == "01"
    assert second["pago_periodo"] == 15

