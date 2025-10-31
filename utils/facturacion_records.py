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
from typing import Any, Dict, Iterable, Iterator, Mapping, Sequence

from paths import resolve_user_visible_path


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
    "07": "Comprobante de donación",
    "08": "Comprobante de retención",
    "09": "Liquidación",
    "10": "Comprobante de liquidación",
    "11": "Factura de exportación",
    "12": "Comprobante de percepción",
    "13": "Liquidación de compra",
    "14": "Despacho aduanero",
    "15": "Mandamiento judicial",
    "16": "Nota de remisión de exportación",
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


def _first_non_empty(mapping: Mapping[str, Any], keys: Iterable[str]) -> str | None:
    for key in keys:
        value = mapping.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _iter_nested_mappings(*values: Any) -> Iterator[Mapping[str, Any]]:
    """Yield every mapping contained in *values* (breadth-first)."""

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


def _collect_first_matching(
    mappings: Iterable[Mapping[str, Any]],
    keys: Sequence[str],
) -> Mapping[str, Any] | None:
    for mapping in mappings:
        for key in keys:
            section = mapping.get(key)
            if isinstance(section, Mapping):
                return section
    return None


def _normalize_mapping_keys(mapping: Mapping[str, Any]) -> set[str]:
    normalized: set[str] = set()
    for key in mapping.keys():
        if isinstance(key, str):
            normalized.add(key.lower())
    return normalized


def _unwrap_document_payload(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return the mapping that stores the DTE document fields."""

    for candidate in _iter_nested_mappings(payload):
        keys = _normalize_mapping_keys(candidate)
        has_ident = bool({"identificacion", "identificador"} & keys)
        has_content = bool(
            keys
            & {
                "resumen",
                "totales",
                "totalesfactura",
                "resumenfactura",
                "receptor",
                "cliente",
                "adquiriente",
                "contribuyente",
                "cuerpodocumento",
            }
        )
        if has_ident or has_content:
            return candidate
    return payload


def _extract_cliente_nombre(payload: Mapping[str, Any] | None) -> str | None:
    if not isinstance(payload, Mapping):
        return None

    document_payload = _unwrap_document_payload(payload)

    candidates: list[Mapping[str, Any]] = []
    for mapping in _iter_nested_mappings(document_payload):
        candidate = _collect_first_matching(
            (mapping,),
            ("receptor", "cliente", "adquiriente", "contribuyente"),
        )
        if candidate:
            candidates.append(candidate)
            contacto = candidate.get("contactoReceptor")
            if isinstance(contacto, Mapping):
                candidates.append(contacto)

    for section in candidates:
        nombre = _first_non_empty(
            section,
            (
                "nombre",
                "nombreComercial",
                "denominacionSocial",
                "razonSocial",
                "nombreRazonSocial",
                "nombreCliente",
                "nombreCompleto",
            ),
        )
        if nombre:
            return nombre

    return None


def _extract_total_from_json(payload: Mapping[str, Any] | None) -> Any:
    if not isinstance(payload, Mapping):
        return None

    document_payload = _unwrap_document_payload(payload)
    sections: list[Mapping[str, Any]] = []

    for mapping in _iter_nested_mappings(document_payload):
        for key in ("resumen", "totales", "totalesFactura", "resumenFactura"):
            section = mapping.get(key)
            if isinstance(section, Mapping):
                sections.append(section)

    for section in sections:
        value = None
        for field in (
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
        ):
            value = section.get(field)
            if value not in (None, ""):
                break
        if value not in (None, ""):
            return value

    return None


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

    document_payload = _unwrap_document_payload(data)
    ident_section = None
    for mapping in _iter_nested_mappings(document_payload, data):
        ident_candidate = mapping.get("identificacion") or mapping.get("identificador")
        if isinstance(ident_candidate, Mapping):
            ident_section = ident_candidate
            break

    return document_payload, ident_section


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
        if not cliente_nombre and isinstance(json_data, Mapping):
            cliente_hint = _extract_cliente_nombre(json_data)
            if cliente_hint:
                cliente_nombre = cliente_hint
        use_json_fecha = venta is None or row_type == "orphan"

        if ident_data:
            numero_control = numero_control or ident_data.get("numeroControl")
            codigo_generacion = codigo_generacion or ident_data.get("codigoGeneracion")

            fecha_ident = (
                ident_data.get("fecEmi")
                or ident_data.get("fechaEmision")
                or ident_data.get("fecha")
            )
            hora_ident = ident_data.get("horEmi") or ident_data.get("horaEmision")
            parsed_fdate = None
            parsed_fecha_str = None
            if fecha_ident:
                try:
                    if hora_ident:
                        parsed_fdate = datetime.strptime(
                            f"{fecha_ident} {hora_ident}", "%Y-%m-%d %H:%M:%S"
                        )
                        parsed_fecha_str = parsed_fdate.strftime("%Y-%m-%d %H:%M")
                    else:
                        parsed_fdate = datetime.strptime(str(fecha_ident), "%Y-%m-%d")
                        parsed_fecha_str = parsed_fdate.strftime("%Y-%m-%d")
                except Exception:
                    parsed_fdate = None

            if parsed_fdate and (use_json_fecha or not fdate):
                fdate = parsed_fdate
                fecha_str = parsed_fecha_str or fecha_str

        if not numero_control and isinstance(json_data, Mapping):
            numero_hint = _first_non_empty(
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

        if not codigo_generacion and isinstance(json_data, Mapping):
            codigo_hint = _first_non_empty(
                json_data,
                ("codigoGeneracion", "codigo_generacion", "codigo", "codigoDeGeneracion"),
            )
            if codigo_hint:
                codigo_generacion = codigo_hint

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
    return rows

