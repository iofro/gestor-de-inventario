"""Catalog utilities for SVFE."""

from __future__ import annotations

from typing import Any, Dict, Iterable

from utils import catalogos

# Catalogo dinámico de ``condicionOperacion``. Si el catálogo local no está
# disponible se utilizan los valores estándar {1, 2, 3}.
_CAT = getattr(catalogos, "CONDICION_OPERACION", {1: "contado", 2: "crédito", 3: "otro"})
CAT016_CONDICION_OPERACION = set(_CAT.keys()) or {1, 2, 3}
CAT016_ALIASES: Dict[str, int] = {str(k): k for k in CAT016_CONDICION_OPERACION}
for code, name in _CAT.items():
    CAT016_ALIASES[name.lower()] = code
CAT016_ALIASES.setdefault("credito", CAT016_ALIASES.get("crédito", 2))


def normalize_condicion_operacion(value: Any) -> int:
    """Normalize ``condicionOperacion`` catalog values.

    Accepts integers or strings and maps common aliases to their numeric
    equivalents. Returns the numeric code ``1``, ``2`` or ``3``.
    Raises :class:`ValueError` if ``value`` cannot be normalized to one of the
    catalog codes.
    """

    code: int | None
    if isinstance(value, (int, float)):
        code = int(value)
    else:
        text = str(value).strip().lower()
        code = CAT016_ALIASES.get(text)
        if code is None and text.isdigit():
            code = int(text)
    if code not in CAT016_CONDICION_OPERACION:
        raise ValueError(f"condicionOperacion inválida: {value}")
    return code


def needs_plazo_periodo(condicion_operacion: int) -> bool:
    """Return ``True`` if ``condicion_operacion`` requires ``plazo`` and ``periodo``.

    Currently only credit sales (code ``2``) require these fields.
    """

    return condicion_operacion == 2


def validate_pagos_basico(resumen: Dict[str, Any], condicion: int) -> None:
    """Validate minimal requirements for ``resumen['pagos']``.

    ``resumen`` must contain a non-empty ``pagos`` list. When ``condicion`` is
    ``2`` (crédito), at least one of the payments must include ``plazo`` greater
    than ``0`` and a non-empty ``periodo`` field.
    """

    pagos = resumen.get("pagos")
    if not isinstance(pagos, Iterable) or isinstance(pagos, (str, bytes)):
        raise ValueError("resumen['pagos'] debe ser una lista de pagos")
    pagos = list(pagos)
    if not pagos:
        raise ValueError("resumen['pagos'] requiere al menos un pago")

    if needs_plazo_periodo(condicion):
        for pago in pagos:
            plazo = pago.get("plazo") if isinstance(pago, dict) else None
            periodo = pago.get("periodo") if isinstance(pago, dict) else None
            if plazo and plazo > 0 and periodo:
                break
        else:
            raise ValueError(
                "condicionOperacion=2 requiere pago con plazo>0 y periodo"
            )
