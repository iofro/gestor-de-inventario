"""Helpers for reading environment configuration values."""
from __future__ import annotations

import os
from typing import Iterable

__all__ = ["env_flag"]


_TRUTHY: Iterable[str] = {"1", "true", "yes", "on"}
_FALSY: Iterable[str] = {"0", "false", "no", "off"}


def env_flag(name: str, default: bool = False) -> bool:
    """Return ``True`` when environment variable ``name`` is truthy."""

    value = os.environ.get(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in _TRUTHY:
        return True
    if normalized in _FALSY:
        return False
    return default
