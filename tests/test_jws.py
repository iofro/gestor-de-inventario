import json
import base64
from utils import jws
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography import x509
from cryptography.x509.oid import NameOID
import datetime
import jwt


def create_p12(path, password):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "SV"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Test"),
        x509.NameAttribute(NameOID.COMMON_NAME, "Test Cert"),
    ])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.utcnow())
        .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    p12 = pkcs12.serialize_key_and_certificates(
        b"test",
        key,
        cert,
        None,
        serialization.BestAvailableEncryption(password.encode()),
    )
    with open(path, "wb") as fh:
        fh.write(p12)


def create_key_cert(key_path, cert_path, password):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    enc = serialization.BestAvailableEncryption(password.encode()) if password else serialization.NoEncryption()
    with open(key_path, "wb") as fh:
        fh.write(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                enc,
            )
        )
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "SV"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Test"),
        x509.NameAttribute(NameOID.COMMON_NAME, "Test Cert"),
    ])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.utcnow())
        .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    with open(cert_path, "wb") as fh:
        fh.write(cert.public_bytes(serialization.Encoding.PEM))


def test_sign_and_save_pem(tmp_path, monkeypatch):
    key_path = tmp_path / "key.pem"
    cert_path = tmp_path / "cert.crt"
    password = "pass"
    create_key_cert(key_path, cert_path, password)

    cfg_path = tmp_path / "config.json"
    with open(cfg_path, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "firma_electronica": {
                    "certificado": str(cert_path),
                    "clave_privada": str(key_path),
                    "frase_acceso": base64.b64encode(password.encode()).decode(),
                }
            },
            fh,
        )

    monkeypatch.setattr(jws, "CONFIG_NEGOCIO_PATH", str(cfg_path))

    payload = {"foo": "bar"}
    json_file = tmp_path / "dte.json"
    with open(json_file, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)

    cert, key, phrase = jws.get_cert_config(str(cfg_path))
    jws_path = jws.sign_and_save(payload, str(json_file), cert, phrase, key)
    token = open(jws_path).read()

    cert_obj = x509.load_pem_x509_certificate(open(cert_path, "rb").read())
    public_pem = cert_obj.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    data = jwt.decode(token, public_pem, algorithms=["RS256"])
    assert data == payload


def test_sign_and_save_p12(tmp_path, monkeypatch):
    cert_file = tmp_path / "cert.p12"
    password = "secret"
    create_p12(cert_file, password)

    datos_path = tmp_path / "datos.json"
    with open(datos_path, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "certificado_digital_path": str(cert_file),
                "certificado_digital_password": base64.b64encode(password.encode()).decode(),
            },
            fh,
        )

    monkeypatch.setattr(jws, "CONFIG_NEGOCIO_PATH", str(tmp_path / "missing.json"))
    monkeypatch.setattr(jws, "DATOS_NEGOCIO_PATH", str(datos_path))

    payload = {"foo": "bar"}
    json_file = tmp_path / "dte.json"
    with open(json_file, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)

    cert_path, key_path, cert_pass = jws.get_cert_config(str(tmp_path / "missing.json"))
    jws_path = jws.sign_and_save(payload, str(json_file), cert_path, cert_pass, key_path)
    assert jws_path
    token = open(jws_path).read()
    # verify
    _priv_key, cert, _ = pkcs12.load_key_and_certificates(open(cert_file, "rb").read(), password.encode())
    public_pem = cert.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    data = jwt.decode(token, public_pem, algorithms=["RS256"])
    assert data == payload


def test_get_cert_config_embedded(tmp_path, monkeypatch):
    key_path = tmp_path / "key.pem"
    cert_path = tmp_path / "cert.crt"
    password = "abc"
    create_key_cert(key_path, cert_path, password)
    key_data = key_path.read_bytes()
    cert_data = cert_path.read_bytes()

    cfg_path = tmp_path / "config.json"
    with open(cfg_path, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "firma_electronica": {
                    "certificado": "",
                    "clave_privada": "",
                    "frase_acceso": base64.b64encode(password.encode()).decode(),
                    "certificado_data": base64.b64encode(cert_data).decode(),
                    "clave_privada_data": base64.b64encode(key_data).decode(),
                }
            },
            fh,
        )

    monkeypatch.setattr(jws, "CONFIG_NEGOCIO_PATH", str(cfg_path))

    payload = {"foo": "bar"}
    json_file = tmp_path / "dte.json"
    with open(json_file, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)

    cert, key, phrase = jws.get_cert_config(str(cfg_path))
    jws_path = jws.sign_and_save(payload, str(json_file), cert, phrase, key)
    token = open(jws_path).read()

    cert_obj = x509.load_pem_x509_certificate(cert_data)
    public_pem = cert_obj.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    data = jwt.decode(token, public_pem, algorithms=["RS256"])
    assert data == payload
