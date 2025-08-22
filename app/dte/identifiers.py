"""Helpers for generating DTE identifiers."""
from __future__ import annotations

import random
import re
import string
import uuid
from typing import Dict

# Control-number regexes per DTE type.  Only Nota de Crédito ("05") is
# implemented for now, but the mapping allows future expansion.
NC_CONTROL_RE = re.compile(r"^DTE-05-[A-Z0-9]{8}-[0-9]{15}$")
ND_CONTROL_RE = re.compile(r"^DTE-06-[A-Z0-9]{8}-[0-9]{15}$")

_CONTROL_RE = {
    "05": NC_CONTROL_RE,
    "06": ND_CONTROL_RE,
}


def _control_prefix(tipo: str) -> str:
    return f"DTE-{tipo}-"


def ensure_numero_control(envelope: Dict, correlativo15: str | None = None) -> str:
    """Ensure ``codigoGeneracion`` and ``numeroControl`` are present.

    ``correlativo15`` optionally supplies the 15-digit sequential portion of the
    control number; if omitted a random sequence is used.  A UUIDv4 is injected
    into ``codigoGeneracion`` when missing.
    """

    ident = envelope.setdefault("identificacion", {})

    if ident.get("codigoGeneracion"):
        ident["codigoGeneracion"] = str(ident["codigoGeneracion"]).upper()
    else:
        ident["codigoGeneracion"] = str(uuid.uuid4()).upper()

    tipo = ident.get("tipoDte")
    regex = _CONTROL_RE.get(str(tipo))
    if regex is None:
        raise ValueError(f"Unsupported tipoDte: {tipo}")

    numero = ident.get("numeroControl") or ""
    if not regex.match(numero):
        prefix = _control_prefix(str(tipo))
        rand_part = "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
        if correlativo15 is None:
            seq_part = "".join(random.choices(string.digits, k=15))
        else:
            seq_part = str(correlativo15).zfill(15)
        ident["numeroControl"] = f"{prefix}{rand_part}-{seq_part}"

    return ident["numeroControl"]
