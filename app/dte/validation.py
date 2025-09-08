"""Validation helpers for DTE envelopes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from decimal import Decimal
from jsonschema import Draft7Validator, validators

SCHEMA_MAP = {
    "04": "fe-nr-v3.json",
    "06": "fe-nd-v3.json",
}

SCHEMAS_DIR = Path(__file__).resolve().parents[2] / "svfe-json-schemas"


def _load_schema(tipo: str) -> Dict[str, Any]:
    schema_file = SCHEMAS_DIR / SCHEMA_MAP[tipo]
    with schema_file.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def validate_dte(envelope: Dict[str, Any], tipo: str) -> List[str]:
    """Validate ``envelope`` against the official schema for ``tipo``.

    Returns a list of human readable error messages.  The list is empty when
    the document is valid.
    """

    schema = _load_schema(tipo)
    type_checker = Draft7Validator.TYPE_CHECKER.redefine(
        "number", lambda checker, value: isinstance(value, (int, float, Decimal))
    )

    def multiple_of(validator, multiple, instance, schema):
        try:
            quotient = Decimal(str(instance)) / Decimal(str(multiple))
            if quotient == quotient.to_integral_value():
                return
        except Exception:
            pass
        yield validators.ValidationError(
            f"{instance} is not a multiple of {multiple}"
        )

    CustomValidator = validators.extend(
        Draft7Validator, type_checker=type_checker, validators={"multipleOf": multiple_of}
    )

    validator = CustomValidator(schema)
    errors = [e.message for e in validator.iter_errors(envelope)]

    ident = envelope.get("identificacion", {})
    tipo_oper = ident.get("tipoOperacion")
    tipo_cont = ident.get("tipoContingencia")
    motivo = ident.get("motivoContin")
    if tipo_oper == 2:
        if not (tipo_cont and motivo):
            errors.append(
                "tipoContingencia y motivoContin requeridos para tipoOperacion=2"
            )
    else:
        if tipo_cont is not None or motivo is not None:
            errors.append(
                "tipoContingencia y motivoContin deben ser null cuando tipoOperacion≠2"
            )

    return errors


__all__ = ["validate_dte"]
