from __future__ import annotations

from pathlib import Path
from typing import Union
import os
import sys


PathLike = Union[str, os.PathLike]


def resource_path(*parts: PathLike) -> Path:
    """Return an absolute path to a bundled resource.

    ``PyInstaller`` extracts resources into ``sys._MEIPASS`` when running in
    frozen mode. During development we resolve paths relative to the project
    root so the same helper works in both environments. ``parts`` accepts
    positional path fragments, mirroring :func:`pathlib.Path.joinpath`.
    """

    base_dir = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    if not parts:
        return base_dir
    return base_dir.joinpath(*parts)


__all__ = ["resource_path"]
