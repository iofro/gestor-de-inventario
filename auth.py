import os
import json
import sqlite3
import time
import base64
import logging
from typing import Optional, Tuple
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

DEFAULT_AUTH_URL = "https://apitest.dtes.mh.gob.sv/seguridad/auth"
# URL de producción proporcionada por el MH
PRODUCTION_AUTH_URL = "https://api.dtes.mh.gob.sv/seguridad/auth"
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config_negocio.json")
DB_PATH = os.path.join(os.path.dirname(__file__), "inventario.db")

_access_token: Optional[str] = None
_expires_at: float = 0.0
_obtained_at: float = 0.0
_token_type: str = ""
# Longitud del último token obtenido
_token_len: int = 0
# Credenciales actualmente asociadas al token en caché
_current_user: Optional[str] = None
_current_pwd: Optional[str] = None
_last_auth_url: Optional[str] = None
_last_auth_host: Optional[str] = None


def _read_db_credentials() -> Tuple[Optional[str], Optional[str]]:
    """Intenta obtener NIT y contraseña desde la tabla 'tokens'."""
    nit = pwd = None
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='tokens'"
            )
            if cur.fetchone():
                cur.execute("SELECT value FROM tokens WHERE key='nit'")
                row = cur.fetchone()
                nit = row[0] if row else None
                cur.execute("SELECT value FROM tokens WHERE key='pwd'")
                row = cur.fetchone()
                pwd = row[0] if row else None
    except sqlite3.Error:
        pass
    return nit, pwd


def _read_config_credentials() -> Tuple[Optional[str], Optional[str]]:
    """Lee NIT y contraseña de ``config_negocio.json``."""
    nit = pwd = None
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)

        ambiente = data.get("ambiente", "pruebas")
        env_conf = data.get(ambiente, {})
        firma_conf = env_conf.get("firma_electronica", {})
        auth_conf = env_conf.get("auth", {})

        nit = (
            auth_conf.get("nitUsuario")
            or auth_conf.get("nit")
            or auth_conf.get("user")
            or auth_conf.get("usuario")
            or env_conf.get("api_nit")
            or env_conf.get("api_user")
            or env_conf.get("api_usuario")
            or env_conf.get("nit")
            or env_conf.get("NIT")
            or env_conf.get("user")
            or env_conf.get("usuario")
            or env_conf.get("api", {}).get("nit")
            or env_conf.get("api", {}).get("user")
            or env_conf.get("dte_api", {}).get("nit")
            or env_conf.get("dte_api", {}).get("user")
            or firma_conf.get("nit")
            or firma_conf.get("NIT")
            or firma_conf.get("user")
            or firma_conf.get("usuario")
            or data.get("nit")
            or data.get("NIT")
            or data.get("user")
            or data.get("usuario")
            or data.get("api_nit")
            or data.get("api_user")
            or data.get("api_usuario")
            or data.get("api", {}).get("nit")
            or data.get("api", {}).get("user")
            or data.get("dte_api", {}).get("nit")
            or data.get("dte_api", {}).get("user")
        )
        pwd = (
            auth_conf.get("pwd")
            or auth_conf.get("password")
            or env_conf.get("api_pwd")
            or env_conf.get("api_password")
            or env_conf.get("clave")
            or env_conf.get("api", {}).get("pwd")
            or env_conf.get("dte_api", {}).get("pwd")
            or firma_conf.get("pwd")
            or firma_conf.get("password")
            or firma_conf.get("passwordPri")
            or data.get("api_pwd")
            or data.get("api_password")
            or data.get("clave")
            or data.get("api", {}).get("pwd")
            or data.get("dte_api", {}).get("pwd")
        )
        if pwd:
            try:
                pwd = base64.b64decode(pwd).decode()
            except Exception:
                pass
    except (OSError, json.JSONDecodeError):
        pass
    return nit, pwd


def _get_config_nit_and_url() -> Tuple[Optional[str], Optional[str]]:
    """Obtiene ``nitUsuario`` y ``auth_url`` de ``config_negocio.json``."""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        ambiente = data.get("ambiente", "pruebas")
        env_conf = data.get(ambiente, {})
        auth_conf = env_conf.get("auth", {})
        nit = auth_conf.get("nitUsuario")
        url = env_conf.get("auth_url") or data.get("auth_url")
        if url:
            url = url.strip()
        return nit, url
    except (OSError, json.JSONDecodeError):
        return None, None


def _get_credentials() -> Tuple[str, str]:
    """Obtiene NIT y contraseña de base de datos o de archivo de configuración."""
    nit, pwd = _read_db_credentials()
    if not nit or not pwd:
        nit2, pwd2 = _read_config_credentials()
        nit = nit or nit2
        pwd = pwd or pwd2
    if not nit or not pwd:
        raise RuntimeError("Credenciales de API no configuradas")
    return nit, pwd


