import pytest
from decimal import Decimal

from utils.stable_json import stable_stringify


@pytest.mark.parametrize(
    "value,expected",
    [
        (10.1, '{"monto":10.1}'),
        (10.2, '{"monto":10.2}'),
        (10.3, '{"monto":10.3}'),
        (10.4, '{"monto":10.4}'),
    ],
)
def test_stable_stringify_handles_float_precisely(value, expected):
    """stable_stringify must not introduce floating point artifacts."""
    assert stable_stringify({"monto": value}) == expected


def test_stable_stringify_handles_decimal():
    """Decimals should serialize without negative zero artifacts."""
    assert stable_stringify({"monto": Decimal("10.3")}) == '{"monto":10.3}'


def test_decimal_encoder_preserves_trailing_zeros():
    """Decimals retain their explicit scale when serialized."""
    assert stable_stringify({"monto": Decimal("1.50")}) == '{"monto":1.50}'
    assert (
        stable_stringify({"gravadas": Decimal("13.0000")})
        == '{"gravadas":13.0000}'
    )
