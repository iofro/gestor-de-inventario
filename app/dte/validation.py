"""Validation helpers for DTE envelopes."""
from __future__ import annotations

import json
import os
from typing import Dict, List

from jsonschema import Draft7Validator

# ``svfe-json-schemas`` lives at the repository root alongside the ``app``
# package. Allow overriding the directory via ``DTE_SCHEMA_DIR`` to avoid
# coupling callers to the repository layout.
SCHEMA_DIR = os.getenv("DTE_SCHEMA_DIR") or os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "svfe-json-schemas")
)


_DEF_CACHE: dict[str, Draft7Validator] = {}


def _load_schema(tipo: str) -> Draft7Validator:
    """Load and cache JSON schema for the given ``tipo``."""
    if tipo not in _DEF_CACHE:
        name = {
            "05": "fe-nc-v3.json",
        }.get(tipo)
        if not name:
            raise ValueError(f"Unsupported tipo: {tipo}")
        path = os.path.join(SCHEMA_DIR, name)
        with open(path, "r", encoding="utf-8") as fh:
            schema = json.load(fh)
        _DEF_CACHE[tipo] = Draft7Validator(schema)
    return _DEF_CACHE[tipo]


def validate_dte(envelope: Dict, tipo: str) -> List[str]:
    """Validate ``envelope`` using the JSON schema for ``tipo``.

    Returns a list of error messages.  Additional dependent-rule checks are
    implemented to cover the domain specific requirements for contingency
    fields.
    """

    validator = _load_schema(tipo)
    errors: List[str] = []
    for e in validator.iter_errors(envelope):
        path = "/".join(map(str, e.absolute_path))
        errors.append(f"{path}: {e.message}")

    ident = envelope.get("identificacion", {})
    if ident.get("tipoOperacion") == 2 and ident.get("tipoContingencia") is None:
        errors.append("identificacion.tipoContingencia requerido cuando tipoOperacion=2")
    if ident.get("tipoContingencia") == 5 and not ident.get("motivoContin"):
        errors.append("identificacion.motivoContin requerido cuando tipoContingencia=5")

    return errors
