from __future__ import annotations

import json
import logging
import os
import socket
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import requests

from dte import _load_config_negocio, _load_datos_negocio
from paths import user_data_path

logger = logging.getLogger("activation")

_CACHE_FILENAME = "activation_cache.json"
_DEVICE_ID_FILENAME = "device_id.txt"

_YES_VALUES = {
    "1",
    "true",
    "yes",
    "si",
    "activo",
    "active",
    "on",
    "enabled",
    "approved",
}
_NO_VALUES = {
    "0",
    "false",
    "no",
    "inactivo",
    "inactive",
    "off",
    "disabled",
    "blocked",
    "bloqueado",
    "desactivado",
    "expired",
    "expirado",
}


@dataclass(frozen=True)
class ActivationConfig:
    mode: str
    url: str
    share_path: str
    requests_path: str
    filename: str
    timeout_sec: float
    default_active: bool
    device_id: str

    @property
    def enabled(self) -> bool:
        return bool(self.url or self.share_path)

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "ActivationConfig":
        url = _get_str(data, "url", "activation_url", "activationUrl")
        share_path = _get_str(data, "share_path", "activation_path", "path")
        requests_path = _get_str(data, "requests_path", "requests")
        filename = _get_str(data, "filename", "file") or "{device_id}.json"
        mode = (_get_str(data, "mode", "tipo") or "").lower()
        if mode not in {"http", "share"}:
            if url:
                mode = "http"
            elif share_path:
                mode = "share"
            else:
                mode = "none"

        timeout_sec = _get_float(data.get("timeout_sec"), default=3.0)
        default_active = _to_bool(data.get("default_state"))
        if default_active is None:
            default_active = _to_bool(data.get("default_active"))
        if default_active is None:
            default_active = False

        device_id = _get_str(data, "device_id")

        return cls(
            mode=mode,
            url=url,
            share_path=share_path,
            requests_path=requests_path,
            filename=filename,
            timeout_sec=timeout_sec,
            default_active=default_active,
            device_id=device_id,
        )


@dataclass(frozen=True)
class ActivationDecision:
    active: bool
    status: str
    source: str
    device_id: str
    detail: str


def load_activation_config() -> ActivationConfig:
    data: dict[str, Any] = {}
    config = _load_config_negocio()
    if isinstance(config.get("activation"), dict):
        data.update(config["activation"])
    datos = _load_datos_negocio()
    if isinstance(datos.get("activation"), dict):
        data.update(datos["activation"])
    return ActivationConfig.from_mapping(data)


def check_activation() -> ActivationDecision:
    config = load_activation_config()
    device_id = get_device_id(config.device_id)
    if not config.enabled:
        return ActivationDecision(True, "active", "disabled", device_id, "activation_not_configured")

    status, source, detail = _check_remote(config, device_id)
    if status is not None:
        _write_cache(device_id, status, source, detail)
        return ActivationDecision(status, _status_label(status), source, device_id, detail)

    cached = _read_cache(device_id)
    if cached is not None:
        cached_status = cached.get("status")
        cached_active = cached_status == "active"
        return ActivationDecision(
            cached_active,
            cached_status,
            "cache",
            device_id,
            cached.get("detail", "cached"),
        )

    return ActivationDecision(
        config.default_active,
        _status_label(config.default_active),
        "default",
        device_id,
        "default_state",
    )


def get_device_id(override: str | None = None) -> str:
    if override:
        return override.strip()
    env_id = os.getenv("VERTEX_DEVICE_ID") or os.getenv("DEVICE_ID")
    if env_id:
        return env_id.strip()

    path = user_data_path(_DEVICE_ID_FILENAME)
    try:
        if path.is_file():
            existing = path.read_text(encoding="utf-8").strip()
            if existing:
                return existing
    except OSError:
        pass

    device_id = uuid.uuid4().hex
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(device_id, encoding="utf-8")
    except OSError:
        pass
    return device_id


