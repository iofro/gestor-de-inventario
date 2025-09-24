from __future__ import annotations

import os
import re
import shutil
from functools import lru_cache
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


def _is_windows() -> bool:
    return os.name == "nt"


@lru_cache()
def _get_store_package_dirs(local_app_data: str) -> tuple[Path, ...]:
    base = Path(local_app_data)
    packages_dir = base / "Packages"
    try:
        entries = list(packages_dir.iterdir())
    except OSError:
        return ()
    matches = []
    for entry in entries:
        try:
            is_dir = entry.is_dir()
        except OSError:
            continue
        if not is_dir:
            continue
        if entry.name.startswith("PythonSoftwareFoundation.Python."):
            matches.append(entry)
    return tuple(matches)
def resolve_user_visible_path(path: os.PathLike[str] | str) -> str:
    """Return a path that points to the physical file visible to the user.

    When running under the Windows Store distribution of Python the
    application is executed within an AppContainer which transparently
    redirects writes to ``%LocalAppData%`` into the package specific
    ``LocalCache\\Local`` directory.  The logical path is still reported to the
    application which results in confusing messages for end users.  This helper
    attempts to map a logical path back to its physical counterpart so paths
    shown in the UI are consistent with what Windows Explorer exposes.
    """

    try:
        requested = os.fspath(path)
    except TypeError:
        return path  # type: ignore[return-value]

    if not requested:
        return requested

    if not _is_windows():
        return requested

    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        return requested

    package_dirs = _get_store_package_dirs(local_app_data)
    if not package_dirs:
        return requested

    try:
        base_abs = os.path.abspath(local_app_data)
        requested_abs = os.path.abspath(requested)
    except (OSError, TypeError, ValueError):
        return requested

    try:
        relative = os.path.relpath(requested_abs, base_abs)
    except ValueError:
        return requested

    if relative == ".":
        relative = ""

    if relative.startswith(".."):
        return requested

    relative_path = Path(relative) if relative else None
    if relative_path and any(part == os.pardir for part in relative_path.parts):
        return requested

    for package_dir in package_dirs:
        physical_root = package_dir / "LocalCache" / "Local"
        physical_path = physical_root
        if relative_path:
            physical_path = physical_root.joinpath(relative_path)
        try:
            exists = physical_path.exists()
        except OSError:
            continue
        if exists:
            return os.fspath(physical_path)
    return requested
