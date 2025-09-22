from __future__ import annotations

import shutil
from pathlib import Path

from appdirs import user_data_dir

APP_NAME = "VertexDTE"


def _bundle_root() -> Path:
    return Path(__file__).resolve().parent


def _get_user_data_dir() -> Path:
    path = Path(user_data_dir(APP_NAME))
    path.mkdir(parents=True, exist_ok=True)
    return path


USER_DATA_DIR = _get_user_data_dir()
DATOS_NEGOCIO_PATH = USER_DATA_DIR / "datos_negocio.json"
CONFIG_NEGOCIO_PATH = USER_DATA_DIR / "config_negocio.json"
LAST_INVENTORY_PATH = USER_DATA_DIR / "ultimo_inventario.json"
LOGS_DIR = USER_DATA_DIR / "logs"
DEFAULT_DB_PATH = USER_DATA_DIR / "inventario.db"

_DEFAULT_FILES = {
    "datos_negocio.json": DATOS_NEGOCIO_PATH,
    "config_negocio.json": CONFIG_NEGOCIO_PATH,
}


def _copy_default_file(filename: str) -> None:
    target = _DEFAULT_FILES.get(filename)
    if target is None:
        return
    source = _bundle_root() / filename
    if source.exists() and not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copyfile(source, target)
        except OSError:
            pass


def migrate_datos_negocio() -> None:
    """Copy bundled configuration files into the user data directory."""

    for filename in _DEFAULT_FILES:
        _copy_default_file(filename)


def ensure_logs_dir() -> Path:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    return LOGS_DIR


def user_data_path(*parts: str) -> Path:
    """Return a path inside the application data directory."""

    return USER_DATA_DIR.joinpath(*parts)


# Ensure default configuration files exist when the module is imported.
migrate_datos_negocio()


__all__ = [
    "APP_NAME",
    "USER_DATA_DIR",
    "DATOS_NEGOCIO_PATH",
    "CONFIG_NEGOCIO_PATH",
    "LAST_INVENTORY_PATH",
    "LOGS_DIR",
    "DEFAULT_DB_PATH",
    "migrate_datos_negocio",
    "ensure_logs_dir",
    "user_data_path",
]