def _get_auth_url() -> str:
    """Obtiene la URL de autenticación según el ambiente configurado."""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        ambiente = data.get("ambiente", "pruebas")
        env_conf = data.get(ambiente, {})
        url = env_conf.get("auth_url") or data.get("auth_url")
        if url:
            url = url.strip()
        return url or DEFAULT_AUTH_URL
    except (OSError, json.JSONDecodeError):
        return DEFAULT_AUTH_URL


def _mask_token(token: str) -> str:
    """Devuelve una versión parcialmente enmascarada del JWT."""
    if len(token) <= 24:
        return token
    return f"{token[:12]}{'*' * (len(token) - 24)}{token[-12:]}"


def _extract_exp(token: str) -> Optional[int]:
    """Extrae el reclamo ``exp`` del JWT si está disponible."""
    try:
        payload_part = token.split(".")[1]
        padding = "=" * (-len(payload_part) % 4)
        payload_bytes = base64.urlsafe_b64decode(payload_part + padding)
        payload = json.loads(payload_bytes.decode())
        exp = payload.get("exp")
        if isinstance(exp, (int, float)):
            return int(exp)
    except Exception:
        pass
    return None


def _log_token(token: str, had_prefix: bool) -> None:
    """Registra información del token sin exponerlo por completo."""
    token_len = len(token)
    prefix_msg = "con" if had_prefix else "sin"
    base_msg = f"Token {prefix_msg} prefijo Bearer; len={token_len}"
    if token_len < 100:
        logger.warning("Token sospechoso (%s); patrón=%s", base_msg, _mask_token(token))
    elif logger.isEnabledFor(logging.DEBUG):
        logger.debug("%s; patrón=%s", base_msg, _mask_token(token))
    else:
        logger.info(base_msg)


def _check_and_update_token_len(token: str) -> int:
    """Actualiza la longitud almacenada del JWT."""
    global _token_len
    token_len = len(token)
    if _token_len and token_len != _token_len:
        logger.warning(
            "La longitud del token difiere de la previamente almacenada: %s vs %s",
            token_len,
            _token_len,
        )
    _token_len = token_len
    return token_len


def _request_new_token(nit: str, pwd: str, url: Optional[str] = None) -> Tuple[str, int, str]:
    """Solicita un nuevo token de acceso a la API."""
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {"user": nit, "pwd": pwd}
    url = url or _get_auth_url()
    global _last_auth_url, _last_auth_host
    _last_auth_url = url
    _last_auth_host = urlparse(url).netloc
    try:
        resp = requests.post(url, data=data, headers=headers, timeout=20)
        status_code = getattr(resp, "status_code", "N/A")
        resp_text = getattr(resp, "text", "")
        try:
            data_logged = json.loads(resp_text)
            token_field = data_logged.get("body", {}).get("token")
            if isinstance(token_field, str):
                had_prefix = token_field.startswith("Bearer ")
                token_clean = token_field[7:] if had_prefix else token_field
                data_logged["body"]["token"] = _mask_token(token_clean)
                resp_text = json.dumps(data_logged)
        except Exception:
            pass
        if isinstance(status_code, int) and status_code >= 400:
            logger.error("Respuesta de Hacienda %s: %s", status_code, resp_text)
        else:
            logger.debug("Respuesta de Hacienda %s: %s", status_code, resp_text)
        resp.raise_for_status()
        info = resp.json()
        body = info.get("body", {}) if isinstance(info, dict) else {}
        raw_token = body.get("token") if info.get("status") == "OK" else None
        had_prefix = False
        token = None
        if raw_token and isinstance(raw_token, str):
            had_prefix = raw_token.startswith("Bearer ")
            token = raw_token[7:] if had_prefix else raw_token
            _log_token(token, had_prefix)
        token_type = body.get("tokenType", "") if body else ""
        expires_in = int(body.get("expiresIn", 0)) if body else 0
        if not token:
            response_text = resp.text
            raise ValueError(
                f"Respuesta de autenticación sin token: {response_text[:200]}"
            )
        if token_type.lower() == "bearer":
            token_type = "Bearer"
        return token, expires_in, token_type
    except Exception as exc:
        report = f"Error de autenticación al solicitar token en {url}: {exc}"
        if isinstance(exc, requests.HTTPError) and exc.response is not None:
            try:
                data_logged = json.loads(exc.response.text)
                token_field = data_logged.get("body", {}).get("token")
                if isinstance(token_field, str):
                    had_prefix = token_field.startswith("Bearer ")
                    token_clean = token_field[7:] if had_prefix else token_field
                    data_logged["body"]["token"] = _mask_token(token_clean)
                    report += f"\nRespuesta: {json.dumps(data_logged)[:200]}"
                else:
                    report += f"\nRespuesta: {exc.response.text[:200]}"
            except Exception:
                report += f"\nRespuesta: {exc.response.text[:200]}"
        logger.error(report)
        raise


