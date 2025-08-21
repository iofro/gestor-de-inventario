import pytest
from decimal import Decimal

from utils.stable_json import stable_stringify


@pytest.mark.parametrize("value,expected", [
    (10.1, '{"monto":10.1}'),
    (10.2, '{"monto":10.2}'),
    (10.3, '{"monto":10.3}'),
    (10.4, '{"monto":10.4}'),
])
def test_stable_stringify_handles_float_precisely(value, expected):
    """stable_stringify must not introduce floating point artifacts."""
    assert stable_stringify({"monto": value}) == expected


def test_stable_stringify_handles_decimal():
    """Decimals should serialize to a single decimal place without artifacts."""
    assert stable_stringify({"monto": Decimal("10.3")}) == '{"monto":10.3}'
