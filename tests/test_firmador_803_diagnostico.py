import base64
import hashlib
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

import pytest
import requests

import paths
from utils import jws
from utils.certificates import dump_certificate_diagnosis


@dataclass(frozen=True)
class Scenario:
    name: str
    title: str
    nit_input: str
    cert_filename: str
    cert_nit: str
    cert_password_plain: str
    password_input: str
    response_payload: Dict[str, Any]
    expect_803: bool
    expected_error: str | None
    primary_cause: str | None
    recommendation: str | None
    password_encoding: str | None = None
    extra_cert_files: List[str] | None = None
    signer_dir_mismatch: bool = False
    nit_display: str | None = None


def _sha512_hex(text: str) -> str:
    return hashlib.sha512(text.encode("utf-8")).hexdigest()


def _write_test_certificate(path: Path, nit: str, password_plain: str) -> None:
    xml = (
        "<CertificadoMH>"
        f"<nit>{nit}</nit>"
        "<privateKey><clave>"
        f"{_sha512_hex(password_plain)}"
        "</clave></privateKey>"
        "</CertificadoMH>"
    )
    path.write_text(xml, encoding="utf-8")


class _FakeResponse:
    def __init__(self, payload: Dict[str, Any], status_code: int = 200):
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload)

    def json(self) -> Dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            error = requests.HTTPError(response=self)
            error.response = self
            raise error


SUCCESS_RESPONSE = {"status": "OK", "body": "TOKEN"}
ERROR_803 = {
    "status": "ERROR",
    "body": {
        "codigo": "803",
        "mensaje": "No existe llave publica para este nit",
    },
}


