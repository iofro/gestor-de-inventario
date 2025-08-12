import os
import json
import base64
import requests

CONFIG_NEGOCIO_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config_negocio.json")
DEFAULT_SIGN_URL = "http://127.0.0.1:8080/firma/firmardocumento/"


def _load_config(path: str = CONFIG_NEGOCIO_PATH):
    """Return signer configuration: NIT, password and active flag."""
    nit = password = None
    activo = True
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            ambiente = data.get("ambiente", "pruebas")
            fe = data.get(ambiente, {}).get("firma_electronica", {})
            nit = fe.get("nit")
            password = fe.get("passwordPri")
            if password:
                try:
                    password = base64.b64decode(password).decode()
                except Exception:
                    pass
            activo = fe.get("activo", True)
        except Exception:
            pass
    return nit, password, activo


def sign_json(payload: dict, nit: str | None = None, passwordPri: str | None = None, activo: bool = True, url: str = DEFAULT_SIGN_URL) -> str:
    """Sign ``payload`` using the external ``svfe-api-firmador`` service."""
    if nit is None or passwordPri is None:
        nit, passwordPri, activo = _load_config()
    body = {"nit": nit, "activo": activo, "passwordPri": passwordPri, "dteJson": payload}
    response = requests.post(url, json=body, timeout=30)
    response.raise_for_status()
    data = response.json()
    if isinstance(data, dict):
        if data.get("status") == "OK":
            return data.get("body")
        raise RuntimeError(str(data.get("body")))
    return data


def sign_and_save(payload: dict, json_path: str, nit: str | None = None, passwordPri: str | None = None, activo: bool = True, url: str = DEFAULT_SIGN_URL) -> str:
    """Sign ``payload`` and store the JWS next to ``json_path``."""
    token = sign_json(payload, nit, passwordPri, activo, url)
    jws_path = os.path.splitext(json_path)[0] + ".jws"
    with open(jws_path, "w", encoding="utf-8") as fh:
        fh.write(token)
    return jws_path
