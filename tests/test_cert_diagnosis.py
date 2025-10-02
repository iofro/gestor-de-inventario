import hashlib
import json
from pathlib import Path

import pytest

from utils.certificates import verify_certificate_setup, dump_certificate_diagnosis


def _write_certificate(path: Path, nit: str, password: str) -> None:
    sha512 = hashlib.sha512(password.encode("utf-8")).hexdigest()
    xml = (
        "<CertificadoMH>"
        f"<nit>{nit}</nit>"
        "<privateKey><clave>"
        f"{sha512}"
        "</clave></privateKey>"
        "</CertificadoMH>"
    )
    path.write_text(xml, encoding="utf-8")


def _load_diagnosis(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_missing_file(tmp_path: Path) -> None:
    diagnosis = verify_certificate_setup("00012345678901", "secret", cert_dir=tmp_path)
    assert "missing_file" in diagnosis.errors
    diag_path = dump_certificate_diagnosis(tmp_path / "diag")
    payload = _load_diagnosis(diag_path)
    assert payload["cert_exists"] is False
    assert "missing_file" in payload["errors"]


def test_nit_mismatch(tmp_path: Path) -> None:
    cert_path = tmp_path / "00012345678901.crt"
    _write_certificate(cert_path, "99999999999999", "secret")
    diagnosis = verify_certificate_setup("00012345678901", "secret", cert_dir=tmp_path)
    assert "nit_mismatch" in diagnosis.errors
    diag_path = dump_certificate_diagnosis(tmp_path / "diag_nit")
    payload = _load_diagnosis(diag_path)
    assert payload["nit_crt"] == "99999999999999"
    assert "nit_mismatch" in payload["errors"]


def test_sha512_mismatch(tmp_path: Path) -> None:
    cert_path = tmp_path / "00012345678901.crt"
    _write_certificate(cert_path, "00012345678901", "correct")
    diagnosis = verify_certificate_setup("00012345678901", "wrong", cert_dir=tmp_path)
    assert "sha512_mismatch" in diagnosis.errors
    diag_path = dump_certificate_diagnosis(tmp_path / "diag_sha")
    payload = _load_diagnosis(diag_path)
    assert payload["cert_password_sha512"] == hashlib.sha512("correct".encode("utf-8")).hexdigest()
    assert "sha512_mismatch" in payload["errors"]


def test_multiple_crts(tmp_path: Path) -> None:
    main_cert = tmp_path / "00012345678901.crt"
    _write_certificate(main_cert, "00012345678901", "secret")
    other_cert = tmp_path / "00000000000000.crt"
    _write_certificate(other_cert, "00000000000000", "secret")
    diagnosis = verify_certificate_setup("00012345678901", "secret", cert_dir=tmp_path)
    assert "multiple_crts" in diagnosis.errors
    diag_path = dump_certificate_diagnosis(tmp_path / "diag_multi")
    payload = _load_diagnosis(diag_path)
    assert len(payload["multiple_crts"]) == 2
    assert "multiple_crts" in payload["errors"]
    assert payload["cert_path"].endswith("00012345678901.crt")


def test_dir_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cert_path = tmp_path / "00012345678901.crt"
    _write_certificate(cert_path, "00012345678901", "secret")
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    monkeypatch.setenv("FIRMADOR_CERT_DIR", str(other_dir))
    diagnosis = verify_certificate_setup("00012345678901", "secret", cert_dir=tmp_path)
    assert "dir_mismatch" in diagnosis.errors
    diag_path = dump_certificate_diagnosis(tmp_path / "diag_dir")
    payload = _load_diagnosis(diag_path)
    assert payload["signer_cert_dir"].endswith("other")
    assert "dir_mismatch" in payload["errors"]
