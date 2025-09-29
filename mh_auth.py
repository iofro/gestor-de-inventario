import base64
import hashlib
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

import requests

from paths import CONFIG_NEGOCIO_PATH, DATOS_NEGOCIO_PATH
from utils.env import env_flag

log = logging.getLogger(__name__)


_TOKEN_CACHE: dict[str, str | None] = {}
_AUTO_TOKEN_CACHE: dict[str, str] = {}
_WARMUP_DONE: set[str] = set()


def _normalize_environment(ambiente: str | None) -> str:
    if ambiente is None:
        return "apitest"
    text = str(ambiente).strip().lower()
    if not text:
        return "apitest"
    if text in {"00", "0", "apitest", "pruebas", "test"}:
        return "apitest"
    if text in {"01", "1", "prod", "produccion", "producción", "production"}:
        return "produccion"
    if "prue" in text or "test" in text:
        return "apitest"
    if text.startswith("pro"):
        return "produccion"
    return "apitest"


def _read_negocio_json():
    with open(DATOS_NEGOCIO_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _read_config_json() -> dict[str, Any]:
    try:
        with open(CONFIG_NEGOCIO_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return {}
    except Exception as exc:  # pragma: no cover - logged for observability
        log.warning("AUTH: no se pudo leer config_negocio.json: %s", exc)
        return {}
    return data if isinstance(data, dict) else {}


_ENV_KEY_ALIASES = {
    "apitest": ["apitest", "pruebas", "00", "0", "test"],
    "produccion": ["produccion", "01", "1", "prod", "production"],
}


def _resolve_env_config(env: str, config: dict[str, Any]) -> dict[str, Any]:
    candidates = _ENV_KEY_ALIASES.get(env, [])
    for key in candidates:
        value = config.get(key)
        if isinstance(value, dict):
            return value
    ambiente_raw = config.get("ambiente")
    normalized = _normalize_environment(ambiente_raw) if ambiente_raw else None
    if normalized and normalized != env:
        for key in _ENV_KEY_ALIASES.get(normalized, []):
            value = config.get(key)
            if isinstance(value, dict):
                return value
    return {}


def _decode_secret(raw: Any) -> str:
    if not isinstance(raw, str):
        return ""
    text = raw.strip()
    if not text:
        return ""
    try:
        decoded = base64.b64decode(text.encode("utf-8"), validate=True)
        return decoded.decode("utf-8")
    except Exception:
        return text


def _fingerprint(token: str | None) -> str:
    if not token:
        return "MISSING"
    return hashlib.sha1(token.encode("utf-8")).hexdigest()[:10]


def _normalize_bearer_value(token_raw: Any) -> str:
    from dte import _normalize_bearer as _dte_normalize_bearer  # Lazy import

    return _dte_normalize_bearer(str(token_raw or ""))


def _to_timestamp(raw: Any) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        if text.isdigit():
            try:
                return float(text)
            except Exception:
                return None
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except Exception:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    return None


def _token_ttl_seconds(token: str | None) -> float | None:
    if not token:
        return None
    claims = decode_jwt_claims(token)
    if not claims:
        return None
    exp_ts = _to_timestamp(claims.get("exp"))
    if exp_ts is None:
        return None
    return exp_ts - time.time()


def _resolve_auth_params(env: str) -> tuple[str, str, str]:
    config = _read_config_json()
    env_conf = _resolve_env_config(env, config) if isinstance(config, dict) else {}
    if not isinstance(env_conf, dict):
        env_conf = {}
    auth_conf = env_conf.get("auth") if isinstance(env_conf, dict) else None
    if not isinstance(auth_conf, dict):
        auth_conf = {}
    top_auth = config.get("auth") if isinstance(config, dict) else None
    if not isinstance(top_auth, dict):
        top_auth = {}

    def _first_non_empty(values: list[Any]) -> str:
        for value in values:
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    user = _first_non_empty(
        [
            auth_conf.get("nitUsuario"),
            auth_conf.get("user"),
            auth_conf.get("nit"),
            env_conf.get("api_user") if isinstance(env_conf, dict) else None,
            top_auth.get("nitUsuario"),
            top_auth.get("user"),
            top_auth.get("nit"),
            config.get("api_user") if isinstance(config, dict) else None,
        ]
    )

    pwd = _first_non_empty(
        [
            auth_conf.get("pwd"),
            auth_conf.get("password"),
            env_conf.get("api_pwd") if isinstance(env_conf, dict) else None,
            top_auth.get("pwd"),
            top_auth.get("password"),
            config.get("api_pwd") if isinstance(config, dict) else None,
        ]
    )

    user = _decode_secret(user)
    pwd = _decode_secret(pwd)

    auth_url = None
    if isinstance(env_conf, dict):
        auth_url = env_conf.get("auth_url") or env_conf.get("authUrl")
    if not auth_url and isinstance(config, dict):
        auth_url = config.get("auth_url") or config.get("authUrl")
    if isinstance(auth_url, str):
        auth_url = auth_url.strip()
    if not auth_url:
        try:
            datos = _read_negocio_json()
        except Exception:
            datos = {}
        if isinstance(datos, dict):
            dte_api = datos.get("dte_api")
            if isinstance(dte_api, dict):
                base_url = dte_api.get("url") or dte_api.get("endpoint")
                if isinstance(base_url, str):
                    base = base_url.strip().rstrip("/")
                    if base:
                        auth_url = f"{base}/seguridad/auth"
    if not auth_url:
        raise RuntimeError("URL de autenticación no configurada para Hacienda")
    if not user or not pwd:
        raise RuntimeError("Credenciales API no configuradas para Hacienda")
    return auth_url, user, pwd


def _load_tokens_from_file() -> dict[str, str]:
    try:
        data = _read_negocio_json()
    except FileNotFoundError:
        return {}
    except Exception as exc:  # pragma: no cover - logged for observability
        log.warning("No se pudo leer token manual de datos_negocio.json: %s", exc)
        return {}

    if not isinstance(data, dict):
        return {}

    dte_api = data.get("dte_api")
    if not isinstance(dte_api, dict):
        return {}

    tokens: dict[str, str] = {}
    for field, env in (
        ("token_pruebas", "apitest"),
        ("token_produccion", "produccion"),
    ):
        raw = dte_api.get(field)
        if isinstance(raw, str) and raw:
            tokens[env] = raw

    return tokens


def invalidate_token_cache() -> None:
    _TOKEN_CACHE.clear()
    _AUTO_TOKEN_CACHE.clear()
    _WARMUP_DONE.clear()


def get_manual_token(ambiente: str | None = None) -> str | None:
    env = _normalize_environment(ambiente)
    if env in _TOKEN_CACHE:
        return _TOKEN_CACHE[env]

    tokens = _load_tokens_from_file()
    for env_key, raw in tokens.items():
        _TOKEN_CACHE[env_key] = raw

    if env not in _TOKEN_CACHE:
        _TOKEN_CACHE[env] = None

    return _TOKEN_CACHE[env]


def acquire_token(ambiente: str) -> str:
    env = _normalize_environment(ambiente)
    url, user, pwd = _resolve_auth_params(env)
    try:
        resp = requests.post(url, data={"user": user, "pwd": pwd}, timeout=20)
    except Exception as exc:  # pragma: no cover - network failure
        raise RuntimeError("No se pudo conectar con el servicio de autenticación") from exc

    status_code = getattr(resp, "status_code", None)
    if isinstance(status_code, int) and status_code >= 400:
        log.warning("AUTH: respuesta HTTP %s al solicitar token", status_code)
    try:
        resp.raise_for_status()
    except Exception as exc:  # pragma: no cover - bubbled for observabilidad
        raise RuntimeError("La autenticación con Hacienda fue rechazada") from exc

    try:
        payload = resp.json()
    except Exception as exc:
        raise RuntimeError("Respuesta de autenticación no es JSON válido") from exc

    if isinstance(payload, dict):
        status = payload.get("status")
        if status and str(status).upper() not in {"OK", "200"}:
            message = payload.get("message") or payload.get("error") or payload.get("detalle")
            if message:
                raise RuntimeError(f"Autenticación rechazada ({status}): {message}")
            raise RuntimeError(f"Autenticación rechazada ({status})")
        body = payload.get("body") if isinstance(payload.get("body"), dict) else None
        if isinstance(body, dict):
            token_raw = body.get("token") or body.get("access_token")
            token_type = body.get("tokenType") or body.get("token_type")
        else:
            token_raw = payload.get("token") or payload.get("access_token")
            token_type = payload.get("tokenType") or payload.get("token_type")
    else:
        token_raw = None
        token_type = None

    if not token_raw and isinstance(payload, dict):
        body = payload.get("body")
        if isinstance(body, dict):
            token_raw = body.get("token") or body.get("access_token")
            token_type = body.get("tokenType") or body.get("token_type")

    if not token_raw:
        raise RuntimeError("Respuesta de autenticación sin token válido")

    if isinstance(token_type, str) and token_type.lower() == "bearer" and isinstance(token_raw, str):
        token_raw = f"Bearer {token_raw}"

    normalized = _normalize_bearer_value(token_raw)
    ttl = _token_ttl_seconds(normalized)
    log.info("AUTH: acquired token env=%s fp=%s ttl_s=%s", env, _fingerprint(normalized), int(ttl) if ttl is not None else None)
    return normalized


def _is_token_valid(token: str | None, threshold: int) -> bool:
    if not token:
        return False
    ttl = _token_ttl_seconds(token)
    if ttl is None:
        return False
    return ttl > threshold


def ensure_valid_bearer(
    ambiente: str,
    current: str | None,
    *,
    min_ttl_s: int = 300,
    force: bool = False,
) -> str:
    env = _normalize_environment(ambiente)
    try:
        threshold = max(0, int(min_ttl_s))
    except Exception:
        try:
            threshold = max(0, int(float(min_ttl_s)))
        except Exception:
            threshold = 300

    normalized_current = None
    if current is not None:
        try:
            normalized_current = _normalize_bearer_value(current)
        except Exception:
            normalized_current = None

    cached = _AUTO_TOKEN_CACHE.get(env)

    if not force and _is_token_valid(normalized_current, threshold):
        _AUTO_TOKEN_CACHE[env] = normalized_current  # type: ignore[arg-type]
        _TOKEN_CACHE[env] = normalized_current
        return normalized_current  # type: ignore[return-value]

    if not force and cached and _is_token_valid(cached, threshold):
        return cached

    try:
        refreshed = acquire_token(env)
    except Exception as exc:
        fallback = normalized_current or cached
        if fallback:
            log.warning("AUTH: no se pudo renovar token env=%s, se reutiliza fp=%s (%s)", env, _fingerprint(fallback), exc)
            _AUTO_TOKEN_CACHE[env] = fallback
            _TOKEN_CACHE[env] = fallback
            return fallback
        raise

    normalized = _normalize_bearer_value(refreshed)
    _AUTO_TOKEN_CACHE[env] = normalized
    _TOKEN_CACHE[env] = normalized
    return normalized


def auth_headers(extra: dict | None = None, *, ambiente: str | None = None) -> dict:
    env = _normalize_environment(ambiente)
    manual_token = get_manual_token(env)
    cached = _AUTO_TOKEN_CACHE.get(env)
    current = manual_token or cached

    raw_min_ttl = os.getenv("DTE_TOKEN_MIN_TTL_S", "300")
    try:
        min_ttl = max(0, int(raw_min_ttl))
    except Exception:
        try:
            min_ttl = max(0, int(float(raw_min_ttl)))
        except Exception:
            min_ttl = 300

    warmup_enabled = env_flag("DTE_AUTH_WARMUP", default=True)
    needs_warmup = warmup_enabled and env not in _WARMUP_DONE
    initial_normalized = _normalize_bearer_value(current) if current else None

    try:
        token = ensure_valid_bearer(env, current, min_ttl_s=min_ttl, force=needs_warmup)
    except Exception as exc:
        if manual_token:
            raise
        raise RuntimeError(
            "Token manual no configurado. Use 'Obtener token' en Configuración de Facturación Electrónica."
        ) from exc

    if needs_warmup:
        _WARMUP_DONE.add(env)
        if token != initial_normalized:
            log.info("AUTH: warmup reauth (fp=%s)", _fingerprint(token))

    headers = {"Authorization": token}
    if extra:
        headers.update(extra)

    _TOKEN_CACHE[env] = token
    _AUTO_TOKEN_CACHE[env] = token
    log.info("AUTH: ready token (amb=%s fp=%s)", env, _fingerprint(token))
    return headers


def decode_jwt_claims(auth_header: str | None) -> dict:
    """Extrae claims seguros del JWT contenido en ``auth_header``.

    La firma no se valida: el objetivo es inspeccionar rápidamente el contenido
    del payload para propósitos de diagnóstico. Nunca se devuelve ni se registra
    el token completo.
    """

    if not isinstance(auth_header, str):
        return {}

    token = auth_header.strip()
    if not token:
        return {}

    if token.lower().startswith("bearer "):
        token = token[7:].strip()

    parts = token.split(".")
    if len(parts) < 2:
        return {}

    payload_b64 = parts[1]
    padding = "=" * (-len(payload_b64) % 4)
    try:
        payload_bytes = base64.urlsafe_b64decode((payload_b64 + padding).encode("ascii"))
    except Exception:
        return {}

    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except Exception:
        return {}

    if not isinstance(payload, dict):
        return {}

    claims: dict = {}
    for key in ("sub", "iat", "exp", "roles"):
        if key in payload:
            claims[key] = payload[key]
    return claims
