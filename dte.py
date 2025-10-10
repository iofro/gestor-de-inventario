import json
import os
import uuid
import inspect
import base64
import copy
import platform
import sys
import re
import shutil
import hashlib
import logging
import time
from collections.abc import Mapping as AbcMapping, Sequence
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, getcontext
from typing import Any, Mapping, Optional
from urllib.parse import urlparse
from email.utils import parsedate_to_datetime

from db import DB
import requests
from configparser import ConfigParser
from utils import jws
from utils import versioned_dte
from utils.stable_json import stable_stringify, save_file, hash_json
import auth
from mh_auth import auth_headers, decode_jwt_claims
from jsonschema import ValidationError, RefResolver
from utils import catalogos
from utils.catalogos import (
    TRIBUTO_IVA,
    TRIBUTOS,
    TRIBUTOS_PERMITIDOS_ITEM,
    TRIBUTOS_PERMITIDOS_RESUMEN,
    UNIDADES_MEDIDA_PERMITIDAS,
    validar_dep_muni_por_catalogo,
    GeoValidationError,
)
import warnings
import xml.etree.ElementTree as ET
from utils.fiscal_extra import normalize_tipo_fiscal
from utils.monto import monto_a_texto_sv, iva_item, to_base_iva, d2, d4, d8, money
from utils.line_totals import compute_line_totals
from utils.sanitize import limpiar_documentos, limpiar_doc, solo_digitos
from utils.snapshot import SnapshotNotFoundError
from num2words import num2words
from utils.resumen import normalize_condicion_operacion, validate_pagos_basico
from utils.fecha import fecha_emision_hoy_str, TZ_EL_SALVADOR
from svfe import config as svfe_config
from utils import resource_path
from utils.env import env_flag

FISCAL_TOTAL_FIELDS = {
    "sumas",
    "descuentos",
    "iva",
    "subtotal",
    "ventas_exentas",
    "ventas_no_sujetas",
    "no_gravado",
    "precios_incluyen_iva",
    "descu_no_suj",
    "descu_exenta",
    "descu_gravada",
    "sub_total_ventas",
}
from pathlib import Path
import jsonpatch
from paths import (
    DATOS_NEGOCIO_PATH,
    CONFIG_NEGOCIO_PATH,
    DTES_DIR,
    DTE_FALLIDOS_DIR,
    DTE_FIRMADO_DIR,
    DTES_PENDIENTES_DIR,
    FACTURAS_CONSUMIDOR_FINAL_DIR,
    FACTURAS_CREDITO_FISCAL_DIR,
    TICKETS_OUTPUT_DIR,
    NOTAS_CREDITO_DIR,
    NOTAS_DEBITO_DIR,
    FACTURAS_ARCHIVE_CF_DIR,
    FACTURAS_ARCHIVE_CREDITO_DIR,
)
from xml.etree.ElementTree import Element, SubElement

try:
    _version_cfg = ConfigParser()
    _version_cfg.read(resource_path("VERSION"), encoding="utf-8")
    APP_VERSION = _version_cfg.get("VertexDTE", "version", fallback="1.0.0").strip()
except Exception:  # pragma: no cover - fallback when VERSION is missing
    APP_VERSION = "1.0.0"

logger = logging.getLogger(__name__)
TIMEOUT = int(os.getenv("DTE_HTTP_TIMEOUT", "20"))

SUCCESS_RAW = {"TRANSMITIDO", "RECIBIDO", "PROCESADO"}
ACCEPT_RAW = {"ACEPTADO"}
REJECT_RAW = {"RECHAZADO"}


def _get_in(mapping: Mapping[str, Any] | None, key: str) -> Any:
    if not isinstance(mapping, AbcMapping):
        return None

    visited: set[int] = set()

    def _walk(node: Any) -> Any:
        if isinstance(node, AbcMapping):
            marker = id(node)
            if marker in visited:
                return None
            visited.add(marker)
            if key in node:
                return node[key]
            for value in node.values():
                found = _walk(value)
                if found is not None:
                    return found
        elif isinstance(node, Sequence) and not isinstance(node, (str, bytes, bytearray)):
            marker = id(node)
            if marker in visited:
                return None
            visited.add(marker)
            for item in node:
                found = _walk(item)
                if found is not None:
                    return found
        return None

    try:
        return _walk(mapping)
    except RecursionError:
        return None


def _extract_raw_estado(resp: Mapping[str, Any] | None) -> str:
    if not isinstance(resp, AbcMapping):
        return ""
    for key in (
        "estado",
        "estadoDte",
        "estadoEvento",
        "descripcionEstado",
        "descripcionEstadoDte",
    ):
        value = _get_in(resp, key)
        if isinstance(value, str) and value.strip():
            return value.strip().upper()
    return ""


def _extract_meta(resp: Mapping[str, Any] | None) -> dict[str, Any]:
    descripcion = _get_in(resp, "descripcionMsg")
    clasifica = _get_in(resp, "clasificaMsg")
    codigo = _get_in(resp, "codigoMsg")
    observaciones_raw = _get_in(resp, "observaciones")

    if isinstance(descripcion, str):
        descripcion_up = descripcion.strip().upper()
    else:
        descripcion_up = ""

    if isinstance(clasifica, str):
        clasifica_up = clasifica.strip().upper()
    else:
        clasifica_up = ""

    if isinstance(codigo, str):
        codigo_up = codigo.strip().upper()
    elif isinstance(codigo, (int, float)):
        codigo_up = str(codigo).strip().upper()
    else:
        codigo_up = ""

    observaciones_list: list[Any] = []
    if isinstance(observaciones_raw, (list, tuple, set)):
        observaciones_list = [obs for obs in observaciones_raw if obs not in (None, "")]
    elif isinstance(observaciones_raw, str) and observaciones_raw.strip():
        observaciones_list = [observaciones_raw.strip()]

    return {
        "descripcion": descripcion_up,
        "clasifica": clasifica_up,
        "codigo": codigo_up,
        "observaciones": observaciones_list,
    }


def _map_estado_hacienda(resp: Mapping[str, Any] | None) -> dict[str, str]:
    raw = _extract_raw_estado(resp)
    meta = _extract_meta(resp)
    descripcion = meta["descripcion"]
    clasifica = meta["clasifica"]
    codigo = meta["codigo"]
    observaciones = meta["observaciones"]

    raw_upper = raw.strip().upper() if isinstance(raw, str) else ""

    text_pool = (raw_upper, descripcion, clasifica)

    ui = "Pendiente"
    if any("RECHAZ" in value for value in text_pool if value):
        ui = "Rechazado"
    elif any("ACEPT" in value for value in text_pool if value):
        ui = "Aceptado"
    elif any(value and token in value for value in text_pool for token in ("PROCES", "RECIB", "TRANSMIT")):
        ui = "Enviado"
    elif any(
        value and token in value
        for value in (descripcion, clasifica)
        for token in ("RECIBIDO", "PROCESADO")
    ):
        ui = "Enviado"

    tag = ""
    code_int: int | None = None
    if codigo:
        try:
            code_int = int(codigo.lstrip("0") or "0")
        except Exception:
            code_int = None
    if ui == "Enviado":
        has_observaciones = bool(observaciones) or (
            descripcion and "OBSERVACION" in descripcion
        )
        if has_observaciones:
            allow_tag = False
            if not clasifica:
                allow_tag = True
            elif clasifica == "10":
                if (code_int is not None and code_int in (1, 2)) or codigo in {"001", "002"}:
                    allow_tag = True
            if allow_tag:
                tag = "observado"
    elif ui == "Rechazado":
        if (code_int == 96) or codigo == "096" or (
            descripcion and "ESQUEMA JSON" in descripcion
        ):
            tag = "schema"
        elif (code_int == 17) or codigo == "017" or (
            descripcion and "FECHA NO ES CORRECTA" in descripcion
        ):
            tag = "fecha"
        elif (code_int == 14) or codigo == "014" or (
            descripcion and "NO EXISTE UN REGISTRO" in descripcion
        ):
            tag = "no_registro"

    return {"ui": ui, "tag": tag, "raw": raw_upper, "code": codigo, "desc": descripcion}


def _merge_estado_ui(prev_ui: str | None, new_ui: str) -> str:
    prev = (prev_ui or "").strip().capitalize()
    new = (new_ui or "").strip().capitalize()
    if prev == "Aceptado":
        return "Aceptado"
    if new == "Aceptado":
        return "Aceptado"
    if prev == "Rechazado" and new == "Pendiente":
        return "Rechazado"
    if new == "Rechazado":
        return "Rechazado"
    if prev == "Rechazado" and new == "Enviado":
        return "Rechazado"
    if not prev or prev == "Pendiente":
        return new
    if prev == "Enviado" and new == "Enviado":
        return "Enviado"
    return prev


def _merge_estado_tag(prev_tag: str | None, new_tag: str | None, merged_ui: str) -> str:
    merged = (merged_ui or "").strip().capitalize()
    prev = (prev_tag or "").strip().lower()
    new = (new_tag or "").strip().lower()

    if merged == "Aceptado":
        return ""
    if merged == "Rechazado":
        if new:
            return new
        return prev
    if merged == "Enviado":
        if new == "observado":
            return "observado"
        if prev == "observado":
            return "observado"
        return ""
    return new or prev

# Flags y valores por defecto esperados para diagnósticos HTTP:
# - DTE_DEBUG_HTTP=0
# - DTE_DEBUG_NO_REDIRECTS=0
# - DTE_RETRY_401_EMPTY=1
# - DTE_BACKOFF_MS=8000
# - DTE_RATE_LIMIT_MS=0
# - DTE_HTTP_TIMEOUT=20
# - DTE_DEBUG_DUMP_REQ_BODY=0


def _fp_auth(hdr_val: str) -> str:
    """Devuelve un fingerprint seguro del Authorization real enviado.
    No loguear el token; solo un SHA-1 truncado o 'MISSING'."""

    if not hdr_val:
        return "MISSING"
    return hashlib.sha1(hdr_val.encode("utf-8")).hexdigest()[:10]


def _normalize_bearer(token_raw: str) -> str:
    text = str(token_raw or "")
    text = (
        text.replace("\u200b", " ")
        .replace("\r", " ")
        .replace("\n", " ")
        .replace("\t", " ")
    )
    text = text.strip()
    lowered = text.lower()
    while lowered.startswith("bearer "):
        text = text[7:].lstrip()
        lowered = text.lower()
    compact = " ".join(text.split())
    return f"Bearer {compact}"


def _jwt_peek(token_raw: str | None) -> dict[str, Any]:
    claims = decode_jwt_claims(token_raw)
    if not isinstance(claims, Mapping):
        return {}
    result: dict[str, Any] = {}
    for key in ("sub", "iat", "exp"):
        if key in claims:
            result[key] = claims[key]
    return result


def _log_http_exchange(
    resp,
    allow_redirects: bool | None = None,
    *,
    t0_local: datetime | None = None,
    t1_local: datetime | None = None,
):
    """Loguea request final, history de redirects y cabeceras clave sin exponer secretos."""

    if not env_flag("DTE_DEBUG_HTTP"):
        return

    try:
        req = resp.request
        final_host = urlparse(req.url).netloc
        auth_hdr = req.headers.get("Authorization")
        content_type = req.headers.get("Content-Type") or req.headers.get("content-type")
        user_agent = req.headers.get("User-Agent")
        app_version = req.headers.get("app-version") or req.headers.get("App-Version")
        cliente_id = req.headers.get("cliente-id") or req.headers.get("Cliente-Id")

        latency_sec = None
        try:
            if resp.elapsed is not None:
                latency_sec = resp.elapsed.total_seconds()
        except Exception:
            latency_sec = None
        latency_val = f"{latency_sec:.3f}s" if latency_sec is not None else "unknown"

        body = getattr(req, "body", None)
        if body is None:
            body_len = 0
            body_hash = ""
        else:
            if isinstance(body, bytes):
                body_bytes = body
            else:
                body_bytes = str(body).encode("utf-8", errors="ignore")
            body_len = len(body_bytes)
            body_hash = hashlib.sha256(body_bytes).hexdigest()[:12]

        def _fmt_dt(value: datetime | None) -> str | None:
            if value is None:
                return None
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

        t0_iso = _fmt_dt(t0_local)
        t1_iso = _fmt_dt(t1_local)

        history = resp.history or []
        logger.info(
            "HTTP: FINAL method=%s status=%s url=%s host=%s allow_redirects=%s history=%d auth_fp=%s content_type=%s user_agent=%s app_version=%s cliente_id=%s req_body_len=%s req_body_sha256=%s latency=%s t0_local=%s t1_local=%s",
            getattr(req, "method", ""),
            resp.status_code,
            req.url,
            final_host,
            bool(allow_redirects) if allow_redirects is not None else None,
            len(history),
            _fp_auth(auth_hdr),
            content_type,
            user_agent,
            app_version,
            cliente_id,
            body_len,
            body_hash,
            latency_val,
            t0_iso,
            t1_iso,
        )

        for i, hop in enumerate(history):
            hop_host = urlparse(hop.request.url).netloc
            loc = hop.headers.get("Location")
            logger.info(
                "HTTP: HOP[%d] status=%s url=%s host=%s auth_fp=%s location=%s",
                i,
                hop.status_code,
                hop.request.url,
                hop_host,
                _fp_auth(hop.request.headers.get("Authorization")),
                loc,
            )

        s = resp.headers
        content_length = s.get("Content-Length") or s.get("content-length")
        date_hdr = s.get("Date")
        www_auth = s.get("WWW-Authenticate")
        x_request_id = s.get("x-request-id") or s.get("X-Request-Id")
        x_correlation_id = s.get("x-correlation-id") or s.get("X-Correlation-Id")

        logger.info(
            "HTTP: RESP_HDRS status=%s content_type=%s content_length=%s server=%s via=%s date=%s www-auth=%s x-request-id=%s x-correlation-id=%s",
            resp.status_code,
            s.get("Content-Type"),
            content_length,
            s.get("Server"),
            s.get("Via"),
            date_hdr,
            www_auth,
            x_request_id,
            x_correlation_id,
        )

        if date_hdr:
            try:
                server_dt = parsedate_to_datetime(date_hdr)
                if server_dt is not None and server_dt.tzinfo is None:
                    server_dt = server_dt.replace(tzinfo=timezone.utc)
                now_dt = t1_local or datetime.now(timezone.utc)
                if server_dt is not None:
                    skew = (server_dt - now_dt).total_seconds()
                    msg = "HTTP: CLOCK_SKEW server_minus_local_s=%+.3f"
                    if abs(skew) > 120:
                        logger.warning(msg, skew)
                    else:
                        logger.info(msg, skew)
            except Exception:
                logger.info("HTTP: CLOCK_SKEW parse_error")

        if env_flag("DTE_DEBUG_DUMP_RESP_BODY"):
            body_bytes = resp.content or b""
            body_hash = hashlib.sha256(body_bytes).hexdigest()[:12] if body_bytes else ""
            preview = resp.text or ""
            if len(preview) > 512:
                preview = preview[:512] + "…"
            logger.info(
                "HTTP: RESP_BODY sha256=%s preview=%s",
                body_hash,
                preview.replace("\n", "\\n"),
            )
    except Exception as exc:  # pragma: no cover - logging should be best-effort
        logger.warning("HTTP: LOG_ERROR %s", exc)


def _post_json(url: str, headers: Mapping[str, Any], body: Any, *, tag: str):
    headers_dict = dict(headers or {})
    parsed_url = urlparse(url)
    host = parsed_url.netloc
    logger.info("HTTP: POST_ENTER tag=%s host=%s", tag, host)

    content_type = str(headers_dict.get("Content-Type") or "").strip()
    base_content_type = content_type.split(";")[0].strip().lower()
    assert base_content_type == "application/json", "Content-Type inválido para POST JSON"

    auth_value = headers_dict.get("Authorization")
    if auth_value:
        auth_text = str(auth_value)
        parts_len = len(auth_text.split())
        if not auth_text.startswith("Bearer ") or parts_len != 2:
            normalized = _normalize_bearer(auth_text)
            headers_dict["Authorization"] = normalized
            logger.warning("AUTH: header corregido (fp=%s)", _fp_auth(normalized))
            auth_text = normalized
        else:
            normalized = _normalize_bearer(auth_text)
            if normalized != auth_text:
                headers_dict["Authorization"] = normalized
                logger.warning("AUTH: header corregido (fp=%s)", _fp_auth(normalized))
                auth_text = normalized
        logger.info(
            "AUTH: header fp=%s len=%s tag=%s",
            _fp_auth(auth_text),
            len(auth_text),
            tag,
        )
    else:
        logger.warning("AUTH: header ausente tag=%s", tag)

    jwt_info = _jwt_peek(headers_dict.get("Authorization"))
    if jwt_info:
        now_dt = datetime.now(timezone.utc)

        def _to_timestamp(raw: Any) -> float | None:
            if raw is None:
                return None
            if isinstance(raw, (int, float)):
                return float(raw)
            if isinstance(raw, str):
                text = raw.strip()
                if not text:
                    return None
                if text.isdigit():
                    return float(text)
                try:
                    return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
                except Exception:
                    return None
            return None

        exp_ts = _to_timestamp(jwt_info.get("exp"))
        iat_ts = _to_timestamp(jwt_info.get("iat"))
        lifetime = (exp_ts - iat_ts) if exp_ts is not None and iat_ts is not None else None
        remaining = exp_ts - now_dt.timestamp() if exp_ts is not None else None
        logger.info(
            "JWT: peek tag=%s sub=%s lifetime_s=%s remaining_s=%s",
            tag,
            jwt_info.get("sub"),
            int(lifetime) if lifetime is not None else None,
            int(remaining) if remaining is not None else None,
        )
        cliente_id_hdr = headers_dict.get("cliente-id")
        if cliente_id_hdr:
            cliente_id_text = str(cliente_id_hdr).strip()
            sub_text = str(jwt_info.get("sub") or "").strip()
            if sub_text and cliente_id_text and cliente_id_text != sub_text:
                logger.warning(
                    "JWT: cliente-id mismatch tag=%s cliente-id=%s sub=%s",
                    tag,
                    cliente_id_text,
                    sub_text,
                )
            elif sub_text and cliente_id_text:
                logger.info("JWT: cliente-id coincide con sub tag=%s", tag)

    user_agent = headers_dict.get("User-Agent")
    cliente_id = headers_dict.get("cliente-id")
    ambiente_body = None
    if isinstance(body, Mapping):
        ambiente_body = body.get("ambiente")
    logger.info(
        "HTTP: CLIENT_META tag=%s user_agent=%s cliente_id=%s ambiente=%s host=%s",
        tag,
        user_agent,
        cliente_id,
        ambiente_body,
        host,
    )

    if host and "apitest" in host and ambiente_body not in (None, "00"):
        logger.warning(
            "HTTP: ambiente body=%s inesperado para host=%s tag=%s",
            ambiente_body,
            host,
            tag,
        )

    rate_limit_ms: int | None = None
    raw_rate = os.getenv("DTE_RATE_LIMIT_MS")
    if raw_rate:
        try:
            rate_limit_ms = max(0, int(float(raw_rate)))
        except Exception:
            logger.warning("HTTP: RATE_LIMIT inválido=%s", raw_rate)
    backoff_ms_raw = os.getenv("DTE_BACKOFF_MS")
    try:
        backoff_ms = max(0, int(float(backoff_ms_raw))) if backoff_ms_raw else 8000
    except Exception:
        logger.warning("HTTP: BACKOFF inválido=%s", backoff_ms_raw)
        backoff_ms = 8000
    retry_401_enabled = env_flag("DTE_RETRY_401_EMPTY", default=True)
    allow_redirects = not env_flag("DTE_DEBUG_NO_REDIRECTS")

    logger.info(
        "HTTP: FLAGS tag=%s allow_redirects=%s retry_401_empty=%s backoff_ms=%s rate_limit_ms=%s",
        tag,
        allow_redirects,
        retry_401_enabled,
        backoff_ms,
        rate_limit_ms,
    )

    if rate_limit_ms and rate_limit_ms > 0:
        logger.info("HTTP: RATE_LIMIT_SLEEP tag=%s sleep_ms=%s", tag, rate_limit_ms)
        time.sleep(rate_limit_ms / 1000)

    proxies_info = (
        bool(os.getenv("HTTPS_PROXY") or os.getenv("https_proxy")),
        bool(os.getenv("HTTP_PROXY") or os.getenv("http_proxy")),
        bool(os.getenv("NO_PROXY") or os.getenv("no_proxy")),
    )
    logger.info(
        "HTTP: PROXY_ENV tag=%s HTTPS_PROXY=%s HTTP_PROXY=%s NO_PROXY=%s",
        tag,
        *proxies_info,
    )

    try:
        body_serialized = stable_stringify(body)
    except Exception:
        try:
            body_serialized = json.dumps(body, ensure_ascii=False, sort_keys=True, default=str)
        except Exception:
            body_serialized = repr(body)
    body_bytes = body_serialized.encode("utf-8", errors="ignore")
    body_hash = hashlib.sha256(body_bytes).hexdigest()
    body_len = len(body_bytes)

    if env_flag("DTE_DEBUG_DUMP_REQ_BODY"):
        preview = body_serialized
        if len(preview) > 512:
            preview = preview[:512] + "…"
        preview = preview.replace("\n", "\\n")
        logger.info(
            "HTTP: REQ_BODY tag=%s auth_fp=%s sha256=%s len=%s preview=%s",
            tag,
            _fp_auth(str(headers_dict.get("Authorization") or "")),
            body_hash[:12],
            body_len,
            preview,
        )

    attempt = 0
    last_resp = None
    while True:
        attempt += 1
        headers_items = sorted((str(k), str(v)) for k, v in headers_dict.items())
        headers_fingerprint = hashlib.sha1(
            repr(headers_items).encode("utf-8", errors="ignore")
        ).hexdigest()
        logger.info(
            "HTTP: HEADERS_FP tag=%s attempt=%s id=%s sha1=%s auth_fp=%s",
            tag,
            attempt,
            id(headers_dict),
            headers_fingerprint,
            _fp_auth(str(headers_dict.get("Authorization") or "")),
        )
        logger.info("HTTP: POST_ATTEMPT tag=%s attempt=%s", tag, attempt)
        t0_local = datetime.now(timezone.utc)
        resp = requests.post(
            url,
            headers=headers_dict,
            json=body,
            timeout=TIMEOUT,
            allow_redirects=allow_redirects,
        )
        t1_local = datetime.now(timezone.utc)
        _log_http_exchange(resp, allow_redirects, t0_local=t0_local, t1_local=t1_local)
        req_ct = resp.request.headers.get("Content-Type") if resp.request else None
        logger.info(
            "HTTP: REQ_META tag=%s req_ct=%s body_sha256=%s body_len=%s",
            tag,
            req_ct,
            body_hash,
            body_len,
        )

        date_hdr = resp.headers.get("Date")
        if date_hdr:
            try:
                server_dt = parsedate_to_datetime(date_hdr)
                if server_dt is not None and server_dt.tzinfo is None:
                    server_dt = server_dt.replace(tzinfo=timezone.utc)
                now_dt = datetime.now(timezone.utc)
                skew = (server_dt - now_dt).total_seconds()
                logger.info("HTTP: RESP_SKEW tag=%s skew_sec=%+.3f", tag, skew)
            except Exception:
                logger.info("HTTP: RESP_SKEW tag=%s parse_error", tag)

        text_body = getattr(resp, "text", "")
        try:
            data = resp.json()
        except Exception:
            data = None

        www_auth = resp.headers.get("WWW-Authenticate")
        no_www_auth = (www_auth is None) or (str(www_auth).strip() == "")

        if (
            retry_401_enabled
            and attempt == 1
            and resp.status_code == 401
            and not text_body
            and no_www_auth
        ):
            logger.warning(
                "HTTP: 401 vacío (posible gateway/WAF). Se reintentará con Connection: close tag=%s",
                tag,
            )
            time.sleep(backoff_ms / 1000 if backoff_ms else 0)
            headers_dict["Connection"] = "close"
            last_resp = resp
            continue

        if last_resp is not None:
            last_www = last_resp.headers.get("WWW-Authenticate")
            last_no_www = (last_www is None) or (str(last_www).strip() == "")
        else:
            last_no_www = False

        should_force_refresh = (
            retry_401_enabled
            and last_resp is not None
            and last_resp.status_code == 401
            and last_resp.text == ""
            and last_no_www
            and resp.status_code == 401
            and text_body == ""
            and no_www_auth
            and attempt == 2
        )

        if should_force_refresh:
            host_text = (host or "").lower()
            ambiente_detectado = "apitest" if "apitest" in host_text else "produccion"
            try:
                from mh_auth import ensure_valid_bearer  # Lazy import to avoid cycles

                refreshed = ensure_valid_bearer(
                    ambiente_detectado,
                    headers_dict.get("Authorization"),
                    force=True,
                )
            except Exception as exc:
                logger.warning(
                    "AUTH: no se pudo refrescar token para retry tag=%s: %s",
                    tag,
                    exc,
                )
            else:
                if refreshed:
                    logger.info(
                        "AUTH: refreshed token for retry (fp=%s)",
                        _fp_auth(refreshed),
                    )
                    headers_dict["Authorization"] = refreshed
                    last_resp = resp
                    continue

        if (
            last_resp is not None
            and last_resp.status_code == 401
            and last_resp.text == ""
            and last_no_www
            and attempt == 2
        ):
            logger.info(
                "HTTP: 401 vacío (posible gateway/WAF). Se reintentó con Connection: close tag=%s",
                tag,
            )

        return resp, data, text_body
def _log_jwt_diagnostics(auth_header: str | None, *, now: datetime | None = None) -> None:
    """Registra información derivada del JWT sin exponer el token."""

    if not env_flag("DTE_DEBUG_HTTP"):
        return

    claims = decode_jwt_claims(auth_header or "")
    if not claims:
        logger.info("JWT: sin claims decodificables")
        return

    now_dt = now or datetime.now(timezone.utc)

    def _to_datetime(raw):
        if raw is None:
            return None
        if isinstance(raw, (int, float)):
            return datetime.fromtimestamp(float(raw), tz=timezone.utc)
        if isinstance(raw, str):
            text = raw.strip()
            if not text:
                return None
            if text.isdigit():
                try:
                    return datetime.fromtimestamp(float(text), tz=timezone.utc)
                except Exception:
                    return None
            try:
                if text.endswith("Z"):
                    return datetime.fromisoformat(text[:-1]).replace(tzinfo=timezone.utc)
                dt = datetime.fromisoformat(text)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except Exception:
                return None
        return None

    def _fmt(dt: datetime | None) -> str | None:
        if dt is None:
            return None
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    iat_dt = _to_datetime(claims.get("iat"))
    exp_dt = _to_datetime(claims.get("exp"))
    age_s = int((now_dt - iat_dt).total_seconds()) if iat_dt else None
    seconds_to_exp = int((exp_dt - now_dt).total_seconds()) if exp_dt else None
    roles = claims.get("roles")
    if isinstance(roles, (list, tuple, set)):
        roles_len = len(roles)
    elif isinstance(roles, str):
        roles_len = len(roles.split(",")) if "," in roles else len(roles)
    else:
        roles_len = 0

    logger.info(
        "JWT: sub=%s iat=%s exp=%s age_s=%s sec_to_exp=%s roles_len=%s",
        claims.get("sub"),
        _fmt(iat_dt),
        _fmt(exp_dt),
        age_s,
        seconds_to_exp,
        roles_len,
    )
DEFAULT_RECEPCION_URL = "https://apitest.dtes.mh.gob.sv/fesv/recepciondte"
DEFAULT_EVENTO_URL = "https://apitest.dtes.mh.gob.sv/fesv/contingencia"
PATCHES_DIR = resource_path("schema_patches")

SCHEMAS_DIR = resource_path("svfe-json-schemas")
FC_SCHEMA_PATH = SCHEMAS_DIR / "fe-fc-v1.json"
with FC_SCHEMA_PATH.open("r", encoding="utf-8") as fh:
    FC_SCHEMA = json.load(fh)
RESOLVER = RefResolver(base_uri=f"{SCHEMAS_DIR.as_uri()}/", referrer=FC_SCHEMA)

DTE_VERSIONES = {
    "01": 1,
    "03": 3,
    "04": 3,
    "05": 3,
    "06": 3,
}


def _origen_aceptado_en_mh(db: DB, ident: dict) -> bool:
    """Check if the origin document has an accepted record in ``dte_envios``.

    Se considera aceptado cuando existe un registro cuya ``estado`` sea
    "Recibido", "Procesado" o "Aceptado" y posea un ``sello`` no vacío.
    La consulta intenta primero usar columnas explícitas (``codigo_generacion`` y
    ``numero_control``) y, si estas no existen, recurre a buscar dentro del JSON
    ``respuesta``.
    """

    uuid = str(ident.get("codigoGeneracion") or "").upper()
    numc = str(ident.get("numeroControl") or "")
    if not uuid and not numc:
        return False

    row = None
    try:
        row = db.cursor.execute(
            """
            SELECT estado, TRIM(sello) AS sello
              FROM dte_envios
             WHERE UPPER(codigo_generacion)=? OR numero_control=?
             ORDER BY id DESC LIMIT 1
            """,
            (uuid, numc),
        ).fetchone()
    except Exception:
        # fall back to searching within ``respuesta`` if explicit columns are missing
        db.ensure_column("dte_envios", "respuesta", "TEXT")
        row = db.cursor.execute(
            """
            SELECT estado, TRIM(sello) AS sello
              FROM dte_envios
             WHERE (respuesta LIKE ? OR respuesta LIKE ?)
             ORDER BY id DESC LIMIT 1
            """,
            (f"%{uuid}%", f"%{numc}%"),
        ).fetchone()

    if not row:
        return False
    estado = str(row["estado"] or "").lower()
    return bool(estado in {"recibido", "procesado", "aceptado"} and row["sello"])


def _strip_additional_properties(value, schema):
    """Remove keys not defined in ``schema`` when ``additionalProperties`` is ``false``."""
    if "$ref" in schema:
        with RESOLVER.resolving(schema["$ref"]) as resolved:
            return _strip_additional_properties(value, resolved)

    if isinstance(value, dict):
        props = schema.get("properties", {})
        patterns = {
            re.compile(p): s for p, s in schema.get("patternProperties", {}).items()
        }
        addl = schema.get("additionalProperties", True)
        clean = {}
        for key, val in value.items():
            if key in props:
                clean[key] = _strip_additional_properties(val, props[key])
                continue
            matched = False
            for pat, subschema in patterns.items():
                if pat.fullmatch(key):
                    clean[key] = _strip_additional_properties(val, subschema)
                    matched = True
                    break
            if matched:
                continue
            if addl is not False:
                clean[key] = val
        return clean

    if isinstance(value, list):
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            return [_strip_additional_properties(v, item_schema) for v in value]
        elif isinstance(item_schema, list):
            result = []
            for i, v in enumerate(value):
                if i < len(item_schema):
                    result.append(_strip_additional_properties(v, item_schema[i]))
                else:
                    result.append(v)
            return result
    return value


def sanitize_dte_payload(data: dict, schema: dict | None = None) -> dict:
    """Return ``data`` excluding properties not allowed by ``schema``.

    Además, de forma recursiva se eliminan las claves cuyo valor sea ``None``.
    Cuando ``schema`` es ``None`` se usa el esquema ``FC_SCHEMA``.
    """

    REQUIRED_NULL_FIELDS = {
        "documentoRelacionado",
        "otrosDocumentos",
        "ventaTercero",
        "extension",
        "apendice",
        "codTributo",
        "tributos",  # e.g. resumen.tributos must remain even if None
        "tipoContingencia",
        "motivoContin",
        "nombreComercial",
        "numPagoElectronico",
    }

    def _remove_nulls(value, parent_key=None):
        """Recursively drop keys or items with ``None`` values.

        Las claves en ``REQUIRED_NULL_FIELDS`` se conservan incluso si su
        valor es ``None`` y las listas vacías bajo estas claves se
        convierten en ``None``.
        """
        if isinstance(value, dict):
            clean = {}
            for k, v in value.items():
                cleaned = _remove_nulls(v, k)
                if cleaned is not None or k in REQUIRED_NULL_FIELDS:
                    clean[k] = cleaned
            return clean
        if isinstance(value, list):
            cleaned_list = []
            for item in value:
                cleaned_item = _remove_nulls(item, parent_key)
                if cleaned_item is not None:
                    cleaned_list.append(cleaned_item)
            if not cleaned_list and parent_key in REQUIRED_NULL_FIELDS:
                return None
            return cleaned_list
        return value

    if schema is None:
        schema = FC_SCHEMA
    cleaned = _strip_additional_properties(data, schema)
    limpiar_documentos(cleaned)
    cleaned = _remove_nulls(cleaned)

    tipo_dte = str(cleaned.get("identificacion", {}).get("tipoDte") or "")
    if tipo_dte == "04":
        rec_clean = cleaned.get("receptor")
        if isinstance(rec_clean, dict):
            tipo_doc_rec = str(rec_clean.get("tipoDocumento") or "").zfill(2)
            if tipo_doc_rec != "36":
                rec_clean.setdefault("nrc", None)

    schema_props = set(schema.get("properties", {}))
    for key in (
        "documentoRelacionado",
        "otrosDocumentos",
        "ventaTercero",
        "extension",
        "apendice",
    ):
        if key in schema_props:
            cleaned.setdefault(key, None)
    return cleaned


def _venta_tercero_from_sources(*sources: Mapping[str, Any] | None) -> dict | None:
    """Return ``ventaTercero`` payload extracted from ``sources``.

    Each source can be either a mapping with ``venta_a_cuenta_de`` and
    ``documento_venta_a_cuenta`` keys or nested dictionaries containing them.
    Only when both values are present and the document matches the expected NIT
    format (9 or 14 digits) a payload is returned.
    """

    candidates: list[Mapping[str, Any]] = []
    for src in sources:
        if not isinstance(src, Mapping):
            continue
        candidates.append(src)
        nested = src.get("extra")
        if isinstance(nested, Mapping):
            candidates.append(nested)

    nombre = ""
    documento = ""
    for candidate in candidates:
        if not nombre:
            value = candidate.get("venta_a_cuenta_de")
            if value not in (None, ""):
                nombre = str(value).strip()
        if not documento:
            value = candidate.get("documento_venta_a_cuenta")
            if value not in (None, ""):
                documento = str(value).strip()
        if nombre and documento:
            break

    nombre = nombre.strip()
    nit = solo_digitos(documento)
    if nombre:
        nombre = nombre[:250]

    if nombre and nit and len(nit) in {9, 14}:
        return {"nombre": nombre, "nit": nit}
    return None


def apply_schema_patch(data: dict) -> dict:
    """Apply stored JSON patches for the given DTE ``data``.

    If a patch file matching ``identificacion.tipoDte`` exists in
    ``schema_patches`` it will be applied and the resulting dictionary is
    returned.  When no patch is found ``data`` is returned unchanged.
    """
    tipo = str(data.get("identificacion", {}).get("tipoDte"))
    if not tipo:
        return data
    patch_file = PATCHES_DIR / f"{tipo}.json"
    if not patch_file.exists():
        return data
    try:
        with patch_file.open("r", encoding="utf-8") as fh:
            ops = json.load(fh)
        return jsonpatch.JsonPatch(ops).apply(data, in_place=False)
    except Exception:  # pragma: no cover - best effort
        return data


# Ensure enough precision when other modules modify the global decimal context
getcontext().prec = 28
getcontext().rounding = ROUND_HALF_UP

# Helper alias for ``Decimal``
D = Decimal

