import os
import json
import sqlite3
import time
from typing import Optional, Tuple

import requests

DEFAULT_AUTH_URL = "https://apitest.dtes.mh.gob.sv/seguridad/auth"
# URL de producción proporcionada por el MH
PRODUCTION_AUTH_URL = "https://api.dtes.mh.gob.sv/seguridad/auth"
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config_negocio.json")
DB_PATH = os.path.join(os.path.dirname(__file__), "inventario.db")

_access_token: Optional[str] = None
_expires_at: float = 0.0
_obtained_at: float = 0.0
_token_type: str = ""


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

        nit = (
            firma_conf.get("nit")
            or firma_conf.get("NIT")
            or env_conf.get("nit")
            or env_conf.get("NIT")
            or env_conf.get("api_nit")
            or env_conf.get("api", {}).get("nit")
            or env_conf.get("dte_api", {}).get("nit")
            or data.get("nit")
            or data.get("NIT")
            or data.get("api_nit")
            or data.get("api", {}).get("nit")
            or data.get("dte_api", {}).get("nit")
        )
        pwd = (
            firma_conf.get("pwd")
            or firma_conf.get("password")
            or firma_conf.get("passwordPri")
            or env_conf.get("api_pwd")
            or env_conf.get("api_password")
            or env_conf.get("clave")
            or env_conf.get("api", {}).get("pwd")
            or env_conf.get("dte_api", {}).get("pwd")
            or data.get("api_pwd")
            or data.get("api_password")
            or data.get("clave")
            or data.get("api", {}).get("pwd")
            or data.get("dte_api", {}).get("pwd")
        )
    except (OSError, json.JSONDecodeError):
        pass
    return nit, pwd


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
        return url or DEFAULT_AUTH_URL
    except (OSError, json.JSONDecodeError):
        return DEFAULT_AUTH_URL


def _request_new_token(nit: str, pwd: str) -> Tuple[str, int, str]:
    """Solicita un nuevo token de acceso a la API."""
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {"user": nit, "pwd": pwd}
    url = _get_auth_url()
    try:
        resp = requests.post(url, data=data, headers=headers, timeout=20)
        resp.raise_for_status()
        info = resp.json()
        body = info.get("body", {}) if isinstance(info, dict) else {}
        token = body.get("token") if info.get("status") == "OK" else None
        token_type = body.get("tokenType", "") if body else ""
        expires_in = int(body.get("expiresIn", 0)) if body else 0
        if not token:
            response_text = resp.text
            raise ValueError(
                f"Respuesta de autenticación sin token: {response_text[:200]}"
            )
        if token_type.lower() == "bearer":
            token_type = "Bearer"
            token = f"{token_type} {token}"
        return token, expires_in, token_type
    except Exception as exc:
        report = f"Error de autenticación al solicitar token en {url}: {exc}"
        if isinstance(exc, requests.HTTPError) and exc.response is not None:
            report += f"\nRespuesta: {exc.response.text[:200]}"
        print(report)
        raise


def _save_token(token: str, expires_in: int, obtained_at: float) -> None:
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
            conn.commit()
    except sqlite3.Error:
        pass


def get_token(refresh: bool = False) -> str:
    """Devuelve un token válido reutilizándolo y renovándolo al expirar."""
    global _access_token, _expires_at, _obtained_at, _token_type
    now = time.time()
    if (
        not refresh
        and _access_token
        and now < _expires_at - 60
    ):
        return _access_token

    nit, pwd = _get_credentials()
    try:
        token, expires_in, token_type = _request_new_token(nit, pwd)
    except Exception as exc:
        print(f"No se pudo obtener token: {exc}")
        raise
    obtained_at = time.time()
    _access_token = token
    _token_type = token_type
    _obtained_at = obtained_at
    _expires_at = obtained_at + expires_in
    _save_token(token, expires_in, obtained_at)
    return token
