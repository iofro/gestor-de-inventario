"""Utilities for generating identifiers for DTE documents."""

from __future__ import annotations

import re
import uuid
from typing import Dict, Any

ND_CONTROL_REGEX = r"^DTE-06-[A-Z0-9]{8}-[0-9]{18}$"


def ensure_numero_control(
    envelope: Dict[str, Any],
    sucursal: str = "001",
    punto: str = "001",
    correlativo: int = 1,
) -> str:
    """Ensure ``numeroControl`` and ``codigoGeneracion`` for the envelope.

    ``numeroControl`` follows the official pattern for debit notes::

        ^DTE-06-[A-Z0-9]{8}-[0-9]{18}$

    If ``codigoGeneracion`` is missing a UUIDv4 is generated and stored in
    uppercase format.
    """

    ident = envelope.setdefault("identificacion", {})

    # ``codigoGeneracion`` must be a UUID v4 in uppercase.
    if not ident.get("codigoGeneracion"):
        ident["codigoGeneracion"] = str(uuid.uuid4()).upper()

    numero = ident.get("numeroControl")
    if not (isinstance(numero, str) and re.fullmatch(ND_CONTROL_REGEX, numero)):
        secuencia = f"{correlativo:018d}"
        ident["numeroControl"] = f"DTE-06-S{sucursal}P{punto}-{secuencia}"
    return ident["numeroControl"]


__all__ = ["ND_CONTROL_REGEX", "ensure_numero_control"]
