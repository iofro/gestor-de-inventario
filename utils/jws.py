import os
import json
import base64
import time
import subprocess
from cryptography.hazmat.primitives.serialization import (
    pkcs12,
    Encoding,
    PrivateFormat,
    NoEncryption,
    load_pem_private_key,
    PublicFormat,
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


def _get_ambiente() -> str:
    """Return configured DTE environment or ``"pruebas"`` by default."""
    if os.path.exists(CONFIG_NEGOCIO_PATH):
        try:
            with open(CONFIG_NEGOCIO_PATH, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data.get("ambiente", "pruebas").lower()
        except Exception:
            pass
    if os.path.exists(DATOS_NEGOCIO_PATH):
        try:
            with open(DATOS_NEGOCIO_PATH, "r", encoding="utf-8") as fh:
                datos = json.load(fh)
            return datos.get("dte_api", {}).get("ambiente", "pruebas").lower()
        except Exception:
            pass
    return "pruebas"


def get_cert_config(path: str = CONFIG_NEGOCIO_PATH):
    """Return certificate (.crt), key (.key) and password from config."""
    ambiente = _get_ambiente()
    verificar = ambiente == "produccion"
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            ambiente = data.get("ambiente", "pruebas")
            fe = data.get(ambiente, {}).get("firma_electronica", {})
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
                if verificar:
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
                if verificar:
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
                if verificar:
                    _load_p12_key(cert_path, password)
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


def sign_jwt(payload: dict, key_pem: bytes, cert_der: bytes | None = None) -> str:
    """Sign ``payload`` using RS512 and return a JWT."""
    header = {"alg": "RS512", "typ": "JWT"}
    if cert_der:
        header["x5c"] = [base64.b64encode(cert_der).decode()]
    return jwt.encode(payload, key_pem, algorithm="RS512", headers=header)


def sign_with_container(payload: dict, p12_path: str, password: str | None = None) -> str:
    """Sign ``payload`` using external ``svfe-api-firmador`` container.

    The container should read data from STDIN and output the signed token to
    STDOUT. ``password`` is passed as an optional argument.
    """
    cmd = ["svfe-api-firmador", p12_path]
    if password:
        cmd.append(password)
    proc = subprocess.run(
        cmd,
        input=json.dumps(payload).encode(),
        capture_output=True,
        check=True,
    )
    return proc.stdout.decode().strip()


def sign_json(
    payload: dict,
    cert_path: str | None = None,
    password: str | None = None,
    key_path: str | None = None,
) -> str:
    """Return a JWS token (compact serialization) for ``payload``."""
    if cert_path and isinstance(cert_path, str) and cert_path.lower().endswith(".p12") and not key_path:
        try:
            return sign_with_container(payload, cert_path, password)
        except (FileNotFoundError, subprocess.CalledProcessError):
            # fallback to local signing
            key = _load_p12_key(cert_path, password)
            with open(cert_path, "rb") as fh:
                cert_data = fh.read()
            _k, cert_obj, _ = pkcs12.load_key_and_certificates(
                cert_data, password.encode() if password else None
            )
            cert_bytes = cert_obj.public_bytes(Encoding.DER) if cert_obj else None
            pem = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
            return sign_jwt(payload, pem, cert_bytes)

    if key_path:
        if isinstance(key_path, bytes):
            key_bytes = key_path
        else:
            with open(key_path, "rb") as fh:
                key_bytes = fh.read()
        key = load_pem_private_key(key_bytes, password.encode() if password else None)
        cert_bytes = None
        if cert_path and os.path.exists(cert_path):
            with open(cert_path, "rb") as fh:
                cert_data = fh.read()
            if b"-----BEGIN" in cert_data:
                cert = x509.load_pem_x509_certificate(cert_data)
            else:
                _k, cert, _ = pkcs12.load_key_and_certificates(cert_data, password.encode() if password else None)
            cert_bytes = cert.public_bytes(Encoding.DER)
    elif cert_path:
        if isinstance(cert_path, bytes):
            key = _load_p12_key_bytes(cert_path, password)
            _k, cert, _ = pkcs12.load_key_and_certificates(cert_path, password.encode() if password else None)
            cert_bytes = cert.public_bytes(Encoding.DER) if cert else None
        else:
            key = _load_p12_key(cert_path, password)
            with open(cert_path, "rb") as fh:
                cert_data = fh.read()
            if b"-----BEGIN" in cert_data:
                cert_obj = x509.load_pem_x509_certificate(cert_data)
            else:
                _k, cert_obj, _ = pkcs12.load_key_and_certificates(cert_data, password.encode() if password else None)
            cert_bytes = cert_obj.public_bytes(Encoding.DER)
    else:
        raise ValueError("Missing certificate information")

    pem = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
    return sign_jwt(payload, pem, cert_bytes)


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


def create_auth_jwt(
    subject: str,
    cert_path: str | None = None,
    password: str | None = None,
    key_path: str | None = None,
) -> str:
    """Return a short-lived JWT for API authentication."""
    payload = {
        "sub": subject,
        "iat": int(time.time()),
        "exp": int(time.time()) + 300,
    }
    return sign_json(payload, cert_path, password, key_path)


def verify_jws(token: str, cert_path: str) -> dict:
    """Verify ``token`` using a public certificate located at ``cert_path``."""
    with open(cert_path, "rb") as fh:
        cert_data = fh.read()
    try:
        cert = x509.load_pem_x509_certificate(cert_data)
        public_pem = cert.public_key().public_bytes(
            Encoding.PEM, PublicFormat.SubjectPublicKeyInfo
        )
    except ValueError:
        public_pem = cert_data
    return jwt.decode(token, public_pem, algorithms=["RS512"])
