"""Pre-validation utilities for SVFE envelopes.

This module offers helpers to perform lightweight validation of signed
documents before they are sent to Hacienda.  The goal is to catch obvious
problems early without touching the official JSON schemas shipped in the
project.
"""

from __future__ import annotations

import base64
import json
from typing import Any, Dict, Iterable


# Keys that may be present in a document returned by MH after processing but
# should not be considered when validating against the schema.  These keys are
# simply stripped out by :func:`strip_extras`.
EXTRAS = {"responseMH", "token", "firmaElectronica", "selloRecibido"}


def strip_extras(dte: Dict[str, Any]) -> Dict[str, Any]:
    """Return a shallow copy of ``dte`` without non-schema keys.

    Parameters
    ----------
    dte:
        Original DTE payload potentially containing extra fields added by MH.

    Returns
    -------
    dict
        New dictionary without the keys listed in :data:`EXTRAS`.
    """

    return {k: v for k, v in dte.items() if k not in EXTRAS}


def _b64url_decode(s: str) -> bytes:
    """Decode a base64url string, adding any required padding."""

    s += "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s.encode())


def _decode_jws(jws: str) -> Dict[str, Any]:
    """Return the JSON payload contained in a compact JWS string."""

    assert jws.count(".") == 2, "JWS no compacto"
    _header, payload_b64, _sig = jws.split(".")
    return json.loads(_b64url_decode(payload_b64))


def prevalidate_envelope(
    sobre: Dict[str, Any],
    jws: str,
    schema_path: str | None = None,
    allowed_ambientes: Iterable[str] | None = None,
) -> None:
    """Pre-validate an envelope ``sobre`` and its signed payload ``jws``.

    The function verifies basic envelope consistency (``tipoDte``,
    ``codigoGeneracion`` and ``ambiente``) but no longer validates the payload
    against a JSON schema.  ``schema_path`` is accepted for backwards
    compatibility and ignored.  ``allowed_ambientes`` can be used to specify the
    accepted values for ``identificacion.ambiente`` (``"00"`` por defecto).
    """

    payload = _decode_jws(jws)
    ident = payload.get("identificacion", {})

    tipo_sobre = sobre.get("tipoDte")
    tipo_ident = ident.get("tipoDte")
    try:
        tipo_sobre = int(tipo_sobre)
        tipo_ident = int(tipo_ident)
    except (TypeError, ValueError):
        pass
    assert tipo_sobre == tipo_ident, "tipoDte (sobre vs payload) no coincide"
    assert (
        sobre["codigoGeneracion"] == ident.get("codigoGeneracion")
    ), "codigoGeneracion no coincide"

    ambientes = tuple(allowed_ambientes or ("00",))
    ambiente = ident.get("ambiente")
    assert ambiente in ambientes, (
        f"ambiente debe ser uno de {', '.join(sorted(ambientes))}"
    )


# Backwards compatibility -----------------------------------------------------
def prevalidate(sobre: Dict[str, Any]) -> bool:
    """Compatibility wrapper around :func:`prevalidate_envelope`.

    ``sobre`` must include ``documento`` containing el JWS.  La validación
    contra los *schemas* oficiales fue deshabilitada, por lo que esta función
    solo verifica la consistencia básica del sobre y siempre devuelve ``True``
    si no se encuentran inconsistencias.
    """

    jws = sobre.get("documento", "")
    prevalidate_envelope(sobre, jws)
    return True


__all__ = [
    "strip_extras",
    "prevalidate_envelope",
    "prevalidate",
]