SCENARIOS = [
    Scenario(
        name="ok_password",
        title="OK / contraseña correcta",
        nit_input="09061712791014",
        cert_filename="09061712791014.crt",
        cert_nit="09061712791014",
        cert_password_plain="clave-correcta",
        password_input="clave-correcta",
        response_payload=SUCCESS_RESPONSE,
        expect_803=False,
        expected_error=None,
        primary_cause=None,
        recommendation="El entorno básico funciona: no se detectaron errores.",
    ),
    Scenario(
        name="wrong_password",
        title="Contraseña incorrecta",
        nit_input="09061712791014",
        cert_filename="09061712791014.crt",
        cert_nit="09061712791014",
        cert_password_plain="clave-correcta",
        password_input="clave-incorrecta",
        response_payload=ERROR_803,
        expect_803=True,
        expected_error="sha512_mismatch",
        primary_cause="sha512_mismatch",
        recommendation="Actualizar la contraseña para que coincida con el hash SHA-512 dentro del CRT.",
    ),
    Scenario(
        name="password_base64",
        title="Contraseña almacenada en base64 sin decodificar",
        nit_input="09061712791014",
        cert_filename="09061712791014.crt",
        cert_nit="09061712791014",
        cert_password_plain="clave-correcta",
        password_input=base64.b64encode(b"clave-correcta").decode("ascii"),
        response_payload=ERROR_803,
        expect_803=True,
        expected_error="sha512_mismatch",
        primary_cause="password_encoding_base64",
        recommendation="Decodificar la contraseña base64 antes de calcular el hash SHA-512.",
        password_encoding="base64",
    ),
    Scenario(
        name="cert_dir_mismatch",
        title="Desincronización de directorios (CERT_UPLOAD_DIR)",
        nit_input="09061712791014",
        cert_filename="09061712791014.crt",
        cert_nit="09061712791014",
        cert_password_plain="clave-correcta",
        password_input="clave-correcta",
        response_payload=ERROR_803,
        expect_803=True,
        expected_error="dir_mismatch",
        primary_cause="cert_dir_mismatch",
        recommendation="Alinear CERT_UPLOAD_DIR y FIRMADOR_CERT_DIR para que ambos usen el mismo directorio.",
        signer_dir_mismatch=True,
    ),
    Scenario(
        name="multiple_crts",
        title="Múltiples CRT para el mismo NIT",
        nit_input="09061712791014",
        cert_filename="09061712791014.crt",
        cert_nit="09061712791014",
        cert_password_plain="clave-correcta",
        password_input="clave-correcta",
        response_payload=ERROR_803,
        expect_803=True,
        expected_error="multiple_crts",
        primary_cause="multiple_crts",
        recommendation="Dejar un único archivo .crt por NIT y remover duplicados/renombrados.",
        extra_cert_files=["09061712791014(1).crt"],
    ),
    Scenario(
        name="nit_mismatch",
        title="NIT mal normalizado",
        nit_input="0906-171279-101-5",
        cert_filename="09061712791015.crt",
        cert_nit="09061712791014",
        cert_password_plain="clave-correcta",
        password_input="clave-correcta",
        response_payload=ERROR_803,
        expect_803=True,
        expected_error="nit_mismatch",
        primary_cause="nit_mismatch",
        recommendation="Corregir el NIT configurado o regenerar el certificado para que coincidan.",
        nit_display="0906-171279-101-5",
    ),
]


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda sc: sc.name)
def test_firmador_803_diagnostico(
    scenario: Scenario,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    artifacts_dir: Path,
    record_cert_diag,
) -> None:
    cert_dir = tmp_path / "certs"
    cert_dir.mkdir()

    user_data_dir = tmp_path / "user_data"
    monkeypatch.setattr(paths, "USER_DATA_DIR", user_data_dir)
    monkeypatch.setattr(paths, "CERT_UPLOAD_DIR", str(cert_dir))
    monkeypatch.setenv("CERT_UPLOAD_DIR", str(cert_dir))
    monkeypatch.setattr(jws, "CERT_UPLOAD_DIR", str(cert_dir))

    monkeypatch.delenv("FIRMADOR_CERT_DIR", raising=False)
    if scenario.signer_dir_mismatch:
        signer_dir = tmp_path / "signer_dir"
        signer_dir.mkdir()
        monkeypatch.setenv("FIRMADOR_CERT_DIR", str(signer_dir))
    else:
        monkeypatch.setenv("FIRMADOR_CERT_DIR", str(cert_dir))

    cert_path = cert_dir / scenario.cert_filename
    _write_test_certificate(cert_path, scenario.cert_nit, scenario.cert_password_plain)

    if scenario.extra_cert_files:
        for extra_name in scenario.extra_cert_files:
            extra_path = cert_dir / extra_name
            _write_test_certificate(extra_path, scenario.cert_nit, scenario.cert_password_plain)

    normalised_map: Dict[str, Path] = {}

    for crt in cert_dir.glob("*.crt"):
        stem_digits = "".join(ch for ch in crt.stem if ch.isdigit())
        if stem_digits:
            normalised_map[stem_digits] = crt

    def _normalised_ensure(nit_value: str) -> None:
        digits = "".join(ch for ch in str(nit_value) if ch.isdigit())
        target = normalised_map.get(digits, cert_dir / f"{digits}.crt")
        if not digits or not target.exists():
            raise RuntimeError(f"Certificado no accesible: {target}")

    monkeypatch.setattr(jws, "_ensure_cert_file", _normalised_ensure)

    sent_payload: Dict[str, Any] = {}

    def fake_post(url: str, json: Dict[str, Any], timeout: float | None = None):  # type: ignore[override]
        sent_payload.update({
            "url": url,
            "json": json,
            "timeout": timeout,
        })
        return _FakeResponse(scenario.response_payload)

    monkeypatch.setattr(jws.requests, "post", fake_post)

    caplog.set_level(logging.INFO)

    payload = {
        "identificacion": {
            "version": "1",
            "tipoDte": "01",
        },
        "dummy": True,
    }

    firmador_803 = False
    error_message = None
    nit_for_request = scenario.nit_input
    try:
        jws.sign_json(
            payload,
            nit=nit_for_request,
            passwordPri=scenario.password_input,
            activo=True,
            url="http://firmador.test",
        )
    except RuntimeError as exc:
        error_message = str(exc)
        if scenario.expect_803:
            assert "803" in error_message
            firmador_803 = True
            assert any(
                "firmador_code=803" in record.getMessage()
                for record in caplog.records
                if record.name == "utils.jws"
            )
        else:
            raise
    else:
        assert not scenario.expect_803, "Se esperaba 803 pero la firma fue exitosa"

    diag_json_path = dump_certificate_diagnosis(artifacts_dir / f"{scenario.name}.json")
    diag_payload = json.loads(diag_json_path.read_text(encoding="utf-8"))

    sha512_match = (
        diag_payload.get("password_sha512")
        and diag_payload.get("password_sha512") == diag_payload.get("cert_password_sha512")
    )
    sha512_match = bool(sha512_match)
    cert_path_ok = bool(diag_payload.get("cert_exists") and diag_payload.get("cert_path"))
    cert_dir_mismatch = diag_payload.get("cert_dir") != diag_payload.get("signer_cert_dir")
    multiple_crts = diag_payload.get("multiple_crts") or []

    if scenario.expect_803:
        assert firmador_803, "El firmador no devolvió 803"
        assert scenario.expected_error in diag_payload.get("errors", [])
    else:
        assert not firmador_803
        assert sha512_match
        assert cert_path_ok
        assert diag_payload.get("errors") == []

    password_encoding_detected = None
    if scenario.password_encoding == "base64":
        decoded = base64.b64decode(scenario.password_input.encode("ascii")).decode("utf-8")
        assert decoded == scenario.cert_password_plain
        password_encoding_detected = "base64"

    nit_display = scenario.nit_display or scenario.nit_input
    cert_path_value = diag_payload.get("cert_path")
    nit_filename = Path(cert_path_value).name if cert_path_value else None

    analysis = {
        "scenario": scenario.name,
        "title": scenario.title,
        "result": "PASS",
        "firmador_803": firmador_803,
        "error_message": error_message,
        "sha512_match": sha512_match,
        "cert_path_ok": cert_path_ok,
        "cert_dir_effective": diag_payload.get("cert_dir"),
        "signer_cert_dir": diag_payload.get("signer_cert_dir"),
        "env_CERT_UPLOAD_DIR": os.getenv("CERT_UPLOAD_DIR"),
        "password_sha512": diag_payload.get("password_sha512"),
        "cert_password_sha512": diag_payload.get("cert_password_sha512"),
        "password_encoding_detected": password_encoding_detected,
        "cert_dir_mismatch": cert_dir_mismatch,
        "multiple_crts": multiple_crts,
        "nit_payload": nit_display,
        "nit_filename": nit_filename,
        "nit_from_crt": diag_payload.get("nit_crt"),
        "diagnosis_errors": diag_payload.get("errors", []),
        "diagnosis_json": str(diag_json_path),
        "sha256_of_file": diag_payload.get("cert_sha256"),
        "log_records": [
            {
                "logger": rec.name,
                "level": rec.levelname,
                "message": rec.getMessage(),
            }
            for rec in caplog.records
            if rec.name.startswith("utils.jws") or rec.name.startswith("utils.certificates")
        ],
        "request_payload": sent_payload,
        "primary_cause": scenario.primary_cause,
        "recommendation": scenario.recommendation,
    }

    if scenario.expect_803 and scenario.password_encoding != "base64":
        assert analysis["password_encoding_detected"] is None

    if scenario.primary_cause == "password_encoding_base64":
        assert password_encoding_detected == "base64"

    if scenario.primary_cause == "cert_dir_mismatch":
        assert cert_dir_mismatch

    if scenario.primary_cause == "multiple_crts":
        assert len(multiple_crts) > 1

    if scenario.primary_cause == "nit_mismatch":
        assert diag_payload.get("nit_crt") != "".join(ch for ch in scenario.nit_input if ch.isdigit())

    record_cert_diag(analysis)
