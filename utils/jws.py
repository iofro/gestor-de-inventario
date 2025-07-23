import os
import json
import base64
from cryptography.hazmat.primitives.serialization import (
    pkcs12,
    Encoding,
    PrivateFormat,
    NoEncryption,
)
import jwt

DATOS_NEGOCIO_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "datos_negocio.json")


def get_cert_config(path: str = DATOS_NEGOCIO_PATH):
    """Return certificate path and password from business config."""
    if not os.path.exists(path):
        return None, None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        cert_path = data.get("certificado_digital_path")
        password = data.get("certificado_digital_password")
        if password:
            try:
                password = base64.b64decode(password).decode("utf-8")
            except Exception:
                pass
        return cert_path, password
    except Exception:
        return None, None


def _load_private_key(cert_path: str, password: str | None):
    with open(cert_path, "rb") as fh:
        data = fh.read()
    key, _cert, _ = pkcs12.load_key_and_certificates(data, password.encode() if password else None)
    return key


def sign_json(payload: dict, cert_path: str, password: str | None = None) -> str:
    """Return a JWS token (compact serialization) for ``payload``."""
    key = _load_private_key(cert_path, password)
    pem = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
    token = jwt.encode(payload, pem, algorithm="RS256")
    return token


def sign_and_save(payload: dict, json_path: str, cert_path: str, password: str | None = None) -> str:
    """Sign ``payload`` and store the JWS next to ``json_path``."""
    token = sign_json(payload, cert_path, password)
    jws_path = os.path.splitext(json_path)[0] + "_signed.jws"
    with open(jws_path, "w", encoding="utf-8") as fh:
        fh.write(token)
    return jws_path
