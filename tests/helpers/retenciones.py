from __future__ import annotations

import json
import re
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

_NUMERIC_PATTERN = re.compile(r"^-?\d+\.\d+$")
_CCF_PATH = Path(__file__).resolve().parents[1] / "goldens" / "ccf.json"


def load_ccf_sample() -> dict[str, Any]:
    """Load the bundled credit-fiscal DTE sample normalizing decimal fields."""

    with open(_CCF_PATH, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    return _convert_decimal(deepcopy(data))


def _convert_decimal(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _convert_decimal(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_convert_decimal(item) for item in value]
    if isinstance(value, str) and _NUMERIC_PATTERN.match(value):
        try:
            return Decimal(value)
        except (InvalidOperation, ValueError):
            return value
    return value


__all__ = ["load_ccf_sample"]
