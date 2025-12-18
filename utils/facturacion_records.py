"""Shared helpers to build the Facturación document listing.

This module centralises the logic that determines which registros are
presented in the Facturación tab so that other parts of the application
can rely on the exact same source of truth without duplicating the
queries or the status normalisation rules.
"""

from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, Mapping, Sequence

from paths import RETENCIONES_DIR, ensure_user_dir, resolve_user_visible_path


DOC_SUFFIX_PATTERN = re.compile(
    r"^\d{8}_.+_(ConsumidorFinal|CreditoFiscal|Ticket|NotaDebito|NotaCredito|NotaRemision)$"
)


CANONICAL_TIPO_LABELS = {
    "consumidor final": "Consumidor final",
    "consumidorfinal": "Consumidor final",
    "consumidor_final": "Consumidor final",
    "factura consumidor final": "Consumidor final",
    "facturas consumidor final": "Consumidor final",
    "credito fiscal": "Crédito fiscal",
    "crédito fiscal": "Crédito fiscal",
    "creditofiscal": "Crédito fiscal",
    "factura credito fiscal": "Crédito fiscal",
    "facturas credito fiscal": "Crédito fiscal",
    "ccf": "Crédito fiscal",
    "nota de crédito": "Nota de crédito",
    "nota de credito": "Nota de crédito",
    "notacredito": "Nota de crédito",
    "nota credito": "Nota de crédito",
    "nota crédito": "Nota de crédito",
    "nota de débito": "Nota de débito",
    "nota de debito": "Nota de débito",
    "notadebito": "Nota de débito",
    "nota debito": "Nota de débito",
    "nota débito": "Nota de débito",
    "nota de remisión": "Nota de remisión",
    "nota de remision": "Nota de remisión",
    "notaremision": "Nota de remisión",
    "nota remision": "Nota de remisión",
    "nota remisión": "Nota de remisión",
    "ticket": "Ticket",
}


TIPO_DTE_DESC = {
    "01": "Consumidor final",
    "03": "Crédito fiscal",
    "04": "Nota de remisión",
    "05": "Nota de crédito",
    "06": "Nota de débito",
    "07": "Comprobante de retención",
    "08": "Comprobante de retención",
    "09": "Liquidación",
    "10": "Comprobante de liquidación",
    "11": "Factura de exportación",
    "12": "Comprobante de percepción",
    "13": "Liquidación de compra",
    "14": "Factura sujeto excluido",
    "15": "Mandamiento judicial",
    "16": "Nota de remisión de exportación",
}

TIPO_DTE_SHORT_DESC = {
    "consumidor final": "cons final",
    "crédito fiscal": "cred fiscal",
    "credito fiscal": "cred fiscal",
    "nota de crédito": "not crédito",
    "nota de credito": "not crédito",
    "nota de débito": "not debito",
    "nota de debito": "not debito",
    "nota de remisión": "not remisión",
    "nota de remision": "not remisión",
    "cr-07": "CR-07",
    "comp. retención": "comp reten",
    "comp. retencion": "comp reten",
    "factura sujeto excluido": "suj exclu",
    "sujeto excluido": "suj exclu",
    "suj exclu": "suj exclu",
}


TIPO_DTE_CODE_BY_DESC = {
    "consumidor final": "01",
    "factura": "01",
    "factura consumidor final": "01",
    "facturas consumidor final": "01",
    "credito fiscal": "03",
    "crédito fiscal": "03",
    "creditofiscal": "03",
    "factura credito fiscal": "03",
    "facturas credito fiscal": "03",
    "ccf": "03",
    "nota de credito": "05",
    "nota de crédito": "05",
    "notacredito": "05",
    "nota credito": "05",
    "nota crédito": "05",
    "nota de debito": "06",
    "nota de débito": "06",
    "notadebito": "06",
    "nota debito": "06",
    "nota débito": "06",
    "nota de remision": "04",
    "nota de remisión": "04",
    "notaremision": "04",
    "nota remision": "04",
    "nota remisión": "04",
    "ticket": "01",
    "factura de exportacion": "11",
    "factura de exportación": "11",
    "factura sujeto excluido": "14",
    "sujeto excluido": "14",
    "fse": "14",
}


def _normalize_tipo_key(value: str | None) -> str:
    if not value:
        return ""
    key = str(value).strip()
    key = re.sub(r"(?<=[a-z0-9])([A-Z])", r" \1", key)
    key = key.replace("-", " ").replace("_", " ")
    key = re.sub(r"\s+", " ", key)
    return key.lower().strip()


def canonical_tipo_label(value: str | None) -> str | None:
    key = _normalize_tipo_key(value)
    if not key:
        return None
    return CANONICAL_TIPO_LABELS.get(key)


def short_tipo_label(tipo: str | None) -> str:
    if tipo is None:
        return ""

    text = str(tipo).strip()
    if not text:
        return ""

    tipo_desc = text
    if text.isdigit():
        tipo_desc = TIPO_DTE_DESC.get(text.zfill(2), text)

    lowered = tipo_desc.strip().lower()
    mapped = TIPO_DTE_SHORT_DESC.get(lowered)
    if mapped:
        return mapped

    canonical = canonical_tipo_label(tipo_desc)
    if canonical:
        fallback = TIPO_DTE_SHORT_DESC.get(canonical.lower())
        if fallback:
            return fallback

    return tipo_desc


def _looks_like_note_label(value: str | None) -> bool:
    if not value:
        return False
    lowered = str(value).strip().lower()
    if not lowered:
        return False
    if "nota" in lowered:
        return True
    return "remision" in lowered or "remisión" in lowered


