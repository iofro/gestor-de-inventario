"""Helpers for validating and normalising identification documents."""
from __future__ import annotations

import re

__all__ = ["is_valid_nit", "normalize_dui_to_nit9"]

_NIT_RE = re.compile(r"^(?:\d{9}|\d{14})$")
_DUI_RE = re.compile(r"^\d{9}$")


def is_valid_nit(nit: str | None) -> bool:
    """Return ``True`` if ``nit`` represents a valid NIT (9 or 14 digits)."""

    if nit is None:
        return False
    value = str(nit).strip()
    if not value:
        return False
    digits = value if value.isdigit() else value.replace("-", "")
    return bool(_NIT_RE.fullmatch(digits))


def normalize_dui_to_nit9(dui: str | None) -> str:
    """Normalise ``dui`` removing separators and validating length."""

    cleaned = (dui or "").replace("-", "").strip()
    if not _DUI_RE.fullmatch(cleaned):
        raise ValueError("DUI inválido para normalizar a NIT-9")
    return cleaned
