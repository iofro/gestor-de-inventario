from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from itertools import zip_longest
import json
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
    """Normalize a scalar ``value`` according to ``key``.

    Only numeric fields defined in ``ITEM_KEYS`` and ``TOTAL_KEYS`` are
    converted to :class:`~decimal.Decimal` instances and quantized to the
    required precision.  All other values are returned untouched so that, for
    example, strings like ``"01"`` keep their leading zeroes.
    """

    if key in ITEM_KEYS or key in TOTAL_KEYS:
        try:
            dec = Decimal(str(value))
        except Exception:
            return value
        quant = DEC8 if key in ITEM_KEYS else DEC2
        return str(dec.quantize(quant, rounding=ROUND_HALF_UP))

    if isinstance(value, Decimal):
        return str(value)

    return value


def normalize_for_schema(d: Dict[str, Any]) -> Dict[str, Any]:
    def _norm(obj: Any, key: str | None = None) -> Any:
        if isinstance(obj, dict):
            return {k: _norm(obj[k], k) for k in sorted(obj)}
        if isinstance(obj, list):
            return [_norm(v) for v in obj]
        return _norm_value(obj, key)

    return _norm(d)


MISSING = object()


def deep_diff(a: Any, b: Any, path: str = "") -> Dict[str, Dict[str, Any]]:
    """Recursively compare two structures ``a`` and ``b``.

    The return value is a mapping whose keys are the dotted paths to the fields
    that differ.  Each entry contains the value in ``a`` under ``"a"`` and the
    value in ``b`` under ``"b"``.  Missing values are represented with the
    string ``"<missing>"``.
    """

    diff: Dict[str, Dict[str, Any]] = {}

    if isinstance(a, dict) and isinstance(b, dict):
        keys = sorted(set(a) | set(b))
        for k in keys:
            p = f"{path}.{k}" if path else k
            if k not in a:
                diff[p] = {"a": "<missing>", "b": b[k]}
            elif k not in b:
                diff[p] = {"a": a[k], "b": "<missing>"}
            else:
                diff.update(deep_diff(a[k], b[k], p))
    elif isinstance(a, list) and isinstance(b, list):
        for i, (va, vb) in enumerate(zip_longest(a, b, fillvalue=MISSING)):
            p = f"{path}[{i}]"
            if va is MISSING or vb is MISSING:
                diff[p] = {"a": va if va is not MISSING else "<missing>", "b": vb if vb is not MISSING else "<missing>"}
            else:
                diff.update(deep_diff(va, vb, p))
    else:
        if a != b:
            diff[path or ""] = {"a": a, "b": b}

    return diff


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
    if diffs:
        # ``json.dumps`` is used to provide a readable representation for the
        # caller while keeping the function side-effect free for identical
        # inputs.  ``ensure_ascii=False`` preserves any non ASCII characters.
        print(json.dumps(diffs, indent=2, ensure_ascii=False))
    if total == 0:
        return 1.0
    return 1.0 - (len(diffs) / total)
