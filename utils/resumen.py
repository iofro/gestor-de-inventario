"""Validaciones básicas para campos del resumen de DTE."""
from __future__ import annotations

from typing import Any, Iterable
from decimal import Decimal

from . import catalogos
from .monto import d2

# Catálogo permitido de condicionOperacion
CONDICION_OPERACION_CATALOG = {1, 2, 3}

# Mapeo de nombres a códigos según catálogo oficial
_CONDICION_OPERACION_BY_NAME = {
    "contado": 1,
    "credito": 2,
    "crédito": 2,
    "otro": 3,
    "otros": 3,
}


def normalize_condicion_operacion(value: Any) -> int:
    """Normaliza ``condicionOperacion`` a su código numérico.

    Acepta códigos numéricos o descripciones textuales y devuelve un entero
    dentro del catálogo. Lanza ``ValueError`` si el valor es inválido.
    """
    if value in (None, ""):
        code = 1
    elif isinstance(value, (int, float)):
        code = int(value)
    else:
        val = str(value).strip().lower().replace("...", "")
        if val.isdigit():
            code = int(val)
        else:
            code = _CONDICION_OPERACION_BY_NAME.get(val)
    if code not in CONDICION_OPERACION_CATALOG:
        raise ValueError(f"condicionOperacion inválida: {value}")
    return code


def sync_condicion_operacion_flags(extra: dict | None, value: Any) -> int:
    """Store ``value`` under both camelCase and snake_case keys.

    The canonical representation inside ``extra`` uses ``condicion_operacion``
    while the camelCase variant is preserved for legacy payloads that expect
    it.  The helper returns the normalized catalog code so callers can reuse
    it without recomputing.
    """

    if extra is None:
        extra = {}
    code = normalize_condicion_operacion(value)
    extra["condicion_operacion"] = code
    extra["condicionOperacion"] = code
    return code


def validate_pagos_basico(resumen: dict, condicion: int) -> None:
    """Valida estructura mínima de ``pagos`` en ``resumen``.

    Verifica que los códigos de pago sean válidos según ``CAT-017`` y que la
    suma de ``montoPago`` coincida con ``totalPagar``.  Cuando la
    ``condicionOperacion`` es 2 (crédito) se requiere que el primer pago
    contenga ``plazo`` mayor a cero y ``periodo`` perteneciente al catálogo
    ``PLAZO``.
    """

    pagos: Iterable[dict] | None = resumen.get("pagos")
    if not pagos:
        return
    pagos = list(pagos)

    total = resumen.get("totalPagar")
    if total is not None:
        suma = sum(Decimal(str(p.get("montoPago", 0))) for p in pagos)
        if d2(suma) != d2(total):
            raise ValueError("La suma de pagos no coincide con totalPagar")

    allowed = set(catalogos.FORMA_PAGO.keys())
    for pago in pagos:
        codigo = str(pago.get("codigo", "")).zfill(2)
        if allowed and codigo not in allowed:
            raise ValueError(f"Código de pago inválido: {codigo}")

    if condicion == 2:
        first = pagos[0]
        plazo_code = str(first.get("plazo", "")).zfill(2)
        if plazo_code not in {"01", "02", "03"}:
            raise ValueError(
                "Crédito: unidad inválida (01=días, 02=meses, 03=años)"
            )

        periodo_raw = first.get("periodo", 0)
        try:
            periodo = int(periodo_raw)
        except (TypeError, ValueError):
            raise ValueError("Crédito: periodo debe ser entero > 0") from None
        if periodo <= 0:
            raise ValueError("Crédito: periodo debe ser entero > 0")
