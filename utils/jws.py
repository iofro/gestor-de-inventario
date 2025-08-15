import os
import json
import base64
import requests
import logging

logger = logging.getLogger(__name__)
CONFIG_NEGOCIO_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config_negocio.json")
DEFAULT_SIGN_URL = "http://127.0.0.1:8080/firma/firmardocumento/"
SIGN_TIMEOUT = 10

# Directory where the signing service expects certificate files (.crt)
CERT_UPLOAD_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "svfe-api-firmador", "uploads"
)


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


def _ensure_cert_file(nit: str) -> None:
    """Verify that the certificate file for ``nit`` exists and is readable."""
    cert_path = os.path.join(CERT_UPLOAD_DIR, f"{nit}.crt")
    if not os.path.isfile(cert_path) or not os.access(cert_path, os.R_OK):
        raise RuntimeError(f"Certificado no accesible: {cert_path}")


def sign_json(
    payload: dict,
    nit: str | None = None,
    passwordPri: str | None = None,
    activo: bool = True,
    url: str | None = None,
) -> str:
    """Sign ``payload`` using the external ``svfe-api-firmador`` service."""
    if nit is None or passwordPri is None:
        nit, passwordPri, activo = _load_config()
    if not nit:
        raise RuntimeError("NIT del certificado no configurado")
    _ensure_cert_file(nit)
    url = url or _get_sign_url()
    ident = payload.get("identificacion", {})
    version = ident.get("version")
    tipo_dte = ident.get("tipoDte")
    body = {
        "nit": nit,
        "activo": activo,
        "passwordPri": passwordPri,
        "dteJson": payload,
    }
    if version is not None:
        body["version"] = version
    if tipo_dte is not None:
        body["tipoDte"] = tipo_dte
    try:
        response = requests.post(url, json=body, timeout=SIGN_TIMEOUT)
        status_code = getattr(response, "status_code", "N/A")
        resp_text = getattr(response, "text", "")
        print(status_code)
        print(resp_text)
        if isinstance(status_code, int) and status_code >= 400:
            logger.error("Respuesta del firmador %s: %s", status_code, resp_text)
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
) -> str:
    """Sign ``payload`` and store the JWS next to ``json_path``."""
    token = sign_json(payload, nit, passwordPri, activo, url)
    jws_path = os.path.splitext(json_path)[0] + ".jws"
    with open(jws_path, "w", encoding="utf-8") as fh:
        fh.write(token)
    return jws_path
