import os
import json
import base64
import os
import json
from cryptography.hazmat.primitives.serialization import (
    pkcs12,
    Encoding,
    PrivateFormat,
    NoEncryption,
    load_pem_private_key,
)
from cryptography import x509
try:
    import jwt
except ModuleNotFoundError as exc:  # pragma: no cover - helpful runtime message
    raise ModuleNotFoundError(
        "PyJWT is required to sign DTE payloads. Install it with `pip install pyjwt`."
    ) from exc

DATOS_NEGOCIO_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "datos_negocio.json")
CONFIG_NEGOCIO_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config_negocio.json")


def get_cert_config(path: str = CONFIG_NEGOCIO_PATH):
    """Return certificate (.crt), key (.key) and password from config."""
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            fe = data.get("firma_electronica", {})
            cert = fe.get("certificado")
            key = fe.get("clave_privada")
            cert_data_b64 = fe.get("certificado_data")
            key_data_b64 = fe.get("clave_privada_data")
            password = fe.get("frase_acceso")
            if password:
                try:
                    password = base64.b64decode(password).decode("utf-8")
                except Exception:
                    pass
            if cert and os.path.exists(cert) and key and os.path.exists(key):
                with open(cert, "rb") as fh:
                    x509.load_pem_x509_certificate(fh.read())
                with open(key, "rb") as fh:
                    key_bytes = fh.read()
                if b"-----BEGIN" not in key_bytes:
                    raise ValueError("La clave privada no parece ser PEM")
                load_pem_private_key(key_bytes, password.encode() if password else None)
                return cert, key, password
            if cert_data_b64 and key_data_b64:
                cert_bytes = base64.b64decode(cert_data_b64)
                key_bytes = base64.b64decode(key_data_b64)
                x509.load_pem_x509_certificate(cert_bytes)
                if b"-----BEGIN" not in key_bytes:
                    raise ValueError("La clave privada no parece ser PEM")
                load_pem_private_key(key_bytes, password.encode() if password else None)
                return cert_bytes, key_bytes, password
        except Exception:
            return None, None, None

    if os.path.exists(DATOS_NEGOCIO_PATH):
        try:
            with open(DATOS_NEGOCIO_PATH, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            cert_path = data.get("certificado_digital_path")
            password = data.get("certificado_digital_password")
            if password:
                try:
                    password = base64.b64decode(password).decode("utf-8")
                except Exception:
                    pass
            if cert_path and os.path.exists(cert_path):
                return cert_path, None, password
        except Exception:
            return None, None, None

    return None, None, None


def _load_p12_key(cert_path: str, password: str | None):
    with open(cert_path, "rb") as fh:
        data = fh.read()
    key, _cert, _ = pkcs12.load_key_and_certificates(data, password.encode() if password else None)
    return key


def _load_p12_key_bytes(data: bytes, password: str | None):
    key, _cert, _ = pkcs12.load_key_and_certificates(data, password.encode() if password else None)
    return key


def sign_json(
    payload: dict,
    cert_path: str | None = None,
    password: str | None = None,
    key_path: str | None = None,
) -> str:
    """Return a JWS token (compact serialization) for ``payload``."""
    if key_path:
        if isinstance(key_path, bytes):
            key_bytes = key_path
        else:
            with open(key_path, "rb") as fh:
                key_bytes = fh.read()
        key = load_pem_private_key(key_bytes, password.encode() if password else None)
    elif cert_path:
        if isinstance(cert_path, bytes):
            key = _load_p12_key_bytes(cert_path, password)
        else:
            key = _load_p12_key(cert_path, password)
    else:
        raise ValueError("Missing certificate information")
    pem = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
    token = jwt.encode(payload, pem, algorithm="RS256")
    return token


def sign_and_save(
    payload: dict,
    json_path: str,
    cert_path: str | None = None,
    password: str | None = None,
    key_path: str | None = None,
) -> str:
    """Sign ``payload`` and store the JWS next to ``json_path``."""
    token = sign_json(payload, cert_path, password, key_path)
    jws_path = os.path.splitext(json_path)[0] + "_signed.jws"
    with open(jws_path, "w", encoding="utf-8") as fh:
        fh.write(token)
    return jws_path
