from pathlib import Path
import sys


def resource_path(relative: str) -> Path:
    """Return absolute path to resource bundled via PyInstaller.

    In frozen mode (e.g., when packaged with PyInstaller) resources live
    inside ``sys._MEIPASS``. During development, resources are resolved
    relative to the project root directory.
    """
    base = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
    return base / relative
