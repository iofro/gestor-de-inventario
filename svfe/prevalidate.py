"""Pre-validation utilities for SVFE envelopes.

This module offers helpers to perform lightweight validation of signed
documents before they are sent to Hacienda.  The goal is to catch obvious
problems early without touching the official JSON schemas shipped in the
project.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Dict

from jsonschema import Draft202012Validator, FormatChecker, RefResolver
from utils import catalogos
from .catalogs import (
    normalize_condicion_operacion,
    validate_pagos_basico,
)


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


def validate_against_schema(data: Dict[str, Any], schema_path: str) -> None:
    """Validate ``data`` against the JSON schema located at ``schema_path``.

    The validator uses :class:`Draft202012Validator` with a
    :class:`FormatChecker` and resolves local ``$ref`` references relative to
    ``schema_path``.  All errors are collected and reported together using the
    ``a.b.0.c`` style for paths.
    """

    base = Path(schema_path).resolve()
    schema = json.loads(base.read_text(encoding="utf-8"))
    resolver = RefResolver(base_uri=base.as_uri(), referrer=schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker(), resolver=resolver)

    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
    if errors:
        messages = []
        for err in errors:
            path = ".".join(str(p) for p in err.path) or "<root>"
            messages.append(f"{path}: {err.message}")
        raise ValueError("Errores de validación del schema:\n" + "\n".join(messages))


def prevalidate_envelope(sobre: Dict[str, Any], jws: str, schema_path: str) -> None:
    """Pre-validate an envelope ``sobre`` and its signed payload ``jws``.

    ``sobre`` contains metadata such as ``tipoDte`` and ``codigoGeneracion``.
    The ``jws`` string must be a JWS compact serialization containing the DTE
    payload.  ``schema_path`` points to the JSON schema against which the
    payload will be validated.
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

    ambiente = ident.get("ambiente")
    assert ambiente in {"00", "01"}, "ambiente debe ser '00' o '01'"

    # Rules for tipoOperacion, tipoModelo and tipoContingencia
    tipo_oper = int(ident.get("tipoOperacion", 1) or 1)
    tipo_modelo = ident.get("tipoModelo")
    tipo_cont = ident.get("tipoContingencia")
    motivo = ident.get("motivoContin")
    if isinstance(motivo, str):
        motivo = motivo.strip() or None
    if tipo_oper == 1:
        assert tipo_modelo in (None, 1), "tipoModelo debe ser 1 cuando tipoOperacion=1"
        assert not tipo_cont, "tipoContingencia debe ser nulo cuando tipoOperacion=1"
        assert not motivo, "motivoContin debe ser nulo cuando tipoOperacion=1"
    elif tipo_oper == 2:
        assert tipo_modelo in (None, 2), "tipoModelo debe ser 2 cuando tipoOperacion=2"
        assert tipo_cont is not None, "tipoContingencia requerido cuando tipoOperacion=2"
        tipo_cont = int(tipo_cont)
        assert tipo_cont in catalogos.CONTINGENCIA, "tipoContingencia inválido"
        if tipo_cont == 5:
            assert (
                motivo and 5 <= len(motivo) <= 150
            ), "motivoContin requerido cuando tipoContingencia=5"
        else:
            assert not motivo, "motivoContin sólo permitido cuando tipoContingencia=5"
    else:
        raise AssertionError("tipoOperacion debe ser 1 o 2")

    resumen = payload.get("resumen", {})
    condicion = normalize_condicion_operacion(resumen.get("condicionOperacion"))
    validate_pagos_basico(resumen, condicion)

    if ambiente == "01":
        firma = payload.get("firmaElectronica")
        assert isinstance(firma, str) and firma.strip(), "firmaElectronica requerida"
        try:
            base64.b64decode(firma, validate=True)
        except Exception:
            raise AssertionError("firmaElectronica inválida") from None

    validate_against_schema(strip_extras(payload), schema_path)


# Backwards compatibility -----------------------------------------------------
def prevalidate(sobre: Dict[str, Any]) -> bool:
    """Compatibility wrapper around :func:`prevalidate_envelope`.

    ``sobre`` must include ``documento`` containing the JWS.  The schema path
    is looked up using the existing catalogos mapping.  The function mimics the
    old behaviour by returning ``True`` if validation succeeds.
    """

    jws = sobre.get("documento", "")
    tipo_val = sobre.get("tipoDte")
    if str(tipo_val).isdigit():
        tipo = f"{int(tipo_val):02d}"
    else:
        tipo = str(tipo_val)
    schema_path = catalogos.SCHEMA_MAP.get(tipo)
    if not schema_path:
        raise ValueError(f"Esquema no disponible para tipoDte {tipo}")
    prevalidate_envelope(sobre, jws, schema_path)
    return True


__all__ = [
    "strip_extras",
    "validate_against_schema",
    "prevalidate_envelope",
    "prevalidate",
]

