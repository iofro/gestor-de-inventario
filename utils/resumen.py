"""Validaciones básicas para campos del resumen de DTE."""
from __future__ import annotations

from typing import Any, Iterable

# Catálogo permitido de condicionOperacion
CONDICION_OPERACION_CATALOG = {1, 2, 3}

# Mapeo de nombres a códigos según catálogo oficial
_CONDICION_OPERACION_BY_NAME = {
    "contado": 1,
    "credito": 2,
    "crédito": 2,
    "otro": 3,
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


def validate_pagos_basico(resumen: dict, condicion: int) -> None:
    """Valida estructura básica de ``pagos`` según ``condicionOperacion``.

    Cuando ``condicion`` es 2 (crédito) se requiere ``plazo`` y ``periodo`` en
    cada elemento de ``pagos``. Lanza ``ValueError`` si faltan.
    """
    pagos: Iterable[dict] | None = resumen.get("pagos")
    if not pagos:
        return
    if condicion == 2:
        for pago in pagos:
            if not pago.get("plazo") or not pago.get("periodo"):
                raise ValueError(
                    "Para operaciones a crédito, cada pago requiere 'plazo' y 'periodo'"
                )
