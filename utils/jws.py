import os
import json
import base64
import requests
import logging
import hashlib
import shutil
import re
from pathlib import Path
from urllib.parse import urljoin

from utils.stable_json import (
    stable_stringify,
    save_file,
    assert_same_payload,
    validar_montos,
)

logger = logging.getLogger(__name__)
from paths import (
    CONFIG_NEGOCIO_PATH,
    CERT_UPLOAD_DIR as _DEFAULT_CERT_DIR,
    ensure_user_dir,
)
from utils import resource_path
from utils.certificates import (
    verify_certificate_setup,
    dump_certificate_diagnosis,
    run_certificate_doctor,
    looks_like_base64,
    resolve_signer_cert_dir,
)
DEFAULT_SIGN_URL = "http://127.0.0.1:8080/firma/firmardocumento/"
SIGN_TIMEOUT = float(os.getenv("SIGN_TIMEOUT", "10"))
SIGN_HEALTH_TIMEOUT = float(os.getenv("SIGN_HEALTH_TIMEOUT", "3"))

SEND_DTEJSON_AS_OBJECT = os.getenv("SEND_DTEJSON_AS_OBJECT", "1") == "1"

# Directory where the signing service expects certificate files (.crt)
# Allow overriding via environment variable and strip any hidden characters.
CERT_UPLOAD_DIR = os.getenv("CERT_UPLOAD_DIR", _DEFAULT_CERT_DIR).strip()
DEBUG_JWS = os.getenv("DTE_DEBUG_JWS", "1") != "0"


def _b64url_decode(seg: str) -> bytes:
    pad = "=" * (-len(seg) % 4)
    return base64.urlsafe_b64decode(seg + pad)


def _canon_json(obj) -> str:
    """Serialize using the same canonical form employed during signing."""
    return stable_stringify(obj)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def set_cert_upload_dir(path: str) -> None:
    """Override global certificate directory to ``path``.

    The provided path is converted to an absolute path and stripped of
    whitespace so that subsequent signing operations read the certificate
    from the same location where it was copied after an upload.
    """
    global CERT_UPLOAD_DIR
    CERT_UPLOAD_DIR = os.path.abspath(path).strip()
    os.environ["CERT_UPLOAD_DIR"] = CERT_UPLOAD_DIR
    os.environ["FIRMADOR_CERT_DIR"] = CERT_UPLOAD_DIR


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


def _build_signer_status_url(sign_url: str | None) -> str | None:
    """Return health-check URL for ``sign_url`` if possible."""

    if not sign_url:
        return None
    if not sign_url.endswith("/"):
        sign_url = f"{sign_url}/"
    return urljoin(sign_url, "status")


def _check_signer_available(sign_url: str | None) -> None:
    """Perform a lightweight health check before signing."""

    status_url = _build_signer_status_url(sign_url)
    if not status_url:
        return

    try:
        logger.debug("SIGN.HEALTH.CHECK: url=%s", status_url)
        response = requests.get(status_url, timeout=SIGN_HEALTH_TIMEOUT)
    except requests.RequestException as exc:  # pragma: no cover - network errors
        print("SIGN: HEALTH_ERROR", type(exc).__name__, str(exc)[:200])
        raise RuntimeError(f"Error al firmar: {exc}") from exc

    if response.status_code in {404, 405}:
        # Older firmador builds do not expose a status endpoint; assume ready.
        logger.debug(
            "SIGN.HEALTH.SKIP: endpoint unavailable status=%s", response.status_code
        )
        return

    if response.status_code >= 500:
        print(
            "SIGN: HEALTH_ERROR",
            f"HTTP {response.status_code}",
            str(getattr(response, "text", ""))[:200],
        )
        raise RuntimeError(
            f"Error al firmar: verificación del firmador devolvió HTTP {response.status_code}"
        )

    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        print("SIGN: HEALTH_ERROR", type(exc).__name__, str(exc)[:200])
        raise RuntimeError(f"Error al firmar: {exc}") from exc

    logger.debug(
        "SIGN.HEALTH.OK: status=%s body=%s",
        response.status_code,
        (response.text or "").strip(),
    )


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
            if isinstance(nit, str):
                nit = nit.strip()
            password = fe.get("passwordPri")
            if password:
                try:
                    password = base64.b64decode(password).decode().strip()
                except Exception:
                    password = password.strip()
            activo = fe.get("activo", True)
        except Exception:
            pass
    return nit, password, activo