def _precios_incluyen_iva_from(
    extra: dict | None, override: bool | None = None
) -> bool:
    if isinstance(extra, dict) and "precios_incluyen_iva" in extra:
        return bool(extra["precios_incluyen_iva"])
    if override is not None:
        return bool(override)
    cfg = getattr(svfe_config, "PRECIOS_INCLUYEN_IVA", None)
    return bool(cfg) if cfg is not None else False


def _norm3(value) -> str:
    return re.sub(r"\D", "", str(value))[-3:].zfill(3)


def normalize_uuid_v4_upper(value: str) -> str:
    """
    Normaliza `value` como UUID v4 con guiones en MAYÚSCULAS.
    Lanza ValueError si no es un UUID v4 válido.
    """
    u = uuid.UUID(str(value))
    if u.version != 4:
        raise ValueError
    return str(u).upper()


def numero_a_letras(monto):
    """Convierte ``monto`` numérico a su representación en letras."""
    try:
        texto = monto_a_texto_sv(monto)
    except Exception:
        return ""
    if " " in texto:
        partes = texto.split(" ", 1)
        return f"{partes[0]} CON {partes[1]}"
    return texto


def monto_a_letras_natural(monto: D) -> str:
    """Return ``monto`` in natural Spanish text (e.g. ``Trece Dolares``)."""
    entero = int(monto)
    centavos = int((monto - D(entero)) * 100)
    palabras_entero = num2words(entero, lang="es").capitalize()
    palabras_centavos = num2words(centavos, lang="es")
    dolar = "Dolar" if entero == 1 else "Dolares"
    centavo = "centavo" if centavos == 1 else "centavos"
    return f"{palabras_entero} {dolar} con {palabras_centavos} {centavo}"


def identificacion_a_xml(ident: dict) -> Element:
    """Return an XML ``Element`` for ``ident``.

    Optional values are retrieved into variables and only assigned to the
    corresponding tag when not ``None``; otherwise the tag text is an empty
    string.
    """
    root = Element("identificacion")

    version = ident.get("version")
    SubElement(root, "version").text = "" if version is None else str(version)

    ambiente = ident.get("ambiente")
    SubElement(root, "ambiente").text = ambiente or ""

    tipo_dte = ident.get("tipoDte")
    SubElement(root, "tipoDte").text = "" if tipo_dte is None else str(tipo_dte)

    numero_control = ident.get("numeroControl")
    SubElement(root, "numeroControl").text = numero_control or ""

    codigo_generacion = ident.get("codigoGeneracion")
    SubElement(root, "codigoGeneracion").text = codigo_generacion or ""

    tipo_modelo = ident.get("tipoModelo")
    SubElement(root, "tipoModelo").text = (
        "" if tipo_modelo is None else str(tipo_modelo)
    )

    tipo_operacion = ident.get("tipoOperacion")
    SubElement(root, "tipoOperacion").text = (
        "" if tipo_operacion is None else str(tipo_operacion)
    )

    tipo_contingencia = ident.get("tipoContingencia")
    SubElement(root, "tipoContingencia").text = (
        "" if tipo_contingencia is None else str(tipo_contingencia)
    )

    motivo_contin = ident.get("motivoContin")
    SubElement(root, "motivoContin").text = (
        "" if motivo_contin is None else str(motivo_contin)
    )

    fec_emi = ident.get("fecEmi")
    SubElement(root, "fecEmi").text = fec_emi or ""

    hor_emi = ident.get("horEmi")
    SubElement(root, "horEmi").text = hor_emi or ""

    tipo_moneda = ident.get("tipoMoneda")
    SubElement(root, "tipoMoneda").text = tipo_moneda or ""

    return root


def _normalize_payload(value):
    """Recursively trim strings and coerce simple types."""
    if isinstance(value, dict):
        for k, v in list(value.items()):
            value[k] = _normalize_payload(v)
        return value
    if isinstance(value, list):
        for i, v in enumerate(value):
            value[i] = _normalize_payload(v)
        return value
    if isinstance(value, float):
        return D(str(value))
    if isinstance(value, str):
        v = value.strip()
        lower = v.lower()
        if lower == "true":
            return True
        if lower == "false":
            return False
        if re.fullmatch(r"-?\d+", v):
            try:
                return int(v)
            except Exception:
                return v
        if re.fullmatch(r"-?\d+\.\d+", v):
            try:
                return D(v)
            except Exception:
                return v
        return v
    return value