def _save_token(
    token: str,
    expires_in: int,
    obtained_at: float,
    token_len: int,
    exp: Optional[int] = None,
) -> None:
    """Guarda el token y metadatos en la tabla 'tokens' si es posible."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute(
                "CREATE TABLE IF NOT EXISTS tokens (key TEXT PRIMARY KEY, value TEXT)"
            )
            cur.execute(
                "INSERT OR REPLACE INTO tokens(key, value) VALUES('access_token', ?)",
                (token,),
            )
            cur.execute(
                "INSERT OR REPLACE INTO tokens(key, value) VALUES('expires_in', ?)",
                (str(expires_in),),
            )
            cur.execute(
                "INSERT OR REPLACE INTO tokens(key, value) VALUES('obtained_at', ?)",
                (str(obtained_at),),
            )
            cur.execute(
                "INSERT OR REPLACE INTO tokens(key, value) VALUES('token_len', ?)",
                (str(token_len),),
            )
            if exp:
                cur.execute(
                    "INSERT OR REPLACE INTO tokens(key, value) VALUES('exp', ?)",
                    (str(exp),),
                )
            conn.commit()
        try:
            os.chmod(DB_PATH, 0o600)
        except OSError:
            pass
    except sqlite3.Error:
        pass


def delete_token() -> None:
    """Elimina el token almacenado y limpia la caché."""
    global _access_token, _expires_at, _obtained_at, _token_type, _token_len
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute(
                "DELETE FROM tokens WHERE key IN ('access_token', 'expires_in', 'obtained_at', 'token_len', 'exp')"
            )
            conn.commit()
    except sqlite3.Error:
        pass
    _access_token = None
    _token_type = ""
    _expires_at = 0.0
    _obtained_at = 0.0
    _token_len = 0


def get_token(
    refresh: bool = False,
    nit: Optional[str] = None,
    pwd: Optional[str] = None,
) -> str:
    """Devuelve un token válido. Puede recibir credenciales explícitas."""
    global _access_token, _expires_at, _obtained_at, _token_type, _current_user, _current_pwd

    if nit is not None and pwd is not None:
        if nit != _current_user or pwd != _current_pwd:
            refresh = True
            _access_token = None
            _expires_at = 0.0
            _current_user, _current_pwd = nit, pwd
    else:
        nit, pwd = _get_credentials()
        if nit != _current_user or pwd != _current_pwd:
            _current_user, _current_pwd = nit, pwd

    now = time.time()
    if _expires_at and _obtained_at:
        # Renovación anticipada ~10-15 minutos antes de expirar
        # (vigencia típica 24h producción / 48h pruebas)
        margin = min(900, max(60, (_expires_at - _obtained_at) / 10))
    else:
        margin = 60
    if not refresh and _access_token and now < _expires_at - margin:
        _check_and_update_token_len(_access_token)
        return _access_token

    url = _get_auth_url()
    global _last_auth_url, _last_auth_host
    _last_auth_url = url
    _last_auth_host = urlparse(url).netloc
    conf_nit, conf_url = _get_config_nit_and_url()
    if conf_nit and nit != conf_nit:
        raise ValueError(
            f"NIT utilizado {nit} difiere del configurado {conf_nit}"
        )
    if conf_url and url != conf_url:
        raise ValueError(
            f"URL de auth {url} difiere de la configurada {conf_url}"
        )
    logger.info("Reautenticando con NIT %s y URL %s", nit, url)
    try:
        token, expires_in, token_type = _request_new_token(nit, pwd, url)
    except Exception as exc:
        print(f"No se pudo obtener token: {exc}")
        raise
    token_len = _check_and_update_token_len(token)
    obtained_at = time.time()
    token_exp = _extract_exp(token)
    _access_token = token
    _token_type = token_type
    _obtained_at = obtained_at
    _expires_at = token_exp if token_exp else obtained_at + expires_in
    _save_token(token, expires_in, obtained_at, token_len, token_exp)
    return token


def get_last_auth_host() -> Optional[str]:
    """Devuelve el host utilizado en la última autenticación."""
    if _last_auth_host:
        return _last_auth_host
    url = _get_auth_url()
    return urlparse(url).netloc