def _ensure_cert_file(nit: str) -> None:
    """Verify that the certificate file for ``nit`` exists and is readable."""
    nit = nit.strip()
    checked_dirs: list[str] = []
    last_access_error: str | None = None

    for cert_dir in _candidate_cert_dirs():
        checked_dirs.append(str(cert_dir))
        canonical = cert_dir / f"{nit}.crt"
        if not canonical.is_file():
            candidates = sorted(cert_dir.glob("*.crt"))
            if len(candidates) == 1:
                try:
                    shutil.copy2(candidates[0], canonical)
                except Exception:
                    pass
        if canonical.is_file():
            set_cert_upload_dir(str(cert_dir))
            if os.access(canonical, os.R_OK):
                return
            last_access_error = f"CERT_ACCESS: Certificado no accesible: {canonical}"

    if last_access_error:
        raise RuntimeError(last_access_error)

    dirs_text = ", ".join(checked_dirs)
    raise RuntimeError(
        "CERT_NOT_FOUND: "
        f"No se detectó el certificado (.crt) esperado {nit}.crt. "
        f"Directorios revisados: {dirs_text}"
    )


def _candidate_cert_dirs() -> list[Path]:
    candidate_dirs = [
        resolve_signer_cert_dir(),
        Path(_DEFAULT_CERT_DIR),
        ensure_user_dir("certificados"),
        resource_path("svfe-api-firmador", "uploads"),
    ]
    unique_dirs: list[Path] = []
    for entry in candidate_dirs:
        try:
            resolved = Path(entry).expanduser().resolve()
        except Exception:
            resolved = Path(entry)
        if resolved not in unique_dirs:
            unique_dirs.append(resolved)
    return unique_dirs


def _find_local_certificate(nit: str) -> Path | None:
    for cert_dir in _candidate_cert_dirs():
        candidate = cert_dir / f"{nit}.crt"
        if candidate.is_file():
            return candidate
    for cert_dir in _candidate_cert_dirs():
        candidates = sorted(cert_dir.glob("*.crt"))
        if len(candidates) == 1:
            return candidates[0]
    return None


def _extract_cert_path(message: str | None) -> Path | None:
    if not message:
        return None
    text = str(message)
    match = re.search(r"([A-Za-z]:\\\\[^\\r\\n]+?\\.crt)", text)
    if match:
        return Path(match.group(1))
    match = re.search(r"(/[^\\r\\n]+?\\.crt)", text)
    if match:
        return Path(match.group(1))
    return None


def _sync_cert_to_target(nit: str, target: Path) -> bool:
    source = _find_local_certificate(nit)
    if not source:
        return False
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        set_cert_upload_dir(str(target.parent))
        return True
    except Exception:
        return False


