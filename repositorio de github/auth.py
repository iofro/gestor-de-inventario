from __future__ import annotations

import json
import logging
from typing import Optional
from urllib.parse import urlparse

from mh_auth import get_manual_token
from paths import CONFIG_NEGOCIO_PATH, DATOS_NEGOCIO_PATH

log = logging.getLogger(__name__)


def _read_json(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception as exc:  # pragma: no cover - logged for diagnostics
        log.debug("No se pudo leer %s: %s", path, exc)
        return {}
    return data if isinstance(data, dict) else {}


def _guess_auth_url() -> Optional[str]:
    data = _read_json(CONFIG_NEGOCIO_PATH)
    ambiente = data.get("ambiente", "pruebas") if isinstance(data, dict) else "pruebas"
    env_conf = data.get(ambiente, {}) if isinstance(data, dict) else {}
    if isinstance(env_conf, dict):
        auth_url = env_conf.get("auth_url")
        if auth_url:
            return str(auth_url).strip() or None
    if isinstance(data, dict):
        auth_url = data.get("auth_url")
        if auth_url:
            return str(auth_url).strip() or None

    negocio = _read_json(DATOS_NEGOCIO_PATH)
    base_url = None
    if isinstance(negocio, dict):
        dte_api = negocio.get("dte_api")
        if isinstance(dte_api, dict):
            base_url = dte_api.get("url")
    if base_url:
        base = str(base_url).strip().rstrip("/")
        if base:
            return f"{base}/seguridad/auth"
    return None


def get_token(*_args, **_kwargs) -> str:
    manual = get_manual_token()
    if manual:
        return manual
    raise RuntimeError(
        "Token manual no configurado. Use 'Obtener token' en Configuración de Facturación Electrónica."
    )


def get_last_auth_host() -> Optional[str]:
    url = _guess_auth_url()
    if not url:
        return None
    try:
        return urlparse(url).netloc or None
    except Exception:  # pragma: no cover - urlparse should handle strings gracefully
        return None
