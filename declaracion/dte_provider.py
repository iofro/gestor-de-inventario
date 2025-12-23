"""Proveedor de datos para la generación de anexos DTE."""

from __future__ import annotations
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, date, time
from pathlib import Path
import json
import logging
import os
import re
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Callable, Mapping

from declaracion.anexo_contribuyentes import VentaContribuyente
from declaracion.anexo_consumidor_final import VentaCF
from declaracion.anexo_xix import DTEAnulado
from utils.facturacion_records import (
    infer_tipo_from_name,
    tipo_code_from_desc,
    get_facturacion_rows as _facturacion_rows,
    TIPO_DTE_DESC,
    short_tipo_label,
    format_envio_state,
)
from paths import (
    FACTURAS_ARCHIVE_CREDITO_DIR,
    FACTURAS_CREDITO_FISCAL_DIR,
    DTES_DIR,
    DTES_PENDIENTES_DIR,
    ensure_user_dir,
)

logger = logging.getLogger(__name__)

CAT002_VALID = {
    "01",
    "02",
    "03",
    "04",
    "05",
    "06",
    "07",
    "08",
    "09",
    "10",
    "11",
    "14",
    "15",
}

APTOS = {"enviado", "aceptado", "recibido"}
ENVIADO_ESTADOS = {"enviado", "aceptado", "recibido"}
ANULADO_ESTADOS = {"anulado", "invalidado"}
ALIASES = {
    "procesado": "recibido",
    "procesada": "recibido",
    "procesamiento": "recibido",
    "recibido": "recibido",
    "recibida": "recibido",
    "enviado": "enviado",
    "enviada": "enviado",
    "transmitido": "enviado",
    "transmitida": "enviado",
    "aceptado": "aceptado",
    "aceptada": "aceptado",
    "aprobado": "aceptado",
    "aprobada": "aceptado",
    "pendiente": "pendiente",
    "rechazado": "rechazado",
    "rechazada": "rechazado",
    "anulado": "anulado",
    "anulada": "anulado",
    "invalidado": "invalidado",
    "invalidada": "invalidado",
    "cancelado": "anulado",
    "cancelada": "anulado",
}

_ESTADO_FIELD_KEYS = {
    "estado",
    "estado_desc",
    "estadodesc",
    "estadoenvio",
    "estado_envio",
    "estadorespuesta",
    "estadodocumento",
    "estadoactual",
    "estado_ui",
    "estado_ui_tag",
}

_TIPO_HINT_ALIASES = {
    "ccf": "03",
    "credito fiscal": "03",
    "nota de credito": "05",
    "nota credito": "05",
    "nota de debito": "06",
    "nota debito": "06",
    "nota de remision": "04",
    "nota remision": "04",
    "factura": "01",
    "consumidor final": "01",
    "ticket": "01",
}

_TIPO_TOKEN_PATTERN = re.compile(r"(?<!\d)(\d{1,2})(?!\d)")

TIPOS_ANEXO_I = {"03", "05", "06"}
TIPOS_ANEXO_II = {"01", "02", "10", "11"}

CLASE_POR_TIPO = {code: "4" for code in CAT002_VALID}

_ACCENT_TRANSLATION = str.maketrans("áéíóúÁÉÍÓÚ", "aeiouaeiou")


@dataclass
class PreviewExclusionEntry:
    """Representa un DTE excluido de la previsualización y su motivo."""

    codigo: str | None = None
    tipo: str | None = None
    fecha: str | None = None
    detalle: str | None = None
    venta_id: int | None = None

    def describe(self) -> str:
        """Texto breve para registros de log."""

        partes: list[str] = []
        if self.codigo:
            partes.append(str(self.codigo))
        if self.detalle:
            partes.append(str(self.detalle))
        if not partes:
            if self.tipo:
                partes.append(str(self.tipo))
            if self.fecha:
                partes.append(str(self.fecha))
            if not partes and self.venta_id is not None:
                partes.append(f"venta {self.venta_id}")
        if not partes:
            return ""
        if len(partes) == 1:
            return partes[0]
        return ":".join(partes)

    def to_display(self) -> str:
        """Descripción enriquecida para la interfaz de usuario."""

        segmentos: list[str] = []
        if self.tipo:
            segmentos.append(str(self.tipo))
        if self.fecha:
            segmentos.append(str(self.fecha))
        if self.codigo:
            if self.detalle:
                segmentos.append(f"{self.codigo}: {self.detalle}")
            else:
                segmentos.append(str(self.codigo))
        elif self.detalle:
            segmentos.append(str(self.detalle))
        if not segmentos and self.venta_id is not None:
            segmentos.append(f"venta {self.venta_id}")
        return " · ".join(segmentos)


@dataclass
class FacturacionDataset:
    rows: list[dict]
    total_leidos: int
    descartes: dict[str, list[PreviewExclusionEntry]]


@dataclass
class PreviewRow:
    fecha: str
    fecha_obj: datetime | None
    tipo: str
    tipo_codigo: str | None
    codigo_generacion: str
    numero_control: str | None
    cliente: str
    identificacion: str | None
    estado_base: str | None
    estado_manual: str | None
    estado_override: bool
    estado_fuente: str | None
    sello_recepcion: str | None
    totales: dict[str, str]
    venta_id: int | None = None

    def sort_key(self) -> tuple:
        return (
            self.fecha_obj or datetime.max,
            self.tipo_codigo or self.tipo or "",
            self.numero_control or "",
            self.codigo_generacion,
        )


@dataclass
class AnexoPreviewData:
    candidatos: int
    incluidos: list[PreviewRow]
    excluidos: dict[str, list[PreviewExclusionEntry]]
    conteos_por_tipo: dict[str, dict[str, int]]
    total_incluidos: int = field(init=False)
    total_excluidos: int = field(init=False)

    def __post_init__(self) -> None:
        self.total_incluidos = len(self.incluidos)
        self.total_excluidos = max(0, self.candidatos - self.total_incluidos)


@dataclass
class DeclaracionPreview:
    periodo: str
    anexo_i: AnexoPreviewData
    anexo_ii: AnexoPreviewData


EXCLUSION_MOTIVOS = (
    "no_enviado",
    "sin_codigo",
    "sin_fecha",
    "duplicado",
    "anulado",
    "correlativo_duplicado",
    "fuera_de_periodo",
    "campos_invalidos",
)


def _ensure_field(row: dict, key: str, extractor: Callable[[dict], str | None]) -> str | None:
    value = row.get(key)
    if value:
        return value
    value = extractor(row)
    if value:
        row[key] = value
    return value


def _make_exclusion_entry(
    row: dict,
    *,
    detalle: str | None = None,
    fecha: str | None = None,
) -> PreviewExclusionEntry:
    codigo = _ensure_field(row, "codigo_generacion", _codigo_generacion)
    tipo = row.get("tipo")
    fecha_texto = fecha or row.get("fecEmi")
    detalle_texto = str(detalle).strip() if detalle else None
    fecha_texto = str(fecha_texto).strip() if fecha_texto else None
    tipo_texto = str(tipo).strip() if tipo else None
    return PreviewExclusionEntry(
        codigo=str(codigo).strip() if codigo else None,
        tipo=tipo_texto or None,
        fecha=fecha_texto or None,
        detalle=detalle_texto or None,
        venta_id=row.get("venta_id"),
    )


def _row_fecha_text(row: dict) -> str | None:
    fecha_obj = row.get("fecha_obj")
    if isinstance(fecha_obj, datetime):
        return fecha_obj.strftime("%Y-%m-%d")
    fec = row.get("fecEmi")
    if fec:
        texto = str(fec).strip()
        if len(texto) == 8 and texto.isdigit():
            return f"{texto[:4]}-{texto[4:6]}-{texto[6:]}"
        return texto
    return None


def _normalize_hora_text(value: Any) -> str | None:
    if value is None:
        return None
    try:
        texto = str(value).strip()
    except Exception:
        return None
    if not texto:
        return None
    texto = texto.replace("T", " ")
    if " " in texto:
        partes = [p for p in texto.split() if ":" in p] or texto.split()
        texto = partes[-1]
    match = re.match(r"^(\d{1,2}):(\d{2})", texto)
    if match:
        try:
            hora = int(match.group(1))
            minutos = match.group(2)
            return f"{hora:02d}:{minutos}"
        except Exception:
            return None
    if texto.isdigit() and len(texto) in (3, 4):
        try:
            horas = int(texto[:-2])
            mins = int(texto[-2:])
            return f"{horas:02d}:{mins:02d}"
        except Exception:
            return None
    return None


def _extract_hora_from_payload(payload: Any) -> str | None:
    if not isinstance(payload, Mapping):
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                return None
            if not isinstance(payload, Mapping):
                return None
        else:
            return None

    stack: list[Mapping[str, Any]] = [payload]
    seen: set[int] = set()
    keys = {"horemi", "horaemision", "hora_emision"}

    while stack:
        current = stack.pop()
        obj_id = id(current)
        if obj_id in seen:
            continue
        seen.add(obj_id)
        for key, value in current.items():
            lowered = str(key).strip().lower()
            if lowered in keys and value:
                hora = _normalize_hora_text(value)
                if hora:
                    return hora
            if isinstance(value, Mapping):
                stack.append(value)
    return None


def _row_hora_text(row: dict) -> str | None:
    ident = row.get("dte_json", {}).get("identificacion") if isinstance(row.get("dte_json"), dict) else {}
    extra = row.get("extra_data") or {}
    candidates = [
        (ident or {}).get("horEmi"),
        row.get("horEmi"),
        extra.get("horEmi") if isinstance(extra, dict) else None,
        extra.get("horaEmision") if isinstance(extra, dict) else None,
        row.get("hora_emision"),
    ]
    envio = row.get("envio")
    if isinstance(envio, Mapping):
        resp = envio.get("respuesta_json") or envio.get("respuesta")
        hora_envio = _extract_hora_from_payload(resp)
        candidates.append(hora_envio)
    extra_resp = (extra or {}).get("respuesta") if isinstance(extra, Mapping) else None
    hora_extra = _extract_hora_from_payload(extra_resp)
    candidates.append(hora_extra)
    for candidate in candidates:
        hora = _normalize_hora_text(candidate)
        if hora:
            return hora
    return None


def _row_fecha_display(row: dict) -> str:
    fecha_obj = row.get("fecha_obj")
    hora_text = _row_hora_text(row)
    if isinstance(fecha_obj, datetime):
        base = fecha_obj.strftime("%Y-%m-%d")
        if fecha_obj.hour or fecha_obj.minute or fecha_obj.second:
            return f"{base} {fecha_obj.strftime('%H:%M')}"
        hora_norm = hora_text
        if hora_norm:
            return f"{base} {hora_norm}"
        return base

    base_fecha = _row_fecha_text(row) or ""
    if not base_fecha:
        return ""

    if not hora_text:
        fec_raw = row.get("fecEmi")
        if isinstance(fec_raw, str) and (" " in fec_raw or "T" in fec_raw):
            maybe_time = fec_raw.replace("T", " ").split(" ", 1)
            if len(maybe_time) > 1:
                hora_text = _normalize_hora_text(maybe_time[1])

    hora_norm = _normalize_hora_text(hora_text)
    if hora_norm:
        # Evita duplicar si la fecha ya trae hora
        if " " in base_fecha:
            return base_fecha
        return f"{base_fecha} {hora_norm}"
    return base_fecha


def _fecha_hora_for_order(row: dict, fecha_obj: datetime | None, hora_text: str | None) -> datetime | None:
    if isinstance(fecha_obj, datetime):
        if fecha_obj.hour or fecha_obj.minute or fecha_obj.second:
            return fecha_obj
        fecha_base = fecha_obj.date()
    else:
        parsed = _parse_fecha(row.get("fecEmi"))
        if not parsed:
            return None
        fecha_base = parsed.date()

    if hora_text:
        for fmt in ("%H:%M:%S", "%H:%M"):
            try:
                hora_val = datetime.strptime(hora_text, fmt).time()
                return datetime.combine(fecha_base, hora_val)
            except ValueError:
                continue
    return datetime.combine(fecha_base, time.min)


