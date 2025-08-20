"""Validaciones básicas para campos del resumen de DTE."""
from __future__ import annotations

from typing import Any, Iterable
from decimal import Decimal

from . import catalogos
from .monto import d2

# Catálogo permitido de ``condicionOperacion`` obtenido dinámicamente.
# Si el catálogo local no provee los códigos se acepta cualquier valor
# entero ingresado manualmente.
_CATALOG = getattr(catalogos, "CONDICION_OPERACION", {})
CONDICION_OPERACION_CATALOG = set(_CATALOG.keys())

# Mapeo de nombres a códigos según catálogo oficial.  Cuando el catálogo no
# está disponible se soportan los alias más comunes.
_CONDICION_OPERACION_BY_NAME = {str(v).lower(): k for k, v in _CATALOG.items()}
if not _CONDICION_OPERACION_BY_NAME:
    _CONDICION_OPERACION_BY_NAME = {
        "contado": 1,
        "credito": 2,
        "crédito": 2,
        "otro": 3,
    }
if "otras" in _CONDICION_OPERACION_BY_NAME:
    _CONDICION_OPERACION_BY_NAME.setdefault(
        "otro", _CONDICION_OPERACION_BY_NAME["otras"]
    )


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

    if CONDICION_OPERACION_CATALOG and code not in CONDICION_OPERACION_CATALOG:
        raise ValueError(f"condicionOperacion inválida: {value}")
    return code


def validate_pagos_basico(resumen: dict, condicion: int) -> None:
    """Valida estructura mínima de ``pagos`` en ``resumen``.

    Verifica que los códigos de pago sean válidos según ``CAT-017`` y que la
    suma de ``montoPago`` no exceda ``totalPagar``.  Cuando la
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
        if d2(suma) > d2(total):
            raise ValueError("La suma de pagos excede totalPagar")

    allowed = set(catalogos.FORMA_PAGO.keys())
    for pago in pagos:
        codigo = str(pago.get("codigo", "")).zfill(2)
        if allowed and codigo not in allowed:
            raise ValueError(f"Código de pago inválido: {codigo}")

        monto = Decimal(str(pago.get("montoPago", 0)))
        if monto <= 0:
            raise ValueError("montoPago debe ser mayor a 0")

        plazo_raw = pago.get("plazo")
        if plazo_raw not in (None, ""):
            try:
                plazo_val = int(plazo_raw)
            except Exception as exc:  # pragma: no cover - error path
                raise ValueError("plazo inválido") from exc
            if plazo_val <= 0:
                raise ValueError("plazo debe ser mayor a 0")

        periodo_raw = pago.get("periodo")
        if periodo_raw not in (None, ""):
            periodo_code = str(periodo_raw).zfill(2)
            if periodo_code not in catalogos.PLAZO:
                raise ValueError("periodo inválido")

    if condicion == 2:
        first = pagos[0]
        plazo = int(first.get("plazo") or 0)
        periodo = str(first.get("periodo") or "").zfill(2)
        if not plazo or periodo not in catalogos.PLAZO:
            raise ValueError(
                "Para operaciones a crédito, pagos[0] requiere plazo>0 y periodo válido",
            )