def sign_json(
    payload: dict | str,
    nit: str | None = None,
    passwordPri: str | None = None,
    activo: bool = True,
    url: str | None = None,
    version: str | None = None,
    tipo_dte: str | None = None,
    preserve_str: bool = False,
) -> str:
    """Sign ``payload`` using the external ``svfe-api-firmador`` service."""
    print("SIGN: START")
    if nit is None or passwordPri is None:
        nit, passwordPri, activo = _load_config()
    if not nit:
        raise RuntimeError("NIT del certificado no configurado")
    cert_dir = str(resolve_signer_cert_dir())
    diagnosis = verify_certificate_setup(nit, passwordPri, cert_dir)
    logger.info(
        "SIGN.DIAG: cert_dir=%s source=%s nit_config=%s nit_crt=%s exists=%s size=%s sha256=%s multiple_crts=%s ok=%s errors=%s",
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
    if "parse_error" in diagnosis.errors:
        detail = diagnosis.parse_error or "XML inválido en certificado"
        raise RuntimeError(f"CERT_INVALID: {detail}")
    _ensure_cert_file(nit)
    cert_dir = str(resolve_signer_cert_dir())
    url = url or _get_sign_url()
    print(
        "SIGN: CERT?",
        bool(nit),
        "KEY?",
        bool(passwordPri),
        "REMOTE_SIGNER?",
        url is not None,
    )

    _check_signer_available(url)

    if passwordPri:
        logger.info(
            "SIGN.PASSWORD: length=%s looks_base64=%s",
            len(passwordPri),
            looks_like_base64(passwordPri),
        )

    if isinstance(payload, str):
        payload_str = payload
        try:
            payload_obj = json.loads(payload_str) if not preserve_str else None
        except Exception as exc:
            raise ValueError("payload_str no es JSON válido") from exc
    else:
        payload_obj = payload
        payload_str = stable_stringify(payload_obj)

    if (version is None or tipo_dte is None) and isinstance(payload_obj, dict):
        ident = payload_obj.get("identificacion", {})
        if version is None:
            version = ident.get("version")
        if tipo_dte is None:
            tipo_dte = ident.get("tipoDte")

    if preserve_str:
        dte_json = json.loads(payload_str) if SEND_DTEJSON_AS_OBJECT else payload_str
    else:
        dte_json = json.loads(payload_str) if SEND_DTEJSON_AS_OBJECT else payload_str
    body = {
        "nit": nit,
        "activo": activo,
        "passwordPri": passwordPri,
        "dteJson": dte_json,
    }
    if version is not None:
        body["version"] = version
    if tipo_dte is not None:
        body["tipoDte"] = tipo_dte

    logger.info(
        "SIGN.REQUEST: url=%s nit=%s cert_exists=%s verify_ok=%s errors=%s",
        url,
        diagnosis.nit_config,
        diagnosis.cert_exists,
        diagnosis.ok,
        diagnosis.errors,
    )
    def _post_request():
        response = requests.post(url, json=body, timeout=SIGN_TIMEOUT)
        status_code = getattr(response, "status_code", "N/A")
        resp_text = getattr(response, "text", "")
        if isinstance(status_code, int) and status_code >= 400:
            logger.error("Respuesta del firmador %s", status_code)
        else:
            logger.debug("Respuesta del firmador %s: %s", status_code, resp_text)
        response.raise_for_status()
        return response

    retried = False
    while True:
        try:
            response = _post_request()
        except requests.Timeout as exc:
            print("SIGN: ERROR", type(exc).__name__, str(exc)[:200])
            raise RuntimeError("Tiempo de espera agotado al firmar") from exc
        except requests.HTTPError as exc:
            print("SIGN: ERROR", type(exc).__name__, str(exc)[:200])
            status = exc.response.status_code
            raise RuntimeError(f"Error HTTP {status} al firmar: {exc.response.text}") from exc
        except requests.RequestException as exc:
            print("SIGN: ERROR", type(exc).__name__, str(exc)[:200])
            raise RuntimeError(f"Error al firmar: {exc}") from exc

        data = response.json()
        if isinstance(data, dict):
            if data.get("status") == "OK":
                return data.get("body")
            body = data.get("body")
            if isinstance(body, dict):
                code = str(body.get("codigo") or body.get("code") or "").strip()
                message = body.get("mensaje") or body.get("message")
                message_text = str(message or "").lower()
                if code in {"801", "812"} or "no se encontro el archivo" in message_text:
                    target_path = _extract_cert_path(message)
                    if not retried and target_path and _sync_cert_to_target(nit, target_path):
                        retried = True
                        continue
                    detail = str(message or "").strip()
                    if detail:
                        raise RuntimeError(f"CERT_NOT_FOUND: {detail}")
                    raise RuntimeError(
                        "CERT_NOT_FOUND: "
                        f"No se detectó el certificado (.crt) esperado {nit}.crt."
                    )
                if code == "803":
                    logger.error(
                        "SIGN.ERROR: firmador_code=%s, firmador_msg=%r",
                        code,
                        message,
                    )
                    logger.error("SIGN.ERROR.BODY: %s", body)
                    diag_dir = ensure_user_dir("diagnostics")
                    try:
                        report = run_certificate_doctor(
                            nit=nit,
                            password=passwordPri or "",
                            signer_url=url,
                            cert_dir=cert_dir,
                            output_dir=diag_dir,
                        )
                        diag_path = report.json_path
                        markdown_path = report.markdown_path
                    except Exception as diag_exc:  # pragma: no cover - safeguard
                        logger.exception("SIGN.DIAG.ERROR: %s", diag_exc)
                        diag_path = dump_certificate_diagnosis(diag_dir)
                        markdown_path = None
                    else:
                        logger.info(
                            "SIGN.DIAG.OK: json=%s markdown=%s",
                            diag_path,
                            markdown_path,
                        )
                    logger.error("SIGN.DIAG.WRITE: path=%s", diag_path)
                    raise RuntimeError(f"{body} (diagnosis: {diag_path})")
            raise RuntimeError(str(body))
        return data


def sign_and_save(
    payload: dict,
    json_path: str,
    nit: str | None = None,
    passwordPri: str | None = None,
    activo: bool = True,
    url: str | None = None,
    return_token: bool = False,
):
    """Sign ``payload`` and store only the JSON representation.

    The previous implementation also persisted the JWS token to disk.  To
    comply with the new requirement of keeping only the original JSON and
    the final state, the JWS token is now generated in memory and returned
    to the caller when needed but **no** ``.jws`` file is written.

    When ``return_token`` is ``True`` the function returns a tuple
    ``(json_path, token)``; otherwise only ``json_path`` is returned.
    """
    json_pretty = stable_stringify(payload, indent=2)
    payload_compact = stable_stringify(payload)
    save_file(json_path, json_pretty)
    print("SIGN: JSON_PRETTY", json_path, json_pretty)
    if os.getenv("STABLE_JSON_CHECK") == "1":
        validar_montos(payload)
        assert_same_payload(payload)
    ident = payload.get("identificacion", {})
    version = ident.get("version")
    tipo_dte = ident.get("tipoDte")
    try:
        token = sign_json(
            payload_compact,
            nit,
            passwordPri,
            activo,
            url,
            version=version,
            tipo_dte=tipo_dte,
        )
    except TypeError:
        # Allows tests to patch ``sign_json`` with a simplified signature
        token = sign_json(payload)
    token = token.rstrip("\n")
    if return_token:
        return json_path, token
    return json_path