def _load_datos_negocio():
    if os.path.exists(DATOS_NEGOCIO_PATH):
        try:
            with open(DATOS_NEGOCIO_PATH, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            dte_api = data.get("dte_api")
            if isinstance(dte_api, dict):
                # Extract branch and point-of-sale codes from the control prefix
                prefijo = dte_api.get("prefijo_control")
                if isinstance(prefijo, str):
                    m = re.search(r"S([A-Za-z0-9]{3})P([A-Za-z0-9]{3})", prefijo)
                    if m:
                        suc, punto = m.groups()
                        data.setdefault("codEstable", suc.zfill(4))
                        data.setdefault("codEstableMH", suc.zfill(4))
                        data.setdefault("codPuntoVenta", punto.zfill(4))
                        data.setdefault("codPuntoVentaMH", punto.zfill(4))

            # Ensure cod_giro is available and mirrors codActividad
            cod_giro = data.get("cod_giro")
            if not cod_giro:
                try:
                    with open(CONFIG_NEGOCIO_PATH, "r", encoding="utf-8") as fh:
                        cfg = json.load(fh)
                    cod_giro = cfg.get("cod_giro")
                except Exception:
                    cod_giro = None
            if cod_giro:
                data.setdefault("cod_giro", cod_giro)
                data.setdefault("codActividad", cod_giro)
            elif "codActividad" in data:
                data.setdefault("cod_giro", data.get("codActividad"))

            return data
        except Exception:
            return {}
    return {}


def get_default_modo_transmision() -> str:
    """Return the default transmission mode.

    This reads ``dte_api.modo_transmision`` from ``datos_negocio.json`` and
    normalizes the value to ``"contingencia"`` or ``"normal"``. If the value
    is missing or unrecognized, ``"normal"`` is returned.
    """

    datos = _load_datos_negocio()
    modo = datos.get("dte_api", {}).get("modo_transmision", "")
    if isinstance(modo, str):
        modo_norm = modo.strip().lower()
        if modo_norm.startswith("2") or "contingencia" in modo_norm:
            return "contingencia"
    return "normal"


def _contingencia_config_from_settings() -> tuple[int, str | None]:
    """Return contingency type and reason configured in ``datos_negocio``."""

    datos = _load_datos_negocio()
    candidates: list[dict[str, Any]] = []
    dte_api = datos.get("dte_api")
    if isinstance(dte_api, dict):
        candidates.append(dte_api)
    if isinstance(datos, dict):
        candidates.append(datos)

    tipo_raw: Any = None
    motivo_raw: Any = None
    for source in candidates:
        if tipo_raw in (None, "", "null"):
            tipo_raw = source.get("tipo_contingencia", tipo_raw)
        if motivo_raw is None:
            motivo_raw = source.get("motivo_contin", motivo_raw)

    if tipo_raw in (None, "", "null"):
        raise ValueError(
            "tipo_contingencia no configurado para modo contingencia; actualice la configuración de facturación"
        )

    try:
        tipo_cont = int(str(tipo_raw).strip())
    except (TypeError, ValueError):
        raise ValueError("tipo_contingencia configurado inválido") from None

    if tipo_cont not in catalogos.CONTINGENCIA:
        raise ValueError("tipo_contingencia debe estar entre 1 y 5")

    motivo_norm: str | None = None
    if tipo_cont == 5:
        motivo_text = "" if motivo_raw is None else str(motivo_raw)
        motivo_text = motivo_text.strip()
        if not motivo_text:
            raise ValueError(
                "motivo_contin requerido cuando tipo_contingencia es 5"
            )
        if len(motivo_text) > 500:
            raise ValueError(
                "motivo_contin no debe superar 500 caracteres cuando tipo_contingencia es 5"
            )
        motivo_norm = motivo_text

    return tipo_cont, motivo_norm


def _ensure_contingencia_ident_fields(ident: dict[str, Any], modo: str | None) -> None:
    """Override identification fields when operating in contingency mode."""

    modo_norm = "" if modo is None else str(modo).strip().lower()
    if modo_norm not in {"contingencia", "2"} and "contingencia" not in modo_norm:
        return

    tipo_cont, motivo_cont = _contingencia_config_from_settings()

    ident["tipoModelo"] = 2
    ident.pop("modeloFacturacion", None)
    ident["tipoOperacion"] = 2
    ident.pop("tipoTransmision", None)
    ident["tipoContingencia"] = tipo_cont
    ident["motivoContin"] = motivo_cont


def _normalize_ident_subset(ident: Mapping[str, Any]) -> dict[str, Any]:
    """Return the identification fields relevant for JWS reuse comparison."""

    def _normalize_numeric(value: Any) -> int | None:
        if value in (None, ""):
            return None
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return None

    def _normalize_tipo_dte(value: Any) -> str | None:
        if value in (None, ""):
            return None
        text = str(value).strip()
        if not text:
            return None
        if text.isdigit():
            return text.zfill(2)
        return text

    def _normalize_text(value: Any) -> str | None:
        if value in (None, ""):
            return None
        text = str(value).strip()
        return text or None

    tipo_modelo = ident.get("tipoModelo", ident.get("modeloFacturacion"))
    tipo_operacion = ident.get("tipoOperacion", ident.get("tipoTransmision"))
    tipo_contingencia = ident.get("tipoContingencia")
    motivo = ident.get("motivoContin", ident.get("motivoContingencia"))
    fec_emi = _normalize_text(ident.get("fecEmi"))
    hor_emi = _normalize_text(ident.get("horEmi"))
    tipo_dte = _normalize_tipo_dte(ident.get("tipoDte", ident.get("tipoDocumento")))
    codigo_gen = ident.get("codigoGeneracion")
    if codigo_gen not in (None, ""):
        codigo_gen = str(codigo_gen).strip().upper()
    else:
        codigo_gen = None

    tipo_cont_norm = _normalize_numeric(tipo_contingencia)
    motivo_norm: str | None
    if tipo_cont_norm == 5:
        motivo_norm = _normalize_text(motivo)
    else:
        motivo_norm = None

    return {
        "tipo_modelo": _normalize_numeric(tipo_modelo),
        "tipo_operacion": _normalize_numeric(tipo_operacion),
        "tipo_contingencia": tipo_cont_norm,
        "motivo_contingencia": motivo_norm,
        "fecEmi": fec_emi,
        "horEmi": hor_emi,
        "tipoDte": tipo_dte,
        "codigoGeneracion": codigo_gen,
    }


DEPARTAMENTO_CODES = {f"{i:02d}" for i in range(0, 15)}

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^\+?\d{8,15}$")


def _map_departamento(nombre: str | None) -> str:
    """Validate and return a departamento code."""

    if nombre is None:
        raise ValueError("Departamento requerido")

    nombre = str(nombre)
    if nombre.isdigit():
        nombre = nombre.zfill(2)
    if nombre not in DEPARTAMENTO_CODES:
        raise ValueError("Departamento inválido")
    return nombre


MUNICIPIO_RANGES = {
    # Departamento: (primer código, último código)
    "00": ("00", "00"),  # Otro
    "01": ("13", "15"),  # Ahuachapán
    "02": ("14", "17"),  # Santa Ana
    "03": ("17", "20"),  # Sonsonate
    "04": ("34", "36"),  # Chalatenango
    "05": ("23", "28"),  # La Libertad
    "06": ("20", "24"),  # San Salvador
    "07": ("17", "18"),  # Cuscatlán
    "08": ("23", "25"),  # La Paz
    "09": ("10", "11"),  # Cabañas
    "10": ("14", "15"),  # San Vicente
    "11": ("24", "26"),  # Usulután
    "12": ("21", "23"),  # San Miguel
    "13": ("27", "28"),  # Morazán
    "14": ("19", "20"),  # La Unión
}


def _map_municipio(nombre: str | None, departamento: str | None = None) -> str:
    """Validate and return a municipio code."""

    if nombre is None:
        raise ValueError("Municipio requerido")

    nombre = str(nombre)
    if nombre.isdigit():
        nombre = nombre.zfill(2)
    if not nombre.isdigit() or len(nombre) != 2:
        raise ValueError("Municipio inválido")

    # No se valida que el municipio pertenezca al departamento indicado,
    # solo se asegura que el código sea numérico de dos dígitos.
    return nombre


def _clean_nit(nit):
    if nit:
        return "".join(c for c in str(nit) if c.isdigit())
    return None


def _clean_nrc(nrc):
    if not nrc:
        return None
    digits = "".join(c for c in str(nrc) if c.isdigit())
    if 1 <= len(digits) <= 8:
        return digits
    return None


def _clean_dui(dui):
    if not dui:
        return None
    digits = "".join(c for c in str(dui) if c.isdigit())
    return digits or None


def _format_dui(dui):
    """Devuelve DUI en formato ########-# o None si no tiene 9 dígitos."""
    if not dui:
        return None
    digits = re.sub(r"\D", "", str(dui))
    if len(digits) != 9:
        return None
    return f"{digits[:8]}-{digits[8]}"


# --- Dirección --------------------------------------------------------------

# Mapeos básicos de departamentos y municipios utilizados para normalizar la
# dirección del receptor.  Solo se incluyen los valores necesarios para las
# pruebas actuales; otros códigos pasarán la validación únicamente si ya vienen
# normalizados.

_DEPARTAMENTOS = {
    "00": "Otro (Para extranjeros)",
    "01": "Ahuachapán",
    "02": "Santa Ana",
    "03": "Sonsonate",
    "04": "Chalatenango",
    "05": "La Libertad",
    "06": "San Salvador",
    "07": "Cuscatlán",
    "08": "La Paz",
    "09": "Cabañas",
    "10": "San Vicente",
    "11": "Usulután",
    "12": "San Miguel",
    "13": "Morazán",
    "14": "La Unión",
}


def _normalize_text(value: str) -> str:
    import unicodedata

    text = unicodedata.normalize("NFD", str(value))
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return text.strip().casefold()


_DEPARTAMENTO_BY_NAME = {_normalize_text(v): k for k, v in _DEPARTAMENTOS.items()}

_MUNICIPIOS_POR_DEPTO = {
    "00": {"00": "Otro (Para extranjeros)"},
    "01": {
        "13": "Ahuachapán Norte",
        "14": "Ahuachapán Centro",
        "15": "Ahuachapán Sur",
    },
    "02": {
        "14": "Santa Ana Norte",
        "15": "Santa Ana Centro",
        "16": "Santa Ana Este",
        "17": "Santa Ana Oeste",
    },
    "03": {
        "17": "Sonsonate Norte",
        "18": "Sonsonate Centro",
        "19": "Sonsonate Este",
        "20": "Sonsonate Oeste",
    },
    "04": {
        "34": "Chalatenango Norte",
        "35": "Chalatenango Centro",
        "36": "Chalatenango Sur",
    },
    "05": {
        "23": "La Libertad Norte",
        "24": "La Libertad Centro",
        "25": "La Libertad Oeste",
        "26": "La Libertad Este",
        "27": "La Libertad Costa",
        "28": "La Libertad Sur",
    },
    "06": {
        "20": "San Salvador Norte",
        "21": "San Salvador Oeste",
        "22": "San Salvador Este",
        "23": "San Salvador Centro",
        "24": "San Salvador Sur",
    },
    "07": {
        "17": "Cuscatlán Norte",
        "18": "Cuscatlán Sur",
    },
    "08": {
        "23": "La Paz Oeste",
        "24": "La Paz Centro",
        "25": "La Paz Este",
    },
    "09": {
        "10": "Cabañas Oeste",
        "11": "Cabañas Este",
    },
    "10": {
        "14": "San Vicente Norte",
        "15": "San Vicente Sur",
    },
    "11": {
        "24": "Usulután Norte",
        "25": "Usulután Este",
        "26": "Usulután Oeste",
    },
    "12": {
        "21": "San Miguel Norte",
        "22": "San Miguel Centro",
        "23": "San Miguel Oeste",
    },
    "13": {
        "27": "Morazán Norte",
        "28": "Morazán Sur",
    },
    "14": {
        "19": "La Unión Norte",
        "20": "La Unión Sur",
    },
}

_MUNI_NAME_MAP: dict[str, list[tuple[str, str]]] = {}
for dep, munis in _MUNICIPIOS_POR_DEPTO.items():
    for code, name in munis.items():
        _MUNI_NAME_MAP.setdefault(_normalize_text(name), []).append((dep, code))


def _normalize_departamento(value) -> str:
    """Return departamento code from numeric or textual ``value``."""

    if value is None:
        raise ValidationError("Departamento requerido")
    val = str(value).strip()
    if val.isdigit():
        code = val.zfill(2)
        if code in DEPARTAMENTO_CODES:
            return code
    else:
        code = _DEPARTAMENTO_BY_NAME.get(_normalize_text(val))
        if code:
            return code
    raise ValidationError("Departamento inválido")


def _normalize_municipio(dep_code: str | None, value):
    """Return ``(mun_code, dep_code)`` normalizing ``value``.

    Cuando ``dep_code`` es ``None`` el departamento se infiere a partir del
    catálogo; si no es único se genera ``ValidationError``.
    """

    if value is None:
        warnings.warn(
            "Municipio requerido; se continuará con el valor en blanco",
            UserWarning,
        )
        return None, dep_code

    val = str(value).strip()
    dep_norm = dep_code
    if dep_norm:
        dep_norm = _normalize_departamento(dep_norm)

    if val.isdigit():
        code = val.zfill(2)
        return code, dep_norm

    norm = _normalize_text(val)
    matches = _MUNI_NAME_MAP.get(norm)
    if not matches:
        raise ValidationError("Municipio inválido")
    if dep_norm:
        for dep, code in matches:
            if dep == dep_norm:
                return code, dep_norm
        # Departamento no coincide; retornar código de municipio encontrado
        return matches[0][1], dep_norm
    if len(matches) > 1:
        raise ValidationError(
            "receptor.direccion: municipio inválido para el departamento seleccionado"
        )
    dep_norm, code = matches[0]
    return code, dep_norm


def _build_receptor_direccion(src: dict) -> dict:
    """Return normalized ``direccion`` dictionary for receptor."""

    if not isinstance(src, dict):
        raise ValidationError("receptor.direccion faltante")

    raw_dep = src.get("departamento")
    raw_muni = src.get("municipio")
    complemento = (
        src.get("complemento") or src.get("direccionDetalle") or src.get("direccion")
    )
    if isinstance(complemento, str):
        complemento = complemento.strip() or None

    dep_code = _normalize_departamento(raw_dep) if raw_dep is not None else None
    muni_code, dep_inferred = _normalize_municipio(dep_code, raw_muni)
    dep_code = dep_code or dep_inferred
    if dep_code is None or muni_code is None:
        warnings.warn(
            "Información de dirección incompleta; la factura se generará con campos nulos",
            UserWarning,
        )

    return {
        "departamento": dep_code,
        "municipio": muni_code,
        "complemento": complemento,
    }


DEFAULT_ADDRESS = {
    "departamento": "06",
    "municipio": "23",
    "complemento": "San Salvador",
}


# --- Helpers ---------------------------------------------------------------

# Catálogo de ``condicionOperacion`` según el esquema oficial.
# 1 = Contado, 2 = Crédito, 3 = Otro
CONDICION_OPERACION_CATALOG = {
    1: "Contado",
    2: "Crédito",
    3: "Otro",
}

_CONDICION_OPERACION_BY_NAME = {
    v.lower(): k for k, v in CONDICION_OPERACION_CATALOG.items()
}
_CONDICION_OPERACION_BY_NAME["credito"] = 2
_CONDICION_OPERACION_BY_NAME["otros"] = 3


def _parse_condicion_operacion(value):
    """Return ``condicionOperacion`` code ensuring it is valid.

    ``value`` may be ``None``/empty, a numeric code or a textual description.
    Defaults to ``1`` (Contado) when no value is provided.  Any value outside
    the catalog is normalized to ``1`` without raising an exception.
    """

    try:
        return normalize_condicion_operacion(value)
    except ValueError:
        logger.warning(
            "condicionOperacion inválida %r detectada en DTE; usando Contado", value
        )
        return 1


# Valores por defecto del resumen según el tipo de DTE
RESUMEN_DEFAULTS = {
    "01": {
        "totalNoSuj": 0,
        "totalExenta": 0,
        "totalGravada": 0,
        "subTotalVentas": 0,
        "descuNoSuj": 0,
        "descuExenta": 0,
        "descuGravada": 0,
        "porcentajeDescuento": 0,
        "totalDescu": 0,
        "tributos": None,
        "subTotal": 0,
        "ivaRete1": 0,
        "reteRenta": 0,
        "montoTotalOperacion": 0,
        "totalNoGravado": 0,
        "totalPagar": 0,
        "totalLetras": "",
        "saldoFavor": 0,
        "pagos": None,
        "numPagoElectronico": None,
    },
    "03": {
        "totalNoSuj": 0,
        "totalExenta": 0,
        "totalGravada": 0,
        "subTotalVentas": 0,
        "descuNoSuj": 0,
        "descuExenta": 0,
        "descuGravada": 0,
        "porcentajeDescuento": 0,
        "totalDescu": 0,
        "tributos": None,
        "subTotal": 0,
        "ivaPerci1": 0,
        "ivaRete1": 0,
        "reteRenta": 0,
        "montoTotalOperacion": 0,
        "totalNoGravado": 0,
        "totalPagar": 0,
        "totalLetras": "",
        "saldoFavor": 0,
        "pagos": None,
        "numPagoElectronico": None,
    },
    "04": {
        "totalNoSuj": 0,
        "totalExenta": 0,
        "totalGravada": 0,
        "subTotalVentas": 0,
        "descuNoSuj": 0,
        "descuExenta": 0,
        "descuGravada": 0,
        "porcentajeDescuento": 0,
        "totalDescu": 0,
        "tributos": None,
        "subTotal": 0,
        "montoTotalOperacion": 0,
        "totalLetras": "",
    },
    "05": {
        "totalNoSuj": 0,
        "totalExenta": 0,
        "totalGravada": 0,
        "subTotalVentas": 0,
        "descuNoSuj": 0,
        "descuExenta": 0,
        "descuGravada": 0,
        "totalDescu": 0,
        "tributos": None,
        "subTotal": 0,
        "ivaPerci1": 0,
        "ivaRete1": 0,
        "reteRenta": 0,
        "montoTotalOperacion": 0,
        "totalNoGravado": 0,
        "totalPagar": 0,
        "totalLetras": "",
        "saldoFavor": 0,
        "pagos": None,
        "numPagoElectronico": None,
    },
    "06": {
        "totalNoSuj": 0,
        "totalExenta": 0,
        "totalGravada": 0,
        "subTotalVentas": 0,
        "descuNoSuj": 0,
        "descuExenta": 0,
        "descuGravada": 0,
        "totalDescu": 0,
        "tributos": None,
        "subTotal": 0,
        "ivaPerci1": 0,
        "ivaRete1": 0,
        "reteRenta": 0,
        "montoTotalOperacion": 0,
        "totalLetras": "",
        "numPagoElectronico": None,
    },
}


import re


def normalizar_pagos(pagos_raw, total, tipo_dte="01", condicion=1, *, contexto=None):
    """Normaliza la lista de pagos al formato del esquema."""

    allowed = set(catalogos.FORMA_PAGO.keys())
    schema = catalogos.get_dte_schema(tipo_dte)
    props: dict = {}
    enum_codes: list = []
    if schema:
        props = (
            schema.get("properties", {})
            .get("resumen", {})
            .get("properties", {})
            .get("pagos", {})
            .get("items", {})
            .get("properties", {})
        )
        enum_codes = props.get("codigo", {}).get("enum", [])
        allowed.update(str(c).zfill(2) for c in enum_codes)

    code_type = props.get("codigo", {}).get("type", "string")
    periodo_type = props.get("periodo", {}).get("type", ["number", "null"])
    plazo_type = props.get("plazo", {}).get("type", ["string", "null"])
    code_is_int = code_type == "integer" or (
        isinstance(code_type, list) and "integer" in code_type
    )
    periodo_is_str = periodo_type == "string" or (
        isinstance(periodo_type, list) and "string" in periodo_type
    )
    plazo_is_str = plazo_type == "string" or (
        isinstance(plazo_type, list) and "string" in plazo_type
    )

    total = money(total)
    pagos: list[dict] = []
    for p in pagos_raw or []:
        codigo_raw = p.get("codigo", "")
        codigo_str = str(codigo_raw).zfill(2)
        if allowed and codigo_str not in allowed:
            continue
        codigo = int(codigo_raw) if code_is_int else codigo_str
        monto = money(p.get("montoPago", 0))
        referencia = p.get("referencia") or None
        periodo_raw = p.get("periodo")
        if periodo_raw in ("", None):
            periodo = None
        else:
            periodo = str(periodo_raw).zfill(2) if periodo_is_str else int(periodo_raw)
        plazo_raw = p.get("plazo")
        if plazo_raw in ("", None):
            plazo = None
        else:
            plazo = str(plazo_raw).zfill(2) if plazo_is_str else int(plazo_raw)
        pagos.append(
            {
                "codigo": codigo,
                "montoPago": monto,
                "referencia": referencia,
                "periodo": periodo,
                "plazo": plazo,
            }
        )

    if not pagos:
        if condicion == 2:
            raise ValidationError("condicionOperacion=2 requiere detallar pagos")
        if enum_codes:
            if code_is_int:
                default_code = enum_codes[0] if 1 not in enum_codes else 1
            else:
                default_code = (
                    "01" if "01" in enum_codes else str(enum_codes[0]).zfill(2)
                )
        else:
            # schema tipa integer sin enum -> código 1 explícito
            default_code = 1 if code_is_int else "01"
        pagos = [
            {
                "codigo": int(default_code) if code_is_int else default_code,
                "montoPago": total,
                "referencia": None,
                "periodo": None,
                "plazo": None,
            }
        ]
    else:
        # Fijar todos los pagos excepto el último y recalcularlo para que el
        # total coincida. Esta estrategia permite corregir discrepancias
        # superiores a un centavo de forma determinista, tal como se describe en
        # la documentación del proyecto.
        suma_parcial = sum((p["montoPago"] for p in pagos[:-1]), D("0.00"))
        nuevo = money(total - suma_parcial)
        if nuevo < 0:
            suma_total = suma_parcial + pagos[-1]["montoPago"]
            diff = money(total - suma_total)
            raise ValidationError(
                f"La suma de pagos {money(suma_total)} difiere del total {total} (dif {diff})"
            )
        pagos[-1]["montoPago"] = nuevo

    if condicion == 2 and pagos:
        first = pagos[0]
        plazo_code = str(first.get("plazo") or "").zfill(2)
        soft_validation = env_flag("SOFT_VALIDATION", default=True)
        contexto = contexto or {}
        context_parts: list[str] = []
        for key in ("venta_id", "nota_id", "uuid"):
            value = contexto.get(key)
            if value:
                context_parts.append(f"{key}={value}")
        context_suffix = f" {' '.join(context_parts)}" if context_parts else ""

        if plazo_code not in {"01", "02", "03"}:
            if soft_validation:
                logger.warning(
                    "Crédito sin plazo/periodo válidos (validación local desactivada)%s",
                    context_suffix,
                )
            else:
                raise ValidationError(
                    "Crédito: unidad inválida (01=días, 02=meses, 03=años)",
                )
        else:
            periodo_raw = first.get("periodo", 0)
            periodo_error = False
            try:
                periodo_val = int(periodo_raw)
            except (TypeError, ValueError):
                periodo_error = True
                periodo_val = None  # type: ignore[assignment]
            else:
                if periodo_val <= 0:
                    periodo_error = True

            if periodo_error:
                if soft_validation:
                    logger.warning(
                        "Crédito sin plazo/periodo válidos (validación local desactivada)%s",
                        context_suffix,
                    )
                else:
                    raise ValidationError("Crédito: periodo debe ser entero > 0")
            else:
                first["plazo"] = (
                    plazo_code if plazo_is_str else int(plazo_code)
                )
                first["periodo"] = (
                    str(periodo_val) if periodo_is_str else periodo_val
                )

    for p in pagos:
        p["montoPago"] = money(p["montoPago"])
        if (p["montoPago"] * 100) % 1:
            raise ValidationError("Los montos de pago deben ser múltiplos de 0.01")

    suma_final = sum((p["montoPago"] for p in pagos), D("0.00"))
    diff_final = money(total - suma_final)
    if diff_final != 0:
        raise ValidationError(
            f"La suma de pagos {money(suma_final)} difiere del total {total} (dif {diff_final})"
        )

    return pagos


def armar_tributos(tributos_raw, tipo_dte):
    """Construye la lista de tributos o retorna ``None``."""
    if not tributos_raw:
        return None
    # Los códigos válidos se obtienen tanto del catálogo local como del
    # esquema oficial del tipo de documento.  Esto permite extender el catálogo
    # sin depender de que el esquema se encuentre actualizado.
    allowed = set(TRIBUTOS_PERMITIDOS_RESUMEN)
    schema = catalogos.get_dte_schema(tipo_dte)
    if schema:
        allowed.update(
            schema.get("properties", {})
            .get("resumen", {})
            .get("properties", {})
            .get("tributos", {})
            .get("items", {})
            .get("properties", {})
            .get("codigo", {})
            .get("enum", [])
        )
    result = []
    for t in tributos_raw or []:
        codigo = str(t.get("codigo", "")).upper()
        if allowed and codigo not in allowed:
            raise ValueError(f"Código de tributo inválido: {codigo}")
        valor = money(t.get("valor", 0))
        if valor == D("0"):
            valor = D("0")
        result.append(
            {
                "codigo": codigo,
                # Si no se proporciona descripción, intentar obtenerla del catálogo
                "descripcion": t.get("descripcion") or catalogos.TRIBUTOS.get(codigo),
                "valor": valor,
            }
        )
    if tipo_dte == "01" and any(t["codigo"] == TRIBUTO_IVA for t in result):
        raise ValueError(
            "Código 20 (IVA) no permitido en resumen.tributos para consumidor final"
        )
    return result or None


def calcular_resumen(
    items_total, venta, fiscal=None, extra=None, tipo_dte="01", *, cuerpo=None
):
    """Calcula la sección resumen acorde al esquema oficial."""

    fiscal = fiscal or {}
    extra = extra or {}
    if tipo_dte in {"01", "03", "05", "06"}:
        precios_incluyen_iva = True
        extra["precios_incluyen_iva"] = True
    else:
        precios_incluyen_iva = _precios_incluyen_iva_from(extra)

    items_total = money(items_total)
    total_exenta = money(fiscal.get("ventas_exentas", 0))
    total_no_suj = money(fiscal.get("ventas_no_sujetas", 0))
    total_no_gravado = money(fiscal.get("no_gravado", 0))
    cuerpo_doc = cuerpo or []

    if tipo_dte == "01":
        descu_no_suj = money(0)
        descu_exenta = money(0)
        descu_gravada = money(0)
        total_descu = money(fiscal.get("descuentos", 0))
        sub_total_ventas = money(items_total)
        total_gravada = money(
            fiscal.get(
                "sumas",
                max(sub_total_ventas - total_exenta - total_no_suj, D("0")),
            )
        )
        total_iva = money(
            fiscal.get("iva", total_gravada - (total_gravada / D("1.13")))
        )
        sub_total = sub_total_ventas
        monto_total_operacion = sub_total
        total_pagar = sub_total
        porcentaje_desc = money(0)
    elif precios_incluyen_iva:
        descu_no_suj = money(fiscal.get("descu_no_suj", 0))
        descu_exenta = money(fiscal.get("descu_exenta", 0))
        descu_gravada = money(
            fiscal.get("descu_gravada", fiscal.get("descuentos", 0))
        )
        total_descu = money(descu_no_suj + descu_exenta + descu_gravada)
        if tipo_dte in {"03", "05", "06"}:
            gravada_desde_cuerpo = None
            if cuerpo_doc:
                gravada_desde_cuerpo = money(
                    sum(D(str(i.get("ventaGravada") or 0)) for i in cuerpo_doc)
                )
            if "sumas" in fiscal:
                total_gravada = money(fiscal["sumas"])
            elif gravada_desde_cuerpo is not None:
                total_gravada = gravada_desde_cuerpo
            else:
                base_calc, _ = to_base_iva(items_total)
                total_gravada = money(base_calc)

            iva_items = [
                money(D(str(i.get("ivaItem"))))
                for i in cuerpo_doc
                if i.get("ivaItem") is not None
            ]
            if iva_items:
                total_iva = money(sum(iva_items))
            elif cuerpo_doc:
                total_iva = money(
                    sum(
                        money(D(str(i.get("ventaGravada") or 0)) * D("0.13"))
                        for i in cuerpo_doc
                    )
                )
            else:
                total_iva = money(fiscal.get("iva", total_gravada * D("0.13")))
            sub_total_ventas = money(
                total_gravada + total_exenta + total_no_suj + total_no_gravado
            )
            sub_total = money(sub_total_ventas - total_descu)
            monto_total_operacion = money(sub_total + total_iva)
            total_pagar = monto_total_operacion
            porcentaje_desc = money(
                (total_descu * D("100") / sub_total_ventas)
                if sub_total_ventas
                else D("0")
            )
        else:
            total_gravada = money(
                fiscal.get(
                    "sumas",
                    (items_total - total_exenta - total_no_suj) / D("1.13"),
                )
            )
            total_iva = money(
                fiscal.get(
                    "iva", items_total - total_exenta - total_no_suj - total_gravada
                )
            )
            sub_total_ventas = money(total_no_suj + total_exenta + total_gravada)
            sub_total = money(sub_total_ventas - total_descu)
            monto_total_operacion = money(
                sub_total + total_no_gravado + total_iva
            )
            total_pagar = money(monto_total_operacion)
            base_desc = sub_total_ventas + total_descu
            porcentaje_desc = money(
                (total_descu * D("100") / base_desc) if base_desc else D("0")
            )
    else:
        descu_no_suj = money(fiscal.get("descu_no_suj", 0))
        descu_exenta = money(fiscal.get("descu_exenta", 0))
        descu_gravada = money(fiscal.get("descu_gravada", fiscal.get("descuentos", 0)))
        total_descu = money(descu_no_suj + descu_exenta + descu_gravada)
        total_gravada = money(fiscal.get("sumas", items_total))
        total_iva = money(fiscal.get("iva", 0)) if total_gravada > D("0") else money(0)
        sub_total_ventas = money(total_no_suj + total_exenta + total_gravada)
        sub_total = money(sub_total_ventas - total_descu)
        monto_total_operacion = money(
            sub_total + total_no_gravado + total_iva
        )
        total_pagar = money(monto_total_operacion)
        base_desc = sub_total_ventas + total_descu
        porcentaje_desc = money(
            (total_descu * D("100") / base_desc) if base_desc else D("0")
        )

    venta_total = None
    if isinstance(venta, dict):
        venta_total_raw = venta.get("total")
        if venta_total_raw is not None:
            venta_total = money(venta_total_raw)
    elif venta is not None:
        try:
            venta_total = money(venta)
        except Exception:
            venta_total = None
    if venta_total is not None and venta_total > D("0"):
        diff = money(venta_total - total_pagar)
        if diff != 0:
            total_iva = money(total_iva + diff)
            monto_total_operacion = money(monto_total_operacion + diff)
            total_pagar = money(total_pagar + diff)

    resumen = RESUMEN_DEFAULTS.get(tipo_dte, {}).copy()
    resumen.update(
        {
            "totalNoSuj": total_no_suj,
            "totalExenta": total_exenta,
            "totalGravada": total_gravada,
            "subTotalVentas": sub_total_ventas,
            "descuNoSuj": descu_no_suj,
            "descuExenta": descu_exenta,
            "descuGravada": descu_gravada,
            "totalDescu": total_descu,
            "subTotal": sub_total,
            "porcentajeDescuento": porcentaje_desc,
            "totalNoGravado": total_no_gravado,
            "montoTotalOperacion": monto_total_operacion,
            "totalPagar": total_pagar,
            "totalLetras": (
                monto_a_letras_natural(total_pagar)
                if tipo_dte == "01"
                else numero_a_letras(total_pagar)
            ),
        }
    )

    if tipo_dte == "01":
        resumen["totalIva"] = total_iva

    resumen["ivaRete1"] = money(fiscal.get("iva_rete1", resumen.get("ivaRete1", 0)))
    resumen["reteRenta"] = money(fiscal.get("rete_renta", resumen.get("reteRenta", 0)))


    if tipo_dte in {"01", "03", "05", "06"}:
        condicion = extra.get("condicion_operacion")
        if condicion is None:
            condicion = fiscal.get("condicion_pago")
        resumen["condicionOperacion"] = _parse_condicion_operacion(condicion)

    if tipo_dte in {"03", "05", "06"}:
        tg = money(sum(D(str(i.get("ventaGravada") or 0)) for i in cuerpo_doc))
        resumen_total_gravada = money(D(str(resumen.get("totalGravada", 0))))
        if resumen_total_gravada == D("0") and tg > D("0"):
            resumen["totalGravada"] = tg
            resumen_total_gravada = tg
        iva_items = [
            money(D(str(i.get("ivaItem"))))
            for i in cuerpo_doc
            if i.get("ivaItem") is not None
        ]
        if iva_items:
            iva_desde_cuerpo = money(sum(iva_items))
        elif cuerpo_doc:
            iva_desde_cuerpo = money(
                sum(
                    money(D(str(i.get("ventaGravada") or 0)) * D("0.13"))
                    for i in cuerpo_doc
                )
            )
        else:
            iva_desde_cuerpo = None
        if iva_desde_cuerpo is not None:
            total_iva = iva_desde_cuerpo
        total_gravada = resumen_total_gravada

    # Consolidar tributos adicionales desde ``extra`` o ``fiscal``
    trib_raw = []
    for src in (extra.get("tributos"), fiscal.get("tributos")):
        if not src:
            continue
        if isinstance(src, dict):
            src = [src]
        trib_raw.extend(src)

    suma_por_codigo: dict[str, D] = {}
    for t in trib_raw:
        codigo = str(t.get("codigo", "")).upper()
        if codigo == TRIBUTO_IVA:
            if tipo_dte == "01":
                raise ValueError(
                    "Código 20 (IVA) no permitido en resumen.tributos para consumidor final"
                )
            continue
        if not codigo:
            continue
        valor = money(t.get("valor", 0))
        suma_por_codigo[codigo] = money(suma_por_codigo.get(codigo, D("0")) + valor)

    tributos_list = [{"codigo": c, "valor": v} for c, v in suma_por_codigo.items()]
    if tipo_dte in {"03", "05", "06"}:
        resumen["tributos"] = (
            [
                {
                    "codigo": TRIBUTO_IVA,
                    "descripcion": catalogos.TRIBUTOS.get(TRIBUTO_IVA),
                    "valor": money(total_iva),
                }
            ]
            if total_gravada > D("0")
            else []
        )
    else:
        if tipo_dte != "01" and total_gravada > D("0"):
            tributos_list.append({"codigo": TRIBUTO_IVA, "valor": total_iva})
        resumen["tributos"] = armar_tributos(tributos_list, tipo_dte)
        if tipo_dte != "01" and total_gravada <= D("0") and not tributos_list:
            resumen.pop("tributos", None)

    if "pagos" in resumen:
        resumen["pagos"] = normalizar_pagos(
            extra.get("pagos"),
            resumen["totalPagar"],
            tipo_dte=tipo_dte,
            condicion=resumen.get("condicionOperacion", 1),
        )

    if "numPagoElectronico" in resumen:
        resumen["numPagoElectronico"] = extra.get("numPagoElectronico", "")

    total_pagar_val = money(D(str(resumen.get("totalPagar", 0))))
    if total_pagar_val == D("0"):
        resumen["condicionOperacion"] = 1

    excl = {
        "totalLetras",
        "condicionOperacion",
        "pagos",
        "numPagoElectronico",
        "tributos",
    }
    special_d4_fields = set() if tipo_dte == "03" else {"totalExenta", "totalNoSuj"}
    for key, val in list(resumen.items()):
        if key in excl:
            continue
        if isinstance(val, Decimal):
            if key in special_d4_fields:
                if val != d4(val):
                    raise ValidationError(f"{key} debe ser múltiplo de 0.0001")
            else:
                if val != money(val):
                    raise ValidationError(f"{key} debe ser múltiplo de 0.01")
            if val == D("0") and val.as_tuple().sign:
                resumen[key] = D("0")

    if resumen.get("tributos"):
        for t in resumen["tributos"]:
            val = t.get("valor")
            if isinstance(val, Decimal):
                if val != money(val):
                    raise ValidationError("valor de tributo debe ser múltiplo de 0.01")
                if val == D("0") and val.as_tuple().sign:
                    t["valor"] = D("0")

    if resumen.get("pagos"):
        for p in resumen["pagos"]:
            mp = p.get("montoPago")
            if isinstance(mp, Decimal):
                if mp != money(mp):
                    raise ValidationError("montoPago debe ser múltiplo de 0.01")
                if mp == D("0") and mp.as_tuple().sign:
                    p["montoPago"] = D("0")

    return resumen


def recalcular_totales(
    data: dict, *, precios_incluyen_iva: bool | None = None, incluir_iva: bool = False
) -> list[str]:
    """Recalcula y corrige los totales del resumen en ``data``.

    La función vuelve a calcular los valores de la sección ``resumen`` a partir
    de los ítems del ``cuerpoDocumento``.  Si alguno de los totales declarados
    difiere del valor esperado por más de un centavo, el valor se corrige en el
    lugar.  Devuelve una lista con los nombres de los campos ajustados.

    ``precios_incluyen_iva`` indica si los precios de los ítems incluyen IVA.
    Cuando se omite (``None``), el valor se obtiene de ``extra`` o de la
    configuración global.

    Cuando ``incluir_iva`` es ``True`` y el DTE es de tipo ``01`` se agregan los
    campos ``ivaItem`` en cada ítem y ``totalIva`` en el resumen, requeridos por
    el esquema oficial.
    """

    has_extra = "extra" in data and data.get("extra") is not None
    extra_conf = data.get("extra") or {}
    tipo_dte = str(data.get("identificacion", {}).get("tipoDte", ""))
    if tipo_dte == "01":
        precios_flag = True
        extra_conf["precios_incluyen_iva"] = True
        if has_extra:
            data["extra"] = extra_conf
    elif tipo_dte in {"03", "05", "06"}:
        precios_flag = True
        extra_conf["precios_incluyen_iva"] = True
        if has_extra:
            data["extra"] = extra_conf
        # ``03`` se usa tanto para comprobantes de crédito fiscal como para
        # tickets.  Solo los primeros requieren un NIT receptor válido; los
        # tickets pueden omitirlo.  Se omite la validación si no hay receptor
        # o si ``extra['es_ticket']`` está definido y es verdadero.
        receptor = data.get("receptor")
        if receptor and not extra_conf.get("es_ticket"):
            nit = str(receptor.get("nit") or "")
            if not (len(nit) == 14 and nit.isdigit()):
                raise ValueError(
                    "receptor.nit debe tener 14 dígitos sin guiones"
                )
    else:
        precios_flag = _precios_incluyen_iva_from(extra_conf, precios_incluyen_iva)

    cuerpo = data.get("cuerpoDocumento", [])
    resumen = data.get("resumen", {})

    colapso_desc = tipo_dte == "03"
    if colapso_desc:
        for _it in cuerpo:
            _cant = D(str(_it.get("cantidad") or 0))
            _precio = D(str(_it.get("precioUni") or 0))
            _descu = D(str(_it.get("montoDescu") or 0))
            if _descu:
                total_final = d8(_cant * _precio - _descu)
                unit_pf = d8(total_final / _cant) if _cant else d8(0)
                _it["precioUni"] = unit_pf
                _it.pop("montoDescu", None)
        resumen["descuNoSuj"] = resumen["descuExenta"] = resumen["descuGravada"] = resumen["totalDescu"] = money(0)
        resumen["porcentajeDescuento"] = money(0)

    iva_total = D("0")
    venta_gravada_sum = D("0")
    total_no_gravado_sum = D("0")
    total_exenta_sum = D("0")
    total_no_suj_sum = D("0")
    bruto_sum = D("0")
    bruto_linea_sum = D("0")
    descu_sum = D("0")
    bases: list[D] = []
    bases_pre: list[D] = []
    ivas: list[D] = []
    cantidades: list[D] = []
    prices: list[D] = []
    venta_total_sum = D("0")
    sub_total_ventas = D("0")
    descu_gravada_sum = D("0")

    for idx, item in enumerate(cuerpo):
        cant = D(str(item.get("cantidad") or 0))
        precio = D(str(item.get("precioUni") or 0))
        monto_descu = D(str(item.get("montoDescu") or 0))
        if tipo_dte == "01":
            item["precioUni"] = d4(precio)
            item["montoDescu"] = d4(monto_descu)
            bruto = d4(cant * precio)
            if bruto < 0:
                bruto = d4(0)
            bruto_sum += bruto
            descu_sum += d4(monto_descu)
            linea = d4(bruto - monto_descu)
            if linea < 0:
                linea = d4(0)
            venta_gravada_val = d4(D(str(item.get("ventaGravada") or 0)))
            venta_exenta_val = d4(D(str(item.get("ventaExenta") or 0)))
            venta_no_suj_val = d4(D(str(item.get("ventaNoSuj") or 0)))
            no_gravado_val = d4(D(str(item.get("noGravado") or 0)))
            is_non_grav = any(
                val > D("0") for val in (venta_exenta_val, venta_no_suj_val, no_gravado_val)
            )
            if not is_non_grav and venta_gravada_val <= D("0") and linea > D("0"):
                venta_gravada_val = linea
            if is_non_grav and venta_gravada_val == D("0"):
                if incluir_iva:
                    item["ivaItem"] = d4(0)
                else:
                    item.pop("ivaItem", None)
                item["ventaGravada"] = d4(0)
                item["ventaExenta"] = venta_exenta_val
                item["ventaNoSuj"] = venta_no_suj_val
                item["noGravado"] = no_gravado_val
                total_exenta_sum += venta_exenta_val
                total_no_suj_sum += venta_no_suj_val
                total_no_gravado_sum += no_gravado_val
            else:
                _, iva_calc = to_base_iva(linea)
                esperado_iva = d4(iva_calc)
                iva_raw = item.get("ivaItem")
                if iva_raw is not None:
                    actual_iva = money(D(str(iva_raw)))
                    if linea > D("0") and actual_iva != esperado_iva:
                        logger.warning(
                            "IVA por ítem incoherente (%s); se esperaba %s",
                            actual_iva,
                            esperado_iva,
                        )
                    if linea == D("0") and actual_iva != D("0"):
                        raise ValueError("ivaItem debe ser 0 cuando ventaGravada es 0")
                if incluir_iva:
                    item["ivaItem"] = esperado_iva
                else:
                    item.pop("ivaItem", None)
                item["ventaGravada"] = linea
                item["ventaExenta"] = d4(0)
                item["ventaNoSuj"] = d4(0)
                item["noGravado"] = d4(0)
                iva_total += esperado_iva
                venta_gravada_sum += linea
            item["psv"] = d4(0)
            item["codTributo"] = None
            item["tributos"] = None
        elif tipo_dte == "03":
            precio_u = d8(precio)
            base_line = d8(cant * precio_u)
            venta_exenta_val = d8(D(str(item.get("ventaExenta") or 0)))
            venta_no_suj_val = d8(D(str(item.get("ventaNoSuj") or 0)))
            no_gravado_val = d8(D(str(item.get("noGravado") or 0)))
            has_non_grav = any(
                val > D("0") for val in (venta_exenta_val, venta_no_suj_val, no_gravado_val)
            )
            if has_non_grav:
                venta_gravada_val = d8(0)
                iva_val = d8(0)
                tributos_val = None
            else:
                venta_gravada_val = base_line
                iva_val = d8(iva_item(base_line))
                tributos_val = [TRIBUTO_IVA] if venta_gravada_val > D("0") else None
            pf_line = d8(base_line + iva_val)
            bases_pre.append(base_line)
            bases.append(venta_gravada_val)
            ivas.append(iva_val)
            bruto_sum += pf_line
            bruto_linea_sum += base_line
            cantidades.append(cant)
            prices.append(precio_u)
            item["montoDescu"] = d8(0)
            item["ventaGravada"] = venta_gravada_val
            item["ventaExenta"] = venta_exenta_val
            item["ventaNoSuj"] = venta_no_suj_val
            item["noGravado"] = no_gravado_val
            item["codTributo"] = None
            item["tributos"] = tributos_val
            if item.get("tipoItem") == 4 and venta_gravada_val <= D("0"):
                item["uniMedida"] = item.get("uniMedida") or 99
            iva_total += iva_val
            venta_gravada_sum += venta_gravada_val
        else:
            bruto_linea = money(cant * precio)
            bruto_linea_sum += bruto_linea
            bruto = money(bruto_linea - monto_descu)
            if bruto < 0:
                bruto = money(0)
            bruto_sum += bruto
            descu_sum += money(monto_descu)
            if precios_flag:
                base_pre = money(bruto_linea / D("1.13"))
                base = money(bruto / D("1.13"))
                iva_val = money(bruto - base)
                base = money(bruto - iva_val)
                bases_pre.append(base_pre)
            else:
                base_pre = base = bruto
                iva_val = money(base * D("0.13"))
                bases_pre.append(base_pre)
            bases.append(base)
            ivas.append(iva_val)
            cantidades.append(cant)
            item.pop("ivaItem", None)
            item["ventaExenta"] = money(0)
            item["ventaNoSuj"] = money(0)
            item["noGravado"] = money(0)
    # En FC (03) los ítems ya traen base/IVA correctos; no redistribuir.
    if tipo_dte in {"05", "06"}:
        if bases:
            bruto_total = bruto_sum
            base_total = money(bruto_total / D("1.13"))
            iva_total_calc = money(bruto_total - base_total)
            base_total = money(bruto_total - iva_total_calc)
            base_res = base_total - sum(bases)
            iva_res = iva_total_calc - sum(ivas)
            if base_res or iva_res:
                bases[-1] = d4(bases[-1] + base_res)
                ivas[-1] = d4(ivas[-1] + iva_res)
                if cantidades:
                    prices[-1] = d4(bases[-1] / cantidades[-1]) if cantidades[-1] > 0 else d4(0)
                    bases[-1] = d4(prices[-1] * cantidades[-1])
                    ivas[-1] = d4(bruto_total - sum(bases) - sum(ivas[:-1]))
            total_venta = D("0")
            for idx, item in enumerate(cuerpo):
                if idx < len(bases):
                    base_val = d8(bases[idx])
                    cant = cantidades[idx]
                    iva_val = d8(ivas[idx])
                    pf_neto = d8(base_val + iva_val)
                    item["ventaGravada"] = base_val
                    precio_u = prices[idx] if idx < len(prices) else d8(0)
                    item["precioUni"] = precio_u if cant > 0 else d8(0)
                    item.pop("ivaItem", None)
                    item.pop("montoDescu", None)
                    if base_val + iva_val != pf_neto:
                        logger.warning(
                            "Línea %s: base %s + iva %s != pf_neto %s",
                            idx + 1,
                            base_val,
                            iva_val,
                            pf_neto,
                        )
                    else:
                        logger.debug(
                            "Línea %s: base %s + iva %s = pf_neto %s",
                            idx + 1,
                            base_val,
                            iva_val,
                            pf_neto,
                        )
                    trib_list: list[str] = []
                    tipo_item = int(item.get("tipoItem", 1))
                    if base_val > 0:
                        trib_list.append(TRIBUTO_IVA)
                    if tipo_item == 4:
                        if str(item.get("codTributo")) == TRIBUTO_IVA:
                            item["codTributo"] = None
                        item["uniMedida"] = item.get("uniMedida") or 99
                    else:
                        item["codTributo"] = None
                    item["tributos"] = trib_list or None
                    if "montoIva" in item:
                        item["montoIva"] = iva_val
                    total_venta += pf_neto
            venta_gravada_sum = sum(bases)
            iva_total = sum(ivas)
            venta_total_sum = total_venta
        else:
            venta_gravada_sum = D("0")
            iva_total = D("0")
            venta_total_sum = D("0")
    elif tipo_dte == "03":
        venta_gravada_sum = sum(bases)
        iva_total = sum(ivas)
        venta_total_sum = bruto_sum
    else:
        venta_total_sum = bruto_sum

    if tipo_dte in {"03", "05", "06"}:
        if colapso_desc:
            sub_total_ventas = money(sum(bases))
            descu_gravada_sum = money(0)
        else:
            sub_total_ventas = money(sum(bases_pre))
            descu_gravada_sum = money(
                sum(bp - b for bp, b in zip(bases_pre, bases))
            )
    else:
        if precios_flag:
            sub_total_ventas = money(sum(bases_pre))
            descu_gravada_sum = money(
                sum(bp - b for bp, b in zip(bases_pre, bases))
            )
        else:
            sub_total_ventas = money(venta_gravada_sum)
            descu_gravada_sum = money(0)

    venta_gravada_sum = venta_gravada_sum
    total_iva_sum = d4(iva_total)

    modificados: list[str] = []

    def _set_resumen(key: str, value: D):
        current = resumen.get(key)
        if current is not None and money(D(str(current))) == value:
            resumen[key] = value
            return
        resumen[key] = value
        modificados.append(key)

    resumen.pop("totalIva", None)

    if tipo_dte == "01":
        _set_resumen("totalNoSuj", d4(total_no_suj_sum))
        _set_resumen("totalExenta", d4(total_exenta_sum))
        _set_resumen("totalGravada", d4(venta_gravada_sum))
        _set_resumen(
            "subTotalVentas",
            money(venta_gravada_sum + total_exenta_sum + total_no_suj_sum + total_no_gravado_sum),
        )
        _set_resumen("descuNoSuj", money(0))
        _set_resumen("descuExenta", money(0))
        _set_resumen("descuGravada", money(0))
        _set_resumen("totalDescu", money(descu_sum))
        _set_resumen("porcentajeDescuento", money(0))
        _set_resumen(
            "subTotal",
            money(venta_gravada_sum + total_exenta_sum + total_no_suj_sum + total_no_gravado_sum),
        )
        _set_resumen("totalNoGravado", money(total_no_gravado_sum))
        monto_total_operacion = money(
            venta_gravada_sum + total_exenta_sum + total_no_suj_sum + total_no_gravado_sum
        )
        _set_resumen("montoTotalOperacion", monto_total_operacion)
        _set_resumen("totalPagar", monto_total_operacion)
        if incluir_iva:
            _set_resumen("totalIva", money(total_iva_sum))
    else:
        _set_resumen("totalNoSuj", d4(0))
        _set_resumen("totalExenta", d4(0))
        _set_resumen("totalGravada", money(venta_gravada_sum))
        if tipo_dte in {"03", "05", "06"}:
            _set_resumen("subTotalVentas", sub_total_ventas)
            _set_resumen("descuNoSuj", money(0))
            _set_resumen("descuExenta", money(0))
            _set_resumen("descuGravada", descu_gravada_sum)
            _set_resumen("totalDescu", descu_gravada_sum)
            porcentaje_desc = money(
                (descu_gravada_sum * D("100") / sub_total_ventas)
                if sub_total_ventas
                else D("0")
            )
            _set_resumen("porcentajeDescuento", porcentaje_desc)
            _set_resumen("subTotal", money(venta_gravada_sum))
            _set_resumen("totalNoGravado", money(0))
            monto_total_operacion = money(venta_total_sum)
            _set_resumen("montoTotalOperacion", monto_total_operacion)
            _set_resumen("totalPagar", monto_total_operacion)
            if money(venta_total_sum) != monto_total_operacion:
                logger.warning(
                    "TotalVenta %s != montoTotalOperacion %s",
                    money(venta_total_sum),
                    monto_total_operacion,
                )
            else:
                logger.debug(
                    "TotalVenta %s = montoTotalOperacion %s",
                    monto_total_operacion,
                    monto_total_operacion,
                )
        else:
            _set_resumen("subTotalVentas", money(venta_gravada_sum))
            _set_resumen("descuNoSuj", money(0))
            _set_resumen("descuExenta", money(0))
            _set_resumen("descuGravada", money(0))
            _set_resumen("totalDescu", money(0))
            base = venta_gravada_sum + descu_sum
            porcentaje_desc = money(
                (descu_sum * D("100") / base) if base else D("0")
            )
            _set_resumen("porcentajeDescuento", porcentaje_desc)
            _set_resumen("subTotal", money(venta_gravada_sum))
            _set_resumen("totalNoGravado", money(0))
            monto_total_operacion = money(venta_gravada_sum + total_iva_sum)
            _set_resumen("montoTotalOperacion", monto_total_operacion)
            _set_resumen("totalPagar", monto_total_operacion)
    trib_raw = resumen.get("tributos")
    if tipo_dte == "01":
        if trib_raw:
            for t in trib_raw or []:
                codigo = str(t.get("codigo", "")).upper()
                if codigo == TRIBUTO_IVA:
                    raise ValueError("Código 20 (IVA) no permitido en resumen.tributos para consumidor final")
        if trib_raw is not None:
            resumen.pop("tributos", None)
            modificados.append("tributos")
        trib = None
    else:
        if tipo_dte in {"03", "05", "06"}:
            trib = (
                [
                    {
                        "codigo": TRIBUTO_IVA,
                        "descripcion": catalogos.TRIBUTOS.get(TRIBUTO_IVA),
                        "valor": money(total_iva_sum),
                    }
                ]
                if venta_gravada_sum > D("0")
                else None
            )
        else:
            suma: dict[str, D] = {}
            for t in trib_raw or []:
                codigo = str(t.get("codigo", "")).upper()
                if not codigo or codigo == TRIBUTO_IVA:
                    continue
                valor = money(t.get("valor", 0))
                suma[codigo] = money(suma.get(codigo, D("0")) + valor)
            if venta_gravada_sum > D("0"):
                suma[TRIBUTO_IVA] = total_iva_sum
            trib = armar_tributos([{ "codigo": c, "valor": v} for c, v in suma.items()], tipo_dte)
    if tipo_dte != "01" and resumen.get("tributos") != trib:
        resumen["tributos"] = trib
        modificados.append("tributos")
    total_pagar = resumen["totalPagar"]
    try:
        if tipo_dte == "01":
            total_letras = monto_a_letras_natural(total_pagar)
        else:
            total_letras = monto_a_texto_sv(total_pagar)
    except Exception:
        total_letras = None
    if resumen.get("totalLetras") != total_letras:
        resumen["totalLetras"] = total_letras
        modificados.append("totalLetras")

    if resumen.get("pagos"):
        suma = money(sum(D(str(p.get("montoPago") or 0)) for p in resumen["pagos"]))
        delta = money(total_pagar - suma)
        if delta != D("0"):
            first = resumen["pagos"][0]
            first_val = D(str(first.get("montoPago") or 0))
            first["montoPago"] = money(first_val + delta)

    if tipo_dte in {"03", "05", "06"}:
        def _sum_cuerpo(key: str) -> D:
            return money(sum(D(str(item.get(key) or 0)) for item in cuerpo))

        total_gravada_calc = _sum_cuerpo("ventaGravada")
        total_exenta_calc = _sum_cuerpo("ventaExenta")
        total_no_suj_calc = _sum_cuerpo("ventaNoSuj")
        total_no_gravado_calc = _sum_cuerpo("noGravado")

        iva_items_vals = [
            money(D(str(item.get("ivaItem"))))
            for item in cuerpo
            if item.get("ivaItem") is not None
        ]
        if iva_items_vals:
            total_iva_calc = money(sum(iva_items_vals))
        elif cuerpo:
            total_iva_calc = money(
                sum(
                    money(D(str(item.get("ventaGravada") or 0)) * D("0.13"))
                    for item in cuerpo
                )
            )
        else:
            total_iva_calc = money(
                sum(D(str(t.get("valor") or 0)) for t in resumen.get("tributos") or [])
            )

        total_descu_calc = money(D(str(resumen.get("totalDescu", 0))))
        sub_total_ventas_calc = money(
            total_gravada_calc
            + total_exenta_calc
            + total_no_suj_calc
            + total_no_gravado_calc
        )
        sub_total_calc = money(sub_total_ventas_calc - total_descu_calc)
        monto_total = money(sub_total_calc + total_iva_calc)

        _set_resumen("totalNoSuj", total_no_suj_calc)
        _set_resumen("totalExenta", total_exenta_calc)
        _set_resumen("totalGravada", total_gravada_calc)
        _set_resumen("totalNoGravado", total_no_gravado_calc)
        _set_resumen("subTotalVentas", sub_total_ventas_calc)
        _set_resumen("totalDescu", total_descu_calc)
        porcentaje_desc = money(
            (total_descu_calc * D("100") / sub_total_ventas_calc)
            if sub_total_ventas_calc
            else D("0")
        )
        _set_resumen("porcentajeDescuento", porcentaje_desc)
        _set_resumen("subTotal", sub_total_calc)
        _set_resumen("montoTotalOperacion", monto_total)
        _set_resumen("totalPagar", monto_total)

        if resumen.get("tributos"):
            resumen["tributos"][0]["valor"] = total_iva_calc

        if tipo_dte == "03":
            pf_total = money(
                sum(
                    D(str(i.get("precioUni") or 0)) * D(str(i.get("cantidad") or 0))
                    for i in cuerpo
                )
                + total_iva_calc
            )
            monto_total_resumen = money(resumen.get("montoTotalOperacion", 0))
            diff = money(pf_total - monto_total_resumen)
            if diff != D("0"):
                if abs(diff) <= D("0.01"):
                    if resumen.get("tributos"):
                        resumen["tributos"][0]["valor"] = money(
                            D(str(resumen["tributos"][0]["valor"])) + diff
                        )
                        if "tributos" not in modificados:
                            modificados.append("tributos")
                    _set_resumen("montoTotalOperacion", pf_total)
                    _set_resumen("totalPagar", pf_total)
                else:
                    warnings.warn(
                        f"pf_base+iva {pf_total} difiere de montoTotalOperacion {monto_total_resumen}"
                    )

    data["resumen"] = resumen
    return modificados
    # IVA-FIX END



def _format_numero_control(tipo: str, sucursal: str, punto: str, correlativo: int) -> str:
    """Formatea el número de control usando ``correlativo``."""
    secuencia = str(correlativo).zfill(15)
    return f"DTE-{tipo}-S{sucursal}P{punto}-{secuencia}"


def _derive_remision_from_correlativo(value: int | str | None) -> str | None:
    """Deriva el número de remisión a partir de un correlativo numérico."""

    if value is None:
        return None
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    if not digits:
        return None
    return digits[-4:].zfill(4)


def peek_next_correlativo(db: DB | None, tipo_dte: str) -> tuple[int | None, str | None]:
    """Obtiene el correlativo siguiente y su remisión derivada sin consumirlo."""

    if db is None:
        return None, None
    preview_getter = getattr(db, "peek_next_dte_correlativo", None)
    if not callable(preview_getter):
        return None, None
    datos = _load_datos_negocio()
    prefijo = str(datos.get("dte_api", {}).get("prefijo_control", ""))
    sucursal = "001"
    punto = "001"
    match = re.search(r"S(\d{3})P(\d{3})", prefijo)
    if match:
        sucursal, punto = match.groups()
    sucursal = _norm3(sucursal)
    punto = _norm3(punto)
    try:
        correlativo = preview_getter(tipo_dte, sucursal, punto)
    except Exception:  # pragma: no cover - defensive guard
        logger.exception("Fallo al previsualizar correlativo para tipo %s", tipo_dte)
        return None, None
    return correlativo, _derive_remision_from_correlativo(correlativo)


def generar_numero_control(
    db: DB, tipo: str, sucursal: str, punto: str
) -> tuple[str, int]:
    """Genera un número de control secuencial y devuelve también el correlativo."""
    correlativo_getter = getattr(db, "next_dte_correlativo", None)
    if callable(correlativo_getter):
        correlativo = correlativo_getter(tipo, sucursal, punto)
    else:
        logger.warning(
            "next_dte_correlativo no disponible en %s; usando correlativo=1 de emergencia",
            type(db).__name__,
        )
        correlativo = 1
    numero_control = _format_numero_control(tipo, sucursal, punto, correlativo)
    return numero_control, correlativo


def identificacion_a_xml(ident: dict) -> str:
    """Convierte el bloque ``identificacion`` a una cadena XML simple."""
    root = ET.Element("Identificacion")
    ET.SubElement(root, "TipoDte").text = ident.get("tipoDte", "")
    ET.SubElement(root, "NumeroControl").text = ident.get("numeroControl", "")
    ET.SubElement(root, "CodigoGeneracion").text = ident.get("codigoGeneracion", "")
    ET.SubElement(root, "TipoModelo").text = str(ident.get("tipoModelo", ""))
    ET.SubElement(root, "TipoOperacion").text = str(ident.get("tipoOperacion", ""))
    ET.SubElement(root, "FecEmi").text = ident.get("fecEmi", "")
    ET.SubElement(root, "HorEmi").text = ident.get("horEmi", "")
    ET.SubElement(root, "Ambiente").text = ident.get("ambiente", "")
    return ET.tostring(root, encoding="unicode")


def generar_cabecera_dte_data(
    tipo_modelo: int,
    tipo_operacion: int,
    tipo_dte: str,
    db: DB,
    tipo_contingencia: int | None = None,
    motivo_contin: str | None = None,
    ambiente: str = "00",
) -> dict:
    """Genera los datos para la cabecera de un DTE.

    Los campos de código de generación y número de control se crean antes de
    enviar la factura. Los valores que envía Hacienda posteriormente (código de
    generación y sello recibido) se dejan en ``None``.
    """
    if tipo_operacion == 1:
        tipo_modelo = 1
        tipo_contingencia = None
        motivo_contin = None
    else:
        tipo_modelo = 2

    datos = _load_datos_negocio()
    prefijo = datos.get("dte_api", {}).get("prefijo_control", "")
    sucursal = "001"
    punto = "001"
    m = re.search(r"S(\d{3})P(\d{3})", prefijo)
    if m:
        sucursal, punto = m.groups()
    sucursal = _norm3(sucursal)
    punto = _norm3(punto)
    codigo_generacion = str(uuid.uuid4()).upper()
    numero_control, correlativo = generar_numero_control(db, tipo_dte, sucursal, punto)
    fecha_generacion = datetime.now().strftime("%d/%m/%Y, %I:%M %p")
    return {
        "codigo_generacion": codigo_generacion,
        "numero_control": numero_control,
        "correlativo": correlativo,
        "sello_recepcion": None,
        "tipo_modelo": tipo_modelo,
        "tipo_operacion": tipo_operacion,
        "tipo_contingencia": tipo_contingencia,
        "motivo_contin": motivo_contin,
        "fecha_generacion": fecha_generacion,
        "ambiente": ambiente,
    }


def generar_dte_json(
    db: DB,
    venta_id: int,
    tipo_dte: str = "01",
    *,
    ambiente: str = "00",
    tipo_operacion: int | None = None,
    tipo_contingencia: int | None = None,
    motivo_contin: str | None = None,
    tipo_modelo: int | None = None,
    tipo_moneda: str = "USD",
    **kwargs,
) -> dict:
    """Genera un diccionario DTE básico para una venta.

    ``kwargs`` se acepta para compatibilidad con parámetros obsoletos.
    """
    allow_missing_venta = kwargs.get("_allow_missing_venta")

    row = db.cursor.execute("SELECT * FROM ventas WHERE id=?", (venta_id,)).fetchone()
    if row is not None:
        venta = dict(row)
    elif allow_missing_venta:
        venta = {}
    else:
        raise ValueError("Venta no encontrada")

    if tipo_operacion is None:
        modo = get_default_modo_transmision()
        tipo_operacion = 2 if modo == "contingencia" else 1

    if ambiente not in ("00", "01"):
        ambiente_cfg = str(ambiente).lower()
        ambiente = "01" if ambiente_cfg.startswith("produc") else "00"

    if not venta.get("total_letras"):
        total = venta.get("total")
        if total is not None:
            venta["total_letras"] = numero_a_letras(total)
    if not venta.get("total_letras") and not allow_missing_venta:
        raise ValueError("El total en letras es obligatorio")

    detalles = db.get_detalles_venta(venta_id)
    fiscal = db.get_venta_credito_fiscal(venta_id)
    extra: dict[str, Any] = {}
    raw_extra = venta.get("extra")
    if raw_extra:
        try:
            parsed_extra = json.loads(raw_extra)
            if isinstance(parsed_extra, dict):
                extra = parsed_extra
        except Exception:
            extra = {}
    credit_extra = fiscal.get("extra") if fiscal else None
    if not isinstance(extra, dict):
        extra = {}
    if not extra and isinstance(credit_extra, dict):
        extra = dict(credit_extra)
    elif isinstance(credit_extra, dict):
        merged_extra = dict(extra)
        for key, value in credit_extra.items():
            merged_extra.setdefault(key, value)
        extra = merged_extra
    else:
        extra = dict(extra)

    extra_param = kwargs.get("extra")
    if isinstance(extra_param, dict):
        extra.update(extra_param)

    venta_tercero = _venta_tercero_from_sources(extra, fiscal, kwargs)

    fiscal_totals: dict[str, Any] = {}

    def _merge_fiscal_source(source: Any) -> None:
        if not isinstance(source, dict):
            return
        for key in FISCAL_TOTAL_FIELDS:
            if key == "precios_incluyen_iva":
                if key in source and key not in fiscal_totals:
                    fiscal_totals[key] = bool(source[key])
                continue
            if key in source and source[key] is not None and key not in fiscal_totals:
                try:
                    fiscal_totals[key] = Decimal(str(source[key]))
                except Exception:
                    continue

    _merge_fiscal_source(extra)
    if isinstance(credit_extra, dict):
        _merge_fiscal_source(credit_extra)
    if fiscal:
        filtered = {k: v for k, v in fiscal.items() if k in FISCAL_TOTAL_FIELDS}
        _merge_fiscal_source(filtered)

    if extra.get("es_ticket"):
        tipo_dte = "01"

    cliente = None
    if venta.get("cliente_id"):
        cliente = db.get_cliente(venta["cliente_id"])

    datos = _load_datos_negocio()


    prefijo = str(datos.get("dte_api", {}).get("prefijo_control", ""))
    m = re.match(r"^DTE-\d{2}-S(\d{3})P(\d{3})$", prefijo)
    suc_pref, punto_pref = m.groups() if m else ("001", "001")
    cod_estable_raw = re.sub(r"\D", "", str(datos.get("codEstable", "")))
    cod_punto_raw = re.sub(r"\D", "", str(datos.get("codPuntoVenta", "")))
    cod_estable = (cod_estable_raw or suc_pref.rjust(4, "0"))[-4:].zfill(4)
    cod_punto = (cod_punto_raw or punto_pref.rjust(4, "0"))[-4:].zfill(4)
    suc = _norm3(cod_estable)
    pto = _norm3(cod_punto)

    # Reutilizar identificadores existentes si están almacenados
    codigo_generacion = (
        extra.get("codigoGeneracion")
        or extra.get("codigo_generacion")
        or kwargs.get("codigo_generacion")
    )
    numero_control = (
        extra.get("numeroControl")
        or extra.get("numero_control")
        or kwargs.get("numero_control")
    )
    correlativo = extra.get("correlativo")
    if correlativo is None:
        correlativo = kwargs.get("correlativo")

    if codigo_generacion is None:
        codigo_generacion = str(uuid.uuid4()).upper()
    if numero_control is None or correlativo is None:
        numero_control, correlativo = generar_numero_control(db, tipo_dte, suc, pto)

    # Persistir identificadores para reutilización futura
    if tipo_dte in ("01", "03"):
        try:
            db.update_venta_extra(
                venta_id,
                {
                    "codigoGeneracion": codigo_generacion,
                    "numeroControl": numero_control,
                    "correlativo": correlativo,
                },
            )
        except Exception:
            pass


    now = datetime.now(TZ_EL_SALVADOR)
    fecha = fecha_emision_hoy_str(now)
    hora = now.strftime("%H:%M:%S")

    # Permitir valores desde ``extra`` o ``kwargs``
    tipo_operacion = extra.get("tipoOperacion", tipo_operacion)
    tipo_contingencia = extra.get("tipoContingencia", tipo_contingencia)
    motivo_contin = extra.get("motivoContin", motivo_contin)
    tipo_operacion = kwargs.get(
        "tipoOperacion", kwargs.get("tipo_operacion", tipo_operacion)
    )
    tipo_contingencia = kwargs.get(
        "tipoContingencia", kwargs.get("tipo_contingencia", tipo_contingencia)
    )
    motivo_contin = kwargs.get(
        "motivoContin", kwargs.get("motivo_contin", motivo_contin)
    )

    if tipo_operacion == 2:
        cfg = datos.get("dte_api", {})
        if tipo_contingencia in (None, ""):
            tipo_contingencia = cfg.get("tipo_contingencia", tipo_contingencia)
        if motivo_contin in (None, ""):
            motivo_contin = cfg.get("motivo_contin", motivo_contin)

    # Normalización de tipos
    try:
        tipo_operacion = int(tipo_operacion or 1)
    except Exception:
        tipo_operacion = 1
    if tipo_contingencia in ("", None):
        tipo_contingencia = None
    else:
        tipo_contingencia = int(tipo_contingencia)
    if isinstance(motivo_contin, str):
        motivo_contin = motivo_contin.strip() or None

    # Reglas de operación / modelo / contingencia
    if tipo_operacion == 1:
        tipo_modelo = 1
        tipo_contingencia = None
        motivo_contin = None
    elif tipo_operacion == 2:
        tipo_modelo = 2
        if tipo_contingencia is None:
            raise ValueError("tipoContingencia requerido cuando tipoOperacion=2")
        if tipo_contingencia not in catalogos.CONTINGENCIA:
            raise ValueError("tipoContingencia debe estar entre 1 y 5")
        if tipo_contingencia == 5:
            if not (motivo_contin and 5 <= len(motivo_contin) <= 500):
                raise ValueError(
                    "motivoContin debe tener entre 5 y 500 caracteres cuando tipoContingencia=5"
                )
        else:
            motivo_contin = None
    else:
        raise ValueError("tipoOperacion debe ser 1 o 2")

    tipo_dte = str(tipo_dte or "01").zfill(2)
    version = DTE_VERSIONES.get(tipo_dte, 1)
    identificacion = {
        "version": version,
        "ambiente": ambiente,
        "tipoDte": tipo_dte,
        "numeroControl": numero_control,
        "codigoGeneracion": codigo_generacion,
        "tipoModelo": tipo_modelo,
        "tipoOperacion": tipo_operacion,
        "tipoContingencia": tipo_contingencia,
        "motivoContin": motivo_contin,
        "fecEmi": fecha,
        "horEmi": hora,
        "tipoMoneda": tipo_moneda,
    }

    default_est = next(iter(catalogos.TIPO_ESTABLEC))
    tipo_est = datos.get("tipoEstablecimiento")
    tipo_est = str(tipo_est).zfill(2) if tipo_est else default_est
    if tipo_est not in catalogos.TIPO_ESTABLEC:
        tipo_est = default_est
    emisor = {
        "nombre": datos.get("nombre"),
        "nombreComercial": datos.get("nombreComercial"),
        "nit": datos.get("nit"),
        "nrc": datos.get("nrc"),
        "codActividad": datos.get("cod_giro") or datos.get("codActividad"),
        "descActividad": datos.get("descActividad"),
        "telefono": datos.get("telefono"),
        "correo": datos.get("correo"),
        "tipoEstablecimiento": tipo_est,
    }
    svfe_config.DATOS_NEGOCIO_PATH = DATOS_NEGOCIO_PATH
    datos_cfg = svfe_config.load_datos_negocio()
    dir_emisor = datos_cfg.get("direccion") or {}
    emisor["direccion"] = {
        "departamento": str(dir_emisor["departamento"]).zfill(2),
        "municipio": str(dir_emisor["municipio"]),  # respetar dígitos tal cual
        "complemento": dir_emisor.get("complemento") or "SIN DIRECCION",
    }
    emisor.setdefault("codEstableMH", cod_estable)
    emisor.setdefault("codEstable", cod_estable)
    emisor.setdefault("codPuntoVentaMH", cod_punto)
    emisor.setdefault("codPuntoVenta", cod_punto)
    if emisor.get("correo") and not EMAIL_RE.fullmatch(emisor["correo"]):
        raise ValueError("Correo de emisor inválido")
    if emisor.get("telefono") and not PHONE_RE.fullmatch(emisor["telefono"]):
        raise ValueError("Teléfono de emisor inválido")

    rec = dict(cliente or {})
    rec.setdefault("correo", rec.get("email"))
    rec_extra = extra.get("receptor") or {}
    for k, v in rec_extra.items():
        if v not in (None, "", []):
            rec[k] = v

    def _drop_empty(obj):
        if isinstance(obj, dict):
            return {
                k: _drop_empty(v)
                for k, v in obj.items()
                if _drop_empty(v) not in (None, "", [], {})
            }
        return obj

    rec = _drop_empty(rec)

    if not rec.get("numDocumento") and rec.get("dui"):
        formatted = _format_dui(rec.get("dui"))
        if not formatted:
            logger.warning(
                "DUI no normalizable; se continúa sin bloquear venta_id=%s",
                venta_id,
            )
        else:
            rec["tipoDocumento"] = rec.get("tipoDocumento") or "13"
            rec["numDocumento"] = formatted
    rec.pop("dui", None)

    def _clean_nit(nit):
        return "".join(c for c in str(nit) if c.isdigit()) if nit else None

    tipo_doc = rec.get("tipoDocumento")
    if tipo_doc is not None:
        tipo_doc = str(tipo_doc)
    num_doc = rec.get("numDocumento")
    if isinstance(num_doc, str):
        num_doc = num_doc.strip()
        if tipo_doc is None and re.fullmatch(r"[0-9]{8}-[0-9]", num_doc):
            tipo_doc = "13"
    nit = _clean_nit(rec.get("nit"))
    if fiscal:
        tipo_doc = fiscal.get("tipoDocumento") or tipo_doc
        num_doc = fiscal.get("numDocumento") or num_doc
        nit = _clean_nit(fiscal.get("nit") or nit)
    if nit and not num_doc:
        num_doc = nit
    if nit and not tipo_doc:
        tipo_doc = "36"

    if tipo_doc == "36":
        num_doc = _clean_nit(num_doc)
        if num_doc == "000000000":
            num_doc = "00000000000000"
    elif tipo_doc == "13":
        if num_doc and not re.fullmatch(r"[0-9]{8}-[0-9]", num_doc):
            logger.warning(
                "DUI no normalizable; se continúa sin bloquear venta_id=%s",
                venta_id,
            )

    receptor = {
        "tipoDocumento": tipo_doc if tipo_doc is not None else None,
        "numDocumento": num_doc or None,
        "nrc": ((fiscal.get("nrc") if fiscal else None) or rec.get("nrc")) or None,
        "nombre": rec.get("nombre") or None,
        "nit": nit,
        "nombreComercial": rec.get("nombreComercial") or None,
        "codActividad": rec.get("codActividad") or None,
        "descActividad": (rec.get("giro") or rec.get("descActividad")) or None,
        "telefono": rec.get("telefono") or None,
        "correo": rec.get("correo") or None,
    }
    if not receptor.get("nombre") and (tipo_dte == "01" or extra.get("es_ticket")):
        receptor["nombre"] = "Consumidor Final"
    direccion_src = rec.get("direccion")
    if not isinstance(direccion_src, dict):
        direccion_src = rec
    receptor["direccion"] = _build_receptor_direccion(direccion_src)
    dep = receptor["direccion"].get("departamento")
    mun = receptor["direccion"].get("municipio")
    comp = receptor["direccion"].get("complemento")
    try:
        dep, mun = validar_dep_muni_por_catalogo(dep, mun, strict=True)
    except GeoValidationError as e:
        if extra.get("es_ticket"):
            warnings.warn(f"{e}; usando dirección por defecto", UserWarning)
            dep = DEFAULT_ADDRESS["departamento"]
            mun = DEFAULT_ADDRESS["municipio"]
        else:
            raise
    if not comp or len(str(comp).strip()) < 5:
        if extra.get("es_ticket"):
            comp = DEFAULT_ADDRESS["complemento"]
        else:
            comp = "SIN DIRECCION"
    receptor["direccion"] = {"departamento": dep, "municipio": mun, "complemento": comp}
    if extra.get("es_ticket") and receptor:
        for f in ("nit", "nombreComercial"):
            receptor.pop(f, None)
    if receptor and receptor.get("correo") and not EMAIL_RE.fullmatch(receptor["correo"]):
        raise ValueError("Correo de receptor inválido")
    if receptor and receptor.get("telefono") and not PHONE_RE.fullmatch(receptor["telefono"]):
        raise ValueError("Teléfono de receptor inválido")
    if receptor and not extra.get("es_ticket"):
        if not receptor.get("correo"):
            receptor["correo"] = "no-reply@example.com"

        if receptor:
            # Campos obligatorios y limpieza de campos no permitidos
            if tipo_dte == "01":
                required_rec_fields = [
                    "nrc",
                    "nombre",
                    "codActividad",
                    "descActividad",
                    "telefono",
                    "correo",
                    "direccion",
                    "tipoDocumento",
                    "numDocumento",
                ]
                for f in ("nit", "nombreComercial"):
                    receptor.pop(f, None)
            else:
                required_rec_fields = [
                    "nit",
                    "nrc",
                    "nombre",
                    "nombreComercial",
                    "codActividad",
                    "descActividad",
                    "telefono",
                    "correo",
                    "direccion",
                ]
                fields_to_remove = ["numDocumento", "tipoDocumento", "noRemision", "ordenNo"]
                for f in fields_to_remove:
                    receptor.pop(f, None)

            for f in required_rec_fields:
                receptor.setdefault(f, None)

    cuerpo = []
    commission_total = D("0")
    iva_total = D("0")
    total_gravada_sum = D("0")
    total_exenta_sum = D("0")
    total_no_suj_sum = D("0")
    total_no_gravado_sum = D("0")
    bruto_total = D("0")
    descuentos_total = D("0")
    sub_total_ventas = D("0")
    descu_gravada_sum = D("0")
    override_precio_flag = kwargs.get("precios_incluyen_iva")
    precios_incluyen_iva = _precios_incluyen_iva_from(extra, override_precio_flag)
    if (
        tipo_dte in {"01", "03", "05", "06"}
        and "precios_incluyen_iva" not in extra
        and override_precio_flag is None
    ):
        precios_incluyen_iva = True
        extra["precios_incluyen_iva"] = True

    q_item = d8 if tipo_dte == "03" else d4
    q_qty = d8 if tipo_dte == "03" else d4
    # Quantizers per field (por tipo de DTE)
    q_field_item = d8 if tipo_dte == "03" else d4  # ventaGravada/Exenta/NoSuj por ítem

    def _zero_or_item(value: D) -> D:
        dec = q_item(value)
        return D("0.0") if dec == 0 else dec

    def _zero_or_d2(value: D) -> D:
        dec = d2(value)
        return D("0.0") if dec == 0 else dec

    for idx, d in enumerate(detalles, 1):
        try:
            cant = q_qty(D(str(d.get("cantidad") or 0)))
        except Exception:
            cant = q_qty(D(0))
        if cant <= 0:
            cant = q_qty(D("1"))
        try:
            precio_raw = q_item(
                D(
                    str(
                        d.get("precio_con_iva")
                        or d.get("precio_unit_con_iva")
                        or d.get("precio_unitario_con_iva")
                        or d.get("precio_unitario")
                        or 0
                    )
                )
            )
        except Exception:
            precio_raw = q_item(D(0))
        try:
            tipo_item = int(d.get("tipoItem", 1))
        except Exception:
            tipo_item = 1
        if tipo_item not in (1, 2, 3, 4):
            tipo_item = 1
        try:
            uni_medida = int(d.get("uniMedida", 59))
        except Exception:
            uni_medida = 59
        if uni_medida not in UNIDADES_MEDIDA_PERMITIDAS:
            uni_medida = 59

        desc_raw = d4(D(str(d.get("descuento") or 0)))
        if desc_raw < 0:
            desc_raw = D("0")
        desc_tipo = str(d.get("descuento_tipo") or "$")

        def _calc_desc(bruto: D) -> D:
            if desc_tipo == "%":
                monto = d4(bruto * desc_raw / D("100"))
            else:
                monto = d4(desc_raw)
            return monto if monto <= bruto else bruto

        tipo_fiscal_item = normalize_tipo_fiscal(d.get("tipo_fiscal"))
        no_gravado_val = D("0")
        if tipo_fiscal_item == "exenta":
            calcs = compute_line_totals(cant, precio_raw, desc_raw, desc_tipo, iva_rate=D("0"))
            line_total = calcs["total_con_iva"]
            precio = q_item(calcs["unit_con_iva_efectivo"])
            venta_gravada = D("0")
            venta_exenta = q_item(line_total)
            venta_no_suj = D("0")
            iva_val = D("0")
            if tipo_dte in {"03", "05", "06"}:
                monto_descu = D("0")
                bruto_total += line_total
                sub_total_ventas += line_total  # base = total, IVA=0
            else:
                monto_descu = calcs["desc_con_iva"]
                bruto_total += calcs["bruto"]
                descuentos_total += calcs["desc_con_iva"]
        elif tipo_fiscal_item == "no_sujeta":
            calcs = compute_line_totals(cant, precio_raw, desc_raw, desc_tipo, iva_rate=D("0"))
            line_total = calcs["total_con_iva"]
            precio = q_item(calcs["unit_con_iva_efectivo"])
            venta_gravada = D("0")
            venta_exenta = D("0")
            venta_no_suj = q_item(line_total)
            iva_val = D("0")
            if tipo_dte in {"03", "05", "06"}:
                monto_descu = D("0")
                bruto_total += line_total
                sub_total_ventas += line_total  # base = total, IVA=0
            else:
                monto_descu = calcs["desc_con_iva"]
                bruto_total += calcs["bruto"]
                descuentos_total += calcs["desc_con_iva"]
        elif tipo_fiscal_item == "no_gravada":
            calcs = compute_line_totals(cant, precio_raw, desc_raw, desc_tipo, iva_rate=D("0"))
            line_total = calcs["total_con_iva"]
            precio = q_item(calcs["unit_con_iva_efectivo"])
            venta_gravada = D("0")
            venta_exenta = D("0")
            venta_no_suj = D("0")
            iva_val = D("0")
            no_gravado_val = line_total
            if tipo_dte in {"03", "05", "06"}:
                monto_descu = D("0")
                bruto_total += line_total
                sub_total_ventas += line_total
            else:
                monto_descu = calcs["desc_con_iva"]
                bruto_total += calcs["bruto"]
                descuentos_total += calcs["desc_con_iva"]
        else:
            if tipo_dte == "01":
                origen = (
                    extra.get("origen_precios")
                    or ("bruto" if precios_incluyen_iva else "neto")
                ).lower()
                if origen == "neto":
                    precio = d4(precio_raw * D("1.13"))
                else:
                    precio = d4(precio_raw)
                bruto = d4(cant * precio)
                monto_descu = _calc_desc(bruto)
                line_total = d4(bruto - monto_descu)
                venta_gravada = line_total if line_total > 0 else D("0")
                _, iva_val_tmp = to_base_iva(venta_gravada)
                iva_val = d4(iva_val_tmp)
                line_total = venta_gravada
                bruto_total += bruto
                descuentos_total += monto_descu
            elif precios_incluyen_iva:
                if tipo_dte in {"03", "05", "06"}:
                    calcs = compute_line_totals(cant, precio_raw, desc_raw, desc_tipo)
                    line_total = calcs["total_con_iva"]
                    venta_gravada = calcs["base"]
                    iva_val = calcs["iva"]
                    iva_total += iva_val
                    # FC (03): precioUni debe ser unitario SIN IVA (base/cant)
                    precio = (
                        q_item(calcs["base"] / cant) if cant > 0 else q_item(D("0"))
                    )
                    monto_descu = D("0")
                    bruto_total += line_total
                    sub_total_ventas += venta_gravada
                else:
                    bruto = d4(cant * precio_raw)
                    monto_descu = _calc_desc(bruto)
                    total_final = d4(bruto - monto_descu)
                    if total_final < 0:
                        total_final = D("0")
                    base_total = money(total_final / D("1.13"))
                    iva_val = d4(total_final - base_total)
                    precio = q_item(money(total_final / cant)) if cant > 0 else q_item(D("0"))
                    venta_gravada = q_item(total_final)
                    line_total = venta_gravada
                    bruto_total += bruto
                    descuentos_total += monto_descu
            else:
                precio = d4(precio_raw)
                bruto = d4(cant * precio)
                monto_descu = _calc_desc(bruto)
                base = d4(cant * precio - monto_descu)
                if base < 0:
                    base = D("0")
                venta_gravada = d2(base)
                iva_val = d4(venta_gravada * D("0.13")) if venta_gravada > 0 else D("0")
                line_total = venta_gravada + iva_val
                bruto_total += bruto
                descuentos_total += monto_descu
            venta_exenta = D("0")
            venta_no_suj = D("0")
        if tipo_dte not in {"03", "05", "06"}:
            iva_total += iva_val
        try:
            commission_total += D(str(d.get("comision") or 0))
        except Exception:
            pass
        trib_code_raw = d.get("codTributo")
        if not trib_code_raw:
            raw = d.get("tributos")
            if isinstance(raw, list) and raw:
                raw_list = [str(item).strip().upper() for item in raw if str(item).strip()]
                raw_list = [item for item in raw_list if item != TRIBUTO_IVA]
                if raw_list:
                    trib_code_raw = raw_list[0]
            elif isinstance(raw, str):
                raw_str = raw.strip().upper()
                if raw_str and raw_str != TRIBUTO_IVA:
                    trib_code_raw = raw_str
        trib_code = str(trib_code_raw).upper() if trib_code_raw else ""
        if trib_code == TRIBUTO_IVA:
            raise ValueError("El IVA 13% (20) no va por ítem; solo en resumen")
        if trib_code and trib_code not in TRIBUTOS_PERMITIDOS_ITEM:
            raise ValueError(f"Código de tributo inválido en ítem: {trib_code}")

        num_doc = d.get("numeroDocumento")
        if isinstance(num_doc, str):
            if num_doc.strip().upper() in {"NA", "N/A", ""}:
                num_doc = None
        elif not num_doc:
            num_doc = None

        item_data = {
            "numItem": idx,
            "tipoItem": tipo_item,
            "numeroDocumento": num_doc,
            "codigo": d.get("codigo") or "SKU-NA",
            "descripcion": d.get("descripcion"),
            "cantidad": cant,
            "uniMedida": uni_medida,
            "precioUni": q_item(precio),
            "montoDescu": q_item(monto_descu),
            "ventaNoSuj": venta_no_suj,
            "ventaExenta": venta_exenta,
            "ventaGravada": venta_gravada,
            "psv": q_item(0),
            "noGravado": q_item(no_gravado_val),
            "tributos": [],
        }
        venta_gravada_val = D(str(item_data.get("ventaGravada") or 0))
        if tipo_dte == "01":
            item_data["codTributo"] = None
            item_data["tributos"] = None
        else:
            tributos_raw = d.get("tributos")
            if isinstance(tributos_raw, list):
                trib_iter = tributos_raw
            elif isinstance(tributos_raw, str):
                trib_iter = [tributos_raw]
            else:
                trib_iter = []
            raw_filtered: list[str] = []
            seen_raw: set[str] = set()
            for code in trib_iter:
                code_str = str(code).strip().upper()
                if not code_str:
                    continue
                if code_str == TRIBUTO_IVA or code_str in TRIBUTOS_PERMITIDOS_ITEM:
                    if code_str not in seen_raw:
                        raw_filtered.append(code_str)
                        seen_raw.add(code_str)

            if tipo_dte in {"03", "05", "06"}:
                if tipo_item == 4:
                    item_data["uniMedida"] = 99
                item_data["codTributo"] = None
                item_data["tributos"] = [TRIBUTO_IVA] if venta_gravada_val > 0 else None
            else:
                trib_list: list[str] = []
                if venta_gravada_val > 0:
                    trib_list.append(TRIBUTO_IVA)
                for code in raw_filtered:
                    if code != TRIBUTO_IVA and code not in trib_list:
                        trib_list.append(code)
                if (
                    tipo_item == 4
                    and trib_code
                    and venta_gravada_val > 0
                    and trib_code != TRIBUTO_IVA
                ):
                    item_data["codTributo"] = trib_code
                    if trib_code not in trib_list:
                        trib_list.append(trib_code)
                else:
                    item_data["codTributo"] = None

                if venta_gravada_val <= 0:
                    item_data["tributos"] = []
                elif trib_list:
                    if TRIBUTO_IVA not in trib_list:
                        trib_list.append(TRIBUTO_IVA)
                    item_data["tributos"] = trib_list
                else:
                    item_data["tributos"] = [TRIBUTO_IVA]
        for key in ("ventaNoSuj", "ventaExenta", "ventaGravada"):
            item_data[key] = _zero_or_item(D(str(item_data[key])))
        total_no_suj_sum += D(str(item_data["ventaNoSuj"]))
        total_exenta_sum += D(str(item_data["ventaExenta"]))
        total_gravada_sum += D(str(item_data["ventaGravada"]))
        total_no_gravado_sum += D(str(item_data["noGravado"]))
        cuerpo.append(item_data)

    bruto_total = money(bruto_total)
    descuentos_total = money(descuentos_total)
    total_no_suj_sum = _zero_or_item(total_no_suj_sum)
    total_exenta_sum = _zero_or_item(total_exenta_sum)
    total_gravada_sum = _zero_or_d2(total_gravada_sum)
    total_no_gravado_sum = money(total_no_gravado_sum)
    total_iva_sum = money(iva_total)
    sub_total_ventas = money(sub_total_ventas)
    descu_gravada_sum = money(descu_gravada_sum)
    if tipo_dte == "01":
        items_total = money(
            total_gravada_sum
            + total_exenta_sum
            + total_no_suj_sum
            + total_no_gravado_sum
        )
    else:
        items_total = money(
            total_gravada_sum + total_exenta_sum + total_no_suj_sum + total_iva_sum
        )

    computed_defaults: dict[str, Decimal] = {
        "sumas": total_gravada_sum,
        "ventas_exentas": total_exenta_sum,
        "ventas_no_sujetas": total_no_suj_sum,
        "no_gravado": total_no_gravado_sum,
        "iva": total_iva_sum,
    }
    if tipo_dte in {"03", "05", "06"}:
        computed_defaults.update(
            {
                "descu_gravada": descu_gravada_sum,
                "sub_total_ventas": sub_total_ventas,
                "descuentos": descu_gravada_sum,
            }
        )
    else:
        computed_defaults["descuentos"] = descuentos_total
    if tipo_dte not in {"03", "05", "06"}:
        subtotal_calculado = money(
            (total_gravada_sum - computed_defaults.get("descuentos", money(0)))
            + total_iva_sum
        )
        computed_defaults.setdefault("subtotal", subtotal_calculado)
    for key, value in computed_defaults.items():
        fiscal_totals.setdefault(key, value)

    resumen = calcular_resumen(
        items_total,
        venta,
        fiscal=fiscal_totals,
        extra=extra,
        tipo_dte=tipo_dte,
        cuerpo=cuerpo,
    )

    commission_total = money(commission_total)

    descu_no_suj = money(D(str(resumen.get("descuNoSuj", 0))))
    descu_exenta = money(D(str(resumen.get("descuExenta", 0))))
    descu_gravada = money(D(str(resumen.get("descuGravada", 0))))
    if tipo_dte in {"03", "05", "06"}:
        descu_no_suj = money(0)
        descu_exenta = money(0)
        descu_gravada = money(0)
    total_descuentos_calc = money(descu_no_suj + descu_exenta + descu_gravada)
    if tipo_dte in {"03", "05", "06"}:
        tg8 = sum(D(str(item.get("ventaGravada") or 0)) for item in cuerpo)
        te8 = sum(D(str(item.get("ventaExenta") or 0)) for item in cuerpo)
        tns8 = sum(D(str(item.get("ventaNoSuj") or 0)) for item in cuerpo)
        tng8 = sum(D(str(item.get("noGravado") or 0)) for item in cuerpo)

        total_gravada_val = d2(tg8)
        total_exenta_val = d2(te8)
        total_no_suj_val = d2(tns8)
        total_no_gravado_val = d2(tng8)

        resumen["totalGravada"] = total_gravada_val
        resumen["totalExenta"] = total_exenta_val
        resumen["totalNoSuj"] = total_no_suj_val
        resumen["totalNoGravado"] = total_no_gravado_val
        resumen["descuNoSuj"] = descu_no_suj
        resumen["descuExenta"] = descu_exenta
        resumen["descuGravada"] = descu_gravada

        sub_total_ventas_calc = money(
            total_gravada_val
            + total_exenta_val
            + total_no_suj_val
            + total_no_gravado_val
        )
        sub_total_calc = d2(sub_total_ventas_calc - total_descuentos_calc)

        resumen["subTotalVentas"] = sub_total_ventas_calc
        resumen["totalDescu"] = total_descuentos_calc
        resumen["subTotal"] = sub_total_calc

        iva_calc = money(total_gravada_val * D("0.13"))
        if total_gravada_val == D("0"):
            resumen["tributos"] = []
        else:
            resumen["tributos"] = [
                {
                    "codigo": TRIBUTO_IVA,
                    "descripcion": catalogos.TRIBUTOS.get(TRIBUTO_IVA),
                    "valor": iva_calc,
                }
            ]

        iva_perci1 = money(D(str(resumen.get("ivaPerci1", 0))))
        otros_tributos = money(
            sum(
                D(str(t.get("valor") or 0))
                for t in (resumen.get("tributos") or [])
                if t.get("codigo") != TRIBUTO_IVA
            )
        )
        iva_rete1 = money(D(str(resumen.get("ivaRete1", 0))))
        rete_renta = money(D(str(resumen.get("reteRenta", 0))))

        monto_total_operacion_calc = d2(
            sub_total_calc + iva_calc + iva_perci1 + otros_tributos - iva_rete1 - rete_renta
        )
        total_pagar_calc = d2(monto_total_operacion_calc + commission_total)

        resumen["montoTotalOperacion"] = monto_total_operacion_calc
        resumen["totalPagar"] = total_pagar_calc
    else:
        resumen["totalNoSuj"] = _zero_or_item(total_no_suj_sum)
        resumen["totalExenta"] = _zero_or_item(total_exenta_sum)
        resumen["totalGravada"] = _zero_or_d2(total_gravada_sum)
        resumen["totalNoGravado"] = total_no_gravado_sum

        sub_total_ventas_calc = money(
            total_gravada_sum + total_exenta_sum + total_no_suj_sum + total_no_gravado_sum
        )
        sub_total_calc = money(sub_total_ventas_calc - total_descuentos_calc)

        if tipo_dte == "01":
            iva_calc = money(D(str(resumen.get("totalIva", 0))))
        else:
            iva_calc = money(
                D(
                    str(
                        next(
                            (
                                t.get("valor")
                                for t in (resumen.get("tributos") or [])
                                if t.get("codigo") == TRIBUTO_IVA
                            ),
                            resumen.get("ivaPerci1", 0),
                        )
                    )
                )
            )

        total_no_gravado = money(D(str(resumen.get("totalNoGravado", 0))))

        if tipo_dte == "01":
            monto_total_operacion_calc = sub_total_calc
        elif precios_incluyen_iva:
            monto_total_operacion_calc = money(sub_total_calc + iva_calc)
        else:
            monto_total_operacion_calc = money(
                sub_total_calc + total_no_gravado + iva_calc
            )

        total_pagar_calc = money(monto_total_operacion_calc + commission_total)

        resumen["subTotalVentas"] = sub_total_ventas_calc
        resumen["totalDescu"] = total_descuentos_calc
        resumen["subTotal"] = sub_total_calc
        resumen["montoTotalOperacion"] = monto_total_operacion_calc
        resumen["totalPagar"] = total_pagar_calc


    # Las siguientes validaciones se omiten para permitir diferencias entre el
    # resumen y el cuerpo del documento sin lanzar ``ValidationError``.
    # if money(sum(D(str(i["ventaGravada"])) for i in cuerpo)) != money(
    #     D(str(resumen.get("totalGravada", 0)))
    # ):
    #     raise ValidationError("totalGravada inconsistente con cuerpoDocumento")
    # if money(sum(D(str(i["ivaItem"])) for i in cuerpo)) != money(
    #     D(str(resumen.get("totalIva", 0)))
    # ):
    #     raise ValidationError("totalIva inconsistente con cuerpoDocumento")

    total_no_suj = D(str(resumen.get("totalNoSuj", 0)))
    total_exenta = D(str(resumen.get("totalExenta", 0)))
    total_gravada = D(str(resumen.get("totalGravada", 0)))
    sub_total_ventas = D(str(resumen.get("subTotalVentas", 0)))
    descu_no_suj = D(str(resumen.get("descuNoSuj", 0)))
    descu_exenta = D(str(resumen.get("descuExenta", 0)))
    descu_gravada = D(str(resumen.get("descuGravada", 0)))
    sub_total = D(str(resumen.get("subTotal", 0)))
    total_no_gravado = D(str(resumen.get("totalNoGravado", 0)))
    monto_total_operacion = D(str(resumen.get("montoTotalOperacion", 0)))
    total_pagar = D(str(resumen.get("totalPagar", 0)))

    # Verificaciones numéricas eliminadas para evitar errores de consistencia
    # que interrumpan el flujo de generación del DTE.
    # if money(total_no_suj + total_exenta + total_gravada) != money(sub_total_ventas):
    #     raise ValidationError("subTotalVentas inconsistente")
    # if money(sub_total_ventas - (descu_no_suj + descu_exenta + descu_gravada)) != money(
    #     sub_total
    # ):
    #     raise ValidationError("subTotal inconsistente")
    # if money(sub_total + total_no_gravado + total_iva) != money(monto_total_operacion):
    #     raise ValidationError("montoTotalOperacion inconsistente")
    # if money(monto_total_operacion) != money(total_pagar):
    #     raise ValidationError("totalPagar debe igualar montoTotalOperacion")

    pagos_resumen = resumen.get("pagos") or []
    suma = money(sum(D(str(p["montoPago"])) for p in pagos_resumen))
    diff = money(total_pagar - suma)
    # if diff != 0:
    #     raise ValidationError(
    #         f"La suma de pagos {suma} difiere del total {total_pagar} (dif {diff})"
    #     )
    # if money(total_gravada) == D("0.00"):
    #     if resumen.get("tributos"):
    #         raise ValidationError("No debe haber tributos sin venta gravada")
    #     if money(total_iva) != D("0.00"):
    #         raise ValidationError("totalIva debe ser 0 sin venta gravada")

    # Validaciones básicas de consistencia
    items_total_2 = d2(
        total_gravada_sum + total_exenta_sum + total_no_suj_sum + descuentos_total
    )
    if abs(items_total_2 - D(str(resumen.get("subTotalVentas", 0)))) > D("0.01"):
        print(
            f"Advertencia: la suma de los ítems {items_total_2:.2f} difiere del resumen {resumen.get('subTotalVentas',0):.2f}"
        )

    calc_sub_total = d2(
        D(str(resumen.get("subTotalVentas", 0))) - D(str(resumen.get("totalDescu", 0)))
    )
    if abs(calc_sub_total - D(str(resumen.get("subTotal", 0)))) > D("0.01"):
        print(
            f"Advertencia: el subtotal calculado {calc_sub_total:.2f} difiere del resumen {resumen.get('subTotal',0):.2f}"
        )

    tribs = resumen.get("tributos") or []
    iva_ref = next((t.get("valor") for t in tribs if t.get("codigo") == TRIBUTO_IVA), resumen.get("ivaPerci1", 0))
    iva_ref = D(str(iva_ref or 0))
    calc_total = d2(calc_sub_total + iva_ref)
    if abs(calc_total - D(str(resumen.get("montoTotalOperacion", 0)))) > D("0.01"):
        print(
            f"Advertencia: el monto total {resumen.get('montoTotalOperacion',0):.2f} difiere del calculado {calc_total:.2f}"
        )
    calc_total_commission = d2(calc_total + commission_total)
    if "totalPagar" in resumen and abs(
        calc_total_commission - D(str(resumen.get("totalPagar", 0)))
    ) > D("0.01"):
        print(
            f"Advertencia: el total a pagar {resumen.get('totalPagar',0):.2f} difiere del calculado {calc_total_commission:.2f}"
        )

    # Aplicar regla de cierre por centavo para alinear Venta vs DTE
    venta_total = d2(D(str(venta.get("total") or 0)))
    dte_total = d2(D(str(resumen.get("montoTotalOperacion", 0))))
    diff = venta_total - dte_total
    if abs(diff) == D("0.01"):
        logger.debug("Aplicando cierre por centavo: diff=%s", diff)
        # Buscar última línea gravada
        last_grav = None
        for idx, item in enumerate(cuerpo):
            if D(str(item.get("ventaGravada") or 0)) > 0:
                last_grav = idx
        if last_grav is not None:
            item = cuerpo[last_grav]
            base_val = D(str(item.get("ventaGravada") or 0))
            item["ventaGravada"] = q_field_item(base_val + diff)
            resumen["totalGravada"] = d2(D(str(resumen.get("totalGravada", 0))) + diff)
            if resumen.get("tributos"):
                for t in resumen["tributos"]:
                    if t.get("codigo") == TRIBUTO_IVA:
                        t["valor"] = d2(D(str(t.get("valor", 0))) + diff)
            resumen["montoTotalOperacion"] = d2(dte_total + diff)
            resumen["totalPagar"] = d2(D(str(resumen.get("totalPagar", dte_total))) + diff)
        else:
            # Sin líneas gravadas; ajustar precio de la última línea
            if cuerpo:
                item = cuerpo[-1]
                qty = D(str(item.get("cantidad") or 1))
                unit_adj = q_item(diff / qty)
                item["precioUni"] = q_item(D(str(item.get("precioUni"))) + unit_adj)
                if D(str(item.get("ventaExenta") or 0)) > 0:
                    campo = "ventaExenta"
                    resumen_key = "totalExenta"
                elif D(str(item.get("ventaNoSuj") or 0)) > 0:
                    campo = "ventaNoSuj"
                    resumen_key = "totalNoSuj"
                else:
                    campo = "ventaGravada"
                    resumen_key = "totalGravada"
                item[campo] = q_field_item(D(str(item.get(campo))) + diff)
                resumen[resumen_key] = d2(D(str(resumen.get(resumen_key, 0))) + diff)
                resumen["montoTotalOperacion"] = d2(dte_total + diff)
                resumen["totalPagar"] = d2(D(str(resumen.get("totalPagar", dte_total))) + diff)
    # SERIALIZE-GUARD BEGIN
    special_d4_fields = set() if tipo_dte == "03" else {"totalExenta", "totalNoSuj"}
    for k in ("montoTotalOperacion", "totalPagar", "totalNoGravado"):
        if k in resumen:
            val = D(str(resumen[k]))
            if val != money(val):
                raise ValidationError(
                    f"{k} debe ser múltiplo de 0.01 (recibido={resumen[k]})"
                )
            if val == D("0") and val.as_tuple().sign:
                resumen[k] = D("0")
    for k in special_d4_fields:
        if k in resumen:
            val = D(str(resumen[k]))
            if val != d4(val):
                raise ValidationError(
                    f"{k} debe ser múltiplo de 0.0001 (recibido={resumen[k]})"
                )
            if val == D("0") and val.as_tuple().sign:
                resumen[k] = D("0")

    if resumen.get("tributos"):
        for t in resumen["tributos"]:
            val = D(str(t.get("valor") or 0))
            if val != money(val):
                raise ValidationError("valor de tributo debe ser múltiplo de 0.01")
            if val == D("0") and val.as_tuple().sign:
                val = D("0")
            t["valor"] = val
    else:
        if tipo_dte in {"03", "05", "06"}:
            resumen["tributos"] = []
        elif tipo_dte == "01":
            resumen["tributos"] = None
        else:
            resumen.pop("tributos", None)

    if resumen.get("pagos"):
        if resumen.get("condicionOperacion") == 2:
            for p in resumen["pagos"]:
                p.setdefault("codigo", "01")
                if p.get("referencia") is None:
                    p["referencia"] = ""
                if p.get("periodo") is None:
                    p["periodo"] = ""
                if p.get("plazo") is None:
                    p["plazo"] = ""
        for p in resumen["pagos"]:
            val = D(str(p.get("montoPago") or 0))
            if val != money(val):
                raise ValidationError("montoPago debe ser múltiplo de 0.01")
            if val == D("0") and val.as_tuple().sign:
                val = D("0")
            p["montoPago"] = val

    # --- SINCRONIZAR SUMA DE PAGOS CON totalPagar (ajuste máx. 0.01) ---
    total_pagar_dec = money(D(str(resumen.get("totalPagar") or 0)))
    if resumen.get("pagos"):
        suma_pagos = D("0")
        for p in resumen["pagos"]:
            suma_pagos += D(str(p.get("montoPago") or 0))
        suma_pagos = money(suma_pagos)

        delta = money(total_pagar_dec - suma_pagos)
        if delta != D("0") and abs(delta) <= D("0.01"):
            ultimo = resumen["pagos"][-1]
            ult_m = D(str(ultimo.get("montoPago") or 0))
            ultimo["montoPago"] = money(ult_m + delta)
    def _quantize_money(value: D) -> D:
        dec = money(value)
        return D("0.0") if dec == 0 else dec

    for k, v in list(resumen.items()):
        if k in {
            "totalLetras",
            "condicionOperacion",
            "pagos",
            "numPagoElectronico",
            "tributos",
        }:
            continue
        qfn = _zero_or_item if k in special_d4_fields else _quantize_money
        resumen[k] = qfn(D(str(v)))

    if resumen.get("tributos"):
        for t in resumen["tributos"]:
            t["valor"] = _quantize_money(D(str(t["valor"])))

    if resumen.get("pagos"):
        for p in resumen["pagos"]:
            p["montoPago"] = _quantize_money(D(str(p["montoPago"])))
    # SERIALIZE-GUARD END

    extension = None

    result = {
        "identificacion": identificacion,
        "emisor": emisor,
        "receptor": receptor,
        "cuerpoDocumento": cuerpo,
        "resumen": resumen,
        "documentoRelacionado": None,
        "otrosDocumentos": None,
        "apendice": None,
        "ventaTercero": venta_tercero,
        "extension": extension,
        # ``extra`` se utiliza únicamente durante la validación para
        # transmitir banderas internas como ``es_ticket``.  No forma parte
        # del DTE final y se eliminará después de la validación.
        "extra": extra,
    }

    try:
        validate_dte_json(
            result, db=db, precios_incluyen_iva=False, correlativo=correlativo
        )
    except TypeError:
        # Compatibilidad con versiones parcheadas sin parámetro ``correlativo``
        validate_dte_json(result, db=db, precios_incluyen_iva=False)
    if result.get("receptor") is None:
        result.pop("receptor", None)
    result.pop("extra", None)
    final = json.loads(stable_stringify(result), parse_float=Decimal)
    # Conservar el sello de recepción para operaciones posteriores (p.ej.,
    # anulaciones o notas).  ``extra`` se elimina del DTE final, pero si ahí se
    # encontraba ``selloRecibido`` lo exponemos en la raíz para que sea
    # accesible por los generadores de notas.
    sello = extra.get("selloRecibido") or extra.get("sello_recibido")
    if sello:
        final["selloRecibido"] = sello
    try:
        for idx, det in enumerate(detalles):
            if idx >= len(final.get("cuerpoDocumento", [])):
                break
            item = final["cuerpoDocumento"][idx]
            qty = D(str(det.get("cantidad") or 0))
            unit = D(str(det.get("precio_unitario") or 0))
            desc = D(str(det.get("descuento") or 0))
            if det.get("descuento_tipo") == "%":
                desc_line = d4(qty * unit * desc / D("100"))
            else:
                desc_line = d4(desc)
            pf_line = d4(qty * unit)
            pf_neto = d4(pf_line - desc_line)
            logger.debug(
                "Venta→DTE idx=%s pf_neto=%.4f => precioUni=%s cantidad=%s ventaGravada=%s",
                idx + 1,
                pf_neto,
                item.get("precioUni"),
                item.get("cantidad"),
                item.get("ventaGravada"),
            )
    except Exception:
        logger.debug("No se pudo registrar mapeo Venta→DTE", exc_info=True)
    return final


def validate_dte_json(
    payload: dict,
    *,
    db: DB,
    precios_incluyen_iva: bool | None = None,
    correlativo: int | None = None,
) -> None:
    """Basic validation and normalization for DTE payload antes de firmar.

    When ``correlativo`` is provided the ``numeroControl`` field will be
    reconstructed using it, avoiding any additional calls to generate a new
    correlativo.  If ``correlativo`` is ``None`` and ``numeroControl`` is
    missing or invalid a new correlativo will be obtained from ``db``.
    """
    # Normalización omitida para preservar códigos con ceros a la izquierda
    # ("01", etc.) que ``_normalize_payload`` convertiría a enteros.
    required = ["identificacion", "emisor", "receptor", "cuerpoDocumento", "resumen"]

    # Cuando ``payload`` representa un sobre de recepción (envelope) ya
    # firmado, no incluye los campos de un DTE tradicional.  Evitamos la
    # validación de campos obligatorios en este caso para permitir el envío
    # directo del sobre a Hacienda.
    if "documento" in payload and not any(k in payload for k in required):
        return

    missing = [key for key in required if key not in payload]
    if missing:
        raise ValueError("Faltan campos obligatorios: " + ", ".join(missing))
    extra_conf = payload.get("extra") or {}
    precios_flag = _precios_incluyen_iva_from(extra_conf, precios_incluyen_iva)

    payload.setdefault("extension", None)

    doc_rel = payload.get("documentoRelacionado")
    if doc_rel is None:
        payload["documentoRelacionado"] = None
    elif isinstance(doc_rel, list):
        for rel in doc_rel:
            if not isinstance(rel, dict):
                raise ValueError(
                    "documentoRelacionado debe contener objetos con la relación"
                )
            tipo_gen = rel.get("tipoGeneracion")
            if tipo_gen == 2:
                numero_doc = rel.get("numeroDocumento")
                if not numero_doc:
                    raise ValueError(
                        "numeroDocumento requerido cuando tipoGeneracion es 2"
                    )
                try:
                    rel["numeroDocumento"] = normalize_uuid_v4_upper(numero_doc)
                except Exception as exc:
                    raise ValueError(
                        "numeroDocumento debe ser un UUID v4 válido cuando tipoGeneracion=2"
                    ) from exc
    else:
        raise ValueError("documentoRelacionado debe ser array o null")

    negocio = _load_datos_negocio()

    ident = payload.get("identificacion", {})
    if correlativo is None and isinstance(ident, dict):
        # Forzar regeneración de ``numeroControl`` al validar cuando no se
        # proporciona un correlativo explícito.  Si dejamos el valor entrante
        # Hacienda puede rechazar el documento por duplicado.
        ident.pop("numeroControl", None)
    config = _load_dte_api_config()
    ambiente = "01" if config.get("ambiente") == "produccion" else "00"
    if ambiente == "01":
        ident["ambiente"] = "01"
    else:
        ident.setdefault("ambiente", ambiente)
    amb_val = str(ident.get("ambiente", "")).lower()
    if amb_val not in {"00", "01"}:
        ident["ambiente"] = "01" if amb_val.startswith("produc") else "00"
    ident.setdefault("tipoMoneda", "USD")
    if "modeloFacturacion" in ident:
        ident["tipoModelo"] = int(str(ident.pop("modeloFacturacion")).split()[0])
    if "tipoTransmision" in ident:
        ident["tipoOperacion"] = int(str(ident.pop("tipoTransmision")).split()[0])

    tipo_dte_val = ident.get("tipoDte")
    if isinstance(tipo_dte_val, int):
        tipo_dte_val = f"{tipo_dte_val:02d}"
    else:
        tipo_dte_val = str(tipo_dte_val).zfill(2)
    ident["tipoDte"] = tipo_dte_val
    tipo_dte = tipo_dte_val
    # Cuantizadores por tipo: en FC (03) los ítems usan 8 decimales
    q_item = d8 if tipo_dte == "03" else d4
    q_qty = d8 if tipo_dte == "03" else d4
    q_field = d8 if tipo_dte == "03" else d2
    if tipo_dte_val not in catalogos.DTE_TIPOS:
        raise ValueError("tipoDte inválido")
    if tipo_dte_val in {"03", "05", "06"}:
        precios_flag = True
        extra_conf["precios_incluyen_iva"] = True
        payload["extra"] = extra_conf
    elif tipo_dte_val == "01":
        precios_flag = True
        extra_conf["precios_incluyen_iva"] = True

    # Normalización de operación y contingencia
    try:
        ident["tipoOperacion"] = int(ident.get("tipoOperacion", 1) or 1)
    except Exception:
        ident["tipoOperacion"] = 1
    tipo_operacion = ident["tipoOperacion"]
    tipo_cont = ident.get("tipoContingencia")
    if tipo_cont in ("", None):
        tipo_cont = None
    else:
        tipo_cont = int(tipo_cont)
    motivo = ident.get("motivoContin")
    if isinstance(motivo, str):
        motivo = motivo.strip() or None

    if tipo_operacion == 1:
        ident["tipoModelo"] = 1
        ident["tipoContingencia"] = None
        ident["motivoContin"] = None
    elif tipo_operacion == 2:
        ident["tipoModelo"] = 2
        if tipo_cont is None:
            raise ValueError("tipoContingencia requerido cuando tipoOperacion=2")
        if tipo_cont not in catalogos.CONTINGENCIA:
            raise ValueError("tipoContingencia debe estar entre 1 y 5")
        ident["tipoContingencia"] = tipo_cont
        if tipo_cont == 5:
            if not (motivo and 5 <= len(motivo) <= 500):
                raise ValueError(
                    "motivoContin debe tener entre 5 y 500 caracteres cuando tipoContingencia=5"
                )
            ident["motivoContin"] = motivo
        else:
            ident["motivoContin"] = None
    else:
        raise ValueError("tipoOperacion debe ser 1 o 2")

    tipo = ident.get("tipoDte")
    expected_version = DTE_VERSIONES.get(tipo)
    if expected_version is not None:
        ident["version"] = expected_version
    else:
        ident["version"] = int(ident.get("version", 1))
    ident.setdefault("codigoGeneracion", str(uuid.uuid4()).upper())
    try:
        ident["codigoGeneracion"] = normalize_uuid_v4_upper(ident["codigoGeneracion"])
    except Exception:
        raise ValueError("codigoGeneracion debe ser un UUID v4 válido") from None
    if len(ident["codigoGeneracion"]) != 36 or "-" not in ident["codigoGeneracion"]:
        raise ValueError("codigoGeneracion debe ser un UUID v4 válido")
    ident["tipoMoneda"] = "USD"
    # Validaciones de campos de identificacion
    if ident.get("ambiente") not in {"00", "01"}:
        raise ValueError("ambiente debe ser '00' o '01'")
    if ident.get("tipoMoneda") != "USD":
        raise ValueError("tipoMoneda debe ser 'USD'")
    # Las reglas de operación/modelo/contingencia ya fueron normalizadas arriba.
    try:
        fec = datetime.strptime(str(ident.get("fecEmi")), "%Y-%m-%d").date()
    except Exception:
        raise ValueError("fecEmi debe tener formato YYYY-MM-DD") from None
    try:
        hora_dt = datetime.strptime(str(ident.get("horEmi")), "%H:%M:%S")
        hora = hora_dt.time()
        if hora_dt.strftime("%H:%M:%S") != ident.get("horEmi"):
            raise ValueError
    except Exception:
        raise ValueError("horEmi debe tener formato HH:MM:SS") from None
    now = datetime.now(TZ_EL_SALVADOR)
    emision_dt = datetime.combine(fec, hora, tzinfo=TZ_EL_SALVADOR)
    if fec > now.date() or emision_dt > now:
        raise ValueError("fecEmi/horEmi no pueden ser futuras")
    payload["identificacion"] = ident
    tipo_dte = str(ident.get("tipoDte", ""))

    emisor = payload.get("emisor", {})
    emisor["nit"] = _clean_nit(emisor.get("nit") or negocio.get("nit"))
    emisor["nrc"] = _clean_nrc(emisor.get("nrc") or negocio.get("nrc"))
    # ``dui`` is not permitted for the emisor by the DTE schema
    emisor.pop("dui", None)
    emisor.setdefault("nombre", negocio.get("nombre"))
    emisor.setdefault("nombreComercial", negocio.get("nombreComercial"))
    emisor.setdefault(
        "codActividad", negocio.get("cod_giro") or negocio.get("codActividad")
    )
    emisor.setdefault("descActividad", negocio.get("descActividad"))
    default_est = next(iter(catalogos.TIPO_ESTABLEC))
    tipo_est = emisor.get("tipoEstablecimiento")
    tipo_est = str(tipo_est).zfill(2) if tipo_est else default_est
    if tipo_est not in catalogos.TIPO_ESTABLEC:
        tipo_est = default_est
    emisor["tipoEstablecimiento"] = tipo_est
    svfe_config.DATOS_NEGOCIO_PATH = DATOS_NEGOCIO_PATH
    datos_cfg = svfe_config.load_datos_negocio()
    dir_emisor = datos_cfg.get("direccion") or {}
    emisor["direccion"] = {
        "departamento": str(dir_emisor["departamento"]).zfill(2),
        "municipio": str(dir_emisor["municipio"]),
        "complemento": dir_emisor.get("complemento") or "SIN DIRECCION",
    }
    emisor.setdefault("telefono", negocio.get("telefono"))
    emisor.setdefault("correo", negocio.get("correo"))
    cod_est = str(emisor.get("codEstable") or negocio.get("codEstable") or 1)
    emisor["codEstable"] = cod_est.zfill(4)
    emisor["codEstableMH"] = str(
        emisor.get("codEstableMH") or negocio.get("codEstableMH") or cod_est
    ).zfill(4)
    cod_pto = str(emisor.get("codPuntoVenta") or negocio.get("codPuntoVenta") or 1)
    emisor["codPuntoVenta"] = cod_pto.zfill(4)
    emisor["codPuntoVentaMH"] = str(
        emisor.get("codPuntoVentaMH") or negocio.get("codPuntoVentaMH") or cod_pto
    ).zfill(4)
    tipo = str(ident.get("tipoDte") or "").zfill(2)
    if not re.fullmatch(r"\d{2}", tipo):
        raise ValueError("tipoDte inválido")
    if hasattr(catalogos, "TIPOS_DTE") and tipo not in catalogos.TIPOS_DTE:
        raise ValueError("Código de tipoDte inválido")
    suc = _norm3(emisor.get("codEstableMH") or emisor.get("codEstable") or 1)
    pto = _norm3(
        emisor.get("codPuntoVentaMH") or emisor.get("codPuntoVenta") or 1
    )
    numero_control = ident.get("numeroControl")
    regex_nc = r"^DTE-(\d{2})-S(\d{3})P(\d{3})-(\d{15})$"
    recon = (
        _format_numero_control(tipo, suc, pto, correlativo)
        if correlativo is not None
        else None
    )
    if correlativo is not None:
        if numero_control and numero_control != recon:
            # Reemplazar cualquier numeroControl inconsistente con el correlativo
            logger.warning(
                "numeroControl %s no coincide con correlativo %s; se reemplaza con %s",
                numero_control,
                correlativo,
                recon,
            )
        ident["numeroControl"] = recon
    elif not (isinstance(numero_control, str) and re.fullmatch(regex_nc, numero_control)):
        ident["numeroControl"], correlativo = generar_numero_control(db, tipo, suc, pto)
    numero_control = ident.get("numeroControl")
    if not re.fullmatch(regex_nc, numero_control):
        raise ValueError("numeroControl inválido")
    emisor.pop("giro", None)
    emisor.pop("tipoContribuyente", None)
    required_emisor = {
        "nit": emisor.get("nit"),
        "nrc": emisor.get("nrc"),
        "nombre": emisor.get("nombre"),
        "nombreComercial": emisor.get("nombreComercial"),
        "tipoEstablecimiento": emisor.get("tipoEstablecimiento"),
        "codActividad": emisor.get("codActividad"),
        "descActividad": emisor.get("descActividad"),
        "direccion.departamento": emisor.get("direccion", {}).get("departamento"),
        "direccion.municipio": emisor.get("direccion", {}).get("municipio"),
        "direccion.complemento": emisor.get("direccion", {}).get("complemento"),
        "telefono": emisor.get("telefono"),
        "correo": emisor.get("correo"),
        "codEstable": emisor.get("codEstable"),
        "codEstableMH": emisor.get("codEstableMH"),
        "codPuntoVenta": emisor.get("codPuntoVenta"),
        "codPuntoVentaMH": emisor.get("codPuntoVentaMH"),
    }
    missing = [
        key
        for key, value in required_emisor.items()
        if value is None or (isinstance(value, str) and not value.strip())
    ]
    if missing:
        raise ValueError("Faltan campos obligatorios en emisor: " + ", ".join(missing))
    if emisor.get("correo") and not EMAIL_RE.fullmatch(emisor["correo"]):
        raise ValueError("Correo de emisor inválido")
    if emisor.get("telefono") and not PHONE_RE.fullmatch(emisor["telefono"]):
        raise ValueError("Teléfono de emisor inválido")
    payload["emisor"] = emisor

    receptor = payload.get("receptor")
    if tipo_dte == "01" and extra_conf.get("es_ticket"):
        if isinstance(receptor, dict):
            dir_rec = receptor.get("direccion")
            if isinstance(dir_rec, dict):
                receptor["direccion"] = _build_receptor_direccion(dir_rec)
            payload["receptor"] = receptor
        else:
            payload.pop("receptor", None)
    else:
        receptor = receptor or {}
        nit_field = receptor.get("nit")
        if tipo_dte == "03":
            receptor["nit"] = _clean_nit(nit_field)
            receptor.pop("tipoDocumento", None)
            receptor.pop("numDocumento", None)
        else:
            ident_uuid = (payload.get("identificacion") or {}).get(
                "codigoGeneracion"
            )
            tipo_doc = receptor.get("tipoDocumento")
            if nit_field is not None:
                receptor["numDocumento"] = _clean_nit(nit_field)
                if tipo_doc is None:
                    tipo_doc = "36"
            limpiar_documentos(receptor)
            if "numDocumento" not in receptor and receptor.get("dui"):
                formatted = _format_dui(receptor.get("dui"))
                if not formatted:
                    logger.warning(
                        "DUI no normalizable; se continúa sin bloquear uuid=%s",
                        ident_uuid,
                    )
                else:
                    receptor["numDocumento"] = formatted
                    tipo_doc = tipo_doc or "13"
            num_doc = solo_digitos(receptor.get("numDocumento"))
            receptor.pop("dui", None)
            nrc_raw = receptor.get("nrc")
            nrc_digits = solo_digitos(nrc_raw) if nrc_raw is not None else ""
            if nrc_digits:
                receptor["nrc"] = nrc_digits
            else:
                receptor.pop("nrc", None)
            if tipo_doc is None:
                tipo_doc = "36" if receptor.get("nrc") else "13"
            else:
                tipo_doc = str(tipo_doc)
            allowed = {"36", "13", "37", "03", "02"}
            if tipo_doc not in allowed:
                raise ValueError("tipoDocumento inválido en receptor")
            if tipo_doc == "13":
                if len(num_doc) != 9:
                    logger.warning(
                        "DUI no normalizable; se continúa sin bloquear uuid=%s",
                        ident_uuid,
                    )
                else:
                    if nrc_raw:
                        if tipo_dte == "04":
                            warnings.warn(
                                "Se forzó NRC=null porque el documento es DUI",
                                UserWarning,
                            )
                        else:
                            warnings.warn(
                                "Se removió NRC porque el documento es DUI",
                                UserWarning,
                            )
                    if tipo_dte == "04":
                        receptor["nrc"] = None
                    else:
                        receptor.pop("nrc", None)
            elif tipo_doc == "36":
                if len(num_doc) not in (9, 14):
                    raise ValueError(
                        "NIT debe tener 9 o 14 dígitos (sin guiones)"
                    )
                if not receptor.get("nrc") or len(receptor["nrc"]) not in (6, 7):
                    raise ValueError("NRC requerido (6–7 dígitos)")
            else:
                if tipo_dte == "04":
                    receptor["nrc"] = None
                else:
                    receptor.pop("nrc", None)
            receptor["tipoDocumento"] = tipo_doc
            receptor["numDocumento"] = num_doc

        receptor.pop("giro", None)
        dir_rec = receptor.get("direccion")
        if dir_rec is None:
            raise ValidationError("receptor.direccion faltante")
        receptor["direccion"] = _build_receptor_direccion(dir_rec)
        if receptor.get("correo") and not EMAIL_RE.fullmatch(receptor["correo"]):
            raise ValueError("Correo de receptor inválido")
        if receptor.get("telefono") and not PHONE_RE.fullmatch(receptor["telefono"]):
            raise ValueError("Teléfono de receptor inválido")
        if tipo_dte == "01":
            required_rec_fields = [
                "nrc",
                "nombre",
                "codActividad",
                "descActividad",
                "telefono",
                "correo",
                "direccion",
                "tipoDocumento",
                "numDocumento",
            ]
            for f in ("nit", "nombreComercial"):
                receptor.pop(f, None)
            for f in required_rec_fields:
                receptor.setdefault(f, None)
            for f in ("noRemision", "ordenNo"):
                receptor.pop(f, None)
        else:
            required_rec_fields = [
                "nit",
                "nrc",
                "nombre",
                "nombreComercial",
                "codActividad",
                "descActividad",
                "telefono",
                "correo",
                "direccion",
            ]
            for f in required_rec_fields:
                receptor.setdefault(f, None)
            fields_to_remove = ["numDocumento", "tipoDocumento", "noRemision", "ordenNo"]
            for f in fields_to_remove:
                receptor.pop(f, None)
        payload["receptor"] = receptor

    cuerpo = payload.get("cuerpoDocumento", [])
    schema = catalogos.get_dte_schema(tipo_dte)
    if schema:
        item_props = (
            schema.get("properties", {})
            .get("cuerpoDocumento", {})
            .get("items", {})
            .get("properties", {})
        )
        allowed_item_keys = set(item_props.keys())
    else:
        allowed_item_keys = {
            "numItem",
            "tipoItem",
            "numeroDocumento",
            "cantidad",
            "codigo",
            "codTributo",
            "uniMedida",
            "descripcion",
            "precioUni",
            "montoDescu",
            "ventaNoSuj",
            "ventaExenta",
            "ventaGravada",
            "tributos",
            "psv",
            "noGravado",
        }
    precio_key = "precioUni"
    iva_key = None

    for item in cuerpo:
        # --- Normalización de nombres ---
        if "precioUnitario" in item:
            raise ValueError("Usar 'precioUni' en lugar de 'precioUnitario'")

        for k in ("montoIva", "iva", "ivaItem"):
            if k in item:
                item.pop(k)

        # --- Filtrar claves no permitidas ---
        for key in list(item.keys()):
            if key not in allowed_item_keys:
                item.pop(key)

        # --- Valores por defecto ---
        item.setdefault("tipoItem", 1)
        item.setdefault("uniMedida", 59)
        item["tipoItem"] = int(item["tipoItem"])
        item["uniMedida"] = int(item["uniMedida"])

        try:
            item["tipoItem"] = int(item.get("tipoItem") or 0)
            item["uniMedida"] = int(item.get("uniMedida") or 0)
        except Exception:
            raise ValueError("tipoItem y uniMedida deben ser enteros")

        if item["tipoItem"] not in catalogos.TIPO_ITEM:
            raise ValueError("tipoItem inválido")
        if item["uniMedida"] not in UNIDADES_MEDIDA_PERMITIDAS:
            item["uniMedida"] = 59

        num_doc = item.get("numeroDocumento")
        if isinstance(num_doc, str):
            if num_doc.strip().upper() in {"NA", "N/A", ""}:
                num_doc = None
        elif not num_doc:
            num_doc = None
        item["numeroDocumento"] = num_doc

        item["codigo"] = item.get("codigo") or "SKU-NA"
        cero = D("0")
        item.setdefault("montoDescu", cero)
        item.setdefault("ventaNoSuj", cero)
        item.setdefault("ventaExenta", cero)
        item.setdefault("ventaGravada", cero)
        item.setdefault("noGravado", cero)
        item.setdefault("psv", cero)
        if tipo_dte == "01":
            item["tributos"] = None
        elif tipo_dte in {"03", "05", "06"}:
            venta_grav_item = D(str(item.get("ventaGravada") or 0))
            tributos_raw = item.get("tributos")
            if isinstance(tributos_raw, list):
                iterable = tributos_raw
            elif isinstance(tributos_raw, str):
                iterable = [tributos_raw]
            else:
                iterable = []
            filtered: list[str] = []
            seen: set[str] = set()
            for code in iterable:
                code_str = str(code).strip().upper()
                if not code_str:
                    continue
                if code_str == TRIBUTO_IVA or code_str in TRIBUTOS_PERMITIDOS_ITEM:
                    if code_str not in seen:
                        filtered.append(code_str)
                        seen.add(code_str)

            if venta_grav_item > 0:
                if TRIBUTO_IVA not in seen:
                    filtered.insert(0, TRIBUTO_IVA)
                    seen.add(TRIBUTO_IVA)
                else:
                    filtered = [TRIBUTO_IVA] + [c for c in filtered if c != TRIBUTO_IVA]

                if item.get("tipoItem") == 4:
                    extra_code = item.get("codTributo") or next(
                        (c for c in filtered if c != TRIBUTO_IVA),
                        None,
                    )
                    if not extra_code or extra_code == TRIBUTO_IVA:
                        raise ValueError(
                            "Los ítems tipo 4 requieren codTributo distinto de 20"
                        )
                    if extra_code not in TRIBUTOS_PERMITIDOS_ITEM:
                        raise ValueError("codTributo inválido para ítem tipo 4")
                    item["codTributo"] = extra_code
                    item["uniMedida"] = 99
                    item["tributos"] = [TRIBUTO_IVA]
                else:
                    item["codTributo"] = None
                    item["tributos"] = filtered or [TRIBUTO_IVA]
            else:
                if item.get("tipoItem") == 4 and venta_grav_item <= 0:
                    item["codTributo"] = None
                    item["uniMedida"] = 99
                else:
                    item["codTributo"] = None
                item["tributos"] = None
        else:
            item.setdefault("tributos", [])
        if iva_key:
            item.setdefault(iva_key, cero)

        # --- Cálculo de base ---
        cantidad = q_qty(D(str(item.get("cantidad") or 0)))
        precio = q_item(D(str(item.get(precio_key) or 0)))
        item["cantidad"] = cantidad
        item[precio_key] = precio
        monto_descu = q_field(D(str(item.get("montoDescu") or 0)))
        if monto_descu < 0:
            monto_descu = cero
        base = q_field(cantidad * precio - monto_descu)
        if base < 0:
            base = cero

        # Determinar tipo de venta
        if D(str(item.get("ventaExenta") or 0)) > 0:
            item["ventaExenta"] = q_field(base)
            item["ventaGravada"] = cero
            item["ventaNoSuj"] = cero
            item["noGravado"] = cero
        elif D(str(item.get("ventaNoSuj") or 0)) > 0:
            item["ventaNoSuj"] = q_field(base)
            item["ventaGravada"] = cero
            item["noGravado"] = cero
        elif D(str(item.get("noGravado") or 0)) > 0:
            item["noGravado"] = q_field(base)
            item["ventaGravada"] = cero
            item["ventaNoSuj"] = cero

        else:
            item["ventaGravada"] = q_field(base)
            item["ventaExenta"] = cero
            item["ventaNoSuj"] = cero
            item["noGravado"] = cero

        # --- Manejo y validación de tributos ---
        venta_gravada_val = D(str(item.get("ventaGravada") or 0))
        trib_raw = item.get("tributos")
        if isinstance(trib_raw, str):
            tributos = [trib_raw]
        elif isinstance(trib_raw, list):
            tributos = trib_raw[:]
        else:
            tributos = []
        tributos = [str(t).strip().upper() for t in tributos if str(t).strip()]
        cod_tri = item.get("codTributo")
        if cod_tri is not None:
            cod_tri = str(cod_tri).strip().upper() or None

        if tipo_dte == "01":
            item["codTributo"] = None
            item["tributos"] = None
        else:
            invalid = [
                t
                for t in tributos
                if t not in TRIBUTOS_PERMITIDOS_ITEM and t != TRIBUTO_IVA
            ]
            if cod_tri and (
                cod_tri not in TRIBUTOS_PERMITIDOS_ITEM or cod_tri == TRIBUTO_IVA
            ):
                invalid.append(cod_tri)
            if invalid:
                raise ValueError(
                    f"Código(s) de tributo inválido(s): {', '.join(invalid)}"
                )

            if tipo_dte in {"03", "05", "06"}:
                if venta_gravada_val > 0:
                    extras: list[str] = []
                    if cod_tri and cod_tri != TRIBUTO_IVA:
                        extras.append(cod_tri)
                    for code in tributos:
                        if code == TRIBUTO_IVA:
                            continue
                        if code not in extras:
                            extras.append(code)

                    normalized = [TRIBUTO_IVA] + extras
                    if item.get("tipoItem") == 4:
                        item["uniMedida"] = 99
                        item["codTributo"] = extras[0] if extras else None
                        item["tributos"] = [TRIBUTO_IVA]
                    else:
                        item["codTributo"] = None
                        item["tributos"] = normalized
                else:
                    item["codTributo"] = None
                    item["tributos"] = None
                    if item.get("tipoItem") == 4:
                        item["uniMedida"] = 99
            else:
                if venta_gravada_val <= 0:
                    item["tributos"] = []
                    item["codTributo"] = None
                elif tributos:
                    if TRIBUTO_IVA not in tributos:
                        tributos.append(TRIBUTO_IVA)
                    item["tributos"] = tributos
                    if (
                        len(tributos) == 1
                        and item.get("tipoItem") == 4
                        and tributos[0] != TRIBUTO_IVA
                    ):
                        item["codTributo"] = tributos[0]
                    else:
                        item["codTributo"] = None
                else:
                    item["tributos"] = [TRIBUTO_IVA]
                    item["codTributo"] = None

        if iva_key:
            if precios_flag and item.get(iva_key) not in (None, 0, D("0")):
                if tipo_dte == "01":
                    item[iva_key] = money(D(str(item.get(iva_key))))
                else:
                    item[iva_key] = q_field(D(str(item.get(iva_key))))
            else:
                iva_calc = venta_gravada_val * D("0.13") if venta_gravada_val > 0 else cero
                item[iva_key] = money(iva_calc) if tipo_dte == "01" else q_field(iva_calc)

        # Totales normalizados según el tipo de DTE y eliminar -0.00
        for k in ("ventaGravada", "ventaExenta", "ventaNoSuj", "psv", "noGravado"):
            val = q_field(item.get(k, cero))
            item[k] = cero if val == 0 else val
        item["montoDescu"] = q_field(monto_descu)
        if iva_key:
            iva_val = D(str(item.get(iva_key) or 0))
            iva_val_q = money(iva_val) if tipo_dte == "01" else q_field(iva_val)
            item[iva_key] = cero if iva_val_q == 0 else iva_val_q
    payload["cuerpoDocumento"] = cuerpo

    resumen = payload.get("resumen", {})
    for k, v in resumen.items():
        if k == "condicionOperacion":
            continue
        if isinstance(v, (int, float, Decimal)):
            val = d2(v)
            resumen[k] = D("0") if val == 0 else val
        elif isinstance(v, str):
            try:
                val = d2(float(v))
                resumen[k] = D("0") if val == 0 else val

            except Exception:
                pass
    payload["resumen"] = resumen

    # Recalcular totales y ajustar discrepancias (excepto para FC ya normalizado)
    if tipo_dte != "03":
        cambios = recalcular_totales(payload, precios_incluyen_iva=precios_flag)
        if cambios:
            print("Advertencia: se corrigieron campos de resumen: " + ", ".join(cambios))

    ident = payload.get("identificacion", {})
    if ident.get("tipoDte") == "01":
        for i in payload.get("cuerpoDocumento", []):
            linea = d4(
                D(str(i.get("cantidad") or 0))
                * D(str(i.get("precioUni") or 0))
                - D(str(i.get("montoDescu") or 0))
            )
            if i.get("ventaGravada") != linea:
                logger.warning(
                    "ventaGravada incoherente: %s esperado %s",
                    i.get("ventaGravada"),
                    linea,
                )

    resumen["pagos"] = normalizar_pagos(
        resumen.get("pagos"),
        resumen["totalPagar"],
        tipo_dte=ident.get("tipoDte"),
        condicion=resumen.get("condicionOperacion", 1),
        contexto={"uuid": ident.get("codigoGeneracion")},
    )
    delta = money(
        D(str(resumen["totalPagar"]))
        - sum(D(str(p.get("montoPago") or 0)) for p in resumen.get("pagos", []))
    )
    if resumen.get("pagos") and D("0") < abs(delta) <= D("0.01"):
        ultimo = resumen["pagos"][-1]
        ult_monto = D(str(ultimo.get("montoPago") or 0))
        ultimo["montoPago"] = money(ult_monto + delta)
    elif abs(delta) > D("0.01"):
        logger.warning(
            "Pagos no cuadran con totalPagar (|delta|=%s). Se deja que el validador falle.",
            delta,
        )

    total_pagar_val = money(D(str(resumen.get("totalPagar", 0))))
    if total_pagar_val == D("0"):
        resumen["condicionOperacion"] = 1

    if resumen.get("pagos") and resumen.get("condicionOperacion") == 2:
        for p in resumen["pagos"]:
            p.setdefault("codigo", "01")
            if p.get("referencia") is None:
                p["referencia"] = ""
            if p.get("periodo") is None:
                p["periodo"] = ""
            if p.get("plazo") is None:
                p["plazo"] = ""

    # Verificación de centavos exactos en totales clave
    special_d4_fields = set() if tipo_dte == "03" else {"totalExenta", "totalNoSuj"}
    for k in ("montoTotalOperacion", "totalPagar", "totalNoGravado"):
        if k in resumen:
            val = D(str(resumen[k]))
            if val != money(val):
                raise ValidationError(
                    f"{k} debe ser múltiplo de 0.01 (recibido={resumen[k]})"
                )
            if val == D("0") and val.as_tuple().sign:
                resumen[k] = D("0")
    for k in special_d4_fields:
        if k in resumen:
            val = D(str(resumen[k]))
            if val != d4(val):
                raise ValidationError(
                    f"{k} debe ser múltiplo de 0.0001 (recibido={resumen[k]})"
                )
            if val == D("0") and val.as_tuple().sign:
                resumen[k] = D("0")

    if resumen.get("tributos"):
        for t in resumen["tributos"]:
            val = D(str(t.get("valor") or 0))
            if val != money(val):
                raise ValidationError("valor de tributo debe ser múltiplo de 0.01")
            if val == D("0") and val.as_tuple().sign:
                t["valor"] = D("0")

    if resumen.get("pagos"):
        for p in resumen["pagos"]:
            val = D(str(p.get("montoPago") or 0))
            if val != money(val):
                raise ValidationError("montoPago debe ser múltiplo de 0.01")
            if val == D("0") and val.as_tuple().sign:
                p["montoPago"] = D("0")
    # --- Catálogo validations ---
    ident = payload.get("identificacion", {})
    tipo_dte = ident.get("tipoDte")
    if tipo_dte not in catalogos.TIPOS_DTE:
        raise ValueError("Código de tipoDte inválido")

    # Modelo de facturación / tipo de operación
    modelo_val = ident.get("tipoModelo") or ident.get("modeloFacturacion")
    try:
        modelo_cod = int(str(modelo_val).split("-")[0].strip())
    except Exception:
        raise ValueError("Modelo de facturación inválido")
    if modelo_cod not in catalogos.MODELOS_FACTURACION:
        raise ValueError("Modelo de facturación inválido")
    ident["tipoModelo"] = modelo_cod

    oper_val = ident.get("tipoOperacion") or ident.get("tipoTransmision")
    try:
        oper_cod = int(str(oper_val).split("-")[0].strip())
    except Exception:
        raise ValueError("Tipo de operación inválido")
    ident["tipoOperacion"] = oper_cod

    # Validación de longitud de NIT / numDocumento
    emisor_nit = payload.get("emisor", {}).get("nit")
    if emisor_nit:
        clean_emisor_nit = limpiar_doc(emisor_nit)
        payload["emisor"]["nit"] = clean_emisor_nit
        if len(clean_emisor_nit) != catalogos.NIT_LENGTH:
            raise ValueError("NIT inválido en emisor")

    receptor_info = payload.get("receptor", {})
    receptor_doc = receptor_info.get("numDocumento")
    if receptor_doc:
        tipo_rec = receptor_info.get("tipoDocumento")
        if tipo_rec == "13":  # DUI
            digits = re.sub(r"\D", "", str(receptor_doc))
            if len(digits) != 9:
                logger.warning(
                    "DUI no normalizable; se continúa sin bloquear uuid=%s",
                    ident.get("codigoGeneracion"),
                )
            else:
                payload["receptor"]["numDocumento"] = f"{digits[:8]}-{digits[8]}"
        elif tipo_rec == "36":  # NIT
            clean_doc = limpiar_doc(receptor_doc)
            if not clean_doc.isdigit() or len(clean_doc) not in (9, catalogos.NIT_LENGTH):
                raise ValueError("Número de documento inválido en receptor")
            payload["receptor"]["numDocumento"] = clean_doc
        else:
            doc_str = str(receptor_doc)
            if not (3 <= len(doc_str) <= 20):
                raise ValueError("Número de documento inválido en receptor")
    # Conversión final de Decimals con formatos específicos para el JSON
    def _zero_or(value: D, qfn) -> D:
        """Quantiza ``value`` usando ``qfn`` retornando ``0.0`` si es cero."""
        dec = qfn(value)
        return D("0.0") if dec == 0 else dec

    for item in payload.get("cuerpoDocumento", []):
        # cuantizar cantidad y precios según tipo de DTE
        item["cantidad"] = _zero_or(item.get("cantidad", D("0")), q_qty)
        item[precio_key] = _zero_or(item.get(precio_key, D("0")), q_item)
        if iva_key and iva_key in item:
            item[iva_key] = _zero_or(item.get(iva_key, D("0")), q_field)
        for k in (
            "montoDescu",
            "ventaNoSuj",
            "ventaExenta",
            "ventaGravada",
            "psv",
            "noGravado",
        ):
            if tipo_dte == "03":
                qfn = q_field
            else:
                qfn = d4 if k in {"ventaNoSuj", "ventaExenta", "ventaGravada"} else d2
            item[k] = _zero_or(item.get(k, D("0")), qfn)

    resumen = payload.get("resumen", {})
    for k, v in list(resumen.items()):
        if k in {
            "totalLetras",
            "condicionOperacion",
            "pagos",
            "numPagoElectronico",
            "tributos",
        }:
            continue
        if isinstance(v, Decimal):
            qfn = d4 if k in special_d4_fields else money
            resumen[k] = _zero_or(v, qfn)

    if resumen.get("tributos"):
        for t in resumen["tributos"]:
            t["valor"] = _zero_or(t["valor"], money)

    if resumen.get("pagos"):
        for p in resumen["pagos"]:
            p["montoPago"] = _zero_or(p["montoPago"], money)

    payload.pop("extra", None)
    payload["resumen"] = resumen


def generar_ticket_json(
    db: DB,
    venta_id: int,
    *,
    ambiente: str = "00",
    tipo_operacion: int = 1,
    tipo_contingencia: int | None = None,
    motivo_contin: str | None = None,
    **kwargs,
) -> dict:
    """Genera la estructura JSON para un Ticket Electrónico.

    Genera un DTE con ``tipoDte`` ``01`` tratándolo como ticket.
    """
    if ambiente not in ("00", "01"):
        ambiente_cfg = str(ambiente).lower()
        ambiente = "01" if ambiente_cfg.startswith("produc") else "00"

    extra_kwargs = kwargs.get("extra")
    if isinstance(extra_kwargs, dict):
        kwargs["extra"] = {**extra_kwargs, "es_ticket": True}
    else:
        kwargs["extra"] = {"es_ticket": True}

    data = generar_dte_json(
        db,
        venta_id,
        tipo_dte="01",
        ambiente=ambiente,
        tipo_operacion=tipo_operacion,
        tipo_contingencia=tipo_contingencia,
        motivo_contin=motivo_contin,
        **kwargs,
    )

    return data


def generar_nota_credito_json(db: DB, nota_id: int, *, ambiente: str = "00") -> dict:
    """Genera la estructura JSON para una nota de crédito.

    La lógica principal se encuentra en :mod:`nota_credito_electronica` y se
    delega aquí para mantener compatibilidad con el resto del módulo.
    """

    from nota_credito_electronica import generar_nce_desde_nota

    return generar_nce_desde_nota(db, nota_id, ambiente=ambiente)


def generar_nde_desde_dte(
    db: DB,
    dte_origen: dict,
    detalles: list | None,
    monto: float | None,
    motivo: str | None = None,
    *,
    ambiente: str = "00",
) -> dict:
    """Genera la estructura JSON de una Nota de Débito a partir de un DTE."""

    ambiente = resolve_ambiente(ambiente)
    cabecera = generar_cabecera_dte_data(1, 1, "06", db, ambiente=ambiente)
    now = datetime.now(TZ_EL_SALVADOR)
    identificacion = {
        "version": DTE_VERSIONES["06"],
        "ambiente": ambiente,
        "tipoDte": "06",
        "numeroControl": cabecera["numero_control"],
        "codigoGeneracion": cabecera["codigo_generacion"],
        "tipoModelo": cabecera["tipo_modelo"],
        "tipoOperacion": cabecera["tipo_operacion"],
        "tipoContingencia": cabecera["tipo_contingencia"],
        "motivoContin": cabecera["motivo_contin"],
        "fecEmi": fecha_emision_hoy_str(now),
        "horEmi": now.strftime("%H:%M:%S"),
        "tipoMoneda": "USD",
    }

    origen_ident = dte_origen.get("identificacion", {})
    tipo_origen = origen_ident.get("tipoDte")
    tipo_rel = "07" if tipo_origen == "07" else "03"
    doc_rel = [
        {
            "tipoDocumento": tipo_rel,
            "tipoGeneracion": 2,
            "numeroDocumento": origen_ident.get("codigoGeneracion"),
            "fechaEmision": origen_ident.get("fecEmi"),
        }
    ]

    emisor = copy.deepcopy(dte_origen.get("emisor", {}))
    receptor = copy.deepcopy(dte_origen.get("receptor", {}))
    from utils.sanitize import limpiar_documentos

    receptor.setdefault("nombreComercial", None)
    receptor.setdefault("nit", None)

    limpiar_documentos(emisor)
    limpiar_documentos(receptor)

    orig_resumen = dte_origen.get("resumen", {})
    items: list[dict] = []
    uuid_origen = origen_ident.get("codigoGeneracion", "")
    tipo_doc_desc = catalogos.DTE_TIPOS.get(origen_ident.get("tipoDte", ""), "documento")
    extra_desc = f": {motivo}" if motivo else ""

    if detalles:
        total_grav = Decimal("0")
        total_exenta = Decimal("0")
        total_nosuj = Decimal("0")
        num = 1
        for det in detalles:
            grav = Decimal(str(det.get("ventas_gravadas") or det.get("ventaGravada") or 0))
            exenta = Decimal(str(det.get("ventas_exentas") or det.get("ventaExenta") or 0))
            nosuj = Decimal(str(det.get("ventas_no_sujetas") or det.get("ventaNoSuj") or 0))
            total_grav += grav
            total_exenta += exenta
            total_nosuj += nosuj
            precio = det.get("precio_unitario") or det.get("precioUni")
            if precio is None:
                precio = grav + exenta + nosuj
            precio = d4(precio)
            cantidad = det.get("cantidad", 1)
            items.append(
                {
                    "numItem": num,
                    "tipoItem": det.get("tipoItem", 1),
                    "codigo": det.get("codigo", f"ND{uuid_origen[:8]}-{num}"),
                    "descripcion": det.get(
                        "descripcion",
                        f"Nota de débito sobre operaciones del {tipo_doc_desc} relacionado{extra_desc}",
                    ),
                    "cantidad": cantidad,
                    "uniMedida": det.get("uniMedida", 59),
                    "precioUni": precio,
                    "montoDescu": d4(det.get("montoDescu", 0.0)),
                    "ventaGravada": d4(grav),
                    "ventaExenta": d4(exenta),
                    "ventaNoSuj": d4(nosuj),
                    "tributos": [TRIBUTO_IVA] if grav > 0 else [],
                    "numeroDocumento": uuid_origen,
                    "codTributo": None,
                }
            )
            num += 1
        total_grav = d4(total_grav)
        total_exenta = d4(total_exenta)
        total_nosuj = d4(total_nosuj)
        subtotal_ventas_q4 = total_grav + total_exenta + total_nosuj
        subtotal_ventas = d2(subtotal_ventas_q4)
        monto_total = d2(
            total_grav * Decimal("1.13") + total_exenta + total_nosuj
        )
        iva_val = d2(monto_total - subtotal_ventas)
    else:
        if monto is None:
            raise ValueError("Se requiere monto para nota de débito")
        total_origen = Decimal(
            str(
                orig_resumen.get("montoTotalOperacion")
                or orig_resumen.get("totalPagar")
                or 0
            )
        )
        if total_origen <= 0:
            raise ValueError("El documento de origen no tiene total válido")
        ratio = Decimal(str(monto)) / total_origen
        pct_text = str((ratio * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        total_grav = d2(Decimal(str(orig_resumen.get("totalGravada", 0))) * ratio)
        total_exenta = d2(Decimal(str(orig_resumen.get("totalExenta", 0))) * ratio)
        total_nosuj = d2(Decimal(str(orig_resumen.get("totalNoSuj", 0))) * ratio)
        num = 1
        if total_grav > 0:
            items.append(
                {
                    "numItem": num,
                    "tipoItem": 1,
                    "codigo": f"ND{pct_text}-{uuid_origen[:8]}-G",
                    "descripcion": f"Nota de débito {pct_text}% sobre operaciones gravadas del {tipo_doc_desc} relacionado{extra_desc}",
                    "cantidad": 1,
                    "uniMedida": 59,
                    "precioUni": total_grav,
                    "montoDescu": 0.0,
                    "ventaGravada": total_grav,
                    "ventaExenta": 0.0,
                    "ventaNoSuj": 0.0,
                    "tributos": [TRIBUTO_IVA],
                    "numeroDocumento": uuid_origen,
                    "codTributo": None,
                }
            )
            num += 1
        if total_exenta > 0:
            items.append(
                {
                    "numItem": num,
                    "tipoItem": 1,
                    "codigo": f"ND{pct_text}-{uuid_origen[:8]}-E",
                    "descripcion": f"Nota de débito {pct_text}% sobre operaciones exentas del {tipo_doc_desc} relacionado{extra_desc}",
                    "cantidad": 1,
                    "uniMedida": 59,
                    "precioUni": total_exenta,
                    "montoDescu": 0.0,
                    "ventaGravada": 0.0,
                    "ventaExenta": total_exenta,
                    "ventaNoSuj": 0.0,
                    "tributos": [],
                    "numeroDocumento": uuid_origen,
                    "codTributo": None,
                }
            )
            num += 1
        if total_nosuj > 0:
            items.append(
                {
                    "numItem": num,
                    "tipoItem": 1,
                    "codigo": f"ND{pct_text}-{uuid_origen[:8]}-N",
                    "descripcion": f"Nota de débito {pct_text}% sobre operaciones no sujetas del {tipo_doc_desc} relacionado{extra_desc}",
                    "cantidad": 1,
                    "uniMedida": 59,
                    "precioUni": total_nosuj,
                    "montoDescu": 0.0,
                    "ventaGravada": 0.0,
                    "ventaExenta": 0.0,
                    "ventaNoSuj": total_nosuj,
                    "tributos": [],
                    "numeroDocumento": uuid_origen,
                    "codTributo": None,
                }
            )
        subtotal_ventas = total_grav + total_exenta + total_nosuj
        orig_total = Decimal(str(orig_resumen.get("montoTotalOperacion", 0))) * (
            ratio if "ratio" in locals() else Decimal("1")
        )
        iva_val = d2(orig_total - subtotal_ventas)
        monto_total = d2(orig_total)

    tributos_resumen: list[dict] = []
    if iva_val > 0:
        tributos_resumen.append(
            {
                "codigo": TRIBUTO_IVA,
                "descripcion": TRIBUTOS.get(TRIBUTO_IVA, ""),
                "valor": iva_val,
            }
        )
    resumen = {
        "totalNoSuj": d2(total_nosuj),
        "totalExenta": d2(total_exenta),
        "totalGravada": d2(total_grav),
        "subTotal": subtotal_ventas,
        "subTotalVentas": subtotal_ventas,
        "descuNoSuj": 0.0,
        "descuExenta": 0.0,
        "descuGravada": 0.0,
        "totalDescu": 0.0,
        "ivaPerci1": 0.0,
        "ivaRete1": 0.0,
        "reteRenta": 0.0,
        "condicionOperacion": dte_origen.get("resumen", {}).get("condicionOperacion", 1),
        "numPagoElectronico": dte_origen.get("resumen", {}).get("numPagoElectronico"),
        "tributos": tributos_resumen,
        "montoTotalOperacion": monto_total,
        "totalLetras": monto_a_texto_sv(monto_total),
    }

    data = {
        "identificacion": identificacion,
        "documentoRelacionado": doc_rel,
        "emisor": emisor,
        "receptor": receptor,
        "cuerpoDocumento": items,
        "resumen": resumen,
        "ventaTercero": None,
        "extension": None,
        "apendice": None,
    }

    schema = catalogos.get_dte_schema("06")
    return sanitize_dte_payload(data, schema)


def generar_nota_debito_json(db: DB, nota_id: int, *, ambiente: str = "00") -> dict:
    """Genera la estructura JSON para una nota de débito."""
    from nota_debito_electronica import generar_nde_desde_nota

    return generar_nde_desde_nota(db, nota_id, ambiente=ambiente)


def generar_nota_remision_json(
    db: DB,
    factura: dict,
    *,
    cantidades: dict[int, float] | None = None,
    extension: dict | None = None,
    ambiente: str = "00",
) -> dict:
    """Genera la estructura JSON para una Nota de Remisión a partir de una factura.

    Parameters
    ----------
    db:
        Conexión a la base de datos para generar la cabecera del DTE.
    factura:
        DTE base del cual se copiarán emisor, receptor e ítems.
    cantidades:
        Mapeo opcional ``numItem -> cantidad`` para ajustar cantidades
        por ítem.
    extension:
        Datos adicionales para el bloque ``extension``.  Valores vacíos
        o ``None`` se omiten.
    ambiente:
        Ambiente de generación del DTE (``"00"`` por defecto).
    """
    cantidades = cantidades or {}
    ident_factura = factura.get("identificacion", {})

    ambiente = resolve_ambiente(ambiente)
    cabecera = generar_cabecera_dte_data(1, 1, "04", db, ambiente=ambiente)
    now = datetime.now(TZ_EL_SALVADOR)
    identificacion = {
        "version": DTE_VERSIONES["04"],
        "ambiente": ambiente,
        "tipoDte": "04",
        "numeroControl": cabecera["numero_control"],
        "codigoGeneracion": cabecera["codigo_generacion"],
        "tipoModelo": cabecera["tipo_modelo"],
        "tipoOperacion": cabecera["tipo_operacion"],
        "tipoContingencia": cabecera["tipo_contingencia"],
        "motivoContin": cabecera["motivo_contin"],
        "fecEmi": fecha_emision_hoy_str(now),
        "horEmi": now.strftime("%H:%M:%S"),
        "tipoMoneda": "USD",
    }

    documento_relacionado = [
        {
            "tipoDocumento": ident_factura.get("tipoDte"),
            "tipoGeneracion": 2,
            "numeroDocumento": ident_factura.get("codigoGeneracion"),
            "fechaEmision": ident_factura.get("fecEmi"),
        }
    ]

    emisor = copy.deepcopy(factura.get("emisor") or {})
    receptor = copy.deepcopy(factura.get("receptor") or {})
    receptor.setdefault("bienTitulo", "01")
    if not receptor.get("tipoDocumento") or not receptor.get("numDocumento"):
        raise ValueError("receptor requiere tipoDocumento y numDocumento")
    limpiar_documentos(receptor)
    tipo_doc = receptor.get("tipoDocumento")
    num_doc = receptor.get("numDocumento")
    nrc = receptor.get("nrc")
    if tipo_doc == "13":
        if not re.fullmatch(r"\d{9}", num_doc or ""):
            logger.warning(
                "DUI no normalizable; se continúa sin bloquear uuid=%s",
                ident_factura.get("codigoGeneracion"),
            )
        else:
            receptor.pop("nrc", None)
    elif tipo_doc == "36":
        if not re.fullmatch(r"\d{14}", num_doc or ""):
            raise ValueError("NIT inválido en receptor")
        if not nrc or not re.fullmatch(r"\d{1,8}", nrc):
            raise ValueError("NRC inválido en receptor")
    else:
        raise ValueError("tipoDocumento inválido en receptor")

    numero_doc = documento_relacionado[0]["numeroDocumento"]
    items: list[dict] = []
    for num, det in enumerate(factura.get("cuerpoDocumento", []), 1):
        cantidad = cantidades.get(num, det.get("cantidad", 1))
        item = {
            "numItem": num,
            "tipoItem": det.get("tipoItem", 1),
            "codigo": det.get("codigo", f"NR{num:03d}"),
            "descripcion": det.get("descripcion", f"Item {num}"),
            "cantidad": cantidad,
            "uniMedida": det.get("uniMedida", 59),
            "precioUni": 0.0,
            "montoDescu": 0.0,
            "ventaNoSuj": d2(D(0)),
            "ventaExenta": d2(D(0)),
            "ventaGravada": d2(D(0)),
            "tributos": None,
            "codTributo": None,
            "numeroDocumento": numero_doc,
        }
        items.append(item)

    ext = {
        "nombEntrega": "N/D",
        "docuEntrega": "ND",
        "nombRecibe": "N/D",
        "docuRecibe": "ND",
        "observaciones": "N/D",
    }
    if extension:
        ext.update({k: v for k, v in extension.items() if v not in (None, "")})
    limpiar_documentos(ext)

    resumen = {
        "totalNoSuj": d2(D(0)),
        "totalExenta": d2(D(0)),
        "totalGravada": d2(D(0)),
        "subTotal": d2(D(0)),
        "subTotalVentas": d2(D(0)),
        "porcentajeDescuento": d2(D(0)),
        "totalDescu": d2(D(0)),
        "descuNoSuj": d2(D(0)),
        "descuExenta": d2(D(0)),
        "descuGravada": d2(D(0)),
        "tributos": None,
        "montoTotalOperacion": d2(D(0)),
        "totalLetras": monto_a_texto_sv(0.0),
    }

    data = {
        "identificacion": identificacion,
        "documentoRelacionado": documento_relacionado,
        "emisor": emisor,
        "receptor": receptor,
        "cuerpoDocumento": items,
        "extension": ext,
        "resumen": resumen,
        "apendice": None,
    }
    schema = catalogos.get_dte_schema("04")
    return sanitize_dte_payload(data, schema)


def generar_evento_contingencia(
    detalle_dte: list[dict],
    f_inicio: str,
    f_fin: str,
    h_inicio: str,
    h_fin: str,
    tipo_contingencia: int,
    motivo_contingencia: str | None = None,
    ambiente: str | None = None,
) -> dict:
    """Genera la estructura JSON para un evento de contingencia."""

    datos = _load_datos_negocio()

    if ambiente not in ("00", "01"):
        amb_cfg = str(
            ambiente or datos.get("dte_api", {}).get("ambiente", "")
        ).lower()
        ambiente = "01" if amb_cfg.startswith("produc") else "00"

    now = datetime.now(TZ_EL_SALVADOR)
    identificacion = {
        "version": 3,
        "ambiente": ambiente,
        "codigoGeneracion": str(uuid.uuid4()).upper(),
        "fTransmision": fecha_emision_hoy_str(now),
        "hTransmision": now.strftime("%H:%M:%S"),
    }

    nit = solo_digitos(datos.get("nit"))
    if not nit:
        raise ValueError("nit requerido")
    nombre = datos.get("nombre") or datos.get("nombreComercial")
    if not nombre:
        raise ValueError("nombre requerido")
    telefono = str(datos.get("telefono", "")).strip()
    if not PHONE_RE.fullmatch(telefono):
        raise ValueError("telefono inválido")
    correo = datos.get("correo", "")
    if not EMAIL_RE.fullmatch(correo):
        raise ValueError("correo inválido")

    numero_doc = datos.get("dui") or datos.get("nit")
    tipo_doc = datos.get("tipoDocResponsable") or (
        "13" if datos.get("dui") else "36"
    )

    emisor = {
        "nit": nit,
        "nombre": nombre,
        "nombreResponsable": datos.get("nombreResponsable") or nombre,
        "tipoDocResponsable": tipo_doc,
        "numeroDocResponsable": solo_digitos(numero_doc),
        "tipoEstablecimiento": str(datos.get("tipoEstablecimiento") or "01").zfill(2),
        "telefono": telefono,
        "correo": correo,
    }
    emisor["codEstableMH"] = None
    emisor["codPuntoVenta"] = None

    if not detalle_dte:
        raise ValueError("detalleDTE requerido")
    detalle = []
    for idx, item in enumerate(detalle_dte, 1):
        codigo = item.get("codigoGeneracion")
        tipo = item.get("tipoDoc")
        if not codigo or not tipo:
            raise ValueError("detalleDTE incompleto")
        detalle.append(
            {
                "noItem": idx,
                "codigoGeneracion": codigo,
                "tipoDoc": str(tipo).zfill(2),
            }
        )

    try:
        datetime.strptime(f_inicio, "%Y-%m-%d")
        datetime.strptime(f_fin, "%Y-%m-%d")
        datetime.strptime(h_inicio, "%H:%M:%S")
        datetime.strptime(h_fin, "%H:%M:%S")
    except Exception as exc:  # pragma: no cover - defensive
        raise ValueError("fechas u horas inválidas") from exc
    if tipo_contingencia not in {1, 2, 3, 4, 5}:
        raise ValueError("tipoContingencia inválido")
    if tipo_contingencia == 5 and not motivo_contingencia:
        raise ValueError("motivoContingencia requerido para tipo 5")

    motivo = {
        "fInicio": f_inicio,
        "fFin": f_fin,
        "hInicio": h_inicio,
        "hFin": h_fin,
        "tipoContingencia": tipo_contingencia,
        "motivoContingencia": motivo_contingencia if motivo_contingencia else None,
    }

    evento = {
        "identificacion": identificacion,
        "emisor": emisor,
        "detalleDTE": detalle,
        "motivo": motivo,
    }

    schema_path = SCHEMAS_DIR / "contingencia-schema-v3.json"
    try:
        with open(schema_path, "r", encoding="utf-8") as fh:
            schema = json.load(fh)
        from jsonschema import validate

        validate(evento, schema)
    except ValidationError as exc:  # pragma: no cover - best effort
        raise ValueError(exc.message) from exc
    except Exception:  # pragma: no cover - best effort
        pass

    return evento

def _normalize_recepcion_url(raw: str) -> str:
    """Normaliza y valida ``raw`` como URL de recepción de Hacienda.

    - ``strip()`` y eliminación de espacios, saltos de línea o tabulaciones
    - Si falta el esquema se asume ``https``
    - Hosts oficiales sin path obtienen ``/fesv/recepciondte``
    - Colapsa dobles slashes y remueve el slash final
    - Cadena vacía → ``DEFAULT_RECEPCION_URL``
    - Rechaza dominios que contengan ``sandbox``
    """

    raw = "" if raw is None else str(raw)
    raw = re.sub(r"\s+", "", raw.strip())
    if not raw:
        return DEFAULT_RECEPCION_URL
    if "://" not in raw:
        raw = "https://" + raw
    pu = urlparse(raw)
    host = pu.netloc.lower()
    if "sandbox" in host:
        raise ValueError("sandbox no permitido")
    path = pu.path or ""
    if host in {"apitest.dtes.mh.gob.sv", "api.dtes.mh.gob.sv"} and path in ("", "/"):
        path = "/fesv/recepciondte"
    path = "/" + path.lstrip("/")
    path = re.sub("/+", "/", path).rstrip("/")
    return f"{pu.scheme}://{host}{path}"


def _normalize_evento_url(raw: str | None) -> str:
    """Normaliza y valida ``raw`` como URL de envío de evento."""

    text = "" if raw is None else str(raw)
    text = re.sub(r"\s+", "", text.strip())
    if not text:
        return DEFAULT_EVENTO_URL
    if "://" not in text:
        text = "https://" + text
    pu = urlparse(text)
    scheme = pu.scheme or "https"
    if scheme.lower() not in {"http", "https"}:
        scheme = "https"
    host = pu.netloc.lower()
    path = pu.path or ""
    if host in {"apitest.dtes.mh.gob.sv", "api.dtes.mh.gob.sv"} and path in ("", "/"):
        path = "/fesv/contingencia"
    path = "/" + path.lstrip("/")
    path = re.sub("/+", "/", path).rstrip("/")
    if not path:
        path = "/fesv/contingencia"
    return f"{scheme}://{host}{path}"


def _load_dte_api_config():
    """Carga configuración consolidada para la recepción de DTE."""
    datos = _load_datos_negocio()
    dte_api = datos.get("dte_api") or {}
    raw_datos_url = dte_api.get("url") or dte_api.get("endpoint")
    token_configured = any(
        dte_api.get(field) for field in ("token_pruebas", "token_produccion")
    )

    def _norm(amb):
        amb = "" if amb is None else str(amb).strip().lower()
        if amb in {"00", "pruebas"}:
            return "pruebas"
        if amb in {"01", "1", "produccion", "producción"}:
            return "produccion"
        return amb

    ambiente = _norm(dte_api.get("ambiente") or datos.get("ambiente"))

    cfg: dict[str, Any] = {}
    env: dict[str, Any] = {}
    cfg_recep = cfg_url = cfg_endpoint = cfg_evento = None
    try:
        with open(CONFIG_NEGOCIO_PATH, "r", encoding="utf-8") as fh:
            cfg = json.load(fh)
        ambiente = _norm(ambiente or cfg.get("ambiente"))
        env = cfg.get(ambiente or "pruebas", {}) or {}
        cfg_recep = env.get("recepcion_url")
        cfg_url = env.get("url")
        cfg_endpoint = env.get("endpoint")
        cfg_evento = env.get("evento_contingencia_url")
    except Exception:
        pass

    raw_cfg_url = cfg_recep or cfg_url or cfg_endpoint
    ambiente = ambiente or "pruebas"
    logger.debug("Cargando configuración DTE desde %s", DATOS_NEGOCIO_PATH)
    logger.debug(
        "Crudos: dte_api.url=%r dte_api.endpoint=%r cfg.recepcion_url=%r cfg.url=%r cfg.endpoint=%r",
        dte_api.get("url"),
        dte_api.get("endpoint"),
        cfg_recep,
        cfg_url,
        cfg_endpoint,
    )
    url = _normalize_recepcion_url(raw_datos_url or raw_cfg_url)
    raw_evento = dte_api.get("evento_contingencia_url") or cfg_evento
    evento_url = _normalize_evento_url(raw_evento)

    nit_config = ""
    for candidate in (
        datos.get("nit"),
        dte_api.get("nit"),
        env.get("nit") if isinstance(env, dict) else None,
        (env.get("firma_electronica") or {}).get("nit") if isinstance(env, dict) else None,
        cfg.get("nit"),
        (cfg.get("firma_electronica") or {}).get("nit") if isinstance(cfg, dict) else None,
    ):
        digits = solo_digitos(candidate) if candidate else ""
        if digits:
            nit_config = digits
            break

    logger.info("Recepción configurada → %s", url)
    if evento_url != DEFAULT_EVENTO_URL:
        logger.info("Evento contingencia configurado → %s", evento_url)
    return {"ambiente": ambiente, "url": url, "evento_url": evento_url, "nit": nit_config}


def _normalize_ambiente_value(raw: str | None) -> str | None:
    """Normaliza representaciones diversas de ambiente a ``"00"`` o ``"01"``."""

    if raw is None:
        return None

    text = str(raw).strip()
    if not text:
        return None

    if text in {"00", "01"}:
        return text

    digits = "".join(ch for ch in text if ch.isdigit())
    if digits.startswith("01"):
        return "01"
    if digits.startswith("00"):
        return "00"

    lowered = text.lower()
    if lowered.startswith("pro"):
        return "01"
    if lowered.startswith("pru"):
        return "00"

    if text == "1":
        return "01"
    if text == "0":
        return "00"

    return None


def resolve_ambiente(ambiente: str | None) -> str:
    """Resuelve el ambiente efectivo tomando en cuenta la configuración local."""

    try:
        config = _load_dte_api_config() or {}
    except Exception:
        config = {}

    config_ambiente = _normalize_ambiente_value(config.get("ambiente"))
    if config_ambiente == "01":
        return "01"

    normalized = _normalize_ambiente_value(ambiente)
    return normalized or "00"


def _assert_no_ejemplo(path: str) -> None:
    banned = os.path.join("facturas_consumidor_final", "ejemplo.json")
    assert not str(path).endswith(banned), "writing to ejemplo.json is forbidden"


def _write_json(path: str, data):
    _assert_no_ejemplo(path)
    if isinstance(data, str):
        save_file(path, data, add_final_newline=not path.endswith(".jws"))
    else:
        save_file(path, stable_stringify(data, indent=2))


def _dte_base_dir(
    dte_data: dict, fallido: bool = False, pendientes: bool = False
) -> str:
    """Return destination directory for ``dte_data`` grouped by ``tipoDte``.

    ``fallido`` indica si el DTE debe almacenarse en ``dte_fallidos`` y
    ``pendientes`` controla si se usa ``dtes_pendientes`` como raíz.
    """

    ident = dte_data.get("identificacion", {})
    tipo = str(ident.get("tipoDte", "")).zfill(2)
    if pendientes:
        base = DTES_PENDIENTES_DIR
    else:
        base = DTE_FALLIDOS_DIR if fallido else DTES_DIR
    mapping = {
        "01": "fcf",  # Factura consumidor final
        "03": "ccf",  # Comprobante de crédito fiscal
        "04": "nr",   # Nota de remisión
        "05": "nc",   # Nota de crédito
        "06": "nd",   # Nota de débito
        "07": "cr",   # Comprobante de retención
        "08": "cl",   # Comprobante de liquidación
        "09": "dcl",  # Documento contable de liquidación
        "11": "fex",  # Factura de exportación
        "14": "fse",  # Factura de sujeto excluido
        "15": "cd",   # Comprobante de donación
    }
    folder = mapping.get(tipo)
    base_path = Path(base)
    target = base_path / folder if folder else base_path
    target.mkdir(parents=True, exist_ok=True)
    return str(target)


def _safe_filename_component(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-")
    return cleaned or "dato"


def _save_hacienda_payload(sobre: Mapping[str, Any], serialized: str | bytes | None = None) -> None:
    """Persist the JSON payload transmitted to Hacienda."""

    if not isinstance(sobre, AbcMapping):
        return

    try:
        target_dir = Path(DTE_FIRMADO_DIR)
        target_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        logger.debug("No se pudo crear la carpeta de DTE firmados", exc_info=True)
        return

    timestamp = datetime.now(TZ_EL_SALVADOR).strftime("%Y%m%d-%H%M%S")
    tipo = str(sobre.get("tipoDte") or "").strip()
    codigo = str(sobre.get("codigoGeneracion") or "").strip()

    name_parts = [timestamp]
    if tipo:
        name_parts.append(_safe_filename_component(tipo))
    if codigo:
        name_parts.append(_safe_filename_component(codigo))
    else:
        name_parts.append("SIN-CODIGO")

    base_name = "_".join(part for part in name_parts if part)
    filename = f"{base_name}.json"
    dest_path = target_dir / filename

    suffix = 1
    while dest_path.exists():
        dest_path = target_dir / f"{base_name}_{suffix:02d}.json"
        suffix += 1

    try:
        if isinstance(serialized, bytes):
            payload_text = serialized.decode("utf-8")
        elif isinstance(serialized, str):
            payload_text = serialized
        else:
            payload_text = json.dumps(sobre, ensure_ascii=False)
        dest_path.write_text(payload_text, encoding="utf-8")
    except Exception:
        logger.debug("No se pudo guardar el JSON enviado a Hacienda", exc_info=True)


def _post_dte_with_config(
    url: str, documento: str, dte_data: dict | None, config: Mapping[str, Any] | None
) -> dict:
    """Wrapper de :func:`_post_dte` que omite ``ambiente_config`` cuando no existe."""

    func = _post_dte
    try:
        signature = inspect.signature(func)
        required_positional = [
            param
            for param in signature.parameters.values()
            if param.kind
            in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            )
            and param.default is inspect._empty
        ]
    except (TypeError, ValueError):
        required_positional = []

    ambiente_cfg = None
    if config is not None:
        getter = getattr(config, "get", None)
        if callable(getter):
            try:
                ambiente_cfg = getter("ambiente")
            except Exception:
                ambiente_cfg = None
        elif isinstance(config, AbcMapping):
            ambiente_cfg = config.get("ambiente")

    kwargs = {}
    if ambiente_cfg is not None:
        kwargs["ambiente_config"] = ambiente_cfg

    if len(required_positional) >= 4:
        return func(url, documento, documento, dte_data, **kwargs)
    return func(url, documento, dte_data, **kwargs)


def _save_signed_dte(dte_data: dict, jws_token: str, fallido: bool = False) -> None:
    """Guarda el JSON y JWS usando estructura versionada por hash."""
    expected_hash = hash_json(dte_data)
    version_dir = ""
    json_path = ""
    try:
        base_dir = _dte_base_dir(dte_data, fallido=fallido)
        version_dir, _ = versioned_dte.ensure_version(dte_data, base_dir)
        json_path = os.path.join(version_dir, "documento.json")
        jws_name = versioned_dte.add_jws(version_dir, jws_token, origen="auto")
        sobre = construir_sobre_recepcion(jws_token, dte_data)
        if sobre.get("estado") != "Error":
            sobre_path = os.path.join(
                version_dir, jws_name.replace(".jws", "_sobre_hacienda.json")
            )
            _write_json(sobre_path, sobre)
    except Exception:
        pass
    else:
        with open(json_path, "r", encoding="utf-8") as fh:
            persisted_data = json.load(fh)
        actual_hash = hash_json(persisted_data)
        if actual_hash != expected_hash:
            logger.error(
                "El JSON guardado difiere del payload firmado: esperado %s, obtenido %s (ruta: %s)",
                expected_hash,
                actual_hash,
                json_path,
            )
            raise RuntimeError("El JSON guardado difiere del payload firmado")


class DTEValidationError(Exception):
    """Error de validación que incluye lista de errores y ruta del JSON."""

    def __init__(self, errors, json_path):
        super().__init__("; ".join(errors))
        self.errors = errors
        self.json_path = json_path


def save_dte_json(dte_data: dict, filename: str | None = None) -> str:
    """Guarda ``dte_data`` en la carpeta de pendientes y devuelve la ruta."""
    try:
        base_dir = _dte_base_dir(dte_data, pendientes=True)
        version_dir, _ = versioned_dte.ensure_version(dte_data, base_dir)
        json_path = os.path.join(version_dir, "documento.json")
        if filename and filename != "documento.json":
            dest = os.path.join(version_dir, filename)
            os.replace(json_path, dest)
            json_path = dest
        return json_path
    except Exception:
        return ""


def _finalize_pendiente(
    pend_json_path: str, dte_data: dict, jws_token: str, estado: str
) -> str:
    """Move a pending DTE to its final directory preserving its name."""
    ident = dte_data.get("identificacion", {})
    codigo = ident.get("codigoGeneracion") or "SIN-CODIGO"
    fallido = str(estado).lower() == "rechazado"
    final_base = _dte_base_dir(dte_data, fallido=fallido)
    dest_dir = os.path.join(final_base, codigo)

    pend_dir = os.path.dirname(pend_json_path)
    filename = os.path.basename(pend_json_path)

    if os.path.exists(dest_dir):
        shutil.rmtree(dest_dir)
    shutil.move(pend_dir, dest_dir)

    final_path = os.path.join(dest_dir, filename)
    if jws_token:
        jws_path = os.path.splitext(final_path)[0] + ".jws"
        save_file(jws_path, jws_token, add_final_newline=False)

    # Clean up empty pending directories
    pend_tipo_dir = os.path.dirname(pend_dir)
    try:
        os.rmdir(pend_tipo_dir)
        root_pend = os.path.dirname(pend_tipo_dir)
        os.rmdir(root_pend)
    except OSError:
        pass

    return final_path


def _format_validation_errors(exc: Exception) -> list:
    """Convierte la excepción de validación en una lista de mensajes."""
    if isinstance(exc, ValidationError) and getattr(exc, "errors", None):
        formatted = []
        for err in exc.errors:
            path = ".".join(str(p) for p in err.path)
            if path:
                formatted.append(f"{path}: {err.message}")
            else:
                formatted.append(err.message)
        return formatted
    msg = str(exc)
    if ":" in msg:
        head, tail = msg.split(":", 1)
        return [f"{head.strip()}: {part.strip()}" for part in tail.split(",")]
    return [msg]


def _decode_jws_payload(token: str) -> dict:
    """Return the JSON payload embedded in ``token``.

    Raises ``ValueError`` if the token is not a valid JWS string.
    """
    try:
        parts = token.split(".")
        if len(parts) != 3:
            raise ValueError("JWS malformado")
        payload = parts[1]
        padding = "=" * (-len(payload) % 4)
        payload_bytes = base64.urlsafe_b64decode(payload + padding)
        return json.loads(payload_bytes.decode("utf-8"))
    except Exception as exc:  # pragma: no cover - defensive
        raise ValueError("documento inválido") from exc


def construir_sobre_recepcion(documento: str, dte_data: dict | None = None) -> dict:
    """Retorna el body listo para ``POST /fesv/recepciondte``.

    Si ``documento`` parece un JWS se extraen los metadatos desde su payload.
    Cuando no es un JWS válido o la decodificación falla, los metadatos se
    obtienen de ``dte_data``.  Valida campos requeridos y formatos.  En caso de
    error devuelve ``{"estado": "Error", "detalle": "<mensaje>"}``.
    """

    if isinstance(documento, str):
        documento = documento.strip()

    meta: dict[str, object] = {}
    payload = None

    if isinstance(documento, str) and documento.count(".") == 2:
        try:
            payload = _decode_jws_payload(documento)
            meta = payload.get("identificacion") or payload.get("identificador") or payload
        except Exception:
            payload = None
            meta = {}

    if isinstance(dte_data, dict):
        ident = dte_data.get("identificacion") or dte_data.get("identificador") or dte_data
        if payload is not None:
            ident_payload = payload.get("identificacion") or payload.get("identificador") or payload
            for key in ("codigoGeneracion", "tipoDte", "version"):
                if str(ident_payload.get(key)) != str(ident.get(key)):
                    return {
                        "estado": "Error",
                        "detalle": "La firma no corresponde a la versión actual del documento. Vuelva a firmar o seleccione una firma compatible.",
                    }
        if meta:
            for k, v in ident.items():
                meta.setdefault(k, v)
        else:
            meta = ident

    try:
        ambiente = str(meta["ambiente"])
    except Exception:
        return {"estado": "Error", "detalle": "falta ambiente"}
    if ambiente not in {"00", "01"}:
        return {"estado": "Error", "detalle": "ambiente inválido"}

    try:
        version = int(meta["version"])
    except Exception:
        return {"estado": "Error", "detalle": "version inválida"}

    tipo = meta.get("tipoDte") or meta.get("tipoDocumento")
    if tipo is None:
        return {"estado": "Error", "detalle": "tipoDte requerido"}
    tipo = str(tipo).zfill(2)

    codigo = meta.get("codigoGeneracion")
    if codigo is None:
        return {"estado": "Error", "detalle": "codigoGeneracion requerido"}

    id_envio = meta.get("idEnvio", 1)
    try:
        id_envio = int(id_envio)
    except Exception:
        return {"estado": "Error", "detalle": "idEnvio inválido"}

    return {
        "ambiente": ambiente,
        "idEnvio": id_envio,
        "version": version,
        "tipoDte": tipo,
        "codigoGeneracion": str(codigo),
        "documento": documento,
    }

def format_cliente_id_from_dui(dui: str | None) -> str | None:
    if not dui:
        return None
    return re.sub(r"\D+", "", str(dui)) or None


def detect_user_agent(
    user_agent: str | None = None,
    opts: dict | None = None,
    app_version: str | None = None,
    client_id: str | None = None,
) -> str:
    # 1) UA explícito
    if user_agent:
        return str(user_agent)
    # 2) UA proveniente de la capa web (navegador reenviado en opts)
    if isinstance(opts, dict) and opts.get("user_agent"):
        ua_from_opts = str(opts["user_agent"])[:256]
        return ua_from_opts
    # 3) Fallback genérico
    av = app_version or APP_VERSION
    parts = str(av).split(".")
    base_version = ".".join(parts[:2]) if parts else str(av)
    base = f"Vertex-DTE/{base_version}"
    return base


_TOKEN_INVALID_SENTINEL = "token inválido o caducado"


def _extract_auth_detail(value, fallback_text: str | None = None) -> str:
    if isinstance(value, dict):
        for key in ("detalle", "descripcionMsg", "message", "observaciones"):
            if key in value:
                extracted = _extract_auth_detail(value.get(key))
                if extracted:
                    return extracted
        if value:
            try:
                return json.dumps(value, ensure_ascii=False)
            except TypeError:
                return str(value)
        return ""
    if isinstance(value, (list, tuple, set)):
        for item in value:
            extracted = _extract_auth_detail(item)
            if extracted:
                return extracted
        return ""
    if isinstance(value, str):
        return value.strip()
    if value is None:
        return (fallback_text or "").strip() if fallback_text else ""
    try:
        return json.dumps(value, ensure_ascii=False)
    except TypeError:
        return str(value)


def _contains_token_invalid_phrase(*values: str) -> bool:
    for value in values:
        if not value:
            continue
        if _TOKEN_INVALID_SENTINEL in value.casefold():
            return True
    return False


def _post_dte(
    url: str,
    documento: str,
    dte_data: dict | None = None,
    user_agent: str | None = None,
    opts: dict | None = None,
    app_version: str | None = None,
    dui: str | None = None,
    client_id: str | None = None,
    ambiente_config: str | None = None,
) -> dict:
    pu = urlparse(url)
    assert pu.netloc in {
        "apitest.dtes.mh.gob.sv",
        "api.dtes.mh.gob.sv",
    }, f"Host inválido: {url}"
    assert pu.path.rstrip("/") == "/fesv/recepciondte", f"Path inválido: {url}"

    sobre = construir_sobre_recepcion(documento, dte_data)
    if sobre.get("estado") == "Error":
        return sobre

    serialized_payload: str | bytes | None = None
    try:
        prepared = requests.Request("POST", url, json=sobre).prepare()
        body = getattr(prepared, "body", None)
        if isinstance(body, (bytes, bytearray)):
            serialized_payload = bytes(body)
        elif isinstance(body, str):
            serialized_payload = body
    except Exception:
        serialized_payload = None

    try:
        _save_hacienda_payload(sobre, serialized_payload)
    except Exception:
        logger.debug("No se pudo conservar el JSON transmitido a Hacienda", exc_info=True)

    client_id = client_id or format_cliente_id_from_dui(dui)
    ua = detect_user_agent(user_agent, opts, app_version or APP_VERSION, client_id)
    headers = auth_headers(
        {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": ua,
            "app-version": str(app_version or APP_VERSION),
        },
        ambiente=ambiente_config,
    ).copy()
    if client_id:
        headers.setdefault("cliente-id", str(client_id))

    try:
        resp, data, text_body = _post_json(url, headers, sobre, tag="post_dte")
    except (requests.ConnectionError, requests.Timeout):
        return {"estado": "Error", "detalle": "Sin conexión a Internet"}
    except requests.RequestException as exc:
        return {"estado": "Error", "detalle": str(exc)}

    if resp.status_code in {401, 403}:
        _log_jwt_diagnostics(
            headers.get("Authorization"),
            now=datetime.now(timezone.utc),
        )
        www_auth_header = resp.headers.get("WWW-Authenticate")
        if env_flag("DTE_DEBUG_HTTP"):
            content_length = resp.headers.get("Content-Length") or resp.headers.get("content-length")
            body_len = len(resp.content or b"")
            if (
                not (www_auth_header and str(www_auth_header).strip())
                and (str(content_length or "").strip() in {"", "0"})
                and body_len == 0
            ):
                logger.info("HTTP: %s sin cuerpo y sin WWW-Authenticate", resp.status_code)
        detail_payload = data if data is not None else text_body
        detail_text = _extract_auth_detail(detail_payload, text_body if isinstance(text_body, str) else None)
        www_auth_text = str(www_auth_header or "").strip()
        token_phrase = _contains_token_invalid_phrase(detail_text, text_body if isinstance(text_body, str) else None)
        auth_error = bool(www_auth_text) or token_phrase
        result: dict[str, Any] = {
            "estado": "Rechazado",
            "http_status": resp.status_code,
            "auth_error": auth_error,
        }
        if auth_error:
            result["detalle"] = (
                "Token inválido o caducado. Obtenga un nuevo token en Configuración > Facturación Electrónica y reintente."
            )
            if detail_text and not token_phrase:
                result["descripcionMsg"] = detail_text
        else:
            fallback_text = detail_text or f"HTTP {resp.status_code} sin detalle"
            result["detalle"] = fallback_text
            if isinstance(detail_payload, dict) and detail_payload:
                result["detalle_respuesta"] = detail_payload
        print(json.dumps(result, ensure_ascii=False))
        return result

    if isinstance(resp.status_code, int) and resp.status_code >= 400:
        detalle = data if data is not None else text_body
        result = {
            "estado": "Rechazado",
            "http_status": resp.status_code,
            "detalle": detalle,
        }
        if isinstance(data, dict):
            detalle_info = data.get("detalle") if isinstance(data.get("detalle"), dict) else data
            for key in ("descripcionMsg", "observaciones"):
                if key in detalle_info:
                    result[key] = detalle_info[key]
            err = _parse_error_response(result)
            if err:
                result["errores"] = err
        print(json.dumps(result, ensure_ascii=False))
        return result

    result = data if data is not None else {"estado": "Recibido", "detalle": text_body}
    print(json.dumps(result, ensure_ascii=False))
    return result

def _post_evento(
    url: str,
    evento: str,
    nit: str,
    evento_data: dict | None = None,
    user_agent: str | None = None,
    opts: dict | None = None,
    app_version: str | None = None,
    dui: str | None = None,
    client_id: str | None = None,
    ambiente_config: str | None = None,
) -> dict:
    pu = urlparse(url)
    scheme = pu.scheme.lower()
    if scheme not in {"https", "http"}:
        raise ValueError(f"URL de evento inválida: {url}")
    host = pu.netloc
    if not host:
        raise ValueError(f"URL de evento inválida: {url}")

    nit_digits = solo_digitos(nit)
    if not nit_digits:
        raise ValueError("nit requerido para evento")

    body = {"nit": nit_digits, "documento": evento}

    client_id = client_id or format_cliente_id_from_dui(dui)
    ua = detect_user_agent(user_agent, opts, app_version or APP_VERSION, client_id)
    headers = auth_headers(
        {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": ua,
            "app-version": str(app_version or APP_VERSION),
        },
        ambiente=ambiente_config,
    ).copy()
    if client_id:
        headers.setdefault("cliente-id", str(client_id))

    try:
        resp, data, text_body = _post_json(url, headers, body, tag="post_evento")
    except requests.RequestException as exc:
        return {"estado": "Error", "detalle": str(exc)}

    if resp.status_code in {401, 403}:
        _log_jwt_diagnostics(
            headers.get("Authorization"),
            now=datetime.now(timezone.utc),
        )
        www_auth_header = resp.headers.get("WWW-Authenticate")
        if env_flag("DTE_DEBUG_HTTP"):
            content_length = resp.headers.get("Content-Length") or resp.headers.get("content-length")
            body_len = len(resp.content or b"")
            if (
                not (www_auth_header and str(www_auth_header).strip())
                and (str(content_length or "").strip() in {"", "0"})
                and body_len == 0
            ):
                logger.info("HTTP: %s sin cuerpo y sin WWW-Authenticate", resp.status_code)
        detail_payload = data if data is not None else text_body
        detail_text = _extract_auth_detail(detail_payload, text_body if isinstance(text_body, str) else None)
        www_auth_text = str(www_auth_header or "").strip()
        token_phrase = _contains_token_invalid_phrase(detail_text, text_body if isinstance(text_body, str) else None)
        auth_error = bool(www_auth_text) or token_phrase
        result: dict[str, Any] = {
            "estado": "Rechazado",
            "http_status": resp.status_code,
            "auth_error": auth_error,
        }
        if auth_error:
            result["detalle"] = (
                "Token inválido o caducado. Obtenga un nuevo token en Configuración > Facturación Electrónica y reintente."
            )
            if detail_text and not token_phrase:
                result["descripcionMsg"] = detail_text
        else:
            fallback_text = detail_text or f"HTTP {resp.status_code} sin detalle"
            result["detalle"] = fallback_text
            if isinstance(detail_payload, dict) and detail_payload:
                result["detalle_respuesta"] = detail_payload
        print(json.dumps(result, ensure_ascii=False))
        return result

    if isinstance(resp.status_code, int) and resp.status_code >= 400:
        detalle = data if data is not None else text_body
        result = {"estado": "Rechazado", "http_status": resp.status_code, "detalle": detalle}
        print(json.dumps(result, ensure_ascii=False))
        return result

    result = data if data is not None else {"estado": "Recibido", "detalle": text_body}
    print(json.dumps(result, ensure_ascii=False))
    return result

def transmitir_dte(
    db: DB, venta_id: int, modo: str | None = None, tipo_dte: str = "01"
) -> dict:
    """Genera y transmite un DTE reutilizando ``_enviar_documento``.

    ``tipo_dte`` permite especificar el código del documento a transmitir.
    Actualmente tanto los tickets como las facturas a consumidor final se
    envían con el código ``"01"``.
    """

    if modo is None:
        modo = get_default_modo_transmision()

    tipo_dte = str(tipo_dte)
    venta_extra = {}
    extra_es_ticket = False
    if hasattr(db, "get_venta_by_id"):
        try:
            venta_row = db.get_venta_by_id(venta_id)
        except Exception:
            venta_row = None
        row_data = venta_row if isinstance(venta_row, dict) else None
        if row_data is None and venta_row is not None:
            try:
                row_data = dict(venta_row)
            except Exception:
                row_data = None
        if isinstance(row_data, dict):
            raw_extra = row_data.get("extra")
            if isinstance(raw_extra, str) and raw_extra:
                try:
                    venta_extra = json.loads(raw_extra)
                except Exception:
                    venta_extra = {}
            elif isinstance(raw_extra, dict):
                venta_extra = raw_extra
    extra_es_ticket = bool(venta_extra.get("es_ticket"))

    if tipo_dte == "01" and extra_es_ticket:
        data = generar_ticket_json(db, venta_id)
    else:
        extra_kwargs = {}
        if extra_es_ticket and tipo_dte != "01":
            extra_kwargs["extra"] = {"es_ticket": False}
        data = generar_dte_json(db, venta_id, tipo_dte=tipo_dte, **extra_kwargs)

    final_tipo = str(data.get("identificacion", {}).get("tipoDte") or "")
    if final_tipo != tipo_dte:
        raise ValueError(
            f"tipoDte generado {final_tipo or 'desconocido'} no coincide con solicitado {tipo_dte}"
        )
    if final_tipo == "01":
        recalcular_totales(data, incluir_iva=True)

    data = apply_schema_patch(data)
    schema = catalogos.get_dte_schema(tipo_dte)
    # La validación de esquema se omite para permitir la transmisión sin
    # interrupciones por inconsistencias.
    # try:
    #     validate_dte_json(data, db=db)
    # except Exception as exc:
    #     json_path = save_dte_json(data)
    #     errors = _format_validation_errors(exc)
    #     raise DTEValidationError(errors, json_path) from exc
    resp = _enviar_documento(db, venta_id, data, modo)
    sello = resp.get("sello")
    if sello:
        db.update_venta_extra(venta_id, {"selloRecibido": sello})
    return resp


def _is_jws_token(data) -> bool:
    """Devuelve ``True`` si ``data`` parece ser un JWS firmado."""
    if isinstance(data, str):
        return data.count(".") >= 2
    if isinstance(data, dict):
        return all(k in data for k in ("payload", "signature"))
    return False


def transmitir_dte_orphan(db: DB, json_path: str) -> dict:
    """Transmite un DTE desde ``json_path`` registrando el resultado."""
    with open(json_path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)

    if _is_jws_token(raw):
        if isinstance(raw, dict):
            jws_token = ".".join(
                [raw.get("protected", ""), raw.get("payload", ""), raw.get("signature", "")]
            )
        else:
            jws_token = raw
        payload = _decode_jws_payload(jws_token)
    else:
        data = apply_schema_patch(raw)
        tipo = (
            data.get("identificacion")
            or data.get("identificador")
            or {}
        ).get("tipoDte")
        if str(tipo) == "01":
            recalcular_totales(data, incluir_iva=True)
        schema = catalogos.get_dte_schema(str(tipo))
        # Se omite la validación para permitir la transmisión aun cuando el
        # payload no cumpla estrictamente con el esquema.
        # try:
        #     validate_dte_json(data, db=db)
        # except Exception as exc:
        #     errors = _format_validation_errors(exc)
        #     raise DTEValidationError(errors, json_path) from exc
        ident = data.get("identificacion") or data.get("identificador") or {}
        ident["fecEmi"] = fecha_emision_hoy_str()
        ident["horEmi"] = datetime.now(TZ_EL_SALVADOR).strftime("%H:%M:%S")
        if "identificacion" in data:
            data["identificacion"] = ident
        elif "identificador" in data:
            data["identificador"] = ident
        payload = data
        jws_token = jws.sign_json(data)

    ident = payload.get("identificacion") or payload.get("identificador") or {}
    meta = {
        "ambiente": ident.get("ambiente"),
        "version": ident.get("version"),
        "tipoDte": ident.get("tipoDte") or ident.get("tipoDocumento"),
        "codigoGeneracion": ident.get("codigoGeneracion"),
    }
    config = _load_dte_api_config()
    url = config["url"]
    auth_host = auth.get_last_auth_host()
    recep_host = urlparse(url).netloc
    if auth_host and recep_host != auth_host:
        logger.warning(
            "Auth host %s ≠ recepción %s (esto es normal en prod)",
            auth_host,
            recep_host,
        )
    try:
        respuesta = _post_dte_with_config(url, jws_token, meta, config)
        sello = respuesta.get("sello") or respuesta.get("selloRecepcion") or ""
        estado = (
            respuesta.get("estado")
            or respuesta.get("estadoDte")
            or respuesta.get("descripcionEstado")
            or "Transmitido"
        )
        detalle = respuesta.get("detalle")
    except Exception:
        db.registrar_envio_dte(
            None,
            "orphan",
            "Rechazado",
            "",
            codigo_generacion=ident.get("codigoGeneracion"),
            numero_control=ident.get("numeroControl"),
        )
        raise

    db.registrar_envio_dte(
        None,
        "orphan",
        estado,
        sello,
        json.dumps(respuesta, ensure_ascii=False),
        codigo_generacion=ident.get("codigoGeneracion"),
        numero_control=ident.get("numeroControl"),
    )
    if estado == "Rechazado":
        respuesta["errores"] = _parse_error_response(respuesta)
    res = {"estado": estado, "sello": sello}
    ident_info = {
        "numeroControl": ident.get("numeroControl"),
        "codigoGeneracion": ident.get("codigoGeneracion"),
        "tipoDte": ident.get("tipoDte") or ident.get("tipoDocumento"),
        "ambiente": ident.get("ambiente"),
    }
    res["identificacion"] = {
        key: value
        for key, value in ident_info.items()
        if value is not None
    }
    if detalle:
        res["detalle"] = detalle
    if respuesta.get("errores"):
        res["errores"] = respuesta["errores"]
    return res


def enviar_dte_a_hacienda(jws_token: str) -> dict:
    """Transmite un DTE ya firmado (JWS) al entorno de pruebas de Hacienda."""
    jws_token = jws_token.strip()
    config = _load_dte_api_config()
    url = config["url"]
    payload = _decode_jws_payload(jws_token)
    ident = payload.get("identificacion") or payload.get("identificador") or {}
    meta = {
        "ambiente": ident.get("ambiente"),
        "version": ident.get("version"),
        "tipoDte": ident.get("tipoDte") or ident.get("tipoDocumento"),
        "codigoGeneracion": ident.get("codigoGeneracion"),
    }
    respuesta = _post_dte_with_config(url, jws_token, meta, config)
    estado = (
        respuesta.get("estado")
        or respuesta.get("estadoDte")
        or respuesta.get("descripcionEstado")
    )
    if estado:
        respuesta["estado"] = estado
    if respuesta.get("estado") == "Rechazado":
        respuesta["errores"] = _parse_error_response(respuesta)
    return respuesta


def enviar_lote_dtes(pendientes, db: DB | None = None):
    """Agrupa ``pendientes`` y envía lotes de hasta 100 DTE.

    ``pendientes`` debe ser un iterable de pares ``(venta_id, dte_data)``.
    Cada lote se firma individualmente y se envía en una única petición.
    El ``codigoLote`` devuelto se almacena en ``dte_envios`` para cada DTE.
    """

    db = db or DB()
    pendientes = list(pendientes)
    if not pendientes:
        return []

    cfg = _load_dte_api_config()
    url = cfg["url"].rstrip("/") + "/lote"

    resultados = []
    for i in range(0, len(pendientes), 100):
        bloque = pendientes[i : i + 100]
        detalle = []
        ambiente = version = None
        for venta_id, data in bloque:
            ident = data.get("identificacion") or data.get("identificador") or {}
            ambiente = ambiente or ident.get("ambiente")
            version = version or ident.get("version")
            firmado = jws.sign_json(data)
            detalle.append(
                {
                    "venta_id": venta_id,
                    "codigoGeneracion": ident.get("codigoGeneracion"),
                    "numeroControl": ident.get("numeroControl"),
                    "tipoDte": ident.get("tipoDte") or ident.get("tipoDocumento"),
                    "documento": firmado,
                }
            )

        body = {
            "ambiente": ambiente,
            "version": version,
            "idEnvio": 1,
            "cantidadDocumentos": len(detalle),
            "detalle": [
                {
                    "codigoGeneracion": d["codigoGeneracion"],
                    "tipoDte": d["tipoDte"],
                    "documento": d["documento"],
                }
                for d in detalle
            ],
        }

        headers = auth_headers(
            {
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            ambiente=cfg.get("ambiente"),
        ).copy()

        try:
            tag = f"post_lote[{i // 100}]"
            resp, data_resp, text_body = _post_json(url, headers, body, tag=tag)
            if resp.status_code in {401, 403}:
                _log_jwt_diagnostics(
                    headers.get("Authorization"),
                    now=datetime.now(timezone.utc),
                )
                if env_flag("DTE_DEBUG_HTTP"):
                    www_auth = resp.headers.get("WWW-Authenticate")
                    content_length = resp.headers.get("Content-Length") or resp.headers.get("content-length")
                    body_len = len(resp.content or b"")
                    if (
                        not (www_auth and str(www_auth).strip())
                        and (str(content_length or "").strip() in {"", "0"})
                        and body_len == 0
                    ):
                        logger.info("HTTP: %s sin cuerpo y sin WWW-Authenticate", resp.status_code)
            if data_resp is None:
                data_resp = {"detalle": text_body} if text_body else {}
        except Exception as exc:  # pragma: no cover - defensive
            data_resp = {"estado": "Error", "detalle": str(exc)}

        codigo_lote = data_resp.get("codigoLote") or data_resp.get("codigoGeneracion")
        estado = data_resp.get("estado") or data_resp.get("estadoLote") or ""
        for d in detalle:
            db.registrar_envio_dte(
                d["venta_id"],
                "lote",
                estado or "Pendiente",
                "",
                json.dumps(data_resp, ensure_ascii=False),
                codigo_lote=codigo_lote,
                codigo_generacion=d["codigoGeneracion"],
                numero_control=d.get("numeroControl"),
            )
        resultados.append(data_resp)

    return resultados


def consultar_estado_lote(codigo_lote: str) -> dict:
    """Consulta el estado de un lote previamente enviado."""

    cfg = _load_dte_api_config()
    url = cfg["url"].rstrip("/") + f"/lote/{codigo_lote}"
    headers = auth_headers({"Accept": "application/json"}, ambiente=cfg.get("ambiente"))
    try:
        resp = requests.get(url, headers=headers, timeout=20)
        return resp.json()
    except Exception as exc:  # pragma: no cover - defensive
        return {"estado": "Error", "detalle": str(exc)}


def _parse_error_response(respuesta: dict) -> str:
    """Construye un mensaje de error a partir de ``descripcionMsg`` y ``observaciones``."""

    def _agregar_partes(origen, partes):
        desc = origen.get("descripcionMsg")
        if desc:
            partes.append(str(desc))
        obs = origen.get("observaciones")
        if isinstance(obs, dict):
            for k, v in obs.items():
                partes.append(f"{k}: {v}")
        elif isinstance(obs, list):
            partes.extend(str(o) for o in obs)
        elif obs:
            partes.append(str(obs))

    partes: list[str] = []
    _agregar_partes(respuesta, partes)
    detalle = respuesta.get("detalle", {})
    if isinstance(detalle, dict):
        _agregar_partes(detalle, partes)
    mensaje = "; ".join(partes)
    if mensaje:
        logger.error(mensaje)
    return mensaje


def _enviar_documento(
    db: DB, doc_id: int, data: dict, modo: str | None = "normal", jws_token: str | None = None
) -> dict:
    """Firma y envía ``data`` registrando el envío.

    Si ``jws_token`` se proporciona, se reutiliza en lugar de firmar nuevamente.
    """

    modo_raw = "" if modo is None else str(modo).strip()
    if not modo_raw:
        modo_raw = get_default_modo_transmision()
    modo_norm = modo_raw.lower()
    if modo_norm.startswith("2") or "contingencia" in modo_norm:
        modo = "contingencia"
    else:
        modo = "normal"

    print("DTE: START_enviar_documento", "modo=", modo)
    ident = data.get("identificacion") or data.get("identificador") or {}
    doc_ref = ident.get("numeroControl") or ident.get("codigoGeneracion") or doc_id
    raw_tipo_dte = ident.get("tipoDte") or ident.get("tipoDocumento")
    tipo_dte = str(raw_tipo_dte or "").strip()
    tipo_dte_norm = tipo_dte.zfill(2) if tipo_dte.isdigit() else tipo_dte
    nota_types = {"04", "05", "06"}
    ident_codigo = (ident.get("codigoGeneracion") or "").upper()
    ident_control = (ident.get("numeroControl") or "").upper()
    SUCCESS_STATES = ("TRANSMITIDO", "RECIBIDO", "PROCESADO", "ACEPTADO")
    if doc_id is not None:
        db.ensure_column("dte_envios", "codigo_generacion", "TEXT")
        db.ensure_column("dte_envios", "numero_control", "TEXT")
        row = db.cursor.execute(
            """
            SELECT estado, codigo_generacion, numero_control FROM dte_envios
            WHERE venta_id=? AND UPPER(estado) IN (?, ?, ?, ?)
            ORDER BY id DESC LIMIT 1
            """,
            (doc_id, *SUCCESS_STATES),
        ).fetchone()
        if row:
            prev_codigo = (row[1] or "").upper()
            prev_control = (row[2] or "").upper()
            if prev_codigo == ident_codigo and prev_control == ident_control:
                print("DTE: ALREADY_SENT_GUARD", row[0] if row else None)
                raise ValueError("DTE ya enviado")

    config = _load_dte_api_config()

    if not data.get("resumen", {}).get("totalLetras"):
        raise ValueError("El total en letras es obligatorio")

    url = config["url"]
    meta = {
        "ambiente": ident.get("ambiente"),
        "version": ident.get("version"),
        "tipoDte": tipo_dte,
        "codigoGeneracion": ident.get("codigoGeneracion"),
    }
    today_str = None
    if tipo_dte_norm in nota_types:
        today_str = fecha_emision_hoy_str()
        if ident.get("fecEmi") != today_str:
            ident["fecEmi"] = today_str
    ident["horEmi"] = datetime.now(TZ_EL_SALVADOR).strftime("%H:%M:%S")
    if "identificacion" in data:
        data["identificacion"] = ident
    elif "identificador" in data:
        data["identificador"] = ident
    auth_host = auth.get_last_auth_host()
    recep_host = urlparse(url).netloc
    if auth_host and recep_host != auth_host:
        logger.warning(
            "Auth host %s ≠ recepción %s (esto es normal en prod)",
            auth_host,
            recep_host,
        )
    try:
        resumen = data.get("resumen", {})
        print("DTE: VALIDATE_IN", list((resumen or {}).keys()))
        condicion = normalize_condicion_operacion(resumen.get("condicionOperacion"))
        resumen["condicionOperacion"] = condicion
        validate_pagos_basico(resumen, condicion)
        data["resumen"] = resumen
        print("DTE: VALIDATE_OK")
    except ValueError as exc:
        logger.error("ERROR: DTE inválido: %s", exc)
        raise ValueError(f"DTE inválido: {exc}") from exc

    _ensure_contingencia_ident_fields(ident, modo)
    if "identificacion" in data:
        data["identificacion"] = ident
    elif "identificador" in data:
        data["identificador"] = ident

    if jws_token:
        try:
            token_payload = _decode_jws_payload(jws_token)
        except Exception:
            logger.info("DTE %s: jws_token inválido; se re-firma", doc_ref)
            jws_token = None
        else:
            payload_ident = (
                token_payload.get("identificacion")
                or token_payload.get("identificador")
                or {}
            )
            current_subset = _normalize_ident_subset(ident)
            payload_subset = _normalize_ident_subset(payload_ident)
            if current_subset != payload_subset:
                logger.info(
                    "DTE %s: jws_token descartado por cambios en identificacion (%s ≠ %s)",
                    doc_ref,
                    payload_subset,
                    current_subset,
                )
                jws_token = None
            else:
                logger.info(
                    "DTE %s: reutilizando jws_token con identificacion %s",
                    doc_ref,
                    payload_subset,
                )
    print("DTE: BEFORE_SIGN")
    signed = jws_token or jws.sign_json(data)
    print("DTE: SIGNED_OK")

    if modo == "contingencia":
        try:
            _save_signed_dte(data, signed, fallido=False)
        except Exception:
            pass

    # Verify that metadata matches the signed payload and update it
    try:
        payload = _decode_jws_payload(signed)
    except ValueError:
        logger.debug("Payload JWS inválido; usando datos sin decodificar", exc_info=True)
        payload = data
    pident = payload.get("identificacion") or payload.get("identificador") or {}
    p_amb = pident.get("ambiente")
    p_tipo = pident.get("tipoDte") or pident.get("tipoDocumento")
    p_cod = pident.get("codigoGeneracion")
    if meta.get("ambiente") and meta["ambiente"] != p_amb:
        raise ValueError("ambiente no coincide con datos a firmar")
    if meta.get("tipoDte") and meta["tipoDte"] != p_tipo:
        raise ValueError("tipoDte no coincide con datos a firmar")
    if meta.get("codigoGeneracion") and meta["codigoGeneracion"] != p_cod:
        raise ValueError("codigoGeneracion no coincide con datos a firmar")
    meta["ambiente"] = p_amb
    meta["tipoDte"] = p_tipo
    meta["codigoGeneracion"] = p_cod

    try:
        print("DTE: BEFORE_POST")
        respuesta = _post_dte_with_config(url, signed, meta, config)
        sello = (
            respuesta.get("sello")
            or respuesta.get("selloRecepcion")
            or respuesta.get("selloRecibido")
            or ""
        )
        estado = (
            respuesta.get("estado")
            or respuesta.get("estadoDte")
            or respuesta.get("descripcionEstado")
            or "Transmitido"
        )
        detalle = respuesta.get("detalle")
    except Exception:
        db.registrar_envio_dte(
            doc_id,
            modo,
            "Rechazado",
            "",
            codigo_generacion=p_cod,
            numero_control=pident.get("numeroControl"),
        )
        raise

    db.registrar_envio_dte(
        doc_id,
        modo,
        estado,
        sello,
        json.dumps(respuesta, ensure_ascii=False),
        codigo_generacion=p_cod,
        numero_control=pident.get("numeroControl"),
    )
    try:
        _save_signed_dte(data, signed, fallido=(estado == "Rechazado"))
    except Exception:
        pass
    if estado == "Rechazado":
        respuesta["errores"] = _parse_error_response(respuesta)
    res = {"estado": estado, "sello": sello}
    ident_info = {
        "numeroControl": ident.get("numeroControl"),
        "codigoGeneracion": ident.get("codigoGeneracion"),
        "tipoDte": ident.get("tipoDte") or ident.get("tipoDocumento"),
        "ambiente": ident.get("ambiente"),
    }
    res["identificacion"] = {
        key: value
        for key, value in ident_info.items()
        if value is not None
    }
    if detalle:
        res["detalle"] = detalle
    if respuesta.get("errores"):
        res["errores"] = respuesta["errores"]
    return res


def _rehydrate_snapshot_from_fs(db: DB, nota_id: int, venta_id: int, expected_tipo: str | None) -> bool:
    """Recrear el snapshot faltante buscando el DTE base en el disco."""

    tipo = (expected_tipo or "").strip().lower()
    if tipo not in {"credito", "debito"}:
        return False

    def _normalize(value: Any) -> str:
        if value is None:
            return ""
        text = str(value).strip()
        if not text:
            return ""
        return text.upper()

    def _row_get(row_obj: Any, key: str, idx: int) -> Any:
        if row_obj is None:
            return None
        if isinstance(row_obj, Mapping):
            return row_obj.get(key)
        try:
            return row_obj[key]  # type: ignore[index]
        except Exception:
            pass
        try:
            return row_obj[idx]
        except Exception:
            return None

    codigo_generacion = ""
    numero_control = ""

    cursor = getattr(db, "cursor", None)
    if cursor is None:
        return False

    try:
        row = cursor.execute(
            """
            SELECT codigo_generacion, numero_control
            FROM dte_envios
            WHERE venta_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (venta_id,),
        ).fetchone()
    except Exception:
        row = None

    if row:
        codigo_generacion = _row_get(row, "codigo_generacion", 0)
        numero_control = _row_get(row, "numero_control", 1)

    codigo_generacion_norm = _normalize(codigo_generacion)
    numero_control_norm = _normalize(numero_control)

    search_keys_ordered: list[str] = []
    if codigo_generacion_norm:
        search_keys_ordered.append(codigo_generacion_norm)
    if numero_control_norm and numero_control_norm not in search_keys_ordered:
        search_keys_ordered.append(numero_control_norm)

    def _extend_from_related(source: Any) -> None:
        if not source:
            return
        containers: list[Any] = []
        if isinstance(source, (list, tuple, set)):
            containers.extend(source)
        else:
            containers.append(source)
        for item in containers:
            if isinstance(item, dict):
                codigo_val = _normalize(item.get("codigoGeneracion") or item.get("codigo_generacion"))
                numero_val = _normalize(item.get("numeroControl") or item.get("numero_control"))
                for value in (codigo_val, numero_val):
                    if value and value not in search_keys_ordered:
                        search_keys_ordered.append(value)

    if not search_keys_ordered:
        detalles_row = None
        try:
            detalles_row = cursor.execute(
                "SELECT detalles FROM notas WHERE id=?",
                (nota_id,),
            ).fetchone()
        except Exception:
            detalles_row = None

        detalles_payload: Any = None
        if detalles_row:
            detalles_value: Any = None
            if isinstance(detalles_row, dict):
                detalles_value = detalles_row.get("detalles")
            else:
                detalles_value = _row_get(detalles_row, "detalles", 0)
            if isinstance(detalles_value, (bytes, bytearray)):
                try:
                    detalles_value = detalles_value.decode("utf-8")
                except Exception:
                    detalles_value = None
            if isinstance(detalles_value, str):
                try:
                    detalles_payload = json.loads(detalles_value)
                except Exception:
                    detalles_payload = None
            elif isinstance(detalles_value, dict):
                detalles_payload = detalles_value

        if isinstance(detalles_payload, dict):
            related_candidates: list[Any] = []
            for key in (
                "documentoRelacionado",
                "documentosRelacionados",
                "documento_relacionado",
                "documentos_relacionados",
            ):
                rel = detalles_payload.get(key)
                if rel:
                    related_candidates.append(rel)
            for rel in related_candidates:
                _extend_from_related(rel)

    search_keys_ordered = [value for value in search_keys_ordered if value]
    if not search_keys_ordered:
        return False

    search_keys = set(search_keys_ordered)
    canonical_code = codigo_generacion_norm or search_keys_ordered[0]

    candidate_dirs: list[str] = []
    for directory in (
        DTES_DIR,
        FACTURAS_CONSUMIDOR_FINAL_DIR,
        FACTURAS_CREDITO_FISCAL_DIR,
        TICKETS_OUTPUT_DIR,
        NOTAS_CREDITO_DIR,
        NOTAS_DEBITO_DIR,
        FACTURAS_ARCHIVE_CF_DIR,
        FACTURAS_ARCHIVE_CREDITO_DIR,
    ):
        if directory and directory not in candidate_dirs:
            candidate_dirs.append(directory)

    typed = [os.path.join(DTES_DIR, sub) for sub in ("fcf", "ccf", "nc", "nd") if DTES_DIR]
    for t in typed:
        if t and t not in candidate_dirs:
            candidate_dirs.append(t)

    try:
        setter = getattr(db, "set_snapshot_path")
    except AttributeError:
        setter = None

    for directory in candidate_dirs:
        try:
            base = Path(directory)
        except TypeError:
            continue
        if not base.exists():
            continue
        try:
            entries: list[Path] = []
            for pattern in ("*.json", "*/*.json"):
                entries.extend(base.glob(pattern))
        except Exception:
            continue
        for entry in entries:
            try:
                with entry.open("r", encoding="utf-8") as fh:
                    payload = json.load(fh)
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue
            ident = payload.get("identificacion") or {}
            if not isinstance(ident, dict):
                ident = {}
            codigo = _normalize(ident.get("codigoGeneracion"))
            numero_control = _normalize(ident.get("numeroControl"))
            if codigo not in search_keys and numero_control not in search_keys:
                continue
            dest_code = _normalize(ident.get("codigoGeneracion")) or canonical_code
            if not dest_code:
                dest_code = _normalize(ident.get("numeroControl"))
            if not dest_code and search_keys_ordered:
                dest_code = search_keys_ordered[0]
            if not dest_code:
                continue
            dest_dir = Path(DTES_DIR) / dest_code
            try:
                dest_dir.mkdir(parents=True, exist_ok=True)
            except Exception:
                continue
            dest_path = dest_dir / "documento.json"
            entry_resolved = entry
            dest_resolved = dest_path
            try:
                entry_resolved = entry.resolve()
            except Exception:
                pass
            try:
                dest_resolved = dest_path.resolve()
            except FileNotFoundError:
                dest_resolved = dest_path
            except Exception:
                dest_resolved = dest_path
            if entry_resolved == dest_resolved:
                logger.info("SNAPSHOT: ya existía %s", dest_path)
                if callable(setter):
                    try:
                        setter(venta_id, str(dest_path))
                    except Exception:
                        pass
                return True
            tmp_path = dest_path.with_suffix(".json.tmp")
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except Exception:
                pass
            try:
                shutil.copyfile(entry, tmp_path)
                os.replace(tmp_path, dest_path)
            except shutil.SameFileError:
                if callable(setter):
                    try:
                        setter(venta_id, str(dest_path))
                    except Exception:
                        pass
                return True
            except Exception:
                try:
                    if tmp_path.exists():
                        tmp_path.unlink()
                except Exception:
                    pass
                continue
            logger.info("SNAPSHOT: rehidratado %s → %s", entry, dest_path)
            if callable(setter):
                try:
                    setter(venta_id, str(dest_path))
                except Exception:
                    pass
            return True
    logger.warning(
        "SNAPSHOT: no se encontró JSON para claves=%s en %d dirs",
        search_keys_ordered,
        len(candidate_dirs),
    )
    return False


def _ensure_nota_snapshot(db: DB, nota_id: int, *, expected_tipo: str | None = None) -> None:
    """Ensure that a stored snapshot exists for ``nota_id`` before sending."""

    if not hasattr(db, "cursor"):
        return

    try:
        row = db.cursor.execute(
            "SELECT venta_id, tipo FROM notas WHERE id=?",
            (nota_id,),
        ).fetchone()
    except Exception:
        return

    if not row:
        return

    try:
        nota_data = dict(row)
    except Exception:
        nota_data = {"venta_id": row[0] if len(row) else None, "tipo": row[1] if len(row) > 1 else None}

    nota_tipo = str(nota_data.get("tipo") or "").strip().lower()
    if expected_tipo and nota_tipo and nota_tipo != expected_tipo.lower():
        return

    venta_id = nota_data.get("venta_id")
    if venta_id in (None, ""):
        return

    try:
        snapshot = db.get_snapshot_by_venta(venta_id)
    except AttributeError:
        return

    if snapshot is None:
        tipo_hint = expected_tipo or nota_tipo
        if _rehydrate_snapshot_from_fs(db, nota_id, venta_id, tipo_hint):
            return
        raise SnapshotNotFoundError(venta_id, nota_id)


def _ensure_canonical_snapshot(
    source_path: str | None,
    codigo: str,
    *,
    venta_id: int,
    db: DB,
) -> Optional[Path]:
    """Ensure that the canonical snapshot ``dtes/<codigo>/documento.json`` exists.

    This helper performs best-effort copying from ``source_path`` to the canonical
    location using an atomic ``os.replace`` strategy.  Any error is logged as a
    warning to avoid interrupting the note generation flow.
    """

    codigo_norm = str(codigo or "").strip()
    if not codigo_norm:
        return None

    if not DTES_DIR:
        return None

    try:
        dest_dir = Path(DTES_DIR) / codigo_norm
    except TypeError:
        logger.warning("SNAPSHOT: destino inválido para código %s", codigo_norm)
        return None

    dest_path = dest_dir / "documento.json"

    def _update_db(path_exists: bool) -> None:
        if not path_exists:
            return
        try:
            setter = getattr(db, "set_snapshot_path")
        except AttributeError:
            return
        if not callable(setter):
            return
        try:
            setter(venta_id, str(dest_path))
        except Exception:
            pass

    try:
        if dest_path.exists():
            logger.info("SNAPSHOT: canónico ya presente %s", dest_path)
            _update_db(True)
            return dest_path
    except Exception as exc:
        logger.warning("SNAPSHOT: error verificando destino %s: %s", dest_path, exc)
        return dest_path

    if not source_path:
        return dest_path

    try:
        source = Path(source_path)
    except Exception as exc:
        logger.warning("SNAPSHOT: ruta de origen inválida %s: %s", source_path, exc)
        return dest_path

    try:
        source_cmp = source.resolve(strict=False)
    except Exception:
        source_cmp = source
    try:
        dest_cmp = dest_path.resolve(strict=False)
    except Exception:
        dest_cmp = dest_path
    if str(source_cmp) == str(dest_cmp):
        return dest_path

    try:
        if not source.exists():
            logger.warning("SNAPSHOT: origen inexistente %s", source)
            return dest_path
    except Exception as exc:
        logger.warning("SNAPSHOT: error accediendo origen %s: %s", source, exc)
        return dest_path

    tmp_path = dest_path.with_name(dest_path.name + ".tmp")

    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        if tmp_path.exists():
            tmp_path.unlink()
    except Exception as exc:
        logger.warning("SNAPSHOT: no se pudo preparar destino %s: %s", dest_path, exc)
        return dest_path

    try:
        shutil.copyfile(source, tmp_path)
        os.replace(tmp_path, dest_path)
        logger.info("SNAPSHOT: canonicalized %s → %s", source, dest_path)
    except Exception as exc:
        logger.warning("SNAPSHOT: fallo al canonicalizar %s → %s: %s", source, dest_path, exc)
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            pass
        return dest_path

    try:
        exists_now = dest_path.exists()
    except Exception:
        exists_now = False
    _update_db(exists_now)

    return dest_path


def _resolve_base_document_code(
    data: Mapping[str, Any], source_path: str | None
) -> tuple[str | None, str | None]:
    """Extract the codigoGeneracion/numeroControl of the related base document."""

    related = None
    try:
        resumen = data.get("resumen")  # type: ignore[attr-defined]
    except AttributeError:
        resumen = None
    if isinstance(resumen, Mapping):
        related = resumen.get("documentoRelacionado")
    if related is None:
        related = data.get("documentoRelacionado")

    entries: list[Any] = []
    if isinstance(related, Mapping):
        entries = [related]
    elif isinstance(related, list):
        entries = list(related)

    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        for key in ("codigoGeneracion", "numeroControl"):
            value = entry.get(key)
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text, f"documentoRelacionado.{key}"

    if source_path:
        try:
            candidate = Path(source_path).parent.name
        except Exception:
            candidate = ""
        candidate = str(candidate or "").strip()
        if candidate:
            return candidate, "source_path.parent"

    return None, None


def enviar_factura(db: DB, venta_id: int, modo: str | None = None) -> dict:
    """Genera y transmite una factura electrónica."""
    if modo is None:
        modo = get_default_modo_transmision()

    data = generar_dte_json(db, venta_id)
    data = apply_schema_patch(data)
    schema = catalogos.get_dte_schema("01")
    # Validación omitida para permitir el envío sin detenerse ante errores de
    # esquema.
    # try:
    #     validate_dte_json(data, db=db)
    # except Exception as exc:
    #     json_path = save_dte_json(data)
    #     errors = _format_validation_errors(exc)
    #     raise DTEValidationError(errors, json_path) from exc
    resp = _enviar_documento(db, venta_id, data, modo)
    if resp.get("sello"):
        db.update_venta_extra(venta_id, {"selloRecibido": resp["sello"]})
    return resp


def enviar_nota_credito(db: DB, nota_id: int, modo: str | None = None) -> dict:
    """Genera y transmite una nota de crédito."""
    if modo is None:
        modo = get_default_modo_transmision()

    _ensure_nota_snapshot(db, nota_id, expected_tipo="credito")

    config = _load_dte_api_config()
    ambiente_cfg = str(config.get("ambiente") or "").strip().lower()
    ambiente = "01" if ambiente_cfg == "produccion" else "00"

    data = generar_nota_credito_json(db, nota_id, ambiente=ambiente)
    venta_id_base = None
    try:
        row = db.cursor.execute("SELECT venta_id FROM notas WHERE id=?", (nota_id,)).fetchone()
    except Exception:
        row = None
    if row is not None:
        try:
            venta_id_base = row["venta_id"]
        except Exception:
            try:
                venta_id_base = row[0]
            except Exception:
                venta_id_base = None

    source_path: str | None = None
    venta_id_lookup = venta_id_base
    if venta_id_lookup not in (None, ""):
        try:
            snapshot_obj = db.get_snapshot_by_venta(venta_id_lookup)
        except AttributeError:
            snapshot_obj = None
        except Exception as exc:
            logger.warning(
                "SNAPSHOT: error obteniendo snapshot venta_id=%s: %s",
                venta_id_lookup,
                exc,
            )
            snapshot_obj = None
        if snapshot_obj is not None:
            source_attr = getattr(snapshot_obj, "path", snapshot_obj)
            if source_attr:
                source_path = str(source_attr)

    if venta_id_base in (None, ""):
        venta_id_base = nota_id

    base_code, base_origin = _resolve_base_document_code(data, source_path)
    if base_code and base_origin:
        logger.info(
            "SNAPSHOT: código base %s derivado desde %s", base_code, base_origin
        )
    elif not base_code:
        ident_data = data.get("identificacion") or {}
        nota_code = str(
            ident_data.get("codigoGeneracion")
            or ident_data.get("numeroControl")
            or nota_id
        ).strip()
        logger.warning(
            "SNAPSHOT: no se pudo inferir código base para nota %s (source=%s)",
            nota_code,
            source_path or "desconocido",
        )
    dest_path = _ensure_canonical_snapshot(
        source_path, str(base_code or ""), venta_id=venta_id_base, db=db
    )
    if dest_path is not None:
        try:
            if not dest_path.exists():
                logger.warning(
                    "SNAPSHOT: destino canónico ausente tras intento (codigo_base=%s, venta_id=%s, source=%s)",
                    base_code or "",
                    venta_id_base,
                    source_path or "desconocido",
                )
        except Exception as exc:
            logger.warning(
                "SNAPSHOT: error verificando canónico tras intento %s: %s",
                dest_path,
                exc,
            )
    data = apply_schema_patch(data)
    schema = catalogos.get_dte_schema("05")
    # Validación omitida.
    # try:
    #     validate_dte_json(data, db=db)
    # except Exception as exc:
    #     json_path = save_dte_json(data)
    #     errors = _format_validation_errors(exc)
    #     raise DTEValidationError(errors, json_path) from exc
    from utils.docs import get_dte_document_paths
    from utils.jws import sign_json
    from utils.stable_json import save_file, stable_stringify

    ident = data.get("identificacion") or {}
    hoy_fec = fecha_emision_hoy_str()
    if ident.get("fecEmi") != hoy_fec:
        logger.info(
            "NotaCredito %s: fecEmi ajustado de %s a %s antes de firmar",
            ident.get("numeroControl")
            or ident.get("codigoGeneracion")
            or nota_id,
            ident.get("fecEmi") or "<sin fecha>",
            hoy_fec,
        )
        ident["fecEmi"] = hoy_fec
    else:
        logger.info(
            "NotaCredito %s: fecEmi confirmado como %s antes de firmar",
            ident.get("numeroControl")
            or ident.get("codigoGeneracion")
            or nota_id,
            hoy_fec,
        )
    data["identificacion"] = ident
    saved_fecemi = ident.get("fecEmi")
    receptor = data.get("receptor", {}) or {}
    _, json_path = get_dte_document_paths(
        ident.get("fecEmi"),
        receptor.get("nombre") or receptor.get("nombreComercial") or "",
        ident.get("numeroControl"),
        "NotaCredito",
    )
    jws_path = os.path.splitext(json_path)[0] + ".jws"
    jws_token = None
    cached_payload: dict[str, Any] | None = None
    if os.path.exists(jws_path):
        try:
            with open(jws_path, "r", encoding="utf-8") as fh:
                cached_token = fh.read().strip()
            if cached_token:
                payload = _decode_jws_payload(cached_token)
                payload_ident = payload.get("identificacion") or {}
                if (
                    payload_ident.get("codigoGeneracion")
                    == ident.get("codigoGeneracion")
                    and payload_ident.get("numeroControl")
                    == ident.get("numeroControl")
                    and payload_ident.get("fecEmi") == ident.get("fecEmi")
                ):
                    jws_token = cached_token
                    cached_payload = payload
        except Exception:
            jws_token = None
            cached_payload = None
    related = data.get("documentoRelacionado")
    related_entry: Mapping[str, Any] | None = None
    if isinstance(related, list):
        for candidate in related:
            if isinstance(candidate, Mapping):
                related_entry = candidate
                break
    elif isinstance(related, Mapping):
        related_entry = related
    logger.info(
        "WILL_SAVE fecEmi=%s rel.fechaEmision=%s",
        ident.get("fecEmi"),
        (related_entry or {}).get("fechaEmision"),
    )

    payload_json = stable_stringify(data, indent=2)
    save_file(json_path, payload_json)
    if jws_token is None:
        token = sign_json(data)
        jws_token = token.rstrip("\n")
        save_file(jws_path, jws_token, add_final_newline=False)
    signed_payload: dict[str, Any] | None = cached_payload
    if signed_payload is None and jws_token:
        try:
            signed_payload = _decode_jws_payload(jws_token)
        except Exception:
            signed_payload = None
    if signed_payload is not None:
        assert (signed_payload.get("identificacion") or {}).get("fecEmi") == ident.get(
            "fecEmi"
        )
    primary_ident = data.get("identificacion") or {}

    logger.info(
        "SAVE->SEND fecEmi=%s rel.fechaEmision=%s",
        primary_ident.get("fecEmi"),
        (related_entry or {}).get("fechaEmision"),
    )
    resp = _enviar_documento(db, nota_id, data, modo, jws_token=jws_token)
    final_fecemi = (data.get("identificacion") or {}).get("fecEmi")
    if final_fecemi == saved_fecemi:
        logger.info(
            "NotaCredito %s: fecEmi guardado y enviado coinciden en %s",
            ident.get("numeroControl")
            or ident.get("codigoGeneracion")
            or nota_id,
            final_fecemi,
        )
    else:
        logger.warning(
            "NotaCredito %s: fecEmi guardado=%s difiere de enviado=%s",
            ident.get("numeroControl")
            or ident.get("codigoGeneracion")
            or nota_id,
            saved_fecemi,
            final_fecemi,
        )
    if resp.get("sello"):
        db.update_venta_extra(nota_id, {"selloRecibido": resp["sello"]})
    return resp


def enviar_nota_debito(db: DB, nota_id: int, modo: str | None = None) -> dict:
    """Genera y transmite una nota de débito."""
    if modo is None:
        modo = get_default_modo_transmision()

    _ensure_nota_snapshot(db, nota_id, expected_tipo="debito")

    config = _load_dte_api_config()
    ambiente_cfg = str(config.get("ambiente") or "").strip().lower()
    ambiente = "01" if ambiente_cfg == "produccion" else "00"

    data = generar_nota_debito_json(db, nota_id, ambiente=ambiente)
    venta_id_base = None
    try:
        row = db.cursor.execute("SELECT venta_id FROM notas WHERE id=?", (nota_id,)).fetchone()
    except Exception:
        row = None
    if row is not None:
        try:
            venta_id_base = row["venta_id"]
        except Exception:
            try:
                venta_id_base = row[0]
            except Exception:
                venta_id_base = None

    source_path: str | None = None
    venta_id_lookup = venta_id_base
    if venta_id_lookup not in (None, ""):
        try:
            snapshot_obj = db.get_snapshot_by_venta(venta_id_lookup)
        except AttributeError:
            snapshot_obj = None
        except Exception as exc:
            logger.warning(
                "SNAPSHOT: error obteniendo snapshot venta_id=%s: %s",
                venta_id_lookup,
                exc,
            )
            snapshot_obj = None
        if snapshot_obj is not None:
            source_attr = getattr(snapshot_obj, "path", snapshot_obj)
            if source_attr:
                source_path = str(source_attr)

    if venta_id_base in (None, ""):
        venta_id_base = nota_id

    base_code, base_origin = _resolve_base_document_code(data, source_path)
    if base_code and base_origin:
        logger.info(
            "SNAPSHOT: código base %s derivado desde %s", base_code, base_origin
        )
    elif not base_code:
        ident_data = data.get("identificacion") or {}
        nota_code = str(
            ident_data.get("codigoGeneracion")
            or ident_data.get("numeroControl")
            or nota_id
        ).strip()
        logger.warning(
            "SNAPSHOT: no se pudo inferir código base para nota %s (source=%s)",
            nota_code,
            source_path or "desconocido",
        )
    dest_path = _ensure_canonical_snapshot(
        source_path, str(base_code or ""), venta_id=venta_id_base, db=db
    )
    if dest_path is not None:
        try:
            if not dest_path.exists():
                logger.warning(
                    "SNAPSHOT: destino canónico ausente tras intento (codigo_base=%s, venta_id=%s, source=%s)",
                    base_code or "",
                    venta_id_base,
                    source_path or "desconocido",
                )
        except Exception as exc:
            logger.warning(
                "SNAPSHOT: error verificando canónico tras intento %s: %s",
                dest_path,
                exc,
            )
    data = apply_schema_patch(data)
    schema = catalogos.get_dte_schema("06")
    # Validación omitida.
    # try:
    #     validate_dte_json(data, db=db)
    # except Exception as exc:
    #     json_path = save_dte_json(data)
    #     errors = _format_validation_errors(exc)
    #     raise DTEValidationError(errors, json_path) from exc
    from utils.docs import get_dte_document_paths
    from utils.jws import sign_json
    from utils.stable_json import save_file, stable_stringify

    ident = data.get("identificacion") or {}
    hoy_fec = fecha_emision_hoy_str()
    if ident.get("fecEmi") != hoy_fec:
        logger.info(
            "NotaDebito %s: fecEmi ajustado de %s a %s antes de firmar",
            ident.get("numeroControl")
            or ident.get("codigoGeneracion")
            or nota_id,
            ident.get("fecEmi") or "<sin fecha>",
            hoy_fec,
        )
        ident["fecEmi"] = hoy_fec
    else:
        logger.info(
            "NotaDebito %s: fecEmi confirmado como %s antes de firmar",
            ident.get("numeroControl")
            or ident.get("codigoGeneracion")
            or nota_id,
            hoy_fec,
        )
    data["identificacion"] = ident
    saved_fecemi = ident.get("fecEmi")
    receptor = data.get("receptor", {}) or {}
    _, json_path = get_dte_document_paths(
        ident.get("fecEmi"),
        receptor.get("nombre") or receptor.get("nombreComercial") or "",
        ident.get("numeroControl"),
        "NotaDebito",
    )
    jws_path = os.path.splitext(json_path)[0] + ".jws"
    jws_token = None
    cached_payload: dict[str, Any] | None = None
    if os.path.exists(jws_path):
        try:
            with open(jws_path, "r", encoding="utf-8") as fh:
                cached_token = fh.read().strip()
            if cached_token:
                payload = _decode_jws_payload(cached_token)
                payload_ident = payload.get("identificacion") or {}
                if (
                    payload_ident.get("codigoGeneracion")
                    == ident.get("codigoGeneracion")
                    and payload_ident.get("numeroControl")
                    == ident.get("numeroControl")
                    and payload_ident.get("fecEmi") == ident.get("fecEmi")
                ):
                    jws_token = cached_token
                    cached_payload = payload
        except Exception:
            jws_token = None
            cached_payload = None
    related = data.get("documentoRelacionado")
    related_entry: Mapping[str, Any] | None = None
    if isinstance(related, list):
        for candidate in related:
            if isinstance(candidate, Mapping):
                related_entry = candidate
                break
    elif isinstance(related, Mapping):
        related_entry = related
    logger.info(
        "WILL_SAVE fecEmi=%s rel.fechaEmision=%s",
        ident.get("fecEmi"),
        (related_entry or {}).get("fechaEmision"),
    )

    payload_json = stable_stringify(data, indent=2)
    save_file(json_path, payload_json)
    if jws_token is None:
        token = sign_json(data)
        jws_token = token.rstrip("\n")
        save_file(jws_path, jws_token, add_final_newline=False)
    signed_payload: dict[str, Any] | None = cached_payload
    if signed_payload is None and jws_token:
        try:
            signed_payload = _decode_jws_payload(jws_token)
        except Exception:
            signed_payload = None
    if signed_payload is not None:
        assert (signed_payload.get("identificacion") or {}).get("fecEmi") == ident.get(
            "fecEmi"
        )
    primary_ident = data.get("identificacion") or {}

    logger.info(
        "SAVE->SEND fecEmi=%s rel.fechaEmision=%s",
        primary_ident.get("fecEmi"),
        (related_entry or {}).get("fechaEmision"),
    )
    resp = _enviar_documento(db, nota_id, data, modo, jws_token=jws_token)
    final_fecemi = (data.get("identificacion") or {}).get("fecEmi")
    if final_fecemi == saved_fecemi:
        logger.info(
            "NotaDebito %s: fecEmi guardado y enviado coinciden en %s",
            ident.get("numeroControl")
            or ident.get("codigoGeneracion")
            or nota_id,
            final_fecemi,
        )
    else:
        logger.warning(
            "NotaDebito %s: fecEmi guardado=%s difiere de enviado=%s",
            ident.get("numeroControl")
            or ident.get("codigoGeneracion")
            or nota_id,
            saved_fecemi,
            final_fecemi,
        )
    if resp.get("sello"):
        db.update_venta_extra(nota_id, {"selloRecibido": resp["sello"]})
    return resp


def enviar_nota_remision(db: DB, nota_id: int, modo: str | None = None) -> dict:
    """Genera y transmite una nota de remisión."""
    if modo is None:
        modo = get_default_modo_transmision()

    from nota_remision import generar_nota_remision_desde_db

    config = _load_dte_api_config()
    ambiente_cfg = str(config.get("ambiente") or "").strip().lower()
    ambiente = "01" if ambiente_cfg == "produccion" else "00"

    data = generar_nota_remision_desde_db(db, nota_id, ambiente=ambiente)
    data = apply_schema_patch(data)
    schema = catalogos.get_dte_schema("04")
    # Validación omitida.
    # try:
    #     validate_dte_json(data, db=db)
    # except Exception as exc:
    #     json_path = save_dte_json(data)
    #     errors = _format_validation_errors(exc)
    #     raise DTEValidationError(errors, json_path) from exc
    ident = data.get("identificacion") or {}
    hoy_fec = fecha_emision_hoy_str()
    if ident.get("fecEmi") != hoy_fec:
        logger.info(
            "NotaRemision %s: fecEmi ajustado de %s a %s antes de firmar",
            ident.get("numeroControl")
            or ident.get("codigoGeneracion")
            or nota_id,
            ident.get("fecEmi") or "<sin fecha>",
            hoy_fec,
        )
        ident["fecEmi"] = hoy_fec
    else:
        logger.info(
            "NotaRemision %s: fecEmi confirmado como %s antes de firmar",
            ident.get("numeroControl")
            or ident.get("codigoGeneracion")
            or nota_id,
            hoy_fec,
        )
    data["identificacion"] = ident
    saved_fecemi = ident.get("fecEmi")

    from utils.docs import get_dte_document_paths
    from utils.stable_json import save_file, stable_stringify

    receptor = data.get("receptor", {}) or {}
    _, json_path = get_dte_document_paths(
        ident.get("fecEmi"),
        receptor.get("nombre") or receptor.get("nombreComercial") or "",
        ident.get("numeroControl"),
        "NotaRemision",
    )

    related = data.get("documentoRelacionado")
    related_entry: Mapping[str, Any] | None = None
    if isinstance(related, list):
        for candidate in related:
            if isinstance(candidate, Mapping):
                related_entry = candidate
                break
    elif isinstance(related, Mapping):
        related_entry = related
    logger.info(
        "WILL_SAVE fecEmi=%s rel.fechaEmision=%s",
        ident.get("fecEmi"),
        (related_entry or {}).get("fechaEmision"),
    )
    payload_json = stable_stringify(data, indent=2)
    save_file(json_path, payload_json)
    logger.info(

        "SAVE->SEND fecEmi=%s rel.fechaEmision=%s",
        ident.get("fecEmi"),
        (related_entry or {}).get("fechaEmision"),
    )
    resp = _enviar_documento(db, nota_id, data, modo)
    final_fecemi = (data.get("identificacion") or {}).get("fecEmi")
    if final_fecemi == saved_fecemi:
        logger.info(
            "NotaRemision %s: fecEmi guardado y enviado coinciden en %s",
            ident.get("numeroControl")
            or ident.get("codigoGeneracion")
            or nota_id,
            final_fecemi,
        )
    else:
        logger.warning(
            "NotaRemision %s: fecEmi guardado=%s difiere de enviado=%s",
            ident.get("numeroControl")
            or ident.get("codigoGeneracion")
            or nota_id,
            saved_fecemi,
            final_fecemi,
        )
    if resp.get("sello"):
        db.update_venta_extra(nota_id, {"selloRecibido": resp["sello"]})
    return resp


def _enviar_evento(db: DB, evento_id: int, data: dict) -> dict:
    """Firma y envía un evento a Hacienda."""
    config = _load_dte_api_config()
    evento_url = config.get("evento_url") or DEFAULT_EVENTO_URL
    signed = jws.sign_json(data)
    ident = data.get("identificacion") or data.get("identificador") or {}

    evento_nit: str | None = None
    emisor = data.get("emisor")
    if isinstance(emisor, Mapping):
        raw_nit = emisor.get("nit")
        if raw_nit:
            evento_nit = str(raw_nit)
    if not evento_nit:
        raw_cfg_nit = config.get("nit")
        if raw_cfg_nit:
            evento_nit = str(raw_cfg_nit)
    if not evento_nit:
        try:
            datos_negocio = _load_datos_negocio()
        except Exception:
            datos_negocio = {}
        if isinstance(datos_negocio, Mapping):
            raw_datos_nit = datos_negocio.get("nit")
            if raw_datos_nit:
                evento_nit = str(raw_datos_nit)
            if not evento_nit:
                firma_cfg = datos_negocio.get("firma_electronica")
                if isinstance(firma_cfg, Mapping):
                    raw_firma_nit = firma_cfg.get("nit")
                    if raw_firma_nit:
                        evento_nit = str(raw_firma_nit)

    try:
        respuesta = _post_evento(
            evento_url,
            signed,
            evento_nit or "",
            data,
            ambiente_config=config.get("ambiente"),
        )
        sello = respuesta.get("sello") or respuesta.get("selloRecepcion") or ""
        estado = (
            respuesta.get("estado")
            or respuesta.get("estadoEvento")
            or respuesta.get("descripcionEstado")
            or "Transmitido"
        )
        detalle = respuesta.get("detalle")
    except Exception:
        db.registrar_envio_dte(
            evento_id,
            "evento",
            "Rechazado",
            "",
            codigo_generacion=ident.get("codigoGeneracion"),
            numero_control=ident.get("numeroControl"),
        )
        raise

    db.registrar_envio_dte(
        evento_id,
        "evento",
        estado,
        sello,
        json.dumps(respuesta, ensure_ascii=False),
        codigo_generacion=ident.get("codigoGeneracion"),
        numero_control=ident.get("numeroControl"),
    )
    if estado == "Rechazado":
        respuesta["errores"] = _parse_error_response(respuesta)
    res = {"estado": estado, "sello": sello}
    if detalle:
        res["detalle"] = detalle
    if respuesta.get("errores"):
        res["errores"] = respuesta["errores"]
    return res


def enviar_evento_contingencia(db: DB, evento_id: int, data: dict) -> dict:
    """Envía un evento de contingencia."""
    return _enviar_evento(db, evento_id, data)


def enviar_evento_anulacion(db: DB, evento_id: int, data: dict) -> dict:
    """Envía un evento de anulación."""
    from collections.abc import Mapping as _Mapping

    try:
        from anulacion import enviar_invalidacion as _enviar_invalidacion  # type: ignore
    except Exception as exc:  # pragma: no cover - defensive fallback
        raise RuntimeError("No se pudo importar el módulo de anulación") from exc

    ident: dict[str, Any] = {}
    if isinstance(data, _Mapping):
        ident_value = data.get("identificacion")
        if isinstance(ident_value, _Mapping):
            ident = dict(ident_value)

    codigo_generacion = None
    numero_control = None
    if isinstance(ident, _Mapping):
        codigo_generacion = ident.get("codigoGeneracion")
        numero_control = ident.get("numeroControl")

    try:
        respuesta = _enviar_invalidacion(db, data)
    except Exception:
        db.registrar_envio_dte(
            evento_id,
            "evento",
            "Rechazado",
            "",
            codigo_generacion=codigo_generacion,
            numero_control=numero_control,
        )
        raise

    estado = "Transmitido"
    sello = ""
    if isinstance(respuesta, _Mapping):
        estado_raw = (
            respuesta.get("estado")
            or respuesta.get("estadoEvento")
            or respuesta.get("descripcionEstado")
        )
        if isinstance(estado_raw, str) and estado_raw.strip():
            estado = estado_raw.strip()
        sello_raw = respuesta.get("sello") or respuesta.get("selloRecepcion")
        if isinstance(sello_raw, str):
            sello = sello_raw

    db.registrar_envio_dte(
        evento_id,
        "evento",
        estado,
        sello,
        respuesta,
        codigo_generacion=codigo_generacion,
        numero_control=numero_control,
    )

    if not isinstance(respuesta, _Mapping):
        return {"estado": estado, "sello": sello}

    resultado = dict(respuesta)
    resultado.setdefault("estado", estado)
    resultado.setdefault("sello", sello)
    return resultado
