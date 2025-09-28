"""Helpers to open PDF files with the system's default viewer."""
from __future__ import annotations

import os
import subprocess
import sys
import webbrowser
from pathlib import Path

from paths import resolve_user_visible_path


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
            browser_safe_uri = resolved_path.as_uri()
            return webbrowser.open(browser_safe_uri, new=2)
        except Exception:
            return False


def open_pdf(path: str) -> bool:
    """Open the PDF located at ``path`` with the user's preferred application."""

    if not path:
        return False

    physical_path = resolve_user_visible_path(path)
    candidate_path = physical_path if physical_path != path else path

    def _path_exists(target: str) -> bool:
        try:
            return Path(target).exists()
        except OSError:
            return False

    if candidate_path and _path_exists(candidate_path):
        usable_path = candidate_path
    elif candidate_path != path and path and _path_exists(path):
        usable_path = path
    else:
        return False

    try:
        if open_pdf_with_default_viewer(usable_path):
            return True
    except Exception:
        # If Qt is available but fails, continue with the fallback strategy.
        pass

    return open_pdf_cross_platform(usable_path)

