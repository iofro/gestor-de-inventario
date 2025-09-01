from __future__ import annotations

import json
import hashlib
import os
import re
from decimal import Decimal
from typing import Any, Iterator, Tuple


def stable_stringify(value: Any, indent: int | None = None) -> str:
    """Serialize ``value`` to JSON with stable alphabetical key order.

    The function normalizes ``value`` by sorting dictionary keys
    recursively. ``indent`` controls pretty-printing; when ``None`` the
    result is compact without extra spaces.  Cyclic references raise
    ``ValueError``.
    """

    seen: set[int] = set()

    def order(obj: Any) -> Any:
        if obj is None:
            return obj
        if not isinstance(obj, (dict, list)):
            return obj
        oid = id(obj)
        if oid in seen:
            raise ValueError("Ciclo detectado en JSON")
        seen.add(oid)
        if isinstance(obj, list):
            return [order(item) for item in obj]
        return {k: order(obj[k]) for k in sorted(obj)}

    normalized = order(value)
    if indent is None:
        return json.dumps(
            normalized,
            ensure_ascii=False,
            separators=(",", ":"),
            cls=DecimalEncoder,
        )
    return json.dumps(
        normalized,
        ensure_ascii=False,
        indent=indent,
        cls=DecimalEncoder,
    )


class DecimalEncoder(json.JSONEncoder):
    """Encode :class:`decimal.Decimal` preserving trailing zeros.

    ``format(value, 'f')`` renders the decimal in fixed-point notation,
    so numbers like ``Decimal('1.50')`` are serialized as ``1.50`` and
    ``Decimal('13.0000')`` as ``13.0000``.  The encoded JSON contains
    numbers without surrounding quotes.
    """

    def default(self, obj: Any) -> Any:  # type: ignore[override]
        if isinstance(obj, Decimal):
            return f"__decimal__:{format(obj, 'f')}"
        return super().default(obj)

    def encode(self, o: Any) -> str:  # type: ignore[override]
        s = super().encode(o)
        return re.sub(r'"__decimal__:([^"\n]+)"', r"\1", s)


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def hash_json(value: Any) -> str:
    """Return a deterministic SHA256 hash for ``value`` serialized as JSON."""
    return _sha256(stable_stringify(value))


def assert_same_payload(dte: dict) -> None:
    compact = stable_stringify(dte)
    recompact = stable_stringify(json.loads(compact))
    if _sha256(compact) != _sha256(recompact):
        raise RuntimeError("JSON no estable al re-serializar (no determinista)")
    pretty = stable_stringify(dte, indent=2)
    if _sha256(stable_stringify(json.loads(pretty))) != _sha256(compact):
        raise RuntimeError("El JSON guardado difiere del payload firmado (estructura)")


def _walk(prefix: str, obj: Any) -> Iterator[Tuple[str, Any]]:
    if isinstance(obj, dict):
        for k, v in obj.items():
            new_prefix = f"{prefix}.{k}" if prefix else k
            yield from _walk(new_prefix, v)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            new_prefix = f"{prefix}[{i}]"
            yield from _walk(new_prefix, v)
    else:
        yield prefix, obj


def validar_montos(dte_dict: Any) -> None:
    for clave, valor in _walk("", dte_dict):
        if isinstance(valor, Decimal):
            if (valor * 10) % 1 != 0:
                raise ValueError(f"El campo {clave} = {valor} no es múltiplo de 0.1")


def save_file(path: str, content: str, add_final_newline: bool = True) -> None:
    """Persist ``content`` to ``path`` atomically using UTF-8 encoding.

    ``add_final_newline`` controls whether a trailing newline is appended
    when missing. JWS outputs should pass ``False`` to avoid altering the
    token.
    """
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        if add_final_newline and not content.endswith("\n"):
            fh.write(content + "\n")
        else:
            fh.write(content)
    os.replace(tmp, path)
