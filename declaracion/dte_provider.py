"""Proveedor de datos para la generación de anexos DTE."""

from __future__ import annotations

import calendar
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, date
import json
import logging
import os
import re
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Callable

from declaracion.anexo_contribuyentes import VentaContribuyente
from declaracion.anexo_consumidor_final import VentaCF
from utils.facturacion_records import (
    infer_tipo_from_name,
    tipo_code_from_desc,
    get_facturacion_rows as _facturacion_rows,
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
            self.tipo or "",
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
    "estado_no_apto",
    "sin_codigo",
    "sin_fecha",
    "duplicado",
    "fuera_de_periodo",
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


def _build_preview_row_anexo_i(
    row: dict, codigo: str, base: str | None, manual: str | None
) -> PreviewRow:
    fecha_obj = row.get("fecha_obj") if isinstance(row.get("fecha_obj"), datetime) else None
    fecha_texto = _row_fecha_text(row) or ""
    numero_control = row.get("numero_control")
    if numero_control:
        numero_control = str(numero_control).strip() or None
    sello = row.get("sello_recepcion")
    if sello:
        sello = str(sello).strip() or None
    cliente = _extract_cliente(row)
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
        tipo=str(row.get("tipo") or ""),
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
    fecha_texto = _row_fecha_text(row) or ""
    numero_control = row.get("numero_control")
    if numero_control:
        numero_control = str(numero_control).strip() or None
    sello = row.get("sello_recepcion")
    if sello:
        sello = str(sello).strip() or None
    cliente_nombre = _extract_cliente(row).get("nombre") or ""
    montos = _montos_anexo_ii(row)
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
        tipo=str(row.get("tipo") or ""),
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
        if not estado_apto(base, manual):
            stats[tipo]["excluidos"] += 1
            descripcion = normalize_estado(manual) or normalize_estado(base) or "desconocido"
            excluidos["estado_no_apto"].append(
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
    return DeclaracionPreview(
        periodo=periodo,
        anexo_i=build_anexo_i_preview(dataset),
        anexo_ii=build_anexo_ii_preview(dataset),
    )


def build_anexo_i_records(rows: list[dict], db) -> list[VentaContribuyente]:
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
        apto = estado_apto(base, manual)
        if not apto:
            stats[tipo]["excluidos"] += 1
            descripcion = normalize_estado(manual) or normalize_estado(base) or "desconocido"
            motivos["estado_no_apto"].append(f"{codigo}:{descripcion}")
            continue
        _, fecha_obj = _fecha_emision(row)
        if not fecha_obj:
            stats[tipo]["excluidos"] += 1
            motivos["sin_fecha"].append(f"{codigo}")
            continue

        montos = _montos_anexo_i(row)
        identificacion, dui, nombre = _identificacion_anexo_i(row)
        numero_control = row.get("numero_control") or _numero_control(row)
        registro = VentaContribuyente(
            fecha_emision=fecha_obj.strftime("%d/%m/%Y"),
            clase=CLASE_POR_TIPO.get(tipo, "4"),
            tipo=tipo,
            numero_control=numero_control,
            codigo_generacion=codigo,
            sello_recepcion=row.get("sello_recepcion") if apto else None,
            identificacion=identificacion,
            nombre_cliente=nombre,
            dui=dui,
            tipo_operacion=_tipo_operacion(row),
            tipo_ingreso=_tipo_ingreso(row),
            estado=base,
            estado_manual=manual,
            estado_fuente="db" if row.get("envio") else "extra",
            json_path=row.get("json_path"),
        )
        for clave, valor in montos.items():
            setattr(registro, clave, valor)
        registros.append(registro)
        seen.add(codigo)
        stats[tipo]["incluidos"] += 1

    _log_summary("Anexo I", total_considerados, len(registros), stats, motivos)
    return registros


def build_anexo_ii_records(rows: list[dict], db) -> list[VentaCF]:
    seen: set[str] = set()
    stats = defaultdict(lambda: {"incluidos": 0, "excluidos": 0})
    motivos = defaultdict(list)
    total_considerados = 0
    grupos: dict[tuple[str, str], dict] = {}

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
        apto = estado_apto(base, manual)
        if not apto:
            stats[tipo]["excluidos"] += 1
            descripcion = normalize_estado(manual) or normalize_estado(base) or "desconocido"
            motivos["estado_no_apto"].append(f"{codigo}:{descripcion}")
            continue
        _, fecha_obj = _fecha_emision(row)
        if not fecha_obj:
            stats[tipo]["excluidos"] += 1
            motivos["sin_fecha"].append(f"{codigo}")
            continue

        numero_control = row.get("numero_control") or _numero_control(row)
        montos = _montos_anexo_ii_values(row)
        key = (fecha_obj.strftime("%Y-%m-%d"), tipo)
        if key not in grupos:
            grupos[key] = {
                "fecha": fecha_obj,
                "tipo": tipo,
                "totales": {campo: Decimal("0.00") for campo in montos},
                "controles": [],
                "codigos": [],
                "estado": None,
                "estado_manual": None,
                "estado_fuente": None,
                "tipo_operacion": _tipo_operacion(row),
                "tipo_ingreso": _tipo_ingreso(row),
                "json_path": row.get("json_path"),
                "ultimo_control": None,
                "ultimo_codigo": None,
            }
        grupo = grupos[key]
        for campo, valor in montos.items():
            grupo["totales"][campo] += valor
        if numero_control:
            grupo["controles"].append(numero_control)
            grupo["ultimo_control"] = numero_control
        if codigo:
            grupo["codigos"].append(codigo)
            grupo["ultimo_codigo"] = codigo
        if row.get("json_path") and not grupo["json_path"]:
            grupo["json_path"] = row.get("json_path")
        fuente = "db" if row.get("envio") else "extra"
        if fuente == "db" or not grupo["estado_fuente"]:
            grupo["estado_fuente"] = fuente
        if manual:
            grupo["estado_manual"] = manual
        elif not grupo["estado_manual"]:
            grupo["estado_manual"] = manual
        if base:
            grupo["estado"] = base
        elif not grupo["estado"]:
            grupo["estado"] = base
        seen.add(codigo)

    registros: list[VentaCF] = []
    for key in sorted(grupos):
        grupo = grupos[key]
        tipo = grupo["tipo"]
        totales = grupo["totales"]
        controles = grupo["controles"] or grupo["codigos"]
        documentos = grupo["codigos"] or grupo["controles"]
        ctrl_del = controles[0] if controles else None
        ctrl_al = controles[-1] if controles else None
        doc_del = documentos[0] if documentos else ctrl_del
        doc_al = documentos[-1] if documentos else ctrl_al
        registro = VentaCF(
            fecha=grupo["fecha"].strftime("%d/%m/%Y"),
            clase=CLASE_POR_TIPO.get(tipo, "1"),
            tipo=tipo,
            ctrl_interno_del=ctrl_del,
            ctrl_interno_al=ctrl_al,
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
            tipo_operacion=grupo["tipo_operacion"],
            tipo_ingreso=grupo["tipo_ingreso"],
            codigo_generacion=grupo["ultimo_codigo"],
            numero_control=grupo["ultimo_control"],
            estado=grupo["estado"],
            estado_manual=grupo["estado_manual"],
            estado_fuente=grupo["estado_fuente"],
            json_path=grupo["json_path"],
        )
        registros.append(registro)
        stats[tipo]["incluidos"] += 1

    _log_summary("Anexo II", total_considerados, len(registros), stats, motivos)
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

    sello = None
    if isinstance(dte_json, dict):
        for key in ("selloRecibido", "selloRecibidoDte", "selloRecibidoMH", "sello"):
            if dte_json.get(key):
                sello = dte_json.get(key)
                break
    row["sello_recepcion"] = sello

    envio_text = raw.get("envio")
    envio_info: dict[str, Any] = {}
    if isinstance(envio_text, str) and envio_text.strip():
        envio_info["estado_ui"] = envio_text
        envio_info["estado"] = envio_text
    if row.get("codigo_generacion"):
        envio_info.setdefault("codigo_generacion", row["codigo_generacion"])
    if row.get("numero_control"):
        envio_info.setdefault("numero_control", row["numero_control"])
    row["envio"] = envio_info
    row["estado_manual"] = None
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

    return row


def collect_facturacion_dataset(db, periodo_yyyymm: str) -> FacturacionDataset:
    """Obtiene información cruda de facturación reutilizando la lógica de la tabla."""

    periodo = _validate_periodo(periodo_yyyymm)
    try:
        raw_rows = _facturacion_rows(db)
    except Exception:
        raw_rows = []

    if not raw_rows:
        return _collect_facturacion_dataset_from_ventas(db, periodo)

    total_leidos = len(raw_rows)
    descartes: defaultdict[str, list[PreviewExclusionEntry]] = defaultdict(list)
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

    descartes_dict = {motivo: lista for motivo, lista in descartes.items()}
    _log_summary(
        f"Facturación {periodo}",
        total_leidos,
        len(periodo_rows),
        {},
        descartes_dict,
    )
    return FacturacionDataset(periodo_rows, total_leidos, descartes_dict)


def _collect_facturacion_dataset_from_ventas(db, periodo: str) -> FacturacionDataset:
    db.ensure_column("ventas", "extra", "TEXT")
    query = (
        "SELECT v.id AS venta_id, v.fecha AS fecha_venta, v.total AS total_venta, v.extra, "
        "v.cliente_id, c.nombre AS cliente_nombre, c.nit AS cliente_nit, "
        "c.nrc AS cliente_nrc, c.dui AS cliente_dui "
        "FROM ventas AS v "
        "LEFT JOIN clientes AS c ON c.id = v.cliente_id"
    )
    filas = [dict(row) for row in db.cursor.execute(query)]
    venta_ids = [fila["venta_id"] for fila in filas]

    env_map: dict[int, dict[str, Any]] = {}
    if venta_ids:
        placeholders = ",".join(["?"] * len(venta_ids))
        env_query = (
            "SELECT id, venta_id, codigo_generacion, numero_control, estado_ui, "
            "estado_ui_tag, estado_ui_manual, respuesta "
            "FROM dte_envios WHERE venta_id IN ("
            + placeholders
            + ") ORDER BY id DESC"
        )
        for envio in db.cursor.execute(env_query, venta_ids):
            venta_id = envio["venta_id"]
            if venta_id in env_map:
                continue
            payload = dict(envio)
            respuesta = payload.get("respuesta")
            if respuesta:
                data = _load_json(respuesta) or {}
                if isinstance(data, dict):
                    payload["respuesta_json"] = data
                    payload.setdefault("codigo_generacion", data.get("codigoGeneracion"))
                    payload.setdefault("numero_control", data.get("numeroControl"))
                    if data.get("estado"):
                        payload.setdefault("estado_ui", data.get("estado"))
            env_map[venta_id] = payload

    periodo_rows: list[dict] = []
    descartes: defaultdict[str, list[PreviewExclusionEntry]] = defaultdict(list)

    for fila in filas:
        extra = _load_json(fila.get("extra")) or {}
        dte_json = _load_json(extra.get("dteJson")) or extra.get("dteJson")
        if not isinstance(dte_json, dict):
            dte_json = extra.get("dte_json")
        if not isinstance(dte_json, dict):
            dte_json = extra.get("dte_json_dict")

        row_data = {
            "venta_id": fila["venta_id"],
            "fecha_venta": fila.get("fecha_venta"),
            "extra_data": extra,
            "dte_json": dte_json if isinstance(dte_json, dict) else {},
            "envio": env_map.get(fila["venta_id"], {}),
            "cliente_nombre": fila.get("cliente_nombre"),
            "cliente_nit": fila.get("cliente_nit"),
            "cliente_nrc": fila.get("cliente_nrc"),
            "cliente_dui": fila.get("cliente_dui"),
        }
        json_path = extra.get("dteJsonPath") or extra.get("jsonPath")
        if json_path:
            row_data["json_path"] = json_path

        if isinstance(row_data["envio"].get("respuesta_json"), dict) and "dteJson" in row_data["envio"]["respuesta_json"]:
            row_data["dte_json"] = row_data["envio"]["respuesta_json"].get("dteJson") or row_data["dte_json"]

        _ensure_field(row_data, "codigo_generacion", _codigo_generacion)
        _ensure_field(row_data, "numero_control", _numero_control)
        _ensure_field(row_data, "sello_recepcion", _sello_recepcion)

        tipo = _tipo_dte(row_data)
        if tipo:
            row_data["tipo"] = tipo
        else:
            descartes["sin_tipo"].append(
                _make_exclusion_entry(row_data, detalle=f"venta {fila['venta_id']}")
            )

        fec_texto, fecha_obj = _fecha_emision(row_data)
        if fec_texto:
            row_data["fecEmi"] = fec_texto
        if not fecha_obj:
            descartes["sin_fecha"].append(
                _make_exclusion_entry(row_data, detalle="sin fecha", fecha=fec_texto)
            )
            continue

        row_data["fecha_obj"] = fecha_obj
        periodo_fila = f"{fecha_obj.year:04d}{fecha_obj.month:02d}"
        if periodo_fila != periodo:
            descartes["fuera_de_periodo"].append(
                _make_exclusion_entry(row_data, detalle=periodo_fila, fecha=fec_texto)
            )
            continue

        periodo_rows.append(row_data)

    descartes_dict = {motivo: lista for motivo, lista in descartes.items()}
    _log_summary(
        f"Facturación {periodo}",
        len(filas),
        len(periodo_rows),
        {},
        descartes_dict,
    )
    return FacturacionDataset(periodo_rows, len(filas), descartes_dict)

