"""Utilities for validating signing certificates and generating diagnostics."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path

from paths import CERT_UPLOAD_DIR as _DEFAULT_CERT_DIR

logger = logging.getLogger(__name__)

_CERT_EXT = ".crt"
_LAST_DIAGNOSIS: dict | None = None


@dataclass(slots=True)
class CertificateDiagnosis:
    """Structured information about the certificate environment."""

    cert_dir: str
    cert_dir_source: str
    default_cert_dir: str
    signer_cert_dir: str
    nit_config: str | None
    nit_crt: str | None
    cert_path: str | None
    cert_exists: bool
    cert_size: int | None
    cert_sha256: str | None
    password_sha512: str | None
    cert_password_sha512: str | None
    multiple_crts: list[str] = field(default_factory=list)
    parse_error: str | None = None
    errors: list[str] = field(default_factory=list)
    ok: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


def _normalise_nit(nit: str | None) -> str | None:
    if not nit:
        return None
    digits = "".join(ch for ch in str(nit) if ch.isdigit())
    if not digits:
        return None
    if len(digits) < 14:
        digits = digits.zfill(14)
    return digits


def _list_certificates(directory: Path) -> list[str]:
    try:
        return sorted(
            entry.name
            for entry in directory.glob(f"*{_CERT_EXT}")
            if entry.is_file()
        )
    except OSError:
        return []


def _compute_sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    try:
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(8192), b""):
                if not chunk:
                    break
                digest.update(chunk)
    except OSError as exc:
        logger.error("CERT.ERROR: failed to read certificate for sha256: %s", exc)
        return None
    return digest.hexdigest()


def _parse_certificate(path: Path) -> tuple[str | None, str | None]:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise RuntimeError(f"No se pudo leer certificado: {exc}") from exc
    for encoding in ("utf-8", "latin-1"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = data.decode("utf-8", errors="ignore")
    nit_value = None
    password_hash = None
    try:
        # Lazy import to avoid adding ElementTree to public API
        import xml.etree.ElementTree as ET

        root = ET.fromstring(text)
        nit_node = root.find(".//nit")
        if nit_node is not None and nit_node.text:
            nit_value = _normalise_nit(nit_node.text)
        clave_node = root.find(".//privateKey/clave")
        if clave_node is not None and clave_node.text:
            password_hash = clave_node.text.strip() or None
    except ET.ParseError as exc:  # type: ignore[name-defined]
        raise RuntimeError(f"XML inválido en certificado: {exc}") from exc
    return nit_value, password_hash


def get_effective_cert_dir(cert_dir: str | os.PathLike[str] | None = None) -> tuple[Path, str]:
    if cert_dir:
        directory = Path(cert_dir)
        source = "parameter"
    else:
        env_value = os.getenv("CERT_UPLOAD_DIR")
        if env_value:
            directory = Path(env_value.strip())
            source = "env"
        else:
            directory = Path(_DEFAULT_CERT_DIR)
            source = "default"
    return directory.expanduser().resolve(), source


def resolve_signer_cert_dir() -> Path:
    env_value = os.getenv("FIRMADOR_CERT_DIR")
    if env_value:
        return Path(env_value.strip()).expanduser().resolve()
    return Path(os.getenv("CERT_UPLOAD_DIR", _DEFAULT_CERT_DIR).strip()).expanduser().resolve()


def verify_certificate_setup(
    nit: str | None,
    password: str | None,
    cert_dir: str | os.PathLike[str] | None = None,
) -> CertificateDiagnosis:
    normalised_nit = _normalise_nit(nit)
    effective_dir, source = get_effective_cert_dir(cert_dir)
    default_dir = Path(_DEFAULT_CERT_DIR).expanduser().resolve()
    signer_dir = resolve_signer_cert_dir()
    multiple_crts = _list_certificates(effective_dir)
    cert_path = effective_dir / f"{normalised_nit}{_CERT_EXT}" if normalised_nit else None
    cert_exists = cert_path.is_file() if cert_path else False
    cert_size = cert_path.stat().st_size if cert_exists else None
    cert_sha256 = _compute_sha256(cert_path) if cert_exists else None

    nit_crt = None
    cert_password_hash = None
    parse_error = None
    if cert_exists:
        try:
            nit_crt, cert_password_hash = _parse_certificate(cert_path)
        except RuntimeError as exc:
            parse_error = str(exc)
    password_sha512 = None
    errors: list[str] = []

    if normalised_nit and signer_dir and effective_dir != signer_dir:
        errors.append("dir_mismatch")

    if not cert_exists:
        errors.append("missing_file")
    else:
        if parse_error:
            errors.append("parse_error")
        if normalised_nit and nit_crt and normalised_nit != nit_crt:
            errors.append("nit_mismatch")

    if len(multiple_crts) > 1:
        errors.append("multiple_crts")

    if password:
        password_sha512 = hashlib.sha512(password.encode("utf-8")).hexdigest()
        if cert_password_hash and password_sha512 != cert_password_hash:
            errors.append("sha512_mismatch")
    elif cert_password_hash:
        password_sha512 = None

    diagnosis = CertificateDiagnosis(
        cert_dir=str(effective_dir),
        cert_dir_source=source,
        default_cert_dir=str(default_dir),
        signer_cert_dir=str(signer_dir),
        nit_config=normalised_nit,
        nit_crt=nit_crt,
        cert_path=str(cert_path) if cert_path else None,
        cert_exists=cert_exists,
        cert_size=cert_size,
        cert_sha256=cert_sha256,
        password_sha512=password_sha512,
        cert_password_sha512=cert_password_hash,
        multiple_crts=multiple_crts,
        parse_error=parse_error,
        errors=errors,
        ok=not errors,
    )

    logger.info(
        "CERT.DIAG: cert_dir=%s source=%s nit_config=%s nit_crt=%s exists=%s size=%s sha256=%s multiple_crts=%s ok=%s errors=%s",
        diagnosis.cert_dir,
        diagnosis.cert_dir_source,
        diagnosis.nit_config,
        diagnosis.nit_crt,
        diagnosis.cert_exists,
        diagnosis.cert_size,
        diagnosis.cert_sha256,
        diagnosis.multiple_crts,
        diagnosis.ok,
        diagnosis.errors,
    )

    global _LAST_DIAGNOSIS
    _LAST_DIAGNOSIS = diagnosis.to_dict()
    return diagnosis


def dump_certificate_diagnosis(path: Path) -> Path:
    """Persist the most recent certificate diagnosis as JSON."""

    target: Path
    if path.suffix.lower() == ".json":
        target = path
        target.parent.mkdir(parents=True, exist_ok=True)
    else:
        target = path / "cert_diagnosis.json"
        target.parent.mkdir(parents=True, exist_ok=True)

    payload: dict[str, object]
    if _LAST_DIAGNOSIS is None:
        payload = {"error": "no_diagnosis_available"}
    else:
        payload = _LAST_DIAGNOSIS

    with target.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)

    logger.info("CERT.DIAG.WRITE: path=%s", target)
    return target


__all__ = [
    "CertificateDiagnosis",
    "dump_certificate_diagnosis",
    "get_effective_cert_dir",
    "resolve_signer_cert_dir",
    "verify_certificate_setup",
]
