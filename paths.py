from __future__ import annotations

import os
import shutil
from pathlib import Path

from appdirs import user_data_dir

APP_NAME = "VertexDTE"


def _get_user_data_dir() -> Path:
    path = Path(user_data_dir(APP_NAME))
    path.mkdir(parents=True, exist_ok=True)
    return path


USER_DATA_DIR = _get_user_data_dir()


def user_data_path(*parts: str) -> Path:
    if not parts:
        return USER_DATA_DIR
    path = USER_DATA_DIR.joinpath(*parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def ensure_user_dir(*parts: str) -> Path:
    path = USER_DATA_DIR.joinpath(*parts)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _copy_if_missing(filename: str) -> None:
    src = Path(__file__).resolve().parent / filename
    dst = user_data_path(filename)
    if src.exists() and not dst.exists():
        try:
            shutil.copyfile(src, dst)
        except OSError:
            pass


DATOS_NEGOCIO_PATH = str(user_data_path("datos_negocio.json"))
CONFIG_NEGOCIO_PATH = str(user_data_path("config_negocio.json"))
LAST_INVENTORY_PATH = str(user_data_path("ultimo_inventario.json"))

CERT_UPLOAD_DIR = str(ensure_user_dir("certificados"))
LOG_DIR = str(ensure_user_dir("logs"))

FACTURAS_CONSUMIDOR_FINAL_DIR = str(ensure_user_dir("facturas_consumidor_final"))
FACTURAS_CREDITO_FISCAL_DIR = str(ensure_user_dir("facturas_credito_fiscal"))
TICKETS_OUTPUT_DIR = str(ensure_user_dir("tickets"))
NOTAS_DEBITO_DIR = str(ensure_user_dir("notas_debito"))
NOTAS_CREDITO_DIR = str(ensure_user_dir("notas_credito"))
NOTAS_REMISION_DIR = str(ensure_user_dir("notas_remision"))
DTES_DIR = str(ensure_user_dir("dtes"))
DTE_FALLIDOS_DIR = str(ensure_user_dir("dte_fallidos"))
DTES_PENDIENTES_DIR = str(ensure_user_dir("dtes_pendientes"))
FACTURAS_ARCHIVE_CF_DIR = str(ensure_user_dir("facturas", "consumidor_final"))
FACTURAS_ARCHIVE_CREDITO_DIR = str(ensure_user_dir("facturas", "credito_fiscal"))


def user_logs_path(*parts: str) -> Path:
    base = ensure_user_dir("logs")
    return base.joinpath(*parts) if parts else base


def migrate_datos_negocio() -> None:
    """Copy bundled configuration files to the user data directory."""

    for filename in ("datos_negocio.json", "config_negocio.json"):
        _copy_if_missing(filename)