def _format_fecha_hora_preview(fecha_obj: datetime | None, row: dict) -> str:
    """Devuelve fecha DD/MM/YYYY con hora:min si existe, para la UI de declaración."""

    base_fecha = None
    if isinstance(fecha_obj, datetime):
        base_fecha = fecha_obj.strftime("%d/%m/%Y")
    else:
        raw_fecha = _row_fecha_text(row)
        if raw_fecha:
            try:
                parsed = _parse_fecha(raw_fecha)
                base_fecha = parsed.strftime("%d/%m/%Y") if parsed else None
            except Exception:
                base_fecha = None
            if base_fecha is None:
                base_fecha = raw_fecha

    hora_text = _row_hora_text(row)
    if hora_text:
        if base_fecha:
            return f"{base_fecha} {hora_text}"
        return hora_text
    return base_fecha or ""


def _cliente_nombre(row: dict) -> str:
    nombre = row.get("cliente_nombre") or row.get("cliente")
    if not nombre:
        return ""
    return str(nombre).strip()


def _dedup_priority(row: dict, order: int) -> tuple:
    estado_envio_norm = normalize_estado(row.get("estado_envio"))
    estado_manual_norm = normalize_estado(row.get("estado_manual"))
    sello_flag = 1 if isinstance(row.get("sello_recepcion"), str) and row.get("sello_recepcion").strip() else 0
    fuente_flag = 1 if str(row.get("estado_fuente") or "").strip().lower() == "db" else 0
    json_flag = 1 if row.get("json_path") else 0
    fecha_obj = row.get("fecha_obj")
    fecha_ts = fecha_obj.timestamp() if isinstance(fecha_obj, datetime) else 0.0
    return (
        1 if estado_envio_norm in ENVIADO_ESTADOS else 0,
        1 if estado_manual_norm in ENVIADO_ESTADOS else 0,
        1 if estado_envio_norm in APTOS else 0,
        sello_flag,
        fuente_flag,
        json_flag,
        fecha_ts,
        -order,
    )


def _deduplicate_rows(
    rows: list[dict],
    key_builder: Callable[[dict], tuple | None],
) -> tuple[list[dict], list[dict]]:
    if not rows:
        return [], []

    uniques: list[dict] = []
    duplicates: list[dict] = []
    selected: dict[tuple[str, str, str], tuple[int, tuple, dict]] = {}

    for order, row in enumerate(rows):
        key = key_builder(row)
        if key is None:
            uniques.append(row)
            continue

        priority = _dedup_priority(row, order)
        existing = selected.get(key)
        if existing is None:
            selected[key] = (len(uniques), priority, row)
            uniques.append(row)
            continue

        existing_index, existing_priority, existing_row = existing
        if priority > existing_priority:
            duplicates.append(existing_row)
            selected[key] = (existing_index, priority, row)
            uniques[existing_index] = row
        else:
            duplicates.append(row)

    return uniques, duplicates


