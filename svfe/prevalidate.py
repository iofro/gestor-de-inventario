"""Pre-validation utilities for SVFE envelopes.

This module provides :func:`prevalidate` to perform a minimal validation of
``sobre`` (envelope) structures before they are sent to the SVFE services.
It ensures the envelope matches the signed payload and that the payload
conforms to the official JSON schemas.
"""

from __future__ import annotations

import base64
import json
from typing import Any, Dict

from jsonschema import ValidationError, validate

from utils import catalogos


def _decode_jws_payload(token: str) -> Dict[str, Any]:
    """Return the JSON payload embedded in ``token``.

    The token must be a JWS string of the form ``header.payload.signature``.
    Raises :class:`ValueError` if the token is malformed or cannot be decoded.
    """

    try:
        parts = token.split(".")
        if len(parts) != 3:
            raise ValueError("JWS malformado")
        payload_b64 = parts[1]
        padding = "=" * (-len(payload_b64) % 4)
        payload_bytes = base64.urlsafe_b64decode(payload_b64 + padding)
        return json.loads(payload_bytes.decode("utf-8"))
    except Exception as exc:  # pragma: no cover - defensive
        raise ValueError("documento inválido") from exc


def prevalidate(sobre: Dict[str, Any]) -> bool:
    """Validate a ``sobre`` (envelope) structure.

    Parameters
    ----------
    sobre:
        Dictionary representing the envelope. It must contain ``documento``
        with the JWS, ``tipoDte`` and ``codigoGeneracion`` fields.

    Returns
    -------
    bool
        ``True`` if the envelope passes all checks.

    Raises
    ------
    ValueError
        If any verification fails or the payload does not comply with the
        JSON schema associated with its ``tipoDte``.
    """

    if not isinstance(sobre, dict):
        raise ValueError("sobre inválido")

    jws = sobre.get("documento")
    if not isinstance(jws, str):
        raise ValueError("documento faltante")

    payload = _decode_jws_payload(jws)
    ident = payload.get("identificacion") or {}

    tipo_dte = ident.get("tipoDte")
    codigo = ident.get("codigoGeneracion")

    if sobre.get("tipoDte") != tipo_dte:
        raise ValueError("tipoDte no coincide")
    if sobre.get("codigoGeneracion") != codigo:
        raise ValueError("codigoGeneracion no coincide")
    if ident.get("ambiente") != "00":
        raise ValueError("ambiente inválido")

    schema = catalogos.get_dte_schema(str(tipo_dte))
    if not schema:
        raise ValueError(f"Esquema no disponible para tipoDte {tipo_dte}")

    expected_version = (
        schema.get("properties", {})
        .get("identificacion", {})
        .get("properties", {})
        .get("version", {})
        .get("const")
    )
    version = ident.get("version")
    if expected_version is not None and version != expected_version:
        raise ValueError("versión no coincide con esquema")

    try:
        validate(payload, schema)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc

    return True


__all__ = ["prevalidate"]