def _check_remote(config: ActivationConfig, device_id: str) -> tuple[Optional[bool], str, str]:
    if config.mode == "share":
        status, detail = _check_share(config, device_id)
        if status is not None or detail == "missing_file":
            return status, "share", detail
        if config.url:
            status, detail = _check_http(config, device_id)
            return status, "http", detail
        return None, "share", detail

    status, detail = _check_http(config, device_id)
    if status is not None:
        return status, "http", detail
    if config.share_path:
        status, detail = _check_share(config, device_id)
        return status, "share", detail
    return None, "http", detail


def _check_http(config: ActivationConfig, device_id: str) -> tuple[Optional[bool], str]:
    if not config.url:
        return None, "missing_url"
    url = _apply_template(config.url, device_id)
    try:
        response = requests.get(url, timeout=config.timeout_sec)
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.info("Activation HTTP error: %s", exc)
        return None, "http_error"

    status = _parse_payload(response.text)
    return status, "http_ok"


def _check_share(config: ActivationConfig, device_id: str) -> tuple[Optional[bool], str]:
    path = _resolve_share_path(config, device_id)
    if path is None:
        return None, "missing_share_path"

    try:
        if not path.exists():
            _write_request(config, device_id)
            return None, "missing_file"
        payload = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.info("Activation share error: %s", exc)
        return None, "share_error"

    status = _parse_payload(payload)
    return status, "share_ok"


def _resolve_share_path(config: ActivationConfig, device_id: str) -> Optional[Path]:
    if not config.share_path:
        return None
    if "{device_id}" in config.share_path:
        return Path(_apply_template(config.share_path, device_id))
    base = Path(config.share_path)
    if base.suffix:
        return base
    filename = _apply_template(config.filename, device_id)
    return base / filename


def _write_request(config: ActivationConfig, device_id: str) -> None:
    if not config.requests_path:
        return
    try:
        requests_dir = Path(config.requests_path)
        requests_dir.mkdir(parents=True, exist_ok=True)
        request_path = requests_dir / f"{device_id}.json"
        if request_path.exists():
            return
        payload = {
            "device_id": device_id,
            "alias": socket.gethostname(),
            "requested_at": _utc_now_iso(),
            "notes": "",
        }
        request_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError:
        logger.info("No se pudo escribir solicitud de activacion")


def _parse_payload(raw: str) -> Optional[bool]:
    text = (raw or "").strip()
    if not text:
        return None
    if text[:1] in "{[\"":
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = None
        if data is not None:
            return _parse_json_payload(data)
    return _to_bool(text)


def _parse_json_payload(data: Any) -> Optional[bool]:
    if isinstance(data, dict):
        for key in ("active", "enabled", "approved", "status", "state"):
            if key in data:
                return _to_bool(data.get(key))
        nested = data.get("license")
        if isinstance(nested, dict) and "status" in nested:
            return _to_bool(nested.get("status"))
        return None
    if isinstance(data, (bool, int, float, str)):
        return _to_bool(data)
    return None


def _read_cache(device_id: str) -> Optional[dict[str, str]]:
    path = user_data_path(_CACHE_FILENAME)
    try:
        if not path.is_file():
            return None
        cached = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if cached.get("device_id") and cached.get("device_id") != device_id:
        return None
    if cached.get("status") not in {"active", "inactive"}:
        return None
    return cached


def _write_cache(device_id: str, active: bool, source: str, detail: str) -> None:
    payload = {
        "device_id": device_id,
        "status": _status_label(active),
        "checked_at": _utc_now_iso(),
        "source": source,
        "detail": detail,
    }
    path = user_data_path(_CACHE_FILENAME)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError:
        logger.info("No se pudo escribir cache de activacion")


def _status_label(active: bool) -> str:
    return "active" if active else "inactive"


def _to_bool(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if not text:
        return None
    if text in _YES_VALUES:
        return True
    if text in _NO_VALUES:
        return False
    return None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _apply_template(template: str, device_id: str) -> str:
    if "{device_id}" in template:
        return template.replace("{device_id}", device_id)
    return template


def _get_str(data: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _get_float(value: Any, *, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