def _deduplicate_facturacion_rows(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    def _key(row: dict) -> tuple | None:
        codigo = _ensure_field(row, "codigo_generacion", _codigo_generacion)
        fecha = _row_fecha_text(row)
        cliente = _cliente_nombre(row)
        if not codigo or not fecha or not cliente:
            return None
        return (str(codigo).upper(), fecha, cliente.lower())

    return _deduplicate_rows(rows, _key)


def _deduplicate_correlativo_rows(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    def _key(row: dict) -> tuple | None:
        tipo = row.get("tipo")
        numero = _ensure_field(row, "numero_control", _numero_control)
        if not tipo or not numero:
            return None
        return (str(tipo).strip().lower(), str(numero).strip().upper())

    return _deduplicate_rows(rows, _key)


def _normalize_alias(texto: str | None) -> str | None:
    if not texto:
        return None
    t = str(texto).lower().strip()
    if not t:
        return None
    t = t.replace("-", " ").replace("_", " ")
    t = "".join(ch for ch in t if ch.isalnum() or ch.isspace())
    t = " ".join(t.split())
    code = _TIPO_HINT_ALIASES.get(t)
    if code in CAT002_VALID:
        return code
    return None


def _infer_tipo_from_text(value: Any) -> str | None:
    if value is None:
        return None
    try:
        texto = str(value).strip()
    except Exception:
        return None
    if not texto:
        return None
    for match in _TIPO_TOKEN_PATTERN.finditer(texto):
        candidate = match.group(1).zfill(2)
        if candidate in CAT002_VALID:
            return candidate
    return None


def _infer_tipo_from_path(path: str | None) -> str | None:
    if not path or not isinstance(path, str):
        return None
    base_name = os.path.basename(path)
    tipo_label = infer_tipo_from_name(base_name)
    if tipo_label:
        code = tipo_code_from_desc(tipo_label)
        if code in CAT002_VALID:
            return code
    segments = re.split(r"[\\/]+", path)
    for segment in reversed(segments):
        segment = segment.strip()
        if not segment:
            continue
        alias_code = _normalize_alias(segment)
        if alias_code:
            return alias_code
        label_code = tipo_code_from_desc(segment)
        if label_code in CAT002_VALID:
            return label_code
        inferred = _infer_tipo_from_text(segment)
        if inferred:
            return inferred
    return None


def _collect_type_hints(row: dict) -> list[str]:
    hints: list[str] = []

    def _append(value: Any) -> None:
        if value is None:
            return
        texto = str(value).strip()
        if texto:
            hints.append(texto)

    hint_keys = [
        "tipo_hint",
        "tipo_nombre",
        "tipo_label",
        "tipo_desc",
        "tipoDescripcion",
        "tipoDescripcionDocumento",
        "tipoDocumentoNombre",
        "tipoDocumentoDescripcion",
        "tipo_documento_nombre",
        "tipo_documento_desc",
        "tipo",
        "tipo_doc",
        "tipo_documento",
        "tipo_dte",
    ]

    sources: list[Any] = [row]
    extra = row.get("extra_data") if isinstance(row, dict) else None
    if isinstance(extra, dict):
        sources.append(extra)
        documento = extra.get("documento")
        if isinstance(documento, dict):
            sources.append(documento)
            ident_doc = documento.get("identificacion")
            if isinstance(ident_doc, dict):
                sources.append(ident_doc)
    envio = row.get("envio") if isinstance(row, dict) else None
    if isinstance(envio, dict):
        sources.append(envio)
    dte_json = row.get("dte_json") if isinstance(row, dict) else None
    if isinstance(dte_json, dict):
        sources.append(dte_json)
        identificacion = dte_json.get("identificacion")
        if isinstance(identificacion, dict):
            sources.append(identificacion)

    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in hint_keys:
            _append(source.get(key))

    return hints


def _try_all_known_fields(row: dict) -> str | None:
    def _sanitize(value: Any) -> str | None:
        if value is None:
            return None
        texto = str(value).strip()
        if not texto:
            return None
        if texto.isdigit() and len(texto) == 1:
            return f"0{texto}"
        return texto

    dte_json = row.get("dte_json") or {}
    identificacion = dte_json.get("identificacion") or {}
    candidatos = [
        row.get("tipo"),
        row.get("tipo_dte"),
        identificacion.get("tipoDte"),
        identificacion.get("tipoDocumento"),
        dte_json.get("tipoDte"),
        dte_json.get("tipoDocumento"),
    ]

    extra = row.get("extra_data") or {}
    if isinstance(extra, dict):
        candidatos.extend(
            [
                extra.get("tipoDte"),
                extra.get("tipoDocumento"),
                extra.get("tipo_dte"),
                extra.get("tipo"),
                extra.get("tipo_doc"),
                extra.get("tipo_documento"),
            ]
        )
        documento = extra.get("documento")
        if isinstance(documento, dict):
            ident_doc = documento.get("identificacion")
            if isinstance(ident_doc, dict):
                candidatos.extend(
                    [
                        ident_doc.get("tipoDte"),
                        ident_doc.get("tipoDocumento"),
                    ]
                )

    envio = row.get("envio") or {}
    if isinstance(envio, dict):
        candidatos.extend(
            [
                envio.get("tipoDte"),
                envio.get("tipoDocumento"),
                envio.get("tipo"),
                envio.get("tipo_dte"),
            ]
        )

    primer_no_vacio: str | None = None
    for candidato in candidatos:
        texto = _sanitize(candidato)
        if not texto:
            continue
        if texto in CAT002_VALID:
            return texto
        if primer_no_vacio is None:
            primer_no_vacio = texto
    return primer_no_vacio


def _validate_periodo(periodo_yyyymm: str) -> str:
    texto = str(periodo_yyyymm).strip()
    if len(texto) != 6 or not texto.isdigit():
        raise ValueError("El período debe tener formato YYYYMM.")
    anio = int(texto[:4])
    mes = int(texto[4:])
    if mes < 1 or mes > 12:
        raise ValueError("El período debe tener un mes válido (01-12).")
    if anio < 2000:
        raise ValueError("El período debe tener un año válido.")
    return texto


def _parse_fecha(value: Any) -> datetime | None:
    if not value:
        return None
    texto = str(value).strip()
    if not texto:
        return None
    formatos = ["%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d", "%Y%m%d"]
    for formato in formatos:
        try:
            return datetime.strptime(texto[:10], formato)
        except ValueError:
            continue
    return None


def _load_json(candidate: Any) -> Any:
    if isinstance(candidate, dict):
        return candidate
    if isinstance(candidate, str) and candidate.strip():
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            return None
    return None


def _to_decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal("0")
    texto = str(value).strip()
    if not texto:
        return Decimal("0")
    texto = texto.replace(",", ".")
    try:
        return Decimal(texto)
    except Exception:
        return Decimal("0")


def _decimal_text(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}"


def _extract_cliente(row: dict) -> dict:
    cliente = {
        "nombre": row.get("cliente_nombre"),
        "nit": row.get("cliente_nit"),
        "nrc": row.get("cliente_nrc"),
        "dui": row.get("cliente_dui"),
    }
    extra = row.get("dte_json", {}).get("receptor") or {}
    if extra:
        cliente = {
            "nombre": extra.get("nombre") or cliente.get("nombre"),
            "nit": extra.get("nit") or extra.get("numDocumento") or cliente.get("nit"),
            "nrc": extra.get("nrc") or cliente.get("nrc"),
            "dui": extra.get("dui") or extra.get("numDocumento", cliente.get("dui")),
        }
    return cliente


def _extract_resumen(row: dict) -> dict:
    dte_json = row.get("dte_json") or {}
    resumen = dte_json.get("resumen") or {}
    if not resumen:
        extra = row.get("extra_data") or {}
        resumen = extra.get("resumen") or {}
    return resumen or {}


def _codigo_generacion(row: dict) -> str | None:
    codigo = (row.get("envio") or {}).get("codigo_generacion")
    if not codigo:
        dte_json = row.get("dte_json") or {}
        codigo = dte_json.get("identificacion", {}).get("codigoGeneracion")
    if not codigo:
        extra = row.get("extra_data") or {}
        codigo = extra.get("codigoGeneracion") or extra.get("codigo_generacion")
    if not codigo:
        return None
    codigo = str(codigo).strip()
    return codigo.upper() or None


def _numero_control(row: dict) -> str | None:
    numero = (row.get("envio") or {}).get("numero_control")
    if not numero:
        dte_json = row.get("dte_json") or {}
        numero = dte_json.get("identificacion", {}).get("numeroControl")
    if not numero:
        extra = row.get("extra_data") or {}
        numero = extra.get("numeroControl")
    if not numero:
        return None
    numero = str(numero).strip()
    return numero or None


def _fecha_emision(row: dict) -> tuple[str | None, datetime | None]:
    dte_json = row.get("dte_json") or {}
    identificacion = dte_json.get("identificacion") or {}
    fec = identificacion.get("fecEmi") or row.get("fecEmi")
    if not fec:
        fec = (row.get("fecha_venta") or "")[:10]
    parsed = _parse_fecha(fec)
    return (str(fec).strip() if fec else None, parsed)


def _tipo_dte(row: dict) -> str | None:
    """Obtener el tipo de DTE usando varias fuentes conocidas."""

    code = _try_all_known_fields(row)
    if code and code in CAT002_VALID:
        return code

    if isinstance(code, str):
        inferred = _infer_tipo_from_text(code)
        if inferred:
            return inferred

    numero_control = row.get("numero_control")
    if numero_control:
        inferred = _infer_tipo_from_text(numero_control)
        if inferred:
            return inferred

    path = row.get("json_path") or (row.get("extra_data") or {}).get("jsonPath")
    inferred = _infer_tipo_from_path(path)
    if inferred:
        return inferred

    for texto in _collect_type_hints(row):
        alias_code = _normalize_alias(texto)
        if alias_code:
            return alias_code
        inferred = _infer_tipo_from_text(texto)
        if inferred:
            return inferred

    return None


def _estado_base(row: dict) -> tuple[str | None, str | None]:
    envio = row.get("envio") or {}
    base = envio.get("estado_ui_tag") or envio.get("estado_ui") or row.get("estado_display")
    manual = None
    if envio.get("estado_ui_manual"):
        manual = (
            envio.get("estado_manual")
            or envio.get("estado_manual_text")
            or envio.get("estado_ui")
            or envio.get("estado_ui_tag")
        )
    return base, manual


def _tipo_operacion(row: dict) -> str:
    identificacion = row.get("dte_json", {}).get("identificacion") or {}
    tipo = identificacion.get("tipoOperacion")
    if tipo is None:
        tipo = row.get("extra_data", {}).get("tipoOperacion")
    return str(tipo).strip() if tipo is not None else "0"


def _tipo_ingreso(row: dict) -> str:
    identificacion = row.get("dte_json", {}).get("identificacion") or {}
    tipo = identificacion.get("tipoModelo")
    if tipo is None:
        tipo = row.get("extra_data", {}).get("tipoModelo")
    return str(tipo).strip() if tipo is not None else "0"


def _sello_recepcion(row: dict) -> str | None:
    envio = row.get("envio") or {}
    respuesta = envio.get("respuesta_json")
    if isinstance(respuesta, dict):
        sello = respuesta.get("selloRecibido") or respuesta.get("sello")
        if sello:
            return str(sello).strip() or None
    extra = row.get("extra_data") or {}
    sello = extra.get("selloRecibido") or extra.get("sello")
    if sello:
        return str(sello).strip() or None
    return None


def _log_summary(
    context: str,
    total: int,
    incluidos: int,
    stats: dict[str, dict[str, int]],
    motivos: dict[str, list[object]],
) -> None:
    excluidos = total - incluidos
    motivos_resumen = ", ".join(
        f"{motivo}={len(ejemplos)}" for motivo, ejemplos in motivos.items() if ejemplos
    )
    if motivos_resumen:
        logger.info(
            "%s - total_leidos=%s incluidos=%s excluidos=%s motivos=[%s]",
            context,
            total,
            incluidos,
            excluidos,
            motivos_resumen,
        )
    else:
        logger.info(
            "%s - total_leidos=%s incluidos=%s excluidos=%s",
            context,
            total,
            incluidos,
            excluidos,
        )
    if stats:
        for tipo in sorted(stats):
            datos = stats[tipo]
            logger.info(
                "%s - tipo %s -> incluidos=%s excluidos=%s",
                context,
                tipo,
                datos.get("incluidos", 0),
                datos.get("excluidos", 0),
            )
    for motivo, ejemplos in motivos.items():
        muestras = []
        for ejemplo in ejemplos[:3]:
            if isinstance(ejemplo, PreviewExclusionEntry):
                descripcion = ejemplo.describe()
            else:
                descripcion = str(ejemplo)
            if descripcion:
                muestras.append(descripcion)
        extra = f" ejemplos: {' | '.join(muestras)}" if muestras else ""
        logger.info(
            "%s - descartados_%s=%s%s",
            context,
            motivo,
            len(ejemplos),
            extra,
        )


def _log_preview_rows(rows: list[dict], label: str, limit: int = 50) -> None:
    """Registrar los datos básicos de las filas consideradas para anexos."""

    try:
        logger.info("%s: filas=%s", label, len(rows))
        for idx, row in enumerate(rows[:limit]):
            codigo = row.get("codigo_generacion") or row.get("codigo")
            numero = row.get("numero_control")
            tipo = row.get("tipo")
            fecha_display = row.get("fecha_display") or _row_fecha_display(row)
            hora = _row_hora_text(row) or row.get("horEmi")
            estado = row.get("estado_envio") or row.get("envio")
            fuente = row.get("estado_fuente")
            logger.info(
                "%s [%s] tipo=%s fecha=%s hora=%s codigo=%s numero=%s estado=%s fuente=%s json=%s",
                label,
                idx + 1,
                tipo,
                fecha_display,
                hora,
                codigo,
                numero,
                estado,
                fuente,
                row.get("json_path") or row.get("json"),
            )
    except Exception:
        logger.exception("No se pudieron registrar filas para %s", label)


def get_facturacion_rows(db, periodo_yyyymm: str) -> list[dict]:
    """Compatibilidad: devuelve únicamente las filas de facturación."""

    dataset = collect_facturacion_dataset(db, periodo_yyyymm)
    return dataset.rows


def normalize_estado(value: str | None) -> str | None:
    if not value:
        return None
    texto = str(value).strip().lower()
    if not texto:
        return None
    texto = texto.translate(_ACCENT_TRANSLATION)
    texto = " ".join(texto.split())
    return ALIASES.get(texto, texto)


def estado_apto(value: str | None, override_manual: str | None = None) -> bool:
    override = normalize_estado(override_manual)
    if override and override in APTOS:
        return True
    base = normalize_estado(value)
    if base and base in APTOS:
        return True
    return False


def estado_enviado(base: str | None, override_manual: str | None = None) -> bool:
    override = normalize_estado(override_manual)
    if override and override in ENVIADO_ESTADOS:
        return True
    base_norm = normalize_estado(base)
    if base_norm and base_norm in ENVIADO_ESTADOS:
        return True
    return False


def _iter_estado_variants(value: str) -> tuple[str, ...]:
    texto = str(value or "").strip()
    if not texto:
        return ()
    segmentos = re.split(r"[|/]", texto)
    candidatos: list[str] = []
    vistos: set[str] = set()
    for segmento in segmentos if segmentos else (texto,):
        base = segmento.strip()
        if not base:
            continue
        for separador in ("(", "-", "\u2014", ":", "["):
            if separador in base:
                base = base.split(separador, 1)[0].strip()
        for candidato in (segmento.strip(), base):
            if not candidato:
                continue
            normalizado = " ".join(candidato.split())
            if normalizado and normalizado not in vistos:
                vistos.add(normalizado)
                candidatos.append(normalizado)
    return tuple(candidatos)


def _estado_en_estados(value: object, estados: set[str]) -> bool:
    if not value:
        return False
    if isinstance(value, str):
        for variante in _iter_estado_variants(value):
            estado = normalize_estado(variante)
            if estado and estado in estados:
                return True
    return False


def _row_es_anulado(row: dict, base: str | None, manual: str | None) -> bool:
    if _estado_en_estados(base, ANULADO_ESTADOS):
        return True
    if _estado_en_estados(manual, ANULADO_ESTADOS):
        return True
    candidatos = [
        row.get("estado_documento"),
        row.get("estado_display"),
        row.get("estado"),
        row.get("estado_envio"),
        row.get("estado_manual"),
        row.get("estado_manual_text"),
    ]
    for valor in candidatos:
        if _estado_en_estados(valor, ANULADO_ESTADOS):
            return True
    envio_info = row.get("envio")
    if isinstance(envio_info, dict):
        for clave in ("estado", "estado_ui", "estado_ui_tag", "estado_manual", "estado_manual_text"):
            if _estado_en_estados(envio_info.get(clave), ANULADO_ESTADOS):
                return True
        respuesta = envio_info.get("respuesta_json")
        if isinstance(respuesta, dict):
            for dato in respuesta.values():
                if _estado_en_estados(dato, ANULADO_ESTADOS):
                    return True
    return False


def _choose_envio_state(auto_state: str | None, manual_state: str | None) -> tuple[str | None, bool]:
    auto_norm = normalize_estado(auto_state)
    manual_norm = normalize_estado(manual_state)
    if manual_norm and manual_norm in ENVIADO_ESTADOS:
        return manual_state, True
    return auto_state, False


def _envio_display_apto(value: str | None) -> str | None:
    if not value:
        return None
    texto = str(value)
    segmentos = [segment.strip() for segment in texto.split("|") if segment.strip()]
    if not segmentos:
        segmentos = [texto.strip()]

    def _normalize_segment(segment: str) -> str:
        base = segment.strip()
        if not base:
            return ""
        for sep in ("(", "-", "\u2014", ":", "["):
            if sep in base:
                base = base.split(sep, 1)[0].strip()
        return base

    for segmento in segmentos:
        base = _normalize_segment(segmento)
        base_norm = normalize_estado(base)
        if base_norm and base_norm in ENVIADO_ESTADOS:
            return segmento
        lowered = base.lower()
        if lowered.startswith(("enviado", "aceptado", "recibido")):
            return segmento

    texto_lower = texto.strip().lower()
    if texto_lower.startswith(("enviado", "aceptado", "recibido")):
        return texto.strip()
    return None


def _extract_envio_state_from_payload(payload: dict | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    stack: list[tuple[dict, str | None]] = [(payload, None)]
    visited: set[int] = set()
    while stack:
        current, parent_key = stack.pop()
        ident = id(current)
        if ident in visited:
            continue
        visited.add(ident)
        for key, value in current.items():
            if isinstance(value, str):
                lowered_key = key.lower()
                texto = value.strip()
                if not texto:
                    continue
                if lowered_key in _ESTADO_FIELD_KEYS:
                    return texto
                if lowered_key == "descripcion" and parent_key:
                    parent_lower = parent_key.lower()
                    if "respuesta" in parent_lower or "estado" in parent_lower:
                        return texto
                if lowered_key == "resultado" and parent_key and "respuesta" in parent_key.lower():
                    return texto
            elif isinstance(value, dict):
                stack.append((value, key))
    return None


def _row_enviado(row: dict, base: str | None, manual: str | None) -> bool:
    """Determina si un registro debe considerarse enviado/apto para anexos."""

    override_info = row.get("_envio_override") or {}
    if isinstance(override_info, dict) and override_info.get("manual"):
        logger.info(
            "row_enviado: override manual aplicado código=%s estado=%s",
            row.get("codigo_generacion"),
            row.get("estado_envio"),
        )

    envio_display = _envio_display_apto(row.get("estado_envio"))
    if envio_display:
        return True

    sello = row.get("sello_recepcion")
    if isinstance(sello, str) and sello.strip():
        envio_text = str(row.get("estado_envio") or "").strip().lower()
        estado_text = str(row.get("estado") or "").strip().lower()
        if envio_text.startswith("pendiente") or estado_text.startswith("pendiente"):
            return False
        return True

    return False


def _safe_load_json(path: Path | str | None) -> dict | None:
    if not path:
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


_ANULACION_ESTADO_DETALLE = {
    1: "D",  # Invalidado
    2: "A",  # Anulado
    3: "X",  # Extraviado
}

_ANULACION_ESTADOS_VALIDOS = {"aceptado", "recibido"}


def _map_tipo_anulacion(raw: Any) -> str | None:
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return _ANULACION_ESTADO_DETALLE.get(value)


def _montos_anexo_i(row: dict) -> dict:
    resumen = _extract_resumen(row)
    exentas = _to_decimal(resumen.get("totalExenta"))
    no_sujetas = _to_decimal(resumen.get("totalNoSuj"))
    gravadas = _to_decimal(resumen.get("totalGravada"))
    debito = _to_decimal(resumen.get("totalIva"))
    if debito == Decimal("0"):
        tributos = resumen.get("tributos") or []
        total_tributos = sum((_to_decimal(item.get("valor")) for item in tributos), Decimal("0"))
        debito = total_tributos
    terceros = _to_decimal(resumen.get("ventasTerceros"))
    debito_terceros = _to_decimal(resumen.get("debitoTerceros"))
    total = _to_decimal(resumen.get("totalPagar") or resumen.get("montoTotalOperacion"))
    subtotal = exentas + no_sujetas + gravadas + terceros + debito_terceros
    if total and subtotal != total:
        gravadas += total - subtotal
        subtotal = exentas + no_sujetas + gravadas + terceros + debito_terceros
    return {
        "ventas_exentas": _decimal_text(exentas),
        "ventas_no_sujetas": _decimal_text(no_sujetas),
        "ventas_gravadas_locales": _decimal_text(gravadas),
        "debito_fiscal": _decimal_text(debito),
        "ventas_terceros_no_domiciliados": _decimal_text(terceros),
        "debito_terceros": _decimal_text(debito_terceros),
        "total_ventas": _decimal_text(total or subtotal),
    }


def _montos_anexo_ii_values(row: dict) -> dict[str, Decimal]:
    resumen = _extract_resumen(row)
    exentas = _to_decimal(resumen.get("totalExenta"))
    no_sujetas = _to_decimal(resumen.get("totalNoSuj"))
    gravadas = _to_decimal(resumen.get("totalGravada"))
    total = _to_decimal(resumen.get("totalPagar") or resumen.get("montoTotalOperacion"))
    subtotal = exentas + no_sujetas + gravadas
    if total and subtotal != total:
        gravadas += total - subtotal
        subtotal = exentas + no_sujetas + gravadas
    total_ventas = total or subtotal
    return {
        "ventas_exentas": exentas,
        "internas_exentas_ns": Decimal("0.00"),
        "ventas_no_sujetas": no_sujetas,
        "ventas_gravadas_locales": gravadas,
        "exp_ca": Decimal("0.00"),
        "exp_fuera_ca": Decimal("0.00"),
        "exp_servicios": Decimal("0.00"),
        "zonas_francas_dpa": Decimal("0.00"),
        "terceros_no_domic": Decimal("0.00"),
        "total_ventas": total_ventas,
    }


def _montos_anexo_ii(row: dict) -> dict:
    valores = _montos_anexo_ii_values(row)
    return {clave: _decimal_text(valor) for clave, valor in valores.items()}


def _identificacion_anexo_i(row: dict) -> tuple[str | None, str | None, str]:
    cliente = _extract_cliente(row)
    dui = cliente.get("dui")
    if dui:
        dui_digitos = "".join(ch for ch in str(dui) if ch.isdigit())
        fecha_obj = row.get("fecha_obj")
        if (
            dui_digitos
            and len(dui_digitos) == 9
            and isinstance(fecha_obj, datetime)
            and (fecha_obj.year, fecha_obj.month) >= (2022, 1)
        ):
            return None, dui_digitos, cliente.get("nombre") or ""
    nit = cliente.get("nit")
    nrc = cliente.get("nrc")
    identificacion = None
    if nit:
        identificacion = str(nit).replace("-", "").strip()
    elif nrc:
        identificacion = str(nrc).replace("-", "").strip()
    return identificacion or None, None, cliente.get("nombre") or ""


def _merge_dataset_discards(
    dataset: FacturacionDataset,
    tipos: set[str],
    stats: dict[str, dict[str, int]],
    excluidos: defaultdict[str, list[PreviewExclusionEntry]],
) -> int:
    extras = 0
    for motivo in ("sin_fecha", "fuera_de_periodo"):
        for entry in dataset.descartes.get(motivo, []):
            tipo = entry.tipo
            if tipo and tipo not in tipos:
                continue
            excluidos[motivo].append(entry)
            if tipo and tipo in tipos:
                stats[tipo]["excluidos"] += 1
            extras += 1
    return extras


def _preview_tipo_label(row: dict) -> tuple[str, str | None]:
    raw_tipo = row.get("tipo")
    tipo_codigo: str | None = None
    if raw_tipo is not None:
        raw_texto = str(raw_tipo).strip()
        if raw_texto:
            tipo_codigo = raw_texto.zfill(2) if raw_texto.isdigit() else raw_texto

    display_source = row.get("tipo_desc") or tipo_codigo or raw_tipo
    display = short_tipo_label(display_source)
    if not display:
        display = str(display_source or "").strip()
    return display, tipo_codigo


def _build_preview_row_anexo_i(
    row: dict, codigo: str, base: str | None, manual: str | None
) -> PreviewRow:
    fecha_obj = row.get("fecha_obj") if isinstance(row.get("fecha_obj"), datetime) else None
    fecha_texto = _row_fecha_display(row)
    numero_control = row.get("numero_control")
    if numero_control:
        numero_control = str(numero_control).strip() or None
    sello = row.get("sello_recepcion")
    if sello:
        sello = str(sello).strip() or None
    cliente = _extract_cliente(row)
    tipo_display, tipo_codigo = _preview_tipo_label(row)
    identificacion, dui, nombre_identificado = _identificacion_anexo_i(row)
    cliente_nombre = nombre_identificado or cliente.get("nombre") or ""
    identificacion_cliente = identificacion or dui or None
    montos = _montos_anexo_i(row)
    estado_base_norm = normalize_estado(base)
    estado_manual_norm = normalize_estado(manual)
    override = bool(
        estado_manual_norm
        and estado_manual_norm in APTOS
        and (not estado_base_norm or estado_base_norm not in APTOS)
    )
    estado_fuente = "db" if row.get("envio") else "extra"
    totales = {
        "exentas": montos["ventas_exentas"],
        "no_sujetas": montos["ventas_no_sujetas"],
        "gravadas": montos["ventas_gravadas_locales"],
        "debito": montos["debito_fiscal"],
        "total": montos["total_ventas"],
    }
    return PreviewRow(
        fecha=fecha_texto,
        fecha_obj=fecha_obj,
        tipo=tipo_display,
        tipo_codigo=tipo_codigo,
        codigo_generacion=codigo,
        numero_control=numero_control,
        cliente=cliente_nombre,
        identificacion=identificacion_cliente,
        estado_base=estado_base_norm,
        estado_manual=estado_manual_norm,
        estado_override=override,
        estado_fuente=estado_fuente,
        sello_recepcion=sello,
        totales=totales,
        venta_id=row.get("venta_id"),
    )


def _build_preview_row_anexo_ii(
    row: dict, codigo: str, base: str | None, manual: str | None
) -> PreviewRow:
    fecha_obj = row.get("fecha_obj") if isinstance(row.get("fecha_obj"), datetime) else None
    fecha_texto = _row_fecha_display(row)
    numero_control = row.get("numero_control")
    if numero_control:
        numero_control = str(numero_control).strip() or None
    sello = row.get("sello_recepcion")
    if sello:
        sello = str(sello).strip() or None
    cliente_nombre = _extract_cliente(row).get("nombre") or ""
    montos = _montos_anexo_ii(row)
    tipo_display, tipo_codigo = _preview_tipo_label(row)
    estado_base_norm = normalize_estado(base)
    estado_manual_norm = normalize_estado(manual)
    override = bool(
        estado_manual_norm
        and estado_manual_norm in APTOS
        and (not estado_base_norm or estado_base_norm not in APTOS)
    )
    estado_fuente = "db" if row.get("envio") else "extra"
    totales = {
        "exentas": montos["ventas_exentas"],
        "no_sujetas": montos["ventas_no_sujetas"],
        "gravadas": montos["ventas_gravadas_locales"],
        "total": montos["total_ventas"],
    }
    return PreviewRow(
        fecha=fecha_texto,
        fecha_obj=fecha_obj,
        tipo=tipo_display,
        tipo_codigo=tipo_codigo,
        codigo_generacion=codigo,
        numero_control=numero_control,
        cliente=cliente_nombre,
        identificacion=None,
        estado_base=estado_base_norm,
        estado_manual=estado_manual_norm,
        estado_override=override,
        estado_fuente=estado_fuente,
        sello_recepcion=sello,
        totales=totales,
        venta_id=row.get("venta_id"),
    )


def _build_preview(
    dataset: FacturacionDataset,
    tipos: set[str],
    *,
    anexo: str,
) -> AnexoPreviewData:
    seen: set[str] = set()
    stats: defaultdict[str, dict[str, int]] = defaultdict(lambda: {"incluidos": 0, "excluidos": 0})
    excluidos: defaultdict[str, list[PreviewExclusionEntry]] = defaultdict(list)
    incluidos: list[PreviewRow] = []
    candidatos = 0

    for row in dataset.rows:
        tipo = row.get("tipo")
        if tipo not in tipos:
            continue
        candidatos += 1
        stats[tipo]
        codigo = _ensure_field(row, "codigo_generacion", _codigo_generacion)
        if not codigo:
            stats[tipo]["excluidos"] += 1
            excluidos["sin_codigo"].append(
                _make_exclusion_entry(row, detalle="sin código", fecha=_row_fecha_text(row))
            )
            continue
        codigo = str(codigo)
        if codigo in seen:
            stats[tipo]["excluidos"] += 1
            excluidos["duplicado"].append(
                _make_exclusion_entry(row, detalle="duplicado", fecha=_row_fecha_text(row))
            )
            continue
        base, manual = _estado_base(row)
        if not _row_enviado(row, base, manual):
            stats[tipo]["excluidos"] += 1
            descripcion = normalize_estado(manual) or normalize_estado(base) or "no_enviado"
            excluidos["no_enviado"].append(
                _make_exclusion_entry(row, detalle=descripcion, fecha=_row_fecha_text(row))
            )
            continue
        fecha_obj = row.get("fecha_obj")
        if not isinstance(fecha_obj, datetime):
            stats[tipo]["excluidos"] += 1
            excluidos["sin_fecha"].append(
                _make_exclusion_entry(row, detalle="sin fecha", fecha=_row_fecha_text(row))
            )
            continue

        _ensure_field(row, "numero_control", _numero_control)
        _ensure_field(row, "sello_recepcion", _sello_recepcion)

        if anexo == "I":
            preview_row = _build_preview_row_anexo_i(row, codigo, base, manual)
        else:
            preview_row = _build_preview_row_anexo_ii(row, codigo, base, manual)
        incluidos.append(preview_row)
        seen.add(codigo)
        stats[tipo]["incluidos"] += 1

    candidatos += _merge_dataset_discards(dataset, tipos, stats, excluidos)
    incluidos.sort(key=lambda registro: registro.sort_key())

    conteos: dict[str, dict[str, int]] = {}
    for tipo in sorted(tipos):
        datos = stats.get(tipo, {"incluidos": 0, "excluidos": 0})
        conteos[tipo] = {
            "incluidos": datos.get("incluidos", 0),
            "excluidos": datos.get("excluidos", 0),
        }

    for motivo in EXCLUSION_MOTIVOS:
        excluidos.setdefault(motivo, [])

    return AnexoPreviewData(
        candidatos=candidatos,
        incluidos=incluidos,
        excluidos={motivo: excluidos[motivo] for motivo in EXCLUSION_MOTIVOS},
        conteos_por_tipo=conteos,
    )


def build_anexo_i_preview(dataset: FacturacionDataset) -> AnexoPreviewData:
    return _build_preview(dataset, TIPOS_ANEXO_I, anexo="I")


def build_anexo_ii_preview(dataset: FacturacionDataset) -> AnexoPreviewData:
    return _build_preview(dataset, TIPOS_ANEXO_II, anexo="II")


def get_declaracion_preview(db, periodo_yyyymm: str) -> DeclaracionPreview:
    dataset = collect_facturacion_dataset(db, periodo_yyyymm)
    periodo = _validate_periodo(periodo_yyyymm)
    _log_preview_rows(dataset.rows, f"Declaración dataset {periodo}")
    return DeclaracionPreview(
        periodo=periodo,
        anexo_i=build_anexo_i_preview(dataset),
        anexo_ii=build_anexo_ii_preview(dataset),
    )


def build_anexo_i_contribuyentes(rows: list[dict], db) -> list[VentaContribuyente]:
    registros: list[VentaContribuyente] = []
    seen: set[str] = set()
    stats = defaultdict(lambda: {"incluidos": 0, "excluidos": 0})
    motivos = defaultdict(list)
    total_considerados = 0

    for row in rows:
        tipo = row.get("tipo")
        if tipo not in TIPOS_ANEXO_I:
            continue
        total_considerados += 1
        stats[tipo]
        codigo = row.get("codigo_generacion") or _codigo_generacion(row)
        if not codigo:
            stats[tipo]["excluidos"] += 1
            motivos["sin_codigo"].append(f"venta {row.get('venta_id')}")
            continue
        if codigo in seen:
            stats[tipo]["excluidos"] += 1
            motivos["duplicado"].append(codigo)
            continue
        base, manual = _estado_base(row)
        if _row_es_anulado(row, base, manual):
            stats[tipo]["excluidos"] += 1
            motivos["anulado"].append(
                _make_exclusion_entry(row, detalle="estado anulado")
            )
            seen.add(codigo)
            continue
        enviado = _row_enviado(row, base, manual)
        if not enviado:
            stats[tipo]["excluidos"] += 1
            descripcion = normalize_estado(manual) or normalize_estado(base) or "no_enviado"
            motivos["no_enviado"].append(f"{codigo}:{descripcion}")
            continue
        _, fecha_obj = _fecha_emision(row)
        if not fecha_obj:
            stats[tipo]["excluidos"] += 1
            motivos["sin_fecha"].append(f"{codigo}")
            continue

        hora_text = _row_hora_text(row)
        fecha_display = _format_fecha_hora_preview(fecha_obj, row)

        montos = _montos_anexo_i(row)
        identificacion, dui, nombre = _identificacion_anexo_i(row)
        numero_control = row.get("numero_control") or _numero_control(row)
        try:
            tipo_operacion_val = _tipo_operacion(row)
            tipo_ingreso_val = _tipo_ingreso(row)
            registro = VentaContribuyente(
                fecha_emision=fecha_obj.strftime("%d/%m/%Y"),
                clase=CLASE_POR_TIPO.get(tipo, "4"),
                tipo=tipo,
                numero_control=numero_control,
                codigo_generacion=codigo,
                sello_recepcion=row.get("sello_recepcion") if enviado else None,
                identificacion=identificacion,
                nombre_cliente=nombre,
                dui=dui,
                tipo_operacion=tipo_operacion_val,
                tipo_ingreso=tipo_ingreso_val,
                estado=base,
                estado_manual=manual,
                estado_fuente="db" if row.get("envio") else "extra",
                json_path=row.get("json_path"),
            )
        except Exception as exc:
            stats[tipo]["excluidos"] += 1
            motivos["campos_invalidos"].append(
                _make_exclusion_entry(row, detalle=str(exc), fecha=fecha_obj.strftime("%d/%m/%Y"))
            )
            continue
        for clave, valor in montos.items():
            setattr(registro, clave, valor)
        registro.estado_documento = (
            row.get("estado_documento")
            or row.get("estado_display")
            or row.get("estado")
        )
        if isinstance(registro.estado_documento, str):
            registro.estado_documento = registro.estado_documento.strip() or None
        envio_info = row.get("envio") or {}
        envio_display = (
            row.get("estado_envio")
            or format_envio_state(
                (envio_info or {}).get("estado_ui"),
                (envio_info or {}).get("estado_ui_tag"),
                (envio_info or {}).get("estado"),
            )
        )
        if isinstance(envio_display, str):
            envio_display = envio_display.strip()
        if not envio_display:
            envio_display = "Pendiente de envío"
        registro.estado_envio = envio_display
        # Atributos auxiliares para la previsualización (no afectan la exportación).
        try:
            setattr(registro, "fecha_display", fecha_display or registro.fecha_emision)
            setattr(registro, "hora_emision", hora_text)
        except Exception:
            logger.debug("No se pudo adjuntar fecha/hora auxiliar al registro %s", codigo)
        if not hora_text:
            logger.debug(
                "Anexo I sin hora; codigo=%s fecha=%s raw_fec=%s",
                codigo,
                registro.fecha_emision,
                row.get("fecEmi"),
            )
        registros.append(registro)
        seen.add(codigo)
        stats[tipo]["incluidos"] += 1

    _log_summary("Anexo I", total_considerados, len(registros), stats, motivos)
    return registros


def build_anexo_i_consumidor(rows: list[dict], db) -> list[VentaCF]:
    stats = defaultdict(lambda: {"incluidos": 0, "excluidos": 0})
    motivos = defaultdict(list)
    total_considerados = 0
    eventos: list[dict] = []
    seen: set[str] = set()

    for row in rows:
        tipo = row.get("tipo")
        if tipo not in TIPOS_ANEXO_II:
            continue
        total_considerados += 1
        stats[tipo]
        codigo = row.get("codigo_generacion") or _codigo_generacion(row)
        if not codigo:
            stats[tipo]["excluidos"] += 1
            motivos["sin_codigo"].append(f"venta {row.get('venta_id')}")
            continue
        if codigo in seen:
            stats[tipo]["excluidos"] += 1
            motivos["duplicado"].append(codigo)
            continue
        base, manual = _estado_base(row)
        if _row_es_anulado(row, base, manual):
            stats[tipo]["excluidos"] += 1
            motivos["anulado"].append(
                _make_exclusion_entry(row, detalle="estado anulado")
            )
            seen.add(codigo)
            continue
        enviado = _row_enviado(row, base, manual)
        if not enviado:
            stats[tipo]["excluidos"] += 1
            descripcion = normalize_estado(manual) or normalize_estado(base) or "no_enviado"
            motivos["no_enviado"].append(f"{codigo}:{descripcion}")
            continue
        fecha_texto, fecha_obj = _fecha_emision(row)
        if not fecha_obj:
            stats[tipo]["excluidos"] += 1
            motivos["sin_fecha"].append(f"{codigo}")
            continue

        hora_text = _row_hora_text(row)
        fecha_hora = _fecha_hora_for_order(row, fecha_obj, hora_text)
        if not fecha_hora:
            fecha_hora = datetime.combine(fecha_obj.date(), time.min)
            logger.debug("Anexo II: sin hora, se usa 00:00 para %s", codigo)

        numero_control = row.get("numero_control") or _numero_control(row)
        montos = _montos_anexo_ii_values(row)
        envio_info = row.get("envio") or {}
        envio_display = (
            row.get("estado_envio")
            or format_envio_state(
                (envio_info or {}).get("estado_ui"),
                (envio_info or {}).get("estado_ui_tag"),
                (envio_info or {}).get("estado"),
            )
        )
        evento = {
            "tipo": tipo,
            "fecha": fecha_obj,
            "fecha_text": fecha_texto,
            "codigo": codigo,
            "numero_control": numero_control,
            "hora": hora_text,
            "fecha_hora": fecha_hora,
            "montos": montos,
            "tipo_operacion": _tipo_operacion(row),
            "tipo_ingreso": _tipo_ingreso(row),
            "json_path": row.get("json_path"),
            "estado": base,
            "estado_manual": manual,
            "estado_fuente": "db" if row.get("envio") else "extra",
            "estado_documento": (
                row.get("estado_documento")
                or row.get("estado_display")
                or row.get("estado")
            ),
            "estado_envio": envio_display.strip() if isinstance(envio_display, str) else "",
        }
        eventos.append(evento)
        seen.add(codigo)

    grupos: dict[tuple[str, str], dict] = {}
    for evento in eventos:
        key = (evento["fecha"].strftime("%Y-%m-%d"), evento["tipo"])
        grupo = grupos.setdefault(
            key,
            {
                "fecha": evento["fecha"],
                "tipo": evento["tipo"],
                "totales": defaultdict(lambda: Decimal("0.00")),
                "docs": [],
                "estado": None,
                "estado_manual": None,
                "estado_fuente": None,
                "tipo_operacion": None,
                "tipo_ingreso": None,
                "json_path": None,
                "estado_documento": None,
                "estado_envio_set": set(),
                "fecha_display": None,
            },
        )
        for campo, valor in evento["montos"].items():
            grupo["totales"][campo] += valor
        grupo["docs"].append(
            {
                "codigo": evento["codigo"],
                "numero_control": evento["numero_control"],
                "fecha_hora": evento["fecha_hora"],
                "hora": evento["hora"],
            }
        )
        if evento["json_path"] and not grupo["json_path"]:
            grupo["json_path"] = evento["json_path"]
        if evento["estado_fuente"] == "db" or not grupo["estado_fuente"]:
            grupo["estado_fuente"] = evento["estado_fuente"]
        if evento["estado_manual"]:
            grupo["estado_manual"] = evento["estado_manual"]
        elif grupo["estado_manual"] is None:
            grupo["estado_manual"] = evento["estado_manual"]
        if evento["estado"]:
            grupo["estado"] = evento["estado"]
        elif grupo["estado"] is None:
            grupo["estado"] = evento["estado"]
        if not grupo["estado_documento"] and evento["estado_documento"]:
            grupo["estado_documento"] = evento["estado_documento"]
        envio_val = evento.get("estado_envio")
        if envio_val:
            grupo["estado_envio_set"].add(envio_val)
        if not grupo["tipo_operacion"] and evento["tipo_operacion"]:
            grupo["tipo_operacion"] = evento["tipo_operacion"]
        if not grupo["tipo_ingreso"] and evento["tipo_ingreso"]:
            grupo["tipo_ingreso"] = evento["tipo_ingreso"]
        if not grupo["fecha_display"]:
            grupo["fecha_display"] = _format_fecha_hora_preview(evento["fecha"], {"horEmi": evento["hora"]})

    registros: list[VentaCF] = []
    for key in sorted(grupos):
        grupo = grupos[key]
        tipo = grupo["tipo"]
        totales = grupo["totales"]
        subtotal = (
            totales["ventas_exentas"]
            + totales["internas_exentas_ns"]
            + totales["ventas_no_sujetas"]
            + totales["ventas_gravadas_locales"]
            + totales["exp_ca"]
            + totales["exp_fuera_ca"]
            + totales["exp_servicios"]
            + totales["zonas_francas_dpa"]
            + totales["terceros_no_domic"]
        )
        totales["total_ventas"] = subtotal
        documentos = sorted(
            grupo["docs"],
            key=lambda d: (d["fecha_hora"], str(d["codigo"]).upper()),
        )
        doc_del = documentos[0]["codigo"] if documentos else None
        doc_al = documentos[-1]["codigo"] if documentos else None
        numero_control = documentos[-1]["numero_control"] if documentos else None
        doc_count = len(documentos)
        hora_inicio = None
        hora_fin = None
        if documentos:
            first_doc = documentos[0]
            last_doc = documentos[-1]
            if isinstance(first_doc.get("fecha_hora"), datetime):
                hora_inicio = first_doc["fecha_hora"].strftime("%H:%M")
            hora_inicio = hora_inicio or (first_doc.get("hora") or None)
            if isinstance(last_doc.get("fecha_hora"), datetime):
                hora_fin = last_doc["fecha_hora"].strftime("%H:%M")
            hora_fin = hora_fin or (last_doc.get("hora") or None)
        registro = VentaCF(
            fecha=grupo["fecha"].strftime("%d/%m/%Y"),
            clase=CLASE_POR_TIPO.get(tipo, "1"),
            tipo=tipo,
            numero_doc_del=doc_del,
            numero_doc_al=doc_al,
            ventas_exentas=_decimal_text(totales["ventas_exentas"]),
            internas_exentas_ns=_decimal_text(totales["internas_exentas_ns"]),
            ventas_no_sujetas=_decimal_text(totales["ventas_no_sujetas"]),
            ventas_gravadas_locales=_decimal_text(totales["ventas_gravadas_locales"]),
            exp_ca=_decimal_text(totales["exp_ca"]),
            exp_fuera_ca=_decimal_text(totales["exp_fuera_ca"]),
            exp_servicios=_decimal_text(totales["exp_servicios"]),
            zonas_francas_dpa=_decimal_text(totales["zonas_francas_dpa"]),
            terceros_no_domic=_decimal_text(totales["terceros_no_domic"]),
            total_ventas=_decimal_text(totales["total_ventas"]),
            tipo_operacion=grupo["tipo_operacion"] or "0",
            tipo_ingreso=grupo["tipo_ingreso"] or "0",
            codigo_generacion=doc_al or doc_del,
            numero_control=numero_control,
            estado=grupo["estado"],
            estado_manual=grupo["estado_manual"],
            estado_fuente=grupo["estado_fuente"],
            json_path=grupo["json_path"],
        )
        if documentos:
            registro.hora_emision = documentos[0].get("hora")
        registro.doc_count = doc_count
        registro.hora_inicio = hora_inicio
        registro.hora_fin = hora_fin
        doc_estado = grupo.get("estado_documento")
        if isinstance(doc_estado, str):
            doc_estado = doc_estado.strip()
        registro.estado_documento = doc_estado or None
        registros_envio = grupo.get("estado_envio_set") or set()

        def _envio_priority(value: str) -> tuple[int, str]:
            base = value.strip().lower()
            if "(" in base:
                base = base.split("(", 1)[0].strip()
            order = {
                "aceptado": 0,
                "recibido": 0,
                "enviado": 1,
                "procesado": 1,
                "rechazado": 2,
                "anulado": 3,
                "pendiente de envío": 4,
            }
            priority = order.get(base, 5)
            return (priority, value)

        if registros_envio:
            ordered = sorted({val.strip() for val in registros_envio if val.strip()}, key=_envio_priority)
            envio_display = " | ".join(ordered) if ordered else "Pendiente de envío"
        else:
            envio_display = "Pendiente de envío"
        registro.estado_envio = envio_display
        try:
            setattr(registro, "fecha_display", grupo.get("fecha_display") or registro.fecha)
        except Exception:
            logger.debug("No se pudo adjuntar fecha/hora auxiliar al registro CF %s", registro.codigo_generacion)
        registros.append(registro)
        stats[tipo]["incluidos"] += 1

    _log_summary("Anexo II", total_considerados, len(registros), stats, motivos)
    return registros


def build_anexo_i_anulados(periodo_yyyymm: str, *, base_dir: str | Path | None = None) -> list[DTEAnulado]:
    periodo = _validate_periodo(periodo_yyyymm)
    if base_dir is None:
        base_dir = ensure_user_dir("dtes", "actualizaciones", "anulacion")
    try:
        base_path = Path(base_dir)
    except TypeError:
        base_path = Path(str(base_dir))

    if not base_path.exists():
        return []

    registros: list[DTEAnulado] = []
    for entry in sorted(base_path.iterdir()):
        if not entry.is_dir():
            continue
        payload = _safe_load_json(entry / "documento.json")
        metadata = _safe_load_json(entry / "metadata.json")
        if not isinstance(payload, dict):
            continue

        identificacion = payload.get("identificacion") or {}
        if metadata and not isinstance(metadata, dict):
            metadata = None

        if not identificacion and metadata:
            identificacion = metadata.get("identificacion") or {}

        fecha_texto = identificacion.get("fecAnula") or identificacion.get("fechaAnulacion")
        if not fecha_texto and metadata:
            meta_ident = metadata.get("identificacion")
            if isinstance(meta_ident, dict):
                fecha_texto = meta_ident.get("fecAnula") or meta_ident.get("fechaAnulacion")

        fecha_normalizada = _normalize_fecha_text(fecha_texto)
        fecha_obj = _maybe_parse_fecha(fecha_normalizada)
        if not fecha_obj:
            continue
        periodo_evento = f"{fecha_obj.year:04d}{fecha_obj.month:02d}"
        if periodo_evento != periodo:
            continue

        respuesta = None
        if metadata:
            respuesta = metadata.get("respuesta")
            if isinstance(respuesta, dict) and "estado" in respuesta:
                estado_evento = normalize_estado(respuesta.get("estado"))
            else:
                estado_evento = None
        else:
            estado_evento = None

        if not estado_evento and metadata:
            estado_evento = normalize_estado(metadata.get("estado"))
        if not estado_evento:
            estado_evento = normalize_estado(payload.get("estado"))

        if estado_evento not in _ANULACION_ESTADOS_VALIDOS:
            continue

        motivo_payload = payload.get("motivo") if isinstance(payload.get("motivo"), dict) else {}
        tipo_anulacion = motivo_payload.get("tipoAnulacion")
        if tipo_anulacion is None and isinstance(metadata, dict):
            motivo_meta = metadata.get("motivo")
            if isinstance(motivo_meta, dict):
                tipo_anulacion = motivo_meta.get("tipoAnulacion")

        detalle_estado = _map_tipo_anulacion(tipo_anulacion)
        if not detalle_estado:
            continue

        doc_info: dict[str, Any] = {}
        if isinstance(metadata, dict):
            meta_doc = metadata.get("documento")
            if isinstance(meta_doc, dict):
                doc_info.update(meta_doc)

        doc_payload = payload.get("documento")
        if isinstance(doc_payload, dict):
            for key, value in doc_payload.items():
                doc_info.setdefault(key, value)

        numero_control = doc_info.get("numeroControl")
        codigo_generacion = doc_info.get("codigoGeneracion") or doc_info.get("codigo_generacion")
        sello = doc_info.get("selloRecibido") or doc_info.get("sello")
        tipo_documento = doc_info.get("tipoDte") or doc_info.get("tipoDocumento")

        if not numero_control or not codigo_generacion or not sello or not tipo_documento:
            continue

        numero_control = str(numero_control).strip().upper()
        codigo_generacion = str(codigo_generacion).strip().upper()
        sello = str(sello).strip().upper()
        tipo_documento = str(tipo_documento).strip()
        if tipo_documento.isdigit():
            tipo_documento = tipo_documento.zfill(2)

        registros.append(
            DTEAnulado(
                numero_control=numero_control,
                tipo_documento=tipo_documento,
                sello_recepcion=sello,
                codigo_generacion=codigo_generacion,
                estado=detalle_estado,
            )
        )

    registros.sort(key=lambda registro: (registro.numero_control or "", registro.codigo_generacion or ""))
    return registros

def _load_facturacion_json(path: str | None) -> dict:
    if not path or not isinstance(path, str):
        return {}
    resolved = path
    if not os.path.exists(resolved):
        return {}
    try:
        with open(resolved, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return {}
    if isinstance(data, dict):
        inner = data.get("dteJson")
        if isinstance(inner, dict):
            merged = dict(inner)
            merged.setdefault("dteJson", dict(inner))
            for key, value in data.items():
                if key == "dteJson":
                    continue
                merged.setdefault(key, value)
            return merged
        return data
    return {}


def _from_facturacion_row(raw: dict, db) -> dict:
    row: dict[str, Any] = {
        "venta_id": raw.get("venta_id"),
        "row_type": raw.get("row_type"),
        "total": raw.get("total"),
        "cliente_nombre": raw.get("cliente") or "",
        "cliente_id": raw.get("cliente_id"),
        "vendedor_id": raw.get("vendedor_id"),
        "estado": raw.get("estado"),
        "estado_display": raw.get("estado"),
        "estado_documento": raw.get("estado"),
        "estado_envio": raw.get("envio"),
        "fecha_display": raw.get("fecha"),
    }

    fecha_obj = raw.get("_parsed_fecha")
    if isinstance(fecha_obj, datetime):
        row["fecha_obj"] = fecha_obj
        row["fecEmi"] = fecha_obj.strftime("%Y-%m-%d")
    else:
        row["fecha_obj"] = None
        fecha_text = raw.get("fecha")
        if isinstance(fecha_text, str) and fecha_text:
            row["fecEmi"] = fecha_text.split(" ")[0]

    numero_control = raw.get("numero_control")
    if numero_control:
        row["numero_control"] = numero_control

    codigo_generacion = raw.get("codigo_generacion")
    if codigo_generacion:
        row["codigo_generacion"] = codigo_generacion

    base_tipo_desc = infer_tipo_from_name(raw.get("name"), raw.get("tipo"))
    tipo_desc = base_tipo_desc or raw.get("tipo")
    tipo_code = raw.get("codigo")
    if not tipo_code and tipo_desc:
        tipo_code = tipo_code_from_desc(tipo_desc)
    if tipo_code:
        try:
            tipo_code = str(tipo_code).zfill(2)
        except Exception:
            tipo_code = None
    row["tipo"] = tipo_code
    row["tipo_desc"] = tipo_desc

    json_path = raw.get("json")
    row["json_path"] = json_path if isinstance(json_path, str) else None
    dte_json = _load_facturacion_json(row.get("json_path"))
    row["dte_json"] = dte_json
    row["extra_data"] = {}

    ident = dte_json.get("identificacion") if isinstance(dte_json, dict) else {}
    if isinstance(ident, dict):
        row.setdefault("numero_control", ident.get("numeroControl"))
        row.setdefault("codigo_generacion", ident.get("codigoGeneracion"))
        if ident.get("fecEmi"):
            row["fecEmi"] = ident.get("fecEmi")
        if not row.get("tipo") and ident.get("tipoDte"):
            try:
                row["tipo"] = str(ident.get("tipoDte")).zfill(2)
            except Exception:
                row["tipo"] = ident.get("tipoDte")
        if ident.get("horEmi"):
            row["horEmi"] = ident.get("horEmi")
        elif ident.get("horaEmision"):
            row["horEmi"] = ident.get("horaEmision")

    sello = None
    if isinstance(dte_json, dict):
        for key in ("selloRecibido", "selloRecibidoDte", "selloRecibidoMH", "sello"):
            if dte_json.get(key):
                sello = dte_json.get(key)
                break
    row["sello_recepcion"] = sello

    envio_raw = raw.get("envio_payload")
    if envio_raw is None:
        envio_raw = raw.get("envio")
    if isinstance(envio_raw, dict):
        envio_info = dict(envio_raw)
    elif isinstance(envio_raw, str) and envio_raw.strip():
        envio_info = {
            "estado_ui": envio_raw,
            "estado_ui_tag": envio_raw,
            "estado": envio_raw,
        }
    else:
        envio_info = {}
    if row.get("codigo_generacion"):
        envio_info.setdefault("codigo_generacion", row["codigo_generacion"])
    if row.get("numero_control"):
        envio_info.setdefault("numero_control", row["numero_control"])
    row["envio"] = envio_info
    raw_envio_display = raw.get("envio")
    raw_envio_clean: str | None = None
    raw_envio_base: str | None = None
    raw_envio_tag: str | None = None
    if isinstance(raw_envio_display, str):
        raw_envio_clean = raw_envio_display.strip()
        if raw_envio_clean:
            match = re.match(r"^(.*?)(?:\s*\(([^)]+)\))?$", raw_envio_clean)
            if match:
                raw_envio_base = match.group(1).strip() if match.group(1) else None
                raw_envio_tag = match.group(2).strip().lower() if match.group(2) else None
            else:
                raw_envio_base = raw_envio_clean
        if raw_envio_base:
            for separator in ("-", "\u2014", ":", "["):
                if separator in raw_envio_base:
                    raw_envio_base = raw_envio_base.split(separator, 1)[0].strip()
                    break

    estado_manual_val = None
    if isinstance(envio_info, dict):
        estado_manual_val = envio_info.get("estado_manual") or envio_info.get("estado_manual_text")
    if isinstance(estado_manual_val, str) and estado_manual_val.strip():
        estado_manual_val = estado_manual_val.strip()
        row["estado_manual"] = estado_manual_val
    else:
        estado_manual_val = None
        row["estado_manual"] = None

    manual_from_display = False
    if not estado_manual_val and raw_envio_base:
        base_norm = normalize_estado(raw_envio_base)
        if base_norm and base_norm in ENVIADO_ESTADOS:
            estado_manual_val = raw_envio_base
            row["estado_manual"] = estado_manual_val
            manual_from_display = True

    auto_state_raw = (envio_info or {}).get("estado") or raw.get("envio")
    auto_display = format_envio_state(
        (envio_info or {}).get("estado_ui"),
        (envio_info or {}).get("estado_ui_tag"),
        auto_state_raw,
    )
    merged_state, manual_override = _choose_envio_state(auto_state_raw, estado_manual_val)
    merged_display = format_envio_state(
        (envio_info or {}).get("estado_ui"),
        (envio_info or {}).get("estado_ui_tag"),
        merged_state,
    )
    if manual_override and manual_from_display and raw_envio_clean:
        merged_display = raw_envio_clean
        envio_info = envio_info or {}
        envio_info.setdefault("estado_manual", estado_manual_val)
        envio_info.setdefault("estado_manual_text", raw_envio_clean)
        envio_info.setdefault("estado_ui_manual", 1)
        if raw_envio_base:
            envio_info["estado_ui"] = raw_envio_base
        if raw_envio_tag:
            envio_info["estado_ui_tag"] = raw_envio_tag
        envio_info["estado"] = merged_state
        row["_envio_override"] = {"manual": True, "fuente": "facturacion_envio_display"}
        row["envio"] = envio_info
    else:
        row["envio"] = envio_info
    row["_estado_envio_raw"] = merged_state
    row["estado_envio"] = merged_display
    if manual_override:
        logger.info(
            "Override de estado: base=%s manual=%s codigo=%s",
            normalize_estado(auto_state_raw),
            normalize_estado(estado_manual_val),
            row.get("codigo_generacion"),
        )
        envio_info.setdefault("estado_manual_override", estado_manual_val)
    row["estado_fuente"] = "db" if row.get("venta_id") is not None else "extra"

    row["cliente_nit"] = None
    row["cliente_nrc"] = None
    row["cliente_dui"] = None
    cliente_id = row.get("cliente_id")
    getter = getattr(db, "get_cliente", None)
    if callable(getter) and cliente_id:
        try:
            cliente_info = getter(cliente_id)
        except Exception:
            cliente_info = None
        if isinstance(cliente_info, dict):
            row["cliente_nit"] = cliente_info.get("nit")
            row["cliente_nrc"] = cliente_info.get("nrc")
            row["cliente_dui"] = cliente_info.get("dui")
            if not row["cliente_nombre"]:
                row["cliente_nombre"] = cliente_info.get("nombre") or ""

    _ensure_field(row, "codigo_generacion", _codigo_generacion)
    _ensure_field(row, "numero_control", _numero_control)
    _ensure_field(row, "sello_recepcion", _sello_recepcion)

    if not isinstance(row.get("fecha_obj"), datetime):
        fecha_candidata = row.get("fecEmi") or row.get("fecha_display")
        if fecha_candidata and row.get("horEmi") and (" " not in str(fecha_candidata) and "T" not in str(fecha_candidata)):
            fecha_candidata = f"{fecha_candidata} {row.get('horEmi')}"
        fecha_normalizada = _normalize_fecha_text(fecha_candidata)
        fecha_parseada = _maybe_parse_fecha(fecha_normalizada)
        if fecha_parseada:
            row["fecha_obj"] = fecha_parseada
            if not row.get("fecEmi"):
                row["fecEmi"] = fecha_parseada.strftime("%Y-%m-%d")
            if not row.get("fecha_display"):
                row["fecha_display"] = fecha_parseada.strftime("%Y-%m-%d")
    else:
        # Complementa la hora si existe por separado
        if row.get("horEmi"):
            hora_norm = _normalize_hora_text(row.get("horEmi"))
            if hora_norm:
                try:
                    hora_parts = [int(p) for p in hora_norm.split(":")]
                    if len(hora_parts) >= 2:
                        row["fecha_obj"] = row["fecha_obj"].replace(
                            hour=hora_parts[0],
                            minute=hora_parts[1],
                            second=row["fecha_obj"].second,
                            microsecond=0,
                        )
                except Exception:
                    pass

    return row


def _load_envios_for_ventas(db, venta_ids: set[int]) -> dict[int, dict[str, Any]]:
    if not venta_ids:
        return {}

    cursor = getattr(db, "cursor", None)
    if cursor is None:
        return {}

    placeholders = ",".join(["?"] * len(venta_ids))
    query = (
        "SELECT id, venta_id, codigo_generacion, numero_control, estado_ui, "
        "estado_ui_tag, estado_ui_manual, respuesta "
        "FROM dte_envios WHERE venta_id IN ("
        + placeholders
        + ") ORDER BY estado_ui_manual DESC, id DESC"
    )

    env_map: dict[int, dict[str, Any]] = {}
    try:
        rows = list(cursor.execute(query, list(venta_ids)))
    except Exception:
        return env_map

    for envio in rows:
        try:
            venta_id = int(envio["venta_id"])
        except Exception:
            continue
        if venta_id in env_map:
            continue
        payload = dict(envio)
        respuesta = payload.get("respuesta")
        respuesta_json = _load_json(respuesta)
        if isinstance(respuesta_json, dict):
            payload["respuesta_json"] = respuesta_json
            payload.setdefault("codigo_generacion", respuesta_json.get("codigoGeneracion"))
            payload.setdefault("numero_control", respuesta_json.get("numeroControl"))
            if respuesta_json.get("estado"):
                payload.setdefault("estado_ui", respuesta_json.get("estado"))
        env_map[venta_id] = payload

    return env_map


def _lookup_envio_by_codigo(
    db,
    codigo_generacion: str | None,
    numero_control: str | None,
) -> dict[str, Any] | None:
    cursor = getattr(db, "cursor", None)
    if cursor is None:
        return None
    try:
        if codigo_generacion:
            row = cursor.execute(
                """
                SELECT id, estado_ui, estado_ui_tag, estado, estado_ui_manual, respuesta
                FROM dte_envios
                WHERE codigo_generacion IS NOT NULL AND UPPER(codigo_generacion)=UPPER(?)
                ORDER BY estado_ui_manual DESC, id DESC LIMIT 1
                """,
                (codigo_generacion,),
            ).fetchone()
            if row:
                payload = dict(row)
            else:
                payload = None
        else:
            payload = None
        if not payload and numero_control:
            row = cursor.execute(
                """
                SELECT id, estado_ui, estado_ui_tag, estado, estado_ui_manual, respuesta
                FROM dte_envios
                WHERE numero_control IS NOT NULL AND UPPER(numero_control)=UPPER(?)
                ORDER BY estado_ui_manual DESC, id DESC LIMIT 1
                """,
                (numero_control,),
            ).fetchone()
            if row:
                payload = dict(row)
        if not payload:
            return None
    except Exception:
        return None

    respuesta_raw = payload.get("respuesta")
    if isinstance(respuesta_raw, str):
        try:
            respuesta_json = json.loads(respuesta_raw)
        except Exception:
            respuesta_json = None
    else:
        respuesta_json = None
    if isinstance(respuesta_json, dict):
        payload["respuesta_json"] = respuesta_json
    return payload


def _normalize_fecha_text(value: Any) -> str | None:
    if not value:
        return None
    texto = str(value).strip()
    if not texto:
        return None
    texto = texto.replace("/", "-")
    return texto


def _maybe_parse_fecha(fecha: str | None) -> datetime | None:
    if not fecha:
        return None
    texto = _normalize_fecha_text(fecha)
    if not texto:
        return None
    for fmt in (
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y/%m/%d",
        "%Y/%m/%d %H:%M",
        "%Y/%m/%d %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y %H:%M:%S",
    ):
        try:
            return datetime.strptime(texto, fmt)
        except ValueError:
            continue
    return None


def _enrich_rows_from_db(rows: list[dict], db) -> None:
    if not rows:
        return

    venta_ids: set[int] = set()
    for row in rows:
        try:
            vid = int(row.get("venta_id"))
        except (TypeError, ValueError):
            continue
        venta_ids.add(vid)

    env_map = _load_envios_for_ventas(db, venta_ids)

    get_venta = getattr(db, "get_venta_by_id", None)
    ventas_cache: dict[int, dict[str, Any] | None] = {}

    for row in rows:
        try:
            venta_id = int(row.get("venta_id"))
        except (TypeError, ValueError):
            venta_id = None
        venta_data: dict[str, Any] | None = None
        if venta_id is not None and callable(get_venta):
            if venta_id not in ventas_cache:
                try:
                    venta_data = get_venta(venta_id)
                except Exception:
                    venta_data = None
                ventas_cache[venta_id] = venta_data
            else:
                venta_data = ventas_cache[venta_id]

        if isinstance(venta_data, dict):
            extra_data = _load_json(venta_data.get("extra")) or {}
            if isinstance(extra_data, dict):
                existing_extra = row.get("extra_data")
                if not isinstance(existing_extra, dict):
                    existing_extra = {}
                for key, value in extra_data.items():
                    existing_extra.setdefault(key, value)
                row["extra_data"] = existing_extra

                if not row.get("dte_json"):
                    for candidate_key in ("dteJson", "dte_json", "dte_json_dict"):
                        candidate = extra_data.get(candidate_key)
                        if isinstance(candidate, dict):
                            row["dte_json"] = candidate
                            break

                if not row.get("json_path"):
                    path_candidate = extra_data.get("dteJsonPath") or extra_data.get("jsonPath")
                    if isinstance(path_candidate, str) and path_candidate.strip():
                        row["json_path"] = path_candidate

                _ensure_field(row, "codigo_generacion", _codigo_generacion)
                _ensure_field(row, "numero_control", _numero_control)

                dte_json = row.get("dte_json")
                if isinstance(dte_json, dict):
                    ident = dte_json.get("identificacion")
                    if isinstance(ident, dict):
                        fec = ident.get("fecEmi") or ident.get("fechaEmision")
                        normalizado = _normalize_fecha_text(fec)
                        if normalizado and not row.get("fecEmi"):
                            row["fecEmi"] = normalizado
                        if ident.get("horEmi") and not row.get("horEmi"):
                            row["horEmi"] = ident.get("horEmi")
                        elif ident.get("horaEmision") and not row.get("horEmi"):
                            row["horEmi"] = ident.get("horaEmision")
                if isinstance(extra_data, dict):
                    if not row.get("horEmi"):
                        for key in ("horEmi", "horaEmision", "hora_emision"):
                            if extra_data.get(key):
                                row["horEmi"] = extra_data.get(key)
                                break

            if not isinstance(row.get("fecha_obj"), datetime):
                fecha_texto = row.get("fecEmi") or venta_data.get("fecha")
                if fecha_texto and row.get("horEmi") and (" " not in str(fecha_texto) and "T" not in str(fecha_texto)):
                    fecha_texto = f"{fecha_texto} {row.get('horEmi')}"
                fecha_obj = _maybe_parse_fecha(fecha_texto)
                if fecha_obj:
                    row["fecha_obj"] = fecha_obj
            else:
                if row.get("horEmi"):
                    hora_norm = _normalize_hora_text(row.get("horEmi"))
                    if hora_norm:
                        try:
                            h, m = hora_norm.split(":")
                            row["fecha_obj"] = row["fecha_obj"].replace(
                                hour=int(h),
                                minute=int(m),
                                second=row["fecha_obj"].second,
                                microsecond=0,
                            )
                        except Exception:
                            pass

        envio_payload = env_map.get(venta_id) if venta_id is not None else None
        if envio_payload:
            envio_info = row.get("envio")
            if isinstance(envio_info, str):
                envio_info = {"estado_ui": envio_info, "estado": envio_info}
            elif not isinstance(envio_info, dict):
                envio_info = {}

            estado_manual = None
            if envio_payload.get("estado_ui_manual"):
                estado_manual = envio_payload.get("estado_ui") or envio_payload.get("estado_ui_tag")

            for key in ("estado_ui", "estado_ui_tag", "estado_ui_manual"):
                valor = envio_payload.get(key)
                if valor is not None:
                    envio_info[key] = valor

            codigo_env = envio_payload.get("codigo_generacion")
            numero_env = envio_payload.get("numero_control")
            if codigo_env and not row.get("codigo_generacion"):
                row["codigo_generacion"] = codigo_env
            if numero_env and not row.get("numero_control"):
                row["numero_control"] = numero_env

            respuesta_json = envio_payload.get("respuesta_json")
            if isinstance(respuesta_json, dict):
                envio_info["respuesta_json"] = respuesta_json
                codigo_json = respuesta_json.get("codigoGeneracion")
                numero_json = respuesta_json.get("numeroControl")
                if codigo_json and not row.get("codigo_generacion"):
                    row["codigo_generacion"] = codigo_json
                if numero_json and not row.get("numero_control"):
                    row["numero_control"] = numero_json
                if not row.get("dte_json"):
                    dte_candidate = respuesta_json.get("dteJson")
                    if isinstance(dte_candidate, dict):
                        row["dte_json"] = dte_candidate

            if estado_manual:
                envio_info["estado_manual"] = estado_manual
                envio_info.setdefault("estado_manual_text", estado_manual)
                row["estado_manual"] = estado_manual

            row["envio"] = envio_info
            row["estado_fuente"] = "db"
            row["estado_envio"] = format_envio_state(
                envio_info.get("estado_ui"),
                envio_info.get("estado_ui_tag"),
                envio_info.get("estado"),
            )

        if not isinstance(row.get("fecha_obj"), datetime):
            fecha_obj = _maybe_parse_fecha(row.get("fecEmi"))
            if fecha_obj:
                row["fecha_obj"] = fecha_obj

        _ensure_field(row, "codigo_generacion", _codigo_generacion)
        _ensure_field(row, "numero_control", _numero_control)
        _ensure_field(row, "sello_recepcion", _sello_recepcion)


def _iter_credito_fiscal_json_paths() -> list[Path]:
    """Enumerar posibles rutas JSON de crédito fiscal en el sistema de archivos."""

    bases: list[Path] = []
    if FACTURAS_CREDITO_FISCAL_DIR:
        try:
            bases.append(Path(FACTURAS_CREDITO_FISCAL_DIR))
        except TypeError:
            bases = []

    seen: set[Path] = set()
    results: list[Path] = []
    for base in bases:
        try:
            resolved_base = base.resolve()
        except Exception:
            resolved_base = base
        if not resolved_base.exists():
            continue
        try:
            iterator = resolved_base.rglob("*.json")
        except Exception:
            continue
        for entry in iterator:
            if entry.suffix.lower() != ".json":
                continue
            if entry.name.lower().endswith(".meta.json"):
                continue
            try:
                resolved = entry.resolve()
            except Exception:
                resolved = entry
            if resolved in seen:
                continue
            seen.add(resolved)
            results.append(resolved)
    return results


def _collect_credito_fiscal_orphans(
    periodo: str,
    raw_rows: list[dict],
    db,
) -> tuple[list[dict], dict[str, list[PreviewExclusionEntry]]]:
    """Construir filas sintéticas para DTE de crédito fiscal huérfanos."""

    extra_rows: list[dict] = []
    descartes: defaultdict[str, list[PreviewExclusionEntry]] = defaultdict(list)

    existing_paths: set[str] = set()
    existing_codigos: set[str] = set()
    for row in raw_rows:
        path_value = row.get("json") or row.get("json_path")
        if path_value:
            try:
                existing_paths.add(os.path.abspath(os.fspath(path_value)))
            except (TypeError, ValueError, OSError):
                existing_paths.add(str(path_value))
        codigo = row.get("codigo_generacion")
        if codigo:
            existing_codigos.add(str(codigo).strip().upper())

    seen_paths: set[str] = set()
    for path in _iter_credito_fiscal_json_paths():
        try:
            path_str = os.path.abspath(os.fspath(path))
        except (TypeError, ValueError, OSError):
            path_str = str(path)
        if path_str in existing_paths or path_str in seen_paths:
            continue

        data = _load_facturacion_json(path_str)
        if not data:
            continue

        identificacion = data.get("identificacion") or {}
        tipo_raw = identificacion.get("tipoDte")
        tipo_codigo: str | None = None
        if isinstance(tipo_raw, int):
            tipo_codigo = f"{tipo_raw:02d}"
        elif isinstance(tipo_raw, str):
            tipo_clean = tipo_raw.strip()
            if tipo_clean.isdigit():
                tipo_codigo = tipo_clean.zfill(2)
            elif tipo_clean:
                tipo_codigo = tipo_clean
        if not tipo_codigo or tipo_codigo not in TIPOS_ANEXO_I:
            continue

        codigo_generacion = identificacion.get("codigoGeneracion")
        codigo_norm = str(codigo_generacion).strip().upper() if codigo_generacion else None
        if codigo_norm and codigo_norm in existing_codigos:
            continue

        fecha_texto = identificacion.get("fecEmi") or data.get("fecEmi")
        hora_texto = identificacion.get("horEmi") or data.get("horEmi")
        fecha_obj: datetime | None = None
        if fecha_texto and hora_texto:
            combinada = f"{_normalize_fecha_text(fecha_texto)} {hora_texto}".strip()
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M"):
                try:
                    fecha_obj = datetime.strptime(combinada, fmt)
                    break
                except ValueError:
                    continue
        if fecha_obj is None:
            if fecha_texto and hora_texto and (" " not in str(fecha_texto) and "T" not in str(fecha_texto)):
                fecha_obj = _maybe_parse_fecha(f"{fecha_texto} {hora_texto}")
            else:
                fecha_obj = _maybe_parse_fecha(fecha_texto)

        if not fecha_obj:
            info_row = {"codigo_generacion": codigo_generacion, "tipo": tipo_codigo, "fecEmi": fecha_texto}
            descartes["sin_fecha"].append(
                _make_exclusion_entry(info_row, detalle="sin fecha", fecha=fecha_texto)
            )
            continue

        periodo_fila = f"{fecha_obj.year:04d}{fecha_obj.month:02d}"
        if periodo_fila != periodo:
            info_row = {"codigo_generacion": codigo_generacion, "tipo": tipo_codigo, "fecEmi": fecha_texto}
            descartes["fuera_de_periodo"].append(
                _make_exclusion_entry(info_row, detalle=periodo_fila, fecha=fecha_texto)
            )
            continue

        receptor = data.get("receptor") or {}
        if not isinstance(receptor, dict):
            receptor = {}
        cliente_nombre = receptor.get("nombre") or ""

        resumen = data.get("resumen") or {}
        if not isinstance(resumen, dict):
            resumen = {}
        total = (
            resumen.get("montoTotalOperacion")
            or resumen.get("totalPagar")
            or resumen.get("totalVenta")
            or resumen.get("total")
        )

        respuesta = data.get("respuesta") if isinstance(data, dict) else {}
        if not isinstance(respuesta, dict):
            respuesta = {}
        estado_resp = respuesta.get("estado") or respuesta.get("estadoDesc")
        if not estado_resp:
            estado_resp = _extract_envio_state_from_payload(respuesta) or _extract_envio_state_from_payload(data)

        estado_manual = None
        meta_data: dict[str, Any] = {}
        meta_path = Path(path_str).with_suffix(".meta.json")
        if meta_path.exists():
            try:
                with open(meta_path, "r", encoding="utf-8") as meta_file:
                    loaded_meta = json.load(meta_file)
                    if isinstance(loaded_meta, dict):
                        meta_data = loaded_meta
            except Exception:
                meta_data = {}
        if meta_data:
            estado_manual = meta_data.get("estadoManual") or meta_data.get("estado_manual")
            if not estado_resp:
                estado_resp = (
                    meta_data.get("estado")
                    or meta_data.get("estadoEnvio")
                    or meta_data.get("estado_envio")
                )
            if not estado_resp:
                estado_resp = _extract_envio_state_from_payload(meta_data)
            if meta_data.get("anulado") and not estado_manual:
                estado_manual = "Anulado"

        envio_db = _lookup_envio_by_codigo(
            db,
            codigo_generacion,
            identificacion.get("numeroControl"),
        )

        if envio_db:
            db_estado = envio_db.get("estado")
            if isinstance(db_estado, str) and db_estado.strip():
                estado_resp = db_estado
            if envio_db.get("estado_ui_manual"):
                estado_manual = (
                    estado_manual
                    or envio_db.get("estado_ui")
                    or envio_db.get("estado_ui_tag")
                    or envio_db.get("estado")
                )

        envio_payload: dict[str, Any]
        if estado_manual or estado_resp:
            envio_payload = {}
            if estado_resp:
                envio_payload["estado_ui"] = estado_resp
                envio_payload["estado_ui_tag"] = estado_resp
                envio_payload["estado"] = estado_resp
            if estado_manual:
                envio_payload["estado_manual"] = estado_manual
                envio_payload["estado_manual_text"] = estado_manual
                envio_payload["estado_ui_manual"] = 1
        else:
            envio_payload = {"estado_ui": "Pendiente", "estado_ui_tag": "Pendiente", "estado": "Pendiente"}

        if envio_db:
            for key in ("estado_ui", "estado_ui_tag", "estado_ui_manual", "estado"):
                value = envio_db.get(key)
                if value is not None:
                    envio_payload[key] = value
            respuesta_json = envio_db.get("respuesta_json")
            if isinstance(respuesta_json, dict):
                envio_payload.setdefault("respuesta_json", respuesta_json)

        merged_estado, manual_override = _choose_envio_state(
            envio_payload.get("estado"),
            estado_manual,
        )
        envio_payload["estado"] = merged_estado
        if manual_override:
            envio_payload["estado_override"] = "manual"
            logger.info(
                "Override huérfano: base=%s manual=%s archivo=%s",
                normalize_estado(estado_resp),
                normalize_estado(estado_manual),
                path_str,
            )

        fecha_display = (
            fecha_obj.strftime("%Y-%m-%d %H:%M:%S")
            if fecha_obj.time() != datetime.min.time()
            else fecha_obj.strftime("%Y-%m-%d")
        )

        envio_display = format_envio_state(
            envio_payload.get("estado_ui"),
            envio_payload.get("estado_ui_tag"),
            envio_payload.get("estado"),
        )

        raw = {
            "row_type": "orphan",
            "venta_id": None,
            "name": Path(path_str).stem,
            "numero_control": identificacion.get("numeroControl"),
            "codigo_generacion": codigo_generacion,
            "fecha": fecha_display,
            "_parsed_fecha": fecha_obj,
            "cliente": cliente_nombre,
            "cliente_id": None,
            "vendedor_id": None,
            "total": total,
            "estado": "Sin venta",
            "envio": envio_display,
            "envio_payload": envio_payload,
            "tipo": TIPO_DTE_DESC.get(tipo_codigo, tipo_codigo),
            "codigo": tipo_codigo,
            "json": path_str,
            "sign": 1,
        }

        if estado_manual and not envio_payload.get("estado_manual"):
            raw["estado_manual"] = estado_manual

        extra_rows.append(raw)
        seen_paths.add(path_str)
        if codigo_norm:
            existing_codigos.add(codigo_norm)

    return extra_rows, descartes


# Retrocompatibilidad con nombres previos
def build_anexo_i_records(rows: list[dict], db):
    return build_anexo_i_contribuyentes(rows, db)


def build_anexo_ii_records(rows: list[dict], db):
    return build_anexo_i_consumidor(rows, db)


def collect_facturacion_dataset(db, periodo_yyyymm: str) -> FacturacionDataset:
    """Obtiene información cruda de facturación reutilizando la lógica de la tabla."""

    periodo = _validate_periodo(periodo_yyyymm)
    try:
        raw_rows = _facturacion_rows(db)
    except Exception:
        raw_rows = []

    extra_rows, extra_discards = _collect_credito_fiscal_orphans(periodo, raw_rows, db)
    if extra_rows:
        raw_rows.extend(extra_rows)

    total_leidos = len(raw_rows)
    descartes: defaultdict[str, list[PreviewExclusionEntry]] = defaultdict(list)
    for motivo, entradas in extra_discards.items():
        descartes[motivo].extend(entradas)
    periodo_rows: list[dict] = []

    for raw in raw_rows:
        row_data = _from_facturacion_row(raw, db)
        fecha_obj = row_data.get("fecha_obj") if isinstance(row_data.get("fecha_obj"), datetime) else None
        fecha_texto = row_data.get("fecha_display") or row_data.get("fecEmi")
        if not fecha_obj:
            descartes["sin_fecha"].append(
                _make_exclusion_entry(row_data, detalle="sin fecha", fecha=fecha_texto)
            )
            continue

        periodo_fila = f"{fecha_obj.year:04d}{fecha_obj.month:02d}"
        if periodo_fila != periodo:
            descartes["fuera_de_periodo"].append(
                _make_exclusion_entry(row_data, detalle=periodo_fila, fecha=fecha_texto)
            )
            continue

        periodo_rows.append(row_data)

    _enrich_rows_from_db(periodo_rows, db)

    periodo_rows, duplicados = _deduplicate_facturacion_rows(periodo_rows)
    if duplicados:
        for dup in duplicados:
            descartes["duplicado"].append(
                _make_exclusion_entry(dup, detalle="duplicado", fecha=_row_fecha_text(dup))
            )

    periodo_rows, duplicados_correl = _deduplicate_correlativo_rows(periodo_rows)
    if duplicados_correl:
        for dup in duplicados_correl:
            numero = _ensure_field(dup, "numero_control", _numero_control)
            detalle = f"{dup.get('tipo')}:{numero}" if numero else "duplicado"
            descartes["correlativo_duplicado"].append(
                _make_exclusion_entry(dup, detalle=detalle, fecha=_row_fecha_text(dup))
            )

    descartes_dict = {motivo: lista for motivo, lista in descartes.items()}
    _log_summary(
        f"Facturación {periodo}",
        total_leidos,
        len(periodo_rows),
        {},
        descartes_dict,
    )
    return FacturacionDataset(periodo_rows, total_leidos, descartes_dict)
