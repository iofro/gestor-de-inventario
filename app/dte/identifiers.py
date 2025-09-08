"""Utilities for generating identifiers for DTE documents."""

from __future__ import annotations

import re
import uuid
from typing import Dict, Any

CONTROL_REGEXES = {
    "04": r"^DTE-04-[A-Z0-9]{8}-[0-9]{15}$",
    "06": r"^DTE-06-[A-Z0-9]{8}-[0-9]{15}$",
}

NR_CONTROL_REGEX = CONTROL_REGEXES["04"]
ND_CONTROL_REGEX = CONTROL_REGEXES["06"]


def ensure_numero_control(
    envelope: Dict[str, Any],
    sucursal: str = "001",
    punto: str = "001",
    correlativo: int = 1,
) -> str:
    """Ensure ``numeroControl`` and ``codigoGeneracion`` for the envelope.

    ``numeroControl`` follows the official pattern for the ``tipoDte``
    present in ``identificacion``.  Currently the supported types are:

    * ``"04"`` - Nota de Remisión
    * ``"06"`` - Nota de Débito

    If ``codigoGeneracion`` is missing a UUIDv4 is generated and stored in
    uppercase format.
    """

    ident = envelope.setdefault("identificacion", {})
    tipo = ident.get("tipoDte")
    if tipo not in CONTROL_REGEXES:
        raise ValueError("identificacion.tipoDte inválido o no soportado")

    # ``codigoGeneracion`` must be a UUID v4 in uppercase.
    if not ident.get("codigoGeneracion"):
        ident["codigoGeneracion"] = str(uuid.uuid4()).upper()

    numero = ident.get("numeroControl")
    regex = CONTROL_REGEXES[tipo]
    if not (isinstance(numero, str) and re.fullmatch(regex, numero)):
        secuencia = f"{correlativo:015d}"
        ident["numeroControl"] = f"DTE-{tipo}-S{sucursal}P{punto}-{secuencia}"
    return ident["numeroControl"]


__all__ = [
    "ND_CONTROL_REGEX",
    "NR_CONTROL_REGEX",
    "ensure_numero_control",
]
