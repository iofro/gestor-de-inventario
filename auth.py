import os
import json
import sqlite3
import time
from typing import Optional, Tuple

import requests

DEFAULT_AUTH_URL = "https://apifacturatest.mh.gob.sv/auth"
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config_negocio.json")
DB_PATH = os.path.join(os.path.dirname(__file__), "inventario.db")

_access_token: Optional[str] = None
_expires_at: float = 0.0
_obtained_at: float = 0.0


def _read_db_credentials() -> Tuple[Optional[str], Optional[str]]:
    """Intenta obtener NIT y contraseña desde la tabla 'tokens'."""
    nit = pwd = None
    try:
        conn = sqlite3.connect(DB_PATH)
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
        conn.close()
    except Exception:
        pass
    return nit, pwd


def _read_config_credentials() -> Tuple[Optional[str], Optional[str]]:
    """Lee NIT y contraseña de ``config_negocio.json``."""
    nit = pwd = None
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        nit = (
            data.get("nit")
            or data.get("NIT")
            or data.get("api_nit")
            or data.get("api", {}).get("nit")
            or data.get("dte_api", {}).get("nit")
        )
        pwd = (
            data.get("api_pwd")
            or data.get("api_password")
            or data.get("clave")
            or data.get("api", {}).get("pwd")
            or data.get("dte_api", {}).get("pwd")
        )
    except Exception:
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
        url = env_conf.get("auth_url")
        return url or DEFAULT_AUTH_URL
    except Exception:
        return DEFAULT_AUTH_URL


def _request_new_token(nit: str, pwd: str) -> Tuple[str, int, float]:
    """Solicita un nuevo token de acceso a la API."""
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {"user": nit, "pwd": pwd}
    url = _get_auth_url()
    resp = requests.post(url, data=data, headers=headers, timeout=20)
    resp.raise_for_status()
    info = resp.json()
    token = info.get("access_token")
    expires_in = int(info.get("expires_in", 0))
    obtained_at = time.time()
    return token, expires_in, obtained_at


def _save_token(token: str, expires_in: int, obtained_at: float) -> None:
    """Guarda el token y metadatos en la tabla 'tokens' si es posible."""
    try:
        conn = sqlite3.connect(DB_PATH)
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
        conn.close()
    except Exception:
        pass


def get_token(refresh: bool = False) -> str:
    """Devuelve un token válido reutilizándolo y renovándolo al expirar."""
    global _access_token, _expires_at, _obtained_at
    now = time.time()
    if (
        not refresh
        and _access_token
        and now < _expires_at - 60
    ):
        return _access_token

    nit, pwd = _get_credentials()
    token, expires_in, obtained_at = _request_new_token(nit, pwd)
    _access_token = token
    _obtained_at = obtained_at
    _expires_at = obtained_at + expires_in
    _save_token(token, expires_in, obtained_at)
    return token
