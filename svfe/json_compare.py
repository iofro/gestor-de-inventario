from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from itertools import zip_longest
from typing import Any, Dict, List

DEC8 = Decimal("0.00000001")
DEC2 = Decimal("0.01")

ITEM_KEYS = {
    "cantidad",
    "precioUni",
    "ventaGravada",
    "ventaNoSuj",
    "ventaExenta",
    "montoDescu",
    "psv",
    "noGravado",
}

TOTAL_KEYS = {
    "totalNoSuj",
    "totalExenta",
    "totalGravada",
    "subTotalVentas",
    "descuNoSuj",
    "descuExenta",
    "descuGravada",
    "porcentajeDescuento",
    "totalDescu",
    "subTotal",
    "ivaPerci1",
    "ivaRete1",
    "reteRenta",
    "montoTotalOperacion",
    "totalNoGravado",
    "totalPagar",
    "totalIva",
    "saldoFavor",
    "montoPago",
}


def _norm_value(value: Any, key: str | None) -> Any:
    if isinstance(value, Decimal):
        if key in ITEM_KEYS:
            return format(value.quantize(DEC8, ROUND_HALF_UP), ".8f")
        if key in TOTAL_KEYS:
            return format(value.quantize(DEC2, ROUND_HALF_UP), ".2f")
        return str(value)
    if isinstance(value, str):
        try:
            dec = Decimal(value)
        except Exception:
            return value
        return _norm_value(dec, key)
    return value


def normalize_for_schema(d: Dict[str, Any]) -> Dict[str, Any]:
    def _norm(obj: Any, key: str | None = None) -> Any:
        if isinstance(obj, dict):
            return {k: _norm(obj[k], k) for k in sorted(obj)}
        if isinstance(obj, list):
            return [_norm(v) for v in obj]
        return _norm_value(obj, key)

    return _norm(d)


def deep_diff(a: Any, b: Any, path: str = "") -> List[str]:
    diffs: List[str] = []
    if isinstance(a, dict) and isinstance(b, dict):
        keys = sorted(set(a) | set(b))
        for k in keys:
            p = f"{path}.{k}" if path else k
            if k not in a:
                diffs.append(f"{p}: esperado {b[k]!r}, falta en A")
            elif k not in b:
                diffs.append(f"{p}: presente {a[k]!r}, falta en B")
            else:
                diffs.extend(deep_diff(a[k], b[k], p))
    elif isinstance(a, list) and isinstance(b, list):
        for i, (va, vb) in enumerate(zip_longest(a, b, fillvalue=object())):
            p = f"{path}[{i}]"
            if va is object():
                diffs.append(f"{p}: esperado {vb!r}, falta en A")
            elif vb is object():
                diffs.append(f"{p}: presente {va!r}, falta en B")
            else:
                diffs.extend(deep_diff(va, vb, p))
    else:
        if a != b:
            diffs.append(f"{path}: {a!r} != {b!r}")
    return diffs


def _count_leaves(obj: Any) -> int:
    if isinstance(obj, dict):
        return sum(_count_leaves(v) for v in obj.values())
    if isinstance(obj, list):
        return sum(_count_leaves(v) for v in obj)
    return 1


def similarity(a: Any, b: Any) -> float:
    na = normalize_for_schema(a)
    nb = normalize_for_schema(b)
    diffs = deep_diff(na, nb)
    total = max(_count_leaves(na), _count_leaves(nb))
    if total == 0:
        return 1.0
    return 1.0 - (len(diffs) / total)
