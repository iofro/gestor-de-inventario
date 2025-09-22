from __future__ import annotations

from pathlib import Path
import sys
from typing import Union


def resource_path(*parts: Union[str, Path]) -> Path:
    """Return absolute path to a bundled resource.

    When packaged with PyInstaller the application files are extracted
    to ``sys._MEIPASS``. During development resources should be located
    relative to the repository root. The helper mirrors the behaviour of
    the commonly used snippet in PyInstaller documentation while keeping
    the ``Path`` API available to callers.
    """

    if getattr(sys, "frozen", False):  # pragma: no cover - executed in frozen builds
        base = Path(getattr(sys, "_MEIPASS"))
    else:
        base = Path(__file__).resolve().parent.parent

    if not parts:
        return base

    return base.joinpath(*[Path(p) for p in parts])
