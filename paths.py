from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

from appdirs import user_data_dir


_CANONICAL_DTE_SUBDIRS = {
    "ConsumidorFinal": "facturas_consumidor_final",
    "CreditoFiscal": "facturas_credito_fiscal",
    "NotaRemision": "notas_remision",
    "NotaCredito": "notas_credito",
    "NotaDebito": "notas_debito",
}

_DTE_CODE_TO_DOC = {
    "01": "ConsumidorFinal",
    "03": "CreditoFiscal",
    "04": "NotaRemision",
    "05": "NotaCredito",
    "06": "NotaDebito",
}

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


def _normalise_doc_type(tipo_dte: str | int | None) -> str | None:
    if tipo_dte is None:
        return None
    if isinstance(tipo_dte, int):
        return _DTE_CODE_TO_DOC.get(f"{tipo_dte:02d}")
    if not isinstance(tipo_dte, str):
        tipo_dte = os.fspath(tipo_dte)
    value = tipo_dte.strip()
    if not value:
        return None
    if value.isdigit() and len(value) <= 2:
        return _DTE_CODE_TO_DOC.get(f"{int(value):02d}")
    if value in _DTE_CODE_TO_DOC:
        return _DTE_CODE_TO_DOC[value]
    for canonical in _CANONICAL_DTE_SUBDIRS:
        if canonical.lower() == value.lower():
            return canonical
    return value


def get_canonical_dte_dir(tipo_dte: str | int | os.PathLike | None) -> Path:
    """Return the canonical storage directory for ``tipo_dte``.

    The directory is created if it doesn't exist and accepts either the DTE
    numeric code (``01`` → ``ConsumidorFinal``) or the descriptive name used
    throughout the application.  Any :class:`os.PathLike` inputs are coerced
    via :func:`os.fspath` to provide compatibility with ``pathlib.Path``
    instances that may leak from older call sites.
    """

    doc_key = _normalise_doc_type(tipo_dte)
    if not doc_key:
        raise ValueError("tipo_dte inválido para ruta canónica")
    subdir = _CANONICAL_DTE_SUBDIRS.get(doc_key)
    if not subdir:
        subdir = re.sub(r"[^A-Za-z0-9_.-]", "_", doc_key).strip("_") or "dtes"
    return ensure_user_dir(subdir)


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

FACTURAS_CONSUMIDOR_FINAL_DIR = str(get_canonical_dte_dir("ConsumidorFinal"))
FACTURAS_CREDITO_FISCAL_DIR = str(get_canonical_dte_dir("CreditoFiscal"))
TICKETS_OUTPUT_DIR = str(ensure_user_dir("tickets"))
NOTAS_DEBITO_DIR = str(get_canonical_dte_dir("NotaDebito"))
NOTAS_CREDITO_DIR = str(get_canonical_dte_dir("NotaCredito"))
NOTAS_REMISION_DIR = str(get_canonical_dte_dir("NotaRemision"))
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
