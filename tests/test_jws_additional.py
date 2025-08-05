import datetime
import pytest
import jwt
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives.serialization import load_pem_private_key
import utils.jws as jws


def create_keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "t")]))
        .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "t")]))
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.utcnow())
        .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    )
    return key_pem, cert_pem


def test_verify_jws_invalid_signature(tmp_path):
    key1, _ = create_keypair()
    _, cert2 = create_keypair()
    token = jws.sign_jwt({"a": 1}, key1)
    cert_path = tmp_path / "cert.pem"
    cert_path.write_bytes(cert2)
    with pytest.raises(jwt.exceptions.InvalidSignatureError):
        jws.verify_jws(token, str(cert_path))


def test_expired_token(tmp_path):
    key_pem, _ = create_keypair()
    payload = {"sub": "s", "iat": 0, "exp": 1}
    token = jws.sign_jwt(payload, key_pem)
    priv = load_pem_private_key(key_pem, password=None)
    public_pem = priv.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    with pytest.raises(jwt.ExpiredSignatureError):
        jwt.decode(token, public_pem, algorithms=["RS512"])


def test_invalid_algorithm(tmp_path):
    key_pem, _ = create_keypair()
    token = jws.sign_jwt({"a": 1}, key_pem)
    priv = load_pem_private_key(key_pem, password=None)
    public_pem = priv.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    with pytest.raises(jwt.InvalidAlgorithmError):
        jwt.decode(token, public_pem, algorithms=["HS256"])


def test_sign_json_missing_p12(tmp_path):
    missing = tmp_path / "missing.p12"
    with pytest.raises(FileNotFoundError):
        jws.sign_json({}, cert_path=str(missing), password=None, key_path=None)


def test_sign_json_missing_cert(tmp_path):
    with pytest.raises(ValueError):
        jws.sign_json({}, None, None, None)
