import os
import json
import base64
import requests
import logging
from pathlib import Path

from utils.stable_json import (
    stable_stringify,
    save_file,
    assert_same_payload,
    validar_montos,
)
from paths import CONFIG_NEGOCIO_PATH as _CONFIG_NEGOCIO_PATH

logger = logging.getLogger(__name__)
CONFIG_NEGOCIO_PATH = str(Path(_CONFIG_NEGOCIO_PATH))
DEFAULT_SIGN_URL = "http://127.0.0.1:8080/firma/firmardocumento/"
SIGN_TIMEOUT = float(os.getenv("SIGN_TIMEOUT", "10"))

SEND_DTEJSON_AS_OBJECT = os.getenv("SEND_DTEJSON_AS_OBJECT", "1") == "1"

# Directory where the signing service expects certificate files (.crt)
# Allow overriding via environment variable and strip any hidden characters.
_DEFAULT_CERT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "svfe-api-firmador", "uploads"
)
CERT_UPLOAD_DIR = os.getenv("CERT_UPLOAD_DIR", _DEFAULT_CERT_DIR).strip()


def set_cert_upload_dir(path: str) -> None:
    """Override global certificate directory to ``path``.

    The provided path is converted to an absolute path and stripped of
    whitespace so that subsequent signing operations read the certificate
    from the same location where it was copied after an upload.
    """
    global CERT_UPLOAD_DIR
    CERT_UPLOAD_DIR = os.path.abspath(path).strip()


def _get_sign_url(path: str = CONFIG_NEGOCIO_PATH) -> str:
    """Return signer service URL from ``SIGN_URL`` env, config or default."""
    url = os.getenv("SIGN_URL")
    if not url and os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            url = data.get("sign_url")
        except Exception:
            pass
    return url or DEFAULT_SIGN_URL


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
            if isinstance(nit, str):
                nit = nit.strip()
            password = fe.get("passwordPri")
            if password:
                try:
                    password = base64.b64decode(password).decode().strip()
                except Exception:
                    password = password.strip()
            activo = fe.get("activo", True)
        except Exception:
            pass
    return nit, password, activo


def _ensure_cert_file(nit: str) -> None:
    """Verify that the certificate file for ``nit`` exists and is readable."""
    nit = nit.strip()
    cert_dir = os.path.abspath(CERT_UPLOAD_DIR.strip())
    cert_path = os.path.join(cert_dir, f"{nit}.crt")
    if not (os.path.isfile(cert_path) and os.access(cert_path, os.R_OK)):
        raise RuntimeError(f"Certificado no accesible: {cert_path}")


def sign_json(
    payload: dict | str,
    nit: str | None = None,
    passwordPri: str | None = None,
    activo: bool = True,
    url: str | None = None,
    version: str | None = None,
    tipo_dte: str | None = None,
) -> str:
    """Sign ``payload`` using the external ``svfe-api-firmador`` service."""
    if nit is None or passwordPri is None:
        nit, passwordPri, activo = _load_config()
    if not nit:
        raise RuntimeError("NIT del certificado no configurado")
    _ensure_cert_file(nit)
    url = url or _get_sign_url()

    if isinstance(payload, str):
        payload_str = payload
        try:
            payload_obj = json.loads(payload_str)
        except Exception as exc:
            raise ValueError("payload_str no es JSON válido") from exc
    else:
        payload_obj = payload
        payload_str = stable_stringify(payload_obj)

    if (version is None or tipo_dte is None) and isinstance(payload_obj, dict):
        ident = payload_obj.get("identificacion", {})
        if version is None:
            version = ident.get("version")
        if tipo_dte is None:
            tipo_dte = ident.get("tipoDte")

    dte_json = json.loads(payload_str) if SEND_DTEJSON_AS_OBJECT else payload_str
    body = {
        "nit": nit,
        "activo": activo,
        "passwordPri": passwordPri,
        "dteJson": dte_json,
    }
    if version is not None:
        body["version"] = version
    if tipo_dte is not None:
        body["tipoDte"] = tipo_dte

    try:
        response = requests.post(url, json=body, timeout=SIGN_TIMEOUT)
        status_code = getattr(response, "status_code", "N/A")
        resp_text = getattr(response, "text", "")
        if isinstance(status_code, int) and status_code >= 400:
            logger.error("Respuesta del firmador %s", status_code)
        else:
            logger.debug("Respuesta del firmador %s: %s", status_code, resp_text)
        response.raise_for_status()
    except requests.Timeout as exc:
        raise RuntimeError("Tiempo de espera agotado al firmar") from exc
    except requests.HTTPError as exc:
        status = exc.response.status_code
        raise RuntimeError(f"Error HTTP {status} al firmar: {exc.response.text}") from exc
    except requests.RequestException as exc:
        raise RuntimeError(f"Error al firmar: {exc}") from exc

    data = response.json()
    if isinstance(data, dict):
        if data.get("status") == "OK":
            return data.get("body")
        raise RuntimeError(str(data.get("body")))
    return data


def sign_and_save(
    payload: dict,
    json_path: str,
    nit: str | None = None,
    passwordPri: str | None = None,
    activo: bool = True,
    url: str | None = None,
    return_token: bool = False,
):
    """Sign ``payload`` and store only the JSON representation.

    The previous implementation also persisted the JWS token to disk.  To
    comply with the new requirement of keeping only the original JSON and
    the final state, the JWS token is now generated in memory and returned
    to the caller when needed but **no** ``.jws`` file is written.

    When ``return_token`` is ``True`` the function returns a tuple
    ``(json_path, token)``; otherwise only ``json_path`` is returned.
    """
    json_pretty = stable_stringify(payload, indent=2)
    payload_compact = stable_stringify(payload)
    save_file(json_path, json_pretty)
    if os.getenv("STABLE_JSON_CHECK") == "1":
        validar_montos(payload)
        assert_same_payload(payload)
    ident = payload.get("identificacion", {})
    version = ident.get("version")
    tipo_dte = ident.get("tipoDte")
    try:
        token = sign_json(
            payload_compact,
            nit,
            passwordPri,
            activo,
            url,
            version=version,
            tipo_dte=tipo_dte,
        )
    except TypeError:
        # Allows tests to patch ``sign_json`` with a simplified signature
        token = sign_json(payload)
    token = token.rstrip("\n")
    if return_token:
        return json_path, token
    return json_path