def infer_tipo_from_name(base_name: str | None, fallback: str | None = None) -> str | None:
    suffix = None
    if base_name:
        cleaned = os.path.splitext(os.path.basename(base_name))[0]
        match = DOC_SUFFIX_PATTERN.match(cleaned)
        if match:
            suffix = match.group(1)
        else:
            parts = cleaned.split("_")
            if parts:
                suffix = parts[-1]
    if suffix:
        inferred = canonical_tipo_label(suffix)
        if inferred:
            return inferred
    fallback_canonical = canonical_tipo_label(fallback)
    if fallback_canonical:
        return fallback_canonical
    return fallback


def tipo_code_from_desc(tipo: str | None) -> str | None:
    if not tipo:
        return None
    return TIPO_DTE_CODE_BY_DESC.get(str(tipo).strip().lower())


def _coerce_total(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return abs(float(value))
    if isinstance(value, Decimal):
        return abs(float(value))
    if value is None:
        return None
    try:
        text = str(value).strip()
    except Exception:
        return None
    if not text:
        return None
    try:
        return abs(float(text))
    except (TypeError, ValueError):
        return None


def _normalize_factura_payload(payload):
    """Mimic the JSON flattening used by the facturación detail dialog."""

    if isinstance(payload, dict):
        inner = payload.get("dteJson")
        if isinstance(inner, Mapping):
            merged = dict(inner)
            merged.setdefault("dteJson", dict(inner))
            for key, value in payload.items():
                if key == "dteJson":
                    continue
                merged.setdefault(key, value)
            payload.clear()
            payload.update(merged)
        return payload

    if isinstance(payload, Mapping):
        inner = payload.get("dteJson")
        if isinstance(inner, Mapping):
            merged = dict(inner)
            merged.setdefault("dteJson", dict(inner))
            for key, value in payload.items():
                if key == "dteJson":
                    continue
                merged.setdefault(key, value)
            return merged
        return dict(payload)

    return {} if payload is None else payload


def _iter_tree_mappings(*values: Any) -> Iterator[Mapping[str, Any]]:
    queue: list[Any] = list(values)
    seen: set[int] = set()
    while queue:
        current = queue.pop(0)
        if isinstance(current, Mapping):
            obj_id = id(current)
            if obj_id in seen:
                continue
            seen.add(obj_id)
            yield current
            queue.extend(current.values())
        elif isinstance(current, (list, tuple, set)):
            queue.extend(current)


def _find_first_mapping(payload: Mapping[str, Any], keys: Sequence[str]) -> Mapping[str, Any] | None:
    for mapping in _iter_tree_mappings(payload):
        for key in keys:
            section = mapping.get(key)
            if isinstance(section, Mapping):
                return section
    return None


def _first_non_empty(mapping: Mapping[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value is None:
            continue
        if isinstance(value, str):
            if value.strip():
                return value
            continue
        return value
    return None


def _find_first_non_empty(payload: Mapping[str, Any], keys: Sequence[str]) -> Any:
    for mapping in _iter_tree_mappings(payload):
        value = _first_non_empty(mapping, keys)
        if value not in (None, ""):
            return value
    return None


_TOTAL_FIELD_CANDIDATES = (
    "totalPagar",
    "totalAPagar",
    "montoTotalOperacion",
    "montoTotal",
    "montoTotalComprobante",
    "totalComprobante",
    "total",
    "totalGral",
    "totalGeneral",
    "totalVenta",
    "ventaTotal",
    "ventaGravada",
    "montoTotalResumen",
    "montoPagar",
)


_CLIENT_NAME_FIELDS = (
    "nombre",
    "nombreComercial",
    "denominacionSocial",
    "razonSocial",
    "nombreRazonSocial",
    "nombreCliente",
    "nombreCompleto",
)


def _extract_cliente_nombre(payload: Mapping[str, Any] | None) -> str | None:
    if not isinstance(payload, Mapping):
        return None

    receptor = _find_first_mapping(
        payload,
        ("receptor", "cliente", "adquiriente", "contribuyente"),
    )

    search_spaces: list[Mapping[str, Any]] = []
    if receptor:
        search_spaces.append(receptor)
        contacto = receptor.get("contactoReceptor")
        if isinstance(contacto, Mapping):
            search_spaces.append(contacto)
    else:
        search_spaces.append(payload)

    for space in search_spaces:
        name = _first_non_empty(space, _CLIENT_NAME_FIELDS)
        if name:
            return name
        for mapping in _iter_tree_mappings(space):
            if mapping is space:
                continue
            name = _first_non_empty(mapping, _CLIENT_NAME_FIELDS)
            if name:
                return name

    return None


def _extract_total_from_json(payload: Mapping[str, Any] | None) -> Any:
    if not isinstance(payload, Mapping):
        return None

    resumen = _find_first_mapping(
        payload,
        ("resumen", "totales", "totalesFactura", "resumenFactura"),
    )
    if resumen:
        total = _find_first_non_empty(resumen, _TOTAL_FIELD_CANDIDATES)
        if total not in (None, ""):
            return total

    return _find_first_non_empty(payload, _TOTAL_FIELD_CANDIDATES)


def map_envio_state(state: str | None) -> str:
    est = str(state or "").strip().upper()
    if est == "ACEPTADO":
        return "Aceptado"
    if est == "RECHAZADO":
        return "Rechazado"
    if est in {"TRANSMITIDO", "RECIBIDO", "PROCESADO"}:
        return "Enviado"
    return "Pendiente de envío"


def format_envio_state(estado_ui, estado_ui_tag, estado_raw) -> str:
    base = str(estado_ui or "").strip()
    if base:
        lowered = base.lower()
        if lowered in {"pendiente", "pendiente de envio"}:
            base_display = "Pendiente de envío"
        else:
            base_display = base
        tag_text = str(estado_ui_tag or "").strip().lower()
        if tag_text and base_display in {"Enviado", "Rechazado"}:
            return f"{base_display} ({tag_text})"
        return base_display
    raw = str(estado_raw or "").strip()
    if raw:
        mapped = map_envio_state(raw)
        raw_upper = raw.upper()
        if (
            mapped == "Pendiente de envío"
            and raw_upper not in {"PENDIENTE"}
            and raw_upper
        ):
            return raw.capitalize()
        return mapped
    return "Pendiente de envío"


def _row_get(row: Mapping[str, Any] | Iterable[Any] | None, key: str):
    if row is None:
        return None
    try:
        return row[key]  # type: ignore[index]
    except Exception:
        pass
    getter = getattr(row, "get", None)
    if callable(getter):
        try:
            return getter(key)
        except Exception:
            return None
    try:
        keys = row.keys()  # type: ignore[attr-defined]
    except Exception:
        return None
    try:
        index = list(keys).index(key)
    except Exception:
        return None
    try:
        return row[index]  # type: ignore[index]
    except Exception:
        return None


def _map_row_estado(row: Mapping[str, Any] | Iterable[Any] | None) -> str:
    if not row:
        return "Pendiente de envío"
    ui_val = _row_get(row, "estado_ui")
    tag_val = _row_get(row, "estado_ui_tag")
    estado_val = _row_get(row, "estado")
    return format_envio_state(ui_val, tag_val, estado_val)


def detectar_estado_factura(
    venta,
    pdf_path=None,
    json_path=None,
    cur=None,
    *,
    venta_id=None,
    numero_control=None,
    codigo_generacion=None,
    doc_tipo=None,
):
    pdf_exists = bool(pdf_path and os.path.exists(pdf_path))
    json_exists = bool(json_path and os.path.exists(json_path))

    tipo_lower = str(doc_tipo or "").strip().lower()
    is_nota = tipo_lower.startswith("nota")

    if venta:
        estado = "Completa" if pdf_exists and json_exists else "Incompleta"
    else:
        if is_nota:
            estado = "Completa" if pdf_exists and json_exists else "Incompleta"
        else:
            estado = "Sin venta" if pdf_exists and json_exists else "Incompleta"

    envio = "Pendiente de envío"

    contingencia_pendiente = False
    venta_id_lookup = None
    if venta_id is not None:
        try:
            venta_id_lookup = int(venta_id)
        except (TypeError, ValueError):
            venta_id_lookup = None
    if cur is not None and venta_id_lookup is not None:
        try:
            cur.execute(
                """
                SELECT 1
                FROM dte_pendientes
                WHERE venta_id=? AND transmitido=0
                LIMIT 1
                """,
                (venta_id_lookup,),
            )
            contingencia_pendiente = cur.fetchone() is not None
        except Exception:
            contingencia_pendiente = False
    if contingencia_pendiente:
        estado = "Contingencia"

    estado_manual = None
    if cur is not None and estado.lower() != "contingencia":
        try:
            query = None
            params: tuple[Any, ...] = ()
            if codigo_generacion:
                query = (
                    """
                    SELECT estado_dte_manual, estado_dte_override
                    FROM dte_envios
                    WHERE codigo_generacion IS NOT NULL AND UPPER(codigo_generacion)=UPPER(?)
                    ORDER BY estado_dte_override DESC, id DESC LIMIT 1
                    """
                )
                params = (codigo_generacion,)
            elif numero_control:
                query = (
                    """
                    SELECT estado_dte_manual, estado_dte_override
                    FROM dte_envios
                    WHERE numero_control IS NOT NULL AND UPPER(numero_control)=UPPER(?)
                    ORDER BY estado_dte_override DESC, id DESC LIMIT 1
                    """
                )
                params = (numero_control,)
            elif venta_id_lookup is not None:
                query = (
                    """
                    SELECT estado_dte_manual, estado_dte_override
                    FROM dte_envios
                    WHERE venta_id IS NOT NULL AND venta_id=?
                    ORDER BY estado_dte_override DESC, id DESC LIMIT 1
                    """
                )
                params = (venta_id_lookup,)

            if query:
                try:
                    cur.execute(query, params)
                    row = cur.fetchone()
                except Exception:
                    row = None
                if row:
                    try:
                        override_flag = row["estado_dte_override"]
                        estado_val = row["estado_dte_manual"]
                    except Exception:
                        override_flag = row[1] if len(row) > 1 else None
                        estado_val = row[0] if row else None
                    if override_flag and estado_val:
                        lowered = str(estado_val).strip().lower()
                        if lowered.startswith("sin venta"):
                            estado_manual = "Sin venta"
                        elif lowered.startswith("complet"):
                            estado_manual = "Completa"
                        elif lowered:
                            estado_manual = str(estado_val).strip()
        except Exception:
            estado_manual = None

    if estado_manual:
        estado = estado_manual

    env_row = None
    try:
        if cur is not None and (codigo_generacion or numero_control):
            env_row = cur.execute(
                """
                SELECT estado_ui, estado_ui_tag, estado FROM dte_envios
                WHERE codigo_generacion IS NOT NULL AND UPPER(codigo_generacion)=UPPER(?)
                ORDER BY estado_ui_manual DESC, id DESC LIMIT 1
                """,
                (codigo_generacion or "",),
            ).fetchone()
            if not env_row:
                env_row = cur.execute(
                    """
                    SELECT estado_ui, estado_ui_tag, estado FROM dte_envios
                    WHERE numero_control IS NOT NULL AND UPPER(numero_control)=UPPER(?)
                    ORDER BY estado_ui_manual DESC, id DESC LIMIT 1
                    """,
                    (numero_control or "",),
                ).fetchone()
            if not env_row:
                like_val = codigo_generacion or numero_control
                if like_val:
                    env_row = cur.execute(
                        """
                        SELECT estado FROM dte_envios
                        WHERE respuesta LIKE ?
                        ORDER BY id DESC LIMIT 1
                        """,
                        (f"%{like_val}%",),
                    ).fetchone()
    except Exception:
        env_row = None

    envio = _map_row_estado(env_row)
    return estado, envio


def is_ticket_sale(db, venta: Mapping[str, Any] | None) -> bool:
    if not venta:
        return False
    getter_cf = getattr(db, "get_venta_credito_fiscal", None)
    if getter_cf:
        try:
            if getter_cf(venta["id"]):
                return False
        except Exception:
            pass
    cid = venta.get("cliente_id") if isinstance(venta, Mapping) else None
    if not cid:
        return True
    cliente = None
    getter = getattr(db, "get_cliente", None)
    if getter:
        try:
            cliente = getter(cid)
        except Exception:
            cliente = None
    if not cliente:
        return True
    nit = (cliente.get("nit") or "").strip()
    dui = (cliente.get("dui") or "").strip()
    return not nit and not dui


def _resolve_existing_path(path: str | None) -> str | None:
    """Return the first accessible version of ``path``.

    Historical records may point to logical locations that differ from the
    physical file exposed to the user (for example when Python is executed from
    the Microsoft Store sandbox).  Additionally some users store documents on
    file systems with case-insensitive semantics which results in records using
    a different letter casing than what is reported when running the
    application on Linux or macOS.  This helper tries the original path, its
    user-visible counterpart and, when possible, performs a case-insensitive
    lookup in the target directory.
    """

    if not path:
        return None

    candidates: list[str] = []
    try:
        canonical = os.fspath(path)
    except TypeError:
        canonical = path  # type: ignore[assignment]

    if canonical:
        candidates.append(canonical)

    try:
        visible = resolve_user_visible_path(canonical)
    except Exception:
        visible = None

    if visible and visible not in candidates:
        candidates.append(visible)

    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate

    for candidate in candidates:
        if not candidate:
            continue
        directory, base = os.path.split(candidate)
        if not directory or not base:
            continue
        stem, _ext = os.path.splitext(base)
        try:
            entries = os.listdir(directory)
        except Exception:
            continue
        for entry in entries:
            entry_stem, _entry_ext = os.path.splitext(entry)
            if entry_stem.lower() == stem.lower():
                matched = os.path.join(directory, entry)
                if os.path.exists(matched):
                    return matched

    return path


def _load_json(path: str | None) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if not path:
        return None, None

    resolved_path = _resolve_existing_path(path)
    if not resolved_path or not os.path.exists(resolved_path):
        return None, None
    try:
        with open(resolved_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return None, None
    if not isinstance(data, Mapping):
        return None, None

    payload = _normalize_factura_payload(dict(data))
    if not isinstance(payload, Mapping):
        return None, None

    ident = _find_first_mapping(payload, ("identificacion", "identificador"))
    return payload, ident


def _cr_json_path(
    payload: Mapping[str, Any] | None,
    *,
    numero_control: str | None = None,
    fecha: str | None = None,
) -> str | None:
    ident = payload.get("identificacion") if isinstance(payload, Mapping) else {}
    numero = (
        (ident or {}).get("numeroControl")
        or (ident or {}).get("numero_control")
        or numero_control
        or "CR"
    )
    numero = str(numero or "").replace("-", "")
    fec = (ident or {}).get("fecEmi") or fecha or ""
    fec = str(fec or "").replace("-", "")
    name = f"CR_{fec or '0000'}_{numero or 'retencion'}.json"
    legacy_dir = ensure_user_dir("dtes", "retenciones")
    candidates = [
        os.path.join(RETENCIONES_DIR, name),
        os.path.join(legacy_dir, name),
    ]
    for candidate in candidates:
        resolved = _resolve_existing_path(candidate)
        if resolved and os.path.exists(resolved):
            return resolve_user_visible_path(resolved)
    fallback = _resolve_existing_path(candidates[0])
    return resolve_user_visible_path(fallback) if fallback else fallback


def _collect_subject_excluded_rows(db) -> list[dict[str, Any]]:
    """Lista archivos JSON generados para compras a sujetos excluidos (DTE 14)."""

    base_dir = ensure_user_dir("dtes_sujeto_excluido")
    rows: list[dict[str, Any]] = []
    try:
        base_path = Path(base_dir)
        files = sorted(base_path.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    except Exception:
        files = []

    cur = getattr(db, "cursor", None)
    seen_keys: set[str] = set()

    for fpath in files:
        try:
            with open(fpath, "r", encoding="utf-8") as fh:
                payload = json.load(fh)
        except Exception:
            continue

        ident = payload.get("identificacion") or {}
        sujeto_excluido = payload.get("sujetoExcluido") or {}
        resumen = payload.get("resumen") or {}
        apendice = payload.get("apendice") or []

        compra_id = None
        try:
            for entry in apendice:
                if isinstance(entry, Mapping) and str(entry.get("campo", "")).upper() == "ID_COMPRA":
                    compra_id = entry.get("valor")
                    break
        except Exception:
            compra_id = None

        numero_control = ident.get("numeroControl") or ident.get("numero_control")
        codigo_generacion = ident.get("codigoGeneracion") or ident.get("codigo_generacion")
        fecha_emision = ident.get("fecEmi") or ident.get("fechaEmision") or ident.get("fecha")
        hora_emision = ident.get("horEmi") or ident.get("horaEmision") or ident.get("hora")
        dedupe_key = str(codigo_generacion or numero_control or compra_id or fpath.stem)
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)

        parsed_date = None
        fecha_str = ""
        if fecha_emision:
            try:
                if hora_emision:
                    parsed_date = datetime.strptime(f"{fecha_emision} {hora_emision}", "%Y-%m-%d %H:%M:%S")
                    fecha_str = parsed_date.strftime("%Y-%m-%d %H:%M")
                else:
                    parsed_date = datetime.strptime(str(fecha_emision), "%Y-%m-%d")
                    fecha_str = parsed_date.strftime("%Y-%m-%d")
            except Exception:
                fecha_str = str(fecha_emision)

        total = resumen.get("totalPagar")
        try:
            total = _coerce_total(total)
        except Exception:
            total = None

        envio_estado = "Pendiente"
        if cur is not None:
            try:
                db.ensure_column("dte_envios", "estado_ui", "TEXT")
                db.ensure_column("dte_envios", "estado_ui_tag", "TEXT")
                db.ensure_column("dte_envios", "estado_ui_manual", "INTEGER DEFAULT 0")
                env_row = cur.execute(
                    """
                    SELECT estado_ui, estado_ui_tag, estado
                    FROM dte_envios
                    WHERE (numero_control IS NOT NULL AND UPPER(numero_control)=UPPER(?))
                       OR (codigo_generacion IS NOT NULL AND UPPER(codigo_generacion)=UPPER(?))
                    ORDER BY estado_ui_manual DESC, id DESC LIMIT 1
                    """,
                    (numero_control or "", codigo_generacion or ""),
                ).fetchone()
            except Exception:
                env_row = None
            envio_estado = _map_row_estado(env_row)

        pdf_path = fpath.with_suffix(".pdf")
        pdf_resolved = resolve_user_visible_path(str(pdf_path)) if pdf_path.exists() else None
        name_value = numero_control or codigo_generacion or f"FSE-{compra_id or fpath.stem}"

        rows.append(
            {
                "row_type": "orphan",
                "id": compra_id,
                "venta_id": None,
                "name": name_value,
                "numero_control": numero_control,
                "codigo_generacion": codigo_generacion,
                "fecha": fecha_str,
                "_parsed_fecha": parsed_date,
                "cliente": sujeto_excluido.get("nombre") or "",
                "cliente_id": None,
                "vendedor_id": None,
                "total": total,
                "estado": envio_estado,
                "envio": envio_estado,
                "tipo": "Factura sujeto excluido",
                "codigo": "14",
                "json": resolve_user_visible_path(str(fpath)),
                "pdf": pdf_resolved,
                "sign": 1,
            }
        )
    return rows


def get_facturacion_rows(db) -> list[Dict[str, Any]]:
    cur = getattr(db, "cursor", None)
    if cur is None:
        return []

    factura_records: list[dict[str, Any]] = []
    ticket_records: list[dict[str, Any]] = []

    try:
        cur.execute(
            "SELECT id, venta_id, tipo, ruta, fecha_creacion FROM facturas_pdf"
        )
        for row in cur.fetchall():
            rec = dict(row)
            rec["_source"] = "factura"
            factura_records.append(rec)
    except Exception:
        factura_records = []

    try:
        cur.execute(
            "SELECT id, venta_id, ruta, fecha_creacion FROM tickets_pdf"
        )
        for row in cur.fetchall():
            rec = dict(row)
            rec["_source"] = "ticket"
            rec.setdefault("tipo", "Ticket")
            ticket_records.append(rec)
    except Exception:
        ticket_records = []

    records = factura_records + ticket_records

    grouped: dict[tuple[Any, ...], dict[str, dict[str, Any]]] = defaultdict(dict)
    factura_roots: dict[str, tuple[Any, ...]] = {}

    def _document_root_from_path(path: str | None) -> str | None:
        if not path:
            return None
        try:
            base_name = os.path.splitext(os.path.basename(path))[0]
        except Exception:
            return None
        if not base_name:
            return None

        lowered = base_name.lower()
        for suffix in (
            "_ticket",
            "-ticket",
            "_consumidorfinal",
            "-consumidorfinal",
            "_creditofiscal",
            "-creditofiscal",
            "_factura",
            "-factura",
        ):
            if lowered.endswith(suffix):
                lowered = lowered[: -len(suffix)]
                break
        return lowered or None

    def _normalize_group_key(path: str | None) -> tuple[Any, ...]:
        if not path:
            return ("path", None, None)
        try:
            base_name = os.path.splitext(os.path.basename(path))[0]
            directory = os.path.dirname(path) or ""
        except Exception:
            return ("path", None, None)
        normalized = base_name.lower()
        for suffix in ("_ticket", "-ticket"):
            if normalized.endswith(suffix):
                normalized = normalized[: -len(suffix)]
                break
        return ("path", directory.lower(), normalized)

    for rec in records:
        source = rec.get("_source", "factura")
        doc_tipo = rec.get("tipo")
        tipo_lower = str(doc_tipo or "").strip().lower()
        ruta_value = rec.get("ruta")
        inferred_tipo = None
        if ruta_value:
            try:
                base_name = os.path.splitext(os.path.basename(ruta_value))[0]
            except Exception:
                base_name = None
            inferred_tipo = infer_tipo_from_name(base_name, doc_tipo)
        inferred_lower = str(inferred_tipo or "").strip().lower()
        note_like = _looks_like_note_label(tipo_lower) or _looks_like_note_label(
            inferred_lower
        )
        venta_id = rec.get("venta_id")
        key: tuple[Any, ...]
        if venta_id is not None and not note_like:
            key = ("venta", venta_id)
        else:
            key = _normalize_group_key(ruta_value)
            if key == ("path", None, None):
                rec_id = rec.get("id")
                if rec_id is not None:
                    key = ("id", rec_id)
                elif venta_id is not None:
                    key = ("venta", venta_id, tipo_lower or None)

        if source == "ticket":
            matched_key = None
            if venta_id is not None and not note_like:
                venta_key = ("venta", venta_id)
                existing_bucket = grouped.get(venta_key)
                if existing_bucket and "factura" in existing_bucket:
                    matched_key = venta_key
            if matched_key is None:
                root_key = _document_root_from_path(ruta_value)
                if root_key:
                    matched_key = factura_roots.get(root_key)
            if matched_key is not None:
                key = matched_key

        bucket = grouped.setdefault(key, {})
        if source == "ticket":
            bucket.setdefault("ticket", rec)
        else:
            bucket.setdefault("factura", rec)
            if not note_like:
                root_key = _document_root_from_path(ruta_value)
                if root_key and root_key not in factura_roots:
                    factura_roots[root_key] = key

    combined_records: list[dict[str, Any]] = []
    for bucket in grouped.values():
        factura_rec = bucket.get("factura")
        ticket_rec = bucket.get("ticket")
        if factura_rec and ticket_rec:
            merged = dict(factura_rec)
            merged["_source"] = factura_rec.get("_source", "factura")
            merged["_ticket_record"] = dict(ticket_rec)
            combined_records.append(merged)
        elif factura_rec:
            merged = dict(factura_rec)
            merged["_source"] = factura_rec.get("_source", "factura")
            combined_records.append(merged)
        elif ticket_rec:
            merged = dict(ticket_rec)
            merged["_source"] = ticket_rec.get("_source", "ticket")
            combined_records.append(merged)

    rows: list[Dict[str, Any]] = []
    for rec in combined_records:
        ticket_info = rec.pop("_ticket_record", None)
        source = rec.pop("_source", "factura")
        doc_tipo = rec.get("tipo")
        tipo_lower = str(doc_tipo or "").strip().lower()
        venta = None
        venta_id = rec.get("venta_id")
        if venta_id is not None and not tipo_lower.startswith("nota"):
            try:
                venta = db.get_venta_by_id(venta_id)
            except Exception:
                venta = None
        ruta = _resolve_existing_path(rec.get("ruta")) or rec.get("ruta")
        if not ruta and ticket_info:
            ruta = _resolve_existing_path(ticket_info.get("ruta")) or ticket_info.get("ruta")
        json_path = os.path.splitext(ruta)[0] + ".json" if ruta else None
        json_path = _resolve_existing_path(json_path)
        if ticket_info and (not json_path or not os.path.exists(json_path)):
            ticket_ruta = _resolve_existing_path(ticket_info.get("ruta")) or ticket_info.get("ruta")
            if ticket_ruta:
                ticket_json = os.path.splitext(ticket_ruta)[0] + ".json"
                ticket_json = _resolve_existing_path(ticket_json)
                if ticket_json and os.path.exists(ticket_json):
                    json_path = ticket_json

        fecha_creacion = rec.get("fecha_creacion") or ""
        fdate = None
        if fecha_creacion:
            try:
                fdate = datetime.strptime(fecha_creacion, "%Y-%m-%d %H:%M:%S")
            except Exception:
                fdate = None
        fecha_str = fdate.strftime("%Y-%m-%d %H:%M") if fdate else fecha_creacion

        row_type = "venta"
        prefer_json_timestamp = False
        cliente_nombre = ""
        cliente_id = None
        vendedor_id = None
        total = None
        numero_control = None
        codigo_generacion = None
        tipo_codigo = None
        tipo_desc = doc_tipo

        json_data = None
        ident_data = None
        if json_path and os.path.exists(json_path):
            json_data, ident_data = _load_json(json_path)

        if ident_data is None and isinstance(json_data, Mapping):
            maybe_ident = json_data.get("identificacion") or json_data.get("identificador")
            if isinstance(maybe_ident, Mapping):
                ident_data = maybe_ident

        extra_data = None
        if venta:
            getter = getattr(db, "get_cliente", None)
            if venta.get("cliente_id") and getter:
                try:
                    cliente = getter(venta.get("cliente_id"))
                    cliente_nombre = cliente.get("nombre", "") if cliente else ""
                except Exception:
                    cliente_nombre = ""
            cliente_id = venta.get("cliente_id")
            vendedor_id = venta.get("vendedor_id")
            total = venta.get("total")
            raw_extra = venta.get("extra")
            if isinstance(raw_extra, Mapping):
                extra_data = dict(raw_extra)
            elif isinstance(raw_extra, str):
                try:
                    extra_data = json.loads(raw_extra)
                except Exception:
                    extra_data = {}
            elif raw_extra:
                extra_data = {}
            if source == "ticket":
                row_type = "ticket"
            else:
                row_type = "ticket" if is_ticket_sale(db, venta) else "venta"
        else:
            row_type = "ticket" if source == "ticket" else "orphan"
            if ident_data:
                numero_control = ident_data.get("numeroControl")
                codigo_generacion = ident_data.get("codigoGeneracion")
            prefer_json_timestamp = True
        if not cliente_nombre and isinstance(json_data, Mapping):
            nombre_hint = _extract_cliente_nombre(json_data)
            if nombre_hint:
                cliente_nombre = str(nombre_hint)
        if ident_data:
            numero_control = numero_control or ident_data.get("numeroControl")
            codigo_generacion = codigo_generacion or ident_data.get("codigoGeneracion")

            fecha_ident = (
                ident_data.get("fecEmi")
                or ident_data.get("fechaEmision")
                or ident_data.get("fecha")
            )
            hora_ident = ident_data.get("horEmi") or ident_data.get("horaEmision")
            if fecha_ident:
                try:
                    parsed_fecha = None
                    parsed_display = None
                    if hora_ident:
                        parsed_fecha = datetime.strptime(
                            f"{fecha_ident} {hora_ident}", "%Y-%m-%d %H:%M:%S"
                        )
                        parsed_display = parsed_fecha.strftime("%Y-%m-%d %H:%M")
                    else:
                        parsed_fecha = datetime.strptime(str(fecha_ident), "%Y-%m-%d")
                        parsed_display = parsed_fecha.strftime("%Y-%m-%d")
                except Exception:
                    parsed_fecha = None
                    parsed_display = None
                if parsed_fecha and (prefer_json_timestamp or not fdate):
                    fdate = parsed_fecha
                    fecha_str = parsed_display or fecha_str
        elif isinstance(json_data, Mapping):
            numero_hint = _find_first_non_empty(
                json_data,
                (
                    "numeroControl",
                    "numero_control",
                    "numeroDocumento",
                    "numeroFactura",
                    "numero",
                ),
            )
            if numero_hint:
                numero_control = numero_hint
            codigo_hint = _find_first_non_empty(
                json_data,
                ("codigoGeneracion", "codigo_generacion", "codigo", "codigoDeGeneracion"),
            )
            if codigo_hint:
                codigo_generacion = codigo_hint
            if prefer_json_timestamp or not fdate:
                fecha_hint = _find_first_non_empty(
                    json_data,
                    ("fecEmi", "fechaEmision", "fecha"),
                )
                if fecha_hint:
                    hora_hint = _find_first_non_empty(
                        json_data,
                        ("horEmi", "horaEmision", "hora"),
                    )
                    try:
                        if hora_hint:
                            parsed_fecha = datetime.strptime(
                                f"{fecha_hint} {hora_hint}", "%Y-%m-%d %H:%M:%S"
                            )
                            fecha_str = parsed_fecha.strftime("%Y-%m-%d %H:%M")
                        else:
                            parsed_fecha = datetime.strptime(str(fecha_hint), "%Y-%m-%d")
                            fecha_str = parsed_fecha.strftime("%Y-%m-%d")
                        fdate = parsed_fecha
                    except Exception:
                        fdate = None

        if isinstance(extra_data, Mapping):
            numero_control = numero_control or extra_data.get("numeroControl")
            codigo_generacion = codigo_generacion or extra_data.get("codigoGeneracion")
            if tipo_desc is None:
                tipo_hint = (
                    extra_data.get("tipoDte")
                    or extra_data.get("tipo_dte")
                    or extra_data.get("tipo")
                )
                if tipo_hint is not None:
                    tipo_hint_str = str(tipo_hint).strip()
                    if tipo_hint_str.isdigit():
                        tipo_desc = TIPO_DTE_DESC.get(
                            tipo_hint_str.zfill(2), tipo_desc
                        )
                    elif tipo_hint_str:
                        tipo_desc = tipo_hint_str

        if total is None and isinstance(json_data, Mapping):
            total_hint = _extract_total_from_json(json_data)
            if total_hint not in (None, ""):
                total = total_hint

        if tipo_codigo is None and ident_data:
            tipo_codigo = ident_data.get("tipoDte")
            if tipo_desc is None:
                tipo_codigo_str = str(tipo_codigo or "").zfill(2)
                tipo_desc = TIPO_DTE_DESC.get(tipo_codigo_str)

        if tipo_codigo is None:
            tipo_codigo = tipo_code_from_desc(tipo_desc)

        if tipo_codigo is not None:
            try:
                tipo_codigo = str(tipo_codigo).zfill(2)
            except Exception:
                tipo_codigo = None
        if tipo_desc is None:
            tipo_desc = doc_tipo
        estado, envio = detectar_estado_factura(
            venta,
            ruta,
            json_path,
            cur,
            venta_id=rec.get("venta_id"),
            numero_control=numero_control,
            codigo_generacion=codigo_generacion,
            doc_tipo=doc_tipo,
        )

        path_source = ruta or json_path or ""
        base_name = os.path.splitext(os.path.basename(path_source))[0]
        if not base_name:
            base_name = numero_control or ""
        tipo_desc = infer_tipo_from_name(base_name, tipo_desc or doc_tipo)
        row = {
            "row_type": row_type,
            "id": rec.get("id"),
            "venta_id": venta_id,
            "name": base_name,
            "numero_control": numero_control,
            "codigo_generacion": codigo_generacion,
            "fecha": fecha_str,
            "_parsed_fecha": fdate,
            "cliente": cliente_nombre,
            "cliente_id": cliente_id,
            "vendedor_id": vendedor_id,
            "total": total,
            "estado": estado,
            "envio": envio,
            "tipo": tipo_desc or doc_tipo,
            "codigo": tipo_codigo,
        }
        if json_path and os.path.exists(json_path):
            row["json"] = json_path
        if ticket_info:
            ticket_path_value = ticket_info.get("ruta")
            if ticket_path_value:
                row["ticket_pdf"] = ticket_path_value

        if row_type == "orphan":
            row["pdf"] = ruta
            row["json"] = json_path

        coerced_total = _coerce_total(row.get("total"))
        if coerced_total is not None:
            row["total"] = coerced_total

        tipo_lower_desc = str((tipo_desc or doc_tipo or "").lower())
        note_kind = None
        nota_id: int | None = None
        if "nota" in tipo_lower_desc:
            if "remision" in tipo_lower_desc or "remisión" in tipo_lower_desc:
                note_kind = "remision"
            elif "crédito" in tipo_lower_desc or "credito" in tipo_lower_desc:
                note_kind = "credito"
            elif "débito" in tipo_lower_desc or "debito" in tipo_lower_desc:
                note_kind = "debito"
        if note_kind:
            try:
                nota_id = db.find_nota_by_document(
                    numero_control=numero_control,
                    codigo_generacion=codigo_generacion,
                    json_path=json_path,
                    tipo=note_kind,
                )
            except Exception:
                nota_id = None
            if nota_id is not None:
                row["nota_id"] = nota_id

        sign_value = 1
        coerced_note_total = None
        if note_kind:
            sign_value = -1 if note_kind == "credito" else 1
            note_total_value = None
            if isinstance(json_data, Mapping):
                try:
                    resumen = json_data.get("resumen") or {}
                except AttributeError:
                    resumen = {}
                if isinstance(resumen, Mapping):
                    note_total_value = resumen.get("montoTotalOperacion")
            if note_total_value is None and nota_id is not None and cur is not None:
                try:
                    nota_row = cur.execute(
                        "SELECT monto FROM notas WHERE id=?",
                        (nota_id,),
                    ).fetchone()
                except Exception:
                    nota_row = None
                if nota_row is not None:
                    if isinstance(nota_row, Mapping):
                        note_total_value = nota_row.get("monto")
                    else:
                        try:
                            note_total_value = nota_row[0]
                        except Exception:
                            note_total_value = None
            coerced_note_total = _coerce_total(note_total_value)
        if coerced_note_total is not None:
            row["total"] = coerced_note_total

        row["sign"] = sign_value
        rows.append(row)

    rows.extend(_collect_subject_excluded_rows(db))

    # ---- Retenciones CR-07 -------------------------------------------------
    ret_rows: list[dict[str, Any]] = []
    try:
        ensure_retenciones = getattr(db, "_ensure_retenciones_cr_table", None)
        if callable(ensure_retenciones):
            try:
                ensure_retenciones()
            except Exception:
                pass
        cur.execute("SELECT * FROM retenciones_cr")
        ret_rows = [dict(row) for row in cur.fetchall()]
    except Exception:
        ret_rows = []

    seen_ret_keys: set[tuple[str | None, str | None]] = set()

    def _append_retencion_row(payload: Mapping[str, Any], rec: Mapping[str, Any] | None, venta_id: Any) -> None:
        ident = payload.get("identificacion") or {}
        resumen = payload.get("resumen") or {}
        cuerpo = (payload.get("cuerpoDocumento") or [{}])[0]
        fecha_emision = (
            ident.get("fecEmi")
            or ident.get("fechaEmision")
            or ident.get("fecha")
        )
        hora_emision = ident.get("horEmi") or ident.get("horEmision") or ident.get("hora")
        fdate = None
        fecha_str = ""
        if fecha_emision:
            try:
                if hora_emision:
                    fdate = datetime.strptime(f"{fecha_emision} {hora_emision}", "%Y-%m-%d %H:%M:%S")
                    fecha_str = fdate.strftime("%Y-%m-%d %H:%M")
                else:
                    fdate = datetime.strptime(str(fecha_emision), "%Y-%m-%d")
                    fecha_str = fdate.strftime("%Y-%m-%d")
            except Exception:
                fdate = None
                fecha_str = str(fecha_emision)
        if not fecha_str:
            created_at = rec.get("created_at") if rec else None
            try:
                fdate = datetime.fromisoformat(str(created_at))
                fecha_str = fdate.strftime("%Y-%m-%d %H:%M")
            except Exception:
                fecha_str = str(created_at or "")
        numero_control = ident.get("numeroControl") or (rec.get("numero_control") if rec else None)
        codigo_generacion = ident.get("codigoGeneracion") or (rec.get("codigo_generacion") if rec else None)
        seen_ret_keys.add((numero_control, codigo_generacion))

        cliente_nombre = ""
        cliente_id = None
        if venta_id is not None:
            try:
                venta = db.get_venta_by_id(venta_id)
            except Exception:
                venta = None
            if venta:
                cliente_id = venta.get("cliente_id")
                getter = getattr(db, "get_cliente", None)
                if getter and cliente_id:
                    try:
                        cliente = getter(cliente_id)
                        cliente_nombre = cliente.get("nombre", "") if cliente else ""
                    except Exception:
                        cliente_nombre = ""
        if not cliente_nombre and isinstance(payload, Mapping):
            nombre_hint = _extract_cliente_nombre(payload)
            if nombre_hint:
                cliente_nombre = str(nombre_hint)
        base_retencion = (
            resumen.get("totalSujetoRetencion")
            if isinstance(resumen, Mapping)
            else None
        )
        if base_retencion in (None, ""):
            base_retencion = cuerpo.get("montoSujetoGrav")
        total = _coerce_total(base_retencion)
        estado_raw = rec.get("estado") if rec else None
        envio_estado = format_envio_state(None, None, estado_raw)
        contingencia_pendiente = False
        if cur is not None and venta_id is not None:
            try:
                cur.execute(
                    """
                    SELECT 1
                    FROM dte_pendientes
                    WHERE venta_id=? AND transmitido=0
                    LIMIT 1
                    """,
                    (venta_id,),
                )
                contingencia_pendiente = cur.fetchone() is not None
            except Exception:
                contingencia_pendiente = False
        estado_display = "Contingencia" if contingencia_pendiente else envio_estado
        cr_json_path = _cr_json_path(
            payload,
            numero_control=numero_control,
            fecha=str(fecha_emision or ""),
        )
        rows.append(
            {
                "row_type": "retencion",
                "id": f"CR-{(rec.get('id') if rec and rec.get('id') is not None else numero_control or codigo_generacion or 'file')}",
                "venta_id": venta_id,
                "name": numero_control or codigo_generacion or "CR-07",
                "numero_control": numero_control,
                "codigo_generacion": codigo_generacion,
                "fecha": fecha_str,
                "_parsed_fecha": fdate,
                "cliente": cliente_nombre,
                "cliente_id": cliente_id,
                "vendedor_id": None,
                "total": total,
                "estado": estado_display,
                "envio": envio_estado,
                "tipo": "Comp. retención",
                "codigo": "CR-07",
                "json": cr_json_path,
                "sign": 1,
            }
        )

    for rec in ret_rows:
        try:
            payload_json = rec.get("payload_json")
            try:
                payload = json.loads(payload_json) if payload_json else {}
            except Exception:
                payload = {}
            _append_retencion_row(payload, rec, rec.get("venta_id"))
        except Exception:
            continue

    # Fallback: agregar CR encontrados en disco aunque no haya fila en DB
    legacy_dir = ensure_user_dir("dtes", "retenciones")
    ret_dirs = [RETENCIONES_DIR, os.fspath(legacy_dir)]
    for base_dir in ret_dirs:
        try:
            entries = os.listdir(base_dir)
        except Exception:
            continue
        for entry in entries:
            if not entry.lower().endswith(".json"):
                continue
            if not entry.upper().startswith("CR_"):
                continue
            path = os.path.join(base_dir, entry)
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    payload = json.load(fh)
            except Exception:
                continue
            ident = payload.get("identificacion") or {}
            key = (ident.get("numeroControl"), ident.get("codigoGeneracion"))
            if key in seen_ret_keys:
                continue
            try:
                _append_retencion_row(payload, None, None)
            except Exception:
                continue
    return rows
