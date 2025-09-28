"""Helpers to open PDF files with the system's default viewer."""
from __future__ import annotations

import os
import subprocess
import sys
import webbrowser
from pathlib import Path


def open_pdf_with_default_viewer(path: str) -> bool:
    """Try to open ``path`` using ``QDesktopServices`` if Qt is available."""

    try:
        from PyQt5.QtCore import QUrl
        from PyQt5.QtGui import QDesktopServices
    except ImportError:
        return False

    url = QUrl.fromLocalFile(path)
    return bool(QDesktopServices.openUrl(url))


def open_pdf_cross_platform(path: str) -> bool:
    """Open ``path`` using the platform's default mechanism."""

    resolved_path = Path(path).resolve()
    absolute_path = os.fspath(resolved_path)
    file_uri = resolved_path.as_uri()

    try:
        if sys.platform.startswith("win"):
            os.startfile(absolute_path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", absolute_path])
        else:
            subprocess.Popen(["xdg-open", absolute_path])
        return True
    except Exception:
        try:
            return webbrowser.open(file_uri, new=2)
        except Exception:
            return False


def open_pdf(path: str) -> bool:
    """Open the PDF located at ``path`` with the user's preferred application."""

    if not path or not Path(path).exists():
        return False

    try:
        if open_pdf_with_default_viewer(path):
            return True
    except Exception:
        # If Qt is available but fails, continue with the fallback strategy.
        pass

    return open_pdf_cross_platform(path)

