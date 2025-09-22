"""Centralized application version helpers."""

from __future__ import annotations

from configparser import ConfigParser
from functools import lru_cache
from pathlib import Path

from utils import resource_path

_VERSION_FILE = "app_version.ini"
_SECTION = "VertexDTE"
_KEY = "version"


@lru_cache()
def get_version() -> str:
    """Return the application version declared in ``app_version.ini``."""

    path = Path(resource_path(_VERSION_FILE))
    parser = ConfigParser()
    try:
        with path.open("r", encoding="utf-8") as fh:
            parser.read_file(fh)
        value = parser.get(_SECTION, _KEY, fallback="0.0.0").strip()
    except Exception:
        value = "0.0.0"
    return value or "0.0.0"


APP_VERSION = get_version()


__all__ = ["APP_VERSION", "get_version"]
