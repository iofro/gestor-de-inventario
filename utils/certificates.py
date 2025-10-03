"""Utilities for validating signing certificates and generating diagnostics."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import logging
import os
import shutil
import textwrap
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse, urlunparse

import requests

from paths import CERT_UPLOAD_DIR as _DEFAULT_CERT_DIR

logger = logging.getLogger(__name__)

_CERT_EXT = ".crt"
_LAST_DIAGNOSIS: dict | None = None
_DEFAULT_TIMEOUT = float(os.getenv("SIGNER_DEBUG_TIMEOUT", "5"))


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


@dataclass(slots=True)
class CertificateFileInfo:
    """Description of a certificate file visible to the signer service."""

    name: str
    size: int | None = None
    sha256: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "size": self.size,
            "sha256": self.sha256,
        }


@dataclass(slots=True)
class SignerDebugInfo:
    """Information returned by the signer debug endpoints."""

    available: bool
    error: str | None = None
    status_code: int | None = None
    signer_cert_dir: str | None = None
    env: dict[str, str] | None = None
    files: list[CertificateFileInfo] = field(default_factory=list)
    selected: str | None = None
    nit_from_crt: str | None = None
    cert_password_sha512: str | None = None
    cert_sha256: str | None = None
    password_sha512: str | None = None
    env_available: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "error": self.error,
            "status_code": self.status_code,
            "signer_cert_dir": self.signer_cert_dir,
            "env": self.env,
            "files": [entry.to_dict() for entry in self.files],
            "selected": self.selected,
            "nit_from_crt": self.nit_from_crt,
            "cert_password_sha512": self.cert_password_sha512,
            "cert_sha256": self.cert_sha256,
            "password_sha512": self.password_sha512,
            "env_available": self.env_available,
        }


@dataclass(slots=True)
class DoctorReport:
    """Aggregated local/remote diagnostics and persisted artifact paths."""

    data: dict[str, Any]
    json_path: Path
    markdown_path: Path

    def to_dict(self) -> dict[str, Any]:
        result = dict(self.data)
        result.update(
            {
                "json_path": str(self.json_path),
                "markdown_path": str(self.markdown_path),
            }
        )
        return result


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


def get_effective_cert_dir(
    cert_dir: str | os.PathLike[str] | None = None,
) -> tuple[Path, str]:
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


def _path_is_relative_to(path: Path, other: Path) -> bool:
    try:
        path.relative_to(other)
        return True
    except ValueError:
        return False


def copy_certificate_to_signer_dir(source: Path | str, nit: str) -> Path:
    """Copy ``source`` into the signer directory preserving its original name.


    Any other certificate present in the directory is removed so that only the
    newly uploaded file remains.

    """

    if not nit:
        raise ValueError("NIT vacío para copiar certificado")

    source_path = Path(source).expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"Certificado origen no encontrado: {source_path}")
    dest_dir = resolve_signer_cert_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)

    dest_path = dest_dir / source_path.name
    canonical_path = dest_dir / f"{nit}{_CERT_EXT}"

    temp_path: Path | None = None
    copy_source = source_path
    if _path_is_relative_to(source_path, dest_dir):
        temp_path = dest_dir / f".tmp_{nit}"
        shutil.copy2(source_path, temp_path)
        copy_source = temp_path

    skip_resolved = {source_path, source_path.resolve()}

    for existing in dest_dir.iterdir():
        if existing.suffix.lower() != ".crt":
            continue
        if existing.name in {dest_path.name, canonical_path.name}:
            continue
        try:
            existing_resolved = existing.resolve()
        except OSError:
            existing_resolved = existing
        if existing_resolved in skip_resolved:
            continue
        try:
            existing.unlink()
        except OSError as exc:
            logger.warning("CERT.ERROR: no se pudo eliminar %s: %s", existing, exc)

    shutil.copy2(copy_source, dest_path)

    if canonical_path != dest_path:
        shutil.copy2(dest_path, canonical_path)

    if temp_path is not None:
        try:
            temp_path.unlink()
        except OSError:
            pass

    for target in {dest_path, canonical_path}:
        try:
            target.chmod(0o644)
        except OSError:
            pass

    if not dest_path.is_file():
        raise FileNotFoundError(f"No se pudo copiar certificado a {dest_path}")

    return dest_path


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
    _LAST_DIAGNOSIS = {"local": diagnosis.to_dict()}
    return diagnosis


def looks_like_base64(value: str | None) -> bool:
    """Heuristically determine whether ``value`` is Base64 encoded."""

    if not value:
        return False
    stripped = value.strip()
    if len(stripped) < 8 or len(stripped) % 4 != 0:
        return False
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=")
    if any(ch not in allowed for ch in stripped):
        return False
    try:
        decoded = base64.b64decode(stripped, validate=True)
    except (base64.binascii.Error, ValueError):  # type: ignore[attr-defined]
        return False
    return bool(decoded)


def _normalise_path(path: str | os.PathLike[str] | None) -> str | None:
    if not path:
        return None
    try:
        return str(Path(path).expanduser().resolve())
    except (OSError, RuntimeError):
        return str(path)


def _build_debug_url(sign_url: str | None, endpoint: str) -> str | None:
    base = (sign_url or "").strip()
    if not base:
        return None
    parsed = urlparse(base)
    scheme = parsed.scheme or "http"
    netloc = parsed.netloc
    path = parsed.path or "/"
    if not path.endswith("/"):
        path = f"{path}/"
    segments = [segment for segment in path.split("/") if segment]
    if "firma" in segments:
        idx = len(segments) - 1 - segments[::-1].index("firma")
        base_segments = segments[: idx + 1]
        debug_segments = base_segments + ["debug", endpoint]
    else:
        debug_segments = ["firma", "debug", endpoint]
    debug_path = "/" + "/".join(debug_segments)
    return urlunparse((scheme, netloc, debug_path, "", "", ""))


def _request_json(
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    timeout: float | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    metadata: dict[str, Any] = {
        "url": url,
        "params": params,
        "method": method,
    }
    try:
        response = requests.request(
            method,
            url,
            params=params,
            json=json_body,
            timeout=timeout or _DEFAULT_TIMEOUT,
        )
        metadata["status_code"] = response.status_code
        response.raise_for_status()
        try:
            return response.json(), metadata
        except ValueError as exc:  # invalid JSON
            metadata["error"] = f"invalid_json: {exc}"
            return None, metadata
    except requests.RequestException as exc:
        metadata["error"] = str(exc)
        return None, metadata


def _parse_files_payload(files: Iterable[dict[str, Any]]) -> list[CertificateFileInfo]:
    result: list[CertificateFileInfo] = []
    for entry in files:
        name = entry.get("name")
        if not isinstance(name, str):
            continue
        size = entry.get("size")
        sha256 = entry.get("sha256")
        result.append(
            CertificateFileInfo(
                name=name,
                size=int(size) if isinstance(size, (int, float)) else None,
                sha256=str(sha256) if isinstance(sha256, str) else None,
            )
        )
    return result


def fetch_signer_debug(
    sign_url: str | None,
    nit: str | None,
    password: str | None,
    *,
    timeout: float | None = None,
) -> SignerDebugInfo:
    certs_url = _build_debug_url(sign_url, "certs")
    hash_url = _build_debug_url(sign_url, "hash")
    env_url = _build_debug_url(sign_url, "env")

    if not certs_url:
        return SignerDebugInfo(available=False, error="missing_debug_url")

    params = {"n": nit} if nit else None
    payload, meta = _request_json("GET", certs_url, params=params, timeout=timeout)
    info = SignerDebugInfo(
        available=bool(payload),
        status_code=meta.get("status_code"),
        error=None if payload else meta.get("error"),
    )

    if not payload:
        return info

    info.signer_cert_dir = payload.get("signer_cert_dir")
    info.env = payload.get("env") or payload.get("environment")
    files_payload = payload.get("files")
    if isinstance(files_payload, list):
        info.files = _parse_files_payload(files_payload)
    info.selected = payload.get("selected")
    info.nit_from_crt = payload.get("nit_from_crt")
    info.cert_password_sha512 = payload.get("cert_password_sha512")
    info.cert_sha256 = payload.get("cert_sha256") or payload.get("selected_sha256")

    if env_url:
        env_payload, env_meta = _request_json("GET", env_url, timeout=timeout)
        if env_payload:
            env_values = env_payload.get("env")
            if isinstance(env_values, dict):
                info.env = {str(k): str(v) for k, v in env_values.items()}
        else:
            info.env_available = False
            if info.error:
                info.error = f"{info.error}; env: {env_meta.get('error')}"
            else:
                info.error = env_meta.get("error")

    if hash_url and password is not None:
        hash_payload, hash_meta = _request_json(
            "POST",
            hash_url,
            json_body={"passwordPri": password},
            timeout=timeout,
        )
        if hash_payload and isinstance(hash_payload, dict):
            hashed = hash_payload.get("password_sha512")
            if isinstance(hashed, str):
                info.password_sha512 = hashed
        elif hash_meta.get("error"):
            info.error = hash_meta["error"]

    return info


def _compare_hashes(
    local_hash: str | None,
    remote_hash: str | None,
) -> tuple[bool | None, str | None]:
    if not local_hash and not remote_hash:
        return None, None
    if local_hash is None or remote_hash is None:
        return False, "missing_hash"
    return (local_hash == remote_hash), None


def _derive_probable_cause(issues: list[str]) -> tuple[str, str]:
    if not issues:
        return (
            "Todos los chequeos coinciden",
            "No se requiere acción: el firmador y el cliente están alineados.",
        )

    priority = [
        (
            "dir_mismatch",
            "El firmador usa otra carpeta de certificados",
            "Ajusta CERT_UPLOAD_DIR/FIRMADOR_CERT_DIR en el servicio y reinicia el firmador.",
        ),
        (
            "sha512_mismatch",
            "La contraseña no coincide con el hash del certificado",
            "Verifica la contraseña configurada y vuelve a cargar el certificado correcto.",
        ),
        (
            "password_encoding_base64",
            "La contraseña parece estar codificada en Base64",
            "Configura la contraseña en texto plano y evita enviar la versión codificada.",
        ),
        (
            "multiple_crts",
            "Hay múltiples certificados para el mismo NIT",
            "Deja solo un archivo .crt para el NIT indicado o ajusta el archivo correcto.",
        ),
        (
            "nit_mismatch",
            "El NIT dentro del certificado no coincide",
            "Vuelve a emitir o seleccionar el certificado correcto para el NIT configurado.",
        ),
        (
            "missing_file",
            "El certificado configurado no existe",
            "Copia el archivo .crt al directorio configurado y reinicia el proceso.",
        ),
    ]
    for key, cause, remediation in priority:
        if key in issues:
            return cause, remediation
    return (
        "Se detectaron inconsistencias en el entorno de firma",
        "Revisa el reporte completo para corregir las discrepancias señaladas.",
    )


def _render_markdown_report(data: dict[str, Any]) -> str:
    sections: list[str] = []
    local = data.get("local", {})
    remote = data.get("remote", {})
    comparisons = data.get("comparisons", {})
    issues = data.get("issues", [])
    cause = data.get("probable_cause", "No determinado")
    remediation = data.get("remediation", "Revisa la configuración.")

    sections.append("# Diagnóstico de certificados\n")
    sections.append("## Resumen\n")
    sections.append(
        textwrap.dedent(
            f"""
            * **OK:** {data.get('ok')}
            * **Problemas detectados:** {', '.join(issues) if issues else 'ninguno'}
            * **Causa probable:** {cause}
            * **Remediación sugerida:** {remediation}
            """
        ).strip()
    )

    sections.append("\n## Entorno local\n")
    sections.append("```json\n" + json.dumps(local, indent=2, ensure_ascii=False) + "\n```")

    sections.append("\n## Entorno del firmador\n")
    sections.append("```json\n" + json.dumps(remote, indent=2, ensure_ascii=False) + "\n```")

    sections.append("\n## Comparaciones\n")
    sections.append(
        "```json\n" + json.dumps(comparisons, indent=2, ensure_ascii=False) + "\n```"
    )

    notes = data.get("notes")
    if notes:
        sections.append("\n## Notas\n")
        sections.extend(f"* {note}" for note in notes)

    return "\n\n".join(sections) + "\n"


def _save_report(payload: dict[str, Any], directory: Path) -> DoctorReport:
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "cert_diagnosis.json"
    markdown_path = directory / "cert_diagnosis.md"
    with json_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
    with markdown_path.open("w", encoding="utf-8") as fh:
        fh.write(_render_markdown_report(payload))
    logger.info(
        "CERT.DIAG.WRITE: json=%s markdown=%s", json_path, markdown_path
    )
    return DoctorReport(payload, json_path, markdown_path)


def run_certificate_doctor(
    *,
    nit: str,
    password: str,
    signer_url: str,
    cert_dir: str | os.PathLike[str] | None = None,
    output_dir: Path | None = None,
    timeout: float | None = None,
) -> DoctorReport:
    """Perform an end-to-end validation of the signing environment."""

    local_diag = verify_certificate_setup(nit, password, cert_dir)
    remote_info = fetch_signer_debug(signer_url, nit, password, timeout=timeout)

    local = local_diag.to_dict()
    remote = remote_info.to_dict()

    issues = set(local.get("errors") or [])
    comparisons: dict[str, Any] = {}
    notes: list[str] = []

    local_cert_dir = _normalise_path(local.get("cert_dir"))
    remote_cert_dir = _normalise_path(remote_info.signer_cert_dir)
    if local_cert_dir and remote_cert_dir and local_cert_dir != remote_cert_dir:
        issues.add("dir_mismatch")

    # Compare SHA256 of selected certificate
    local_sha256 = local.get("cert_sha256")
    remote_sha256 = remote_info.cert_sha256
    comparisons["cert_sha256"] = {
        "local": local_sha256,
        "remote": remote_sha256,
        "match": bool(local_sha256 and remote_sha256 and local_sha256 == remote_sha256),
    }

    if remote_sha256 and local_sha256 and local_sha256 != remote_sha256:
        issues.add("dir_mismatch")

    local_cert_password_hash = local.get("cert_password_sha512")
    remote_cert_password_hash = remote_info.cert_password_sha512
    match, reason = _compare_hashes(local_cert_password_hash, remote_cert_password_hash)
    comparisons["cert_password_sha512"] = {
        "local": local_cert_password_hash,
        "remote": remote_cert_password_hash,
        "match": match,
    }
    if match is False:
        issues.add("sha512_mismatch")
    elif reason == "missing_hash":
        notes.append("No se pudo comparar el hash sha512 del certificado en el firmador.")

    local_password_hash = local.get("password_sha512")
    remote_password_hash = remote_info.password_sha512
    match, reason = _compare_hashes(local_password_hash, remote_password_hash)
    comparisons["password_sha512"] = {
        "local": local_password_hash,
        "remote": remote_password_hash,
        "match": match,
    }
    if reason == "missing_hash":
        notes.append(
            "El firmador no devolvió el hash SHA-512 calculado a partir de la contraseña recibida."
        )

    nit_crt = local.get("nit_crt") or remote_info.nit_from_crt
    nit_config = local.get("nit_config")
    if nit_crt and nit_config and nit_crt != nit_config:
        issues.add("nit_mismatch")

    if remote_info.files:
        normalised_nit = _normalise_nit(nit)
        same_nit = [
            entry
            for entry in remote_info.files
            if entry.name.startswith(f"{normalised_nit}")
        ]
        if len(same_nit) > 1:
            issues.add("multiple_crts")

    if looks_like_base64(password):
        try:
            decoded = base64.b64decode(password, validate=True).decode("utf-8")
        except Exception:
            decoded = ""
        if decoded:
            decoded_hash = hashlib.sha512(decoded.encode("utf-8")).hexdigest()
            candidate_hashes = {local_cert_password_hash, remote_cert_password_hash}
            candidate_hashes.discard(None)  # type: ignore[arg-type]
            if candidate_hashes and decoded_hash in candidate_hashes:
                issues.add("password_encoding_base64")

    if not remote_info.available:
        notes.append(
            "El firmador no expone los endpoints /firma/debug; revisa la versión del servicio."
        )

    if not remote_info.env_available:
        notes.append(
            "No se pudo consultar /firma/debug/env; en Windows asegúrate de definir las "
            "variables de entorno del servicio y reiniciar el firmador."
        )
    else:
        env = remote_info.env or {}
        if "FIRMADOR_CERT_DIR" not in env:
            notes.append(
                "El firmador no reporta FIRMADOR_CERT_DIR; si corre como servicio Windows, "
                "define la variable a nivel de Sistema y reinicia el servicio."
            )

    cause, remediation = _derive_probable_cause(sorted(issues))

    payload: dict[str, Any] = {
        "ok": not issues,
        "issues": sorted(issues),
        "local": local,
        "remote": remote,
        "comparisons": comparisons,
        "probable_cause": cause,
        "remediation": remediation,
    }
    if notes:
        payload["notes"] = notes

    if output_dir is None:
        output_dir = Path.cwd() / "diagnostics"

    report = _save_report(payload, Path(output_dir))

    global _LAST_DIAGNOSIS
    _LAST_DIAGNOSIS = payload | {
        "json_path": str(report.json_path),
        "markdown_path": str(report.markdown_path),
    }

    return report


def dump_certificate_diagnosis(path: Path, payload: dict[str, Any] | None = None) -> Path:
    """Persist the most recent certificate diagnosis as JSON."""

    target: Path
    if path.suffix.lower() == ".json":
        target = path
        target.parent.mkdir(parents=True, exist_ok=True)
    else:
        target = path / "cert_diagnosis.json"
        target.parent.mkdir(parents=True, exist_ok=True)

    snapshot = payload or _LAST_DIAGNOSIS
    if snapshot is None:
        snapshot = {"error": "no_diagnosis_available"}

    with target.open("w", encoding="utf-8") as fh:
        json.dump(snapshot, fh, indent=2, ensure_ascii=False)

    logger.info("CERT.DIAG.WRITE: path=%s", target)
    return target


def _doctor_command(args: argparse.Namespace) -> int:
    report = run_certificate_doctor(
        nit=args.nit,
        password=args.password,
        signer_url=args.signer_url,
        cert_dir=args.cert_dir,
        output_dir=Path(args.output_dir) if args.output_dir else None,
    )
    print(f"Diagnóstico JSON: {report.json_path}")
    print(f"Diagnóstico Markdown: {report.markdown_path}")
    print(json.dumps(report.data, indent=2, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Herramientas de diagnóstico de certificados")
    subparsers = parser.add_subparsers(dest="command")

    doctor_parser = subparsers.add_parser(
        "doctor", help="Genera un diagnóstico local/remoto del certificado"
    )
    doctor_parser.add_argument("--nit", required=True, help="NIT configurado en el firmador")
    doctor_parser.add_argument(
        "--password",
        required=True,
        help="Contraseña privada asociada al certificado",
    )
    doctor_parser.add_argument(
        "--signer-url",
        required=True,
        help="URL base del firmador (por ejemplo http://127.0.0.1:8080/firma/firmardocumento/)",
    )
    doctor_parser.add_argument(
        "--cert-dir",
        help="Directorio local donde se almacena el certificado (.crt)",
    )
    doctor_parser.add_argument(
        "--output-dir",
        help="Directorio donde se guardarán los reportes (por defecto ./diagnostics)",
    )
    doctor_parser.set_defaults(func=_doctor_command)

    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 1
    return args.func(args)




__all__ = [
    "CertificateDiagnosis",
    "CertificateFileInfo",
    "DoctorReport",
    "copy_certificate_to_signer_dir",
    "dump_certificate_diagnosis",
    "fetch_signer_debug",
    "get_effective_cert_dir",
    "looks_like_base64",
    "resolve_signer_cert_dir",
    "run_certificate_doctor",
    "verify_certificate_setup",
]


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
