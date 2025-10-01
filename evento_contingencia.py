"""Utilidades para generar eventos de contingencia MH.

Este módulo encapsula la recolección de DTE emitidos en modo de
contingencia y la construcción del payload requerido por el evento de
contingencia (schema v3).  Está diseñado para ser consumido por la capa
UI sin introducir dependencias adicionales en ``dte.py``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
import unicodedata
from typing import Any, Iterable, Mapping, Sequence
from uuid import uuid4

from paths import DTES_PENDIENTES_DIR
from utils.fecha import TZ_EL_SALVADOR
from utils.stable_json import save_file, stable_stringify

import dte


_ALLOWED_DOC_TYPES = {"01", "03", "04", "05", "06", "11", "14", "15"}


@dataclass(slots=True)
class _ContingenciaEntry:
    codigo_generacion: str
    tipo_doc: str
    timestamp: datetime


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=TZ_EL_SALVADOR)
    return value.astimezone(TZ_EL_SALVADOR)


def _coerce_datetime(value: datetime) -> datetime:
    return _normalize_datetime(value)


def _coerce_range_endpoint(value: datetime) -> datetime:
    return _normalize_datetime(value)


def _normalize_tipo_doc(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, int):
        normalized = f"{value:02d}"
    else:
        text = str(value).strip()
        if not text:
            return None
        if text.isdigit():
            normalized = f"{int(text):02d}"
        else:
            digits = "".join(ch for ch in text if ch.isdigit())
            if digits:
                normalized = f"{int(digits):02d}"
            else:
                return None
    return normalized if normalized in _ALLOWED_DOC_TYPES else None


def _maybe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except Exception:
        text = str(value).strip().lower()
        if "contingencia" in text:
            return 2
    return None


def _extract_identificacion(data: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(data, Mapping):
        return {}
    ident = data.get("identificacion")
    if isinstance(ident, Mapping):
        return ident
    ident = data.get("identificador")
    if isinstance(ident, Mapping):
        return ident
    return data


def _combine_datetime(fecha: Any, hora: Any) -> datetime | None:
    if isinstance(fecha, datetime):
        dt = fecha
        if isinstance(hora, (datetime, time)):
            dt = dt.replace(hour=hora.hour, minute=hora.minute, second=getattr(hora, "second", 0))
        return _normalize_datetime(dt)

    if isinstance(fecha, date):
        base = datetime.combine(fecha, time.min)
    else:
        fecha_str = str(fecha).strip()
        if not fecha_str:
            return None
        try:
            base = datetime.fromisoformat(fecha_str)
        except ValueError:
            try:
                base = datetime.strptime(fecha_str[:10], "%Y-%m-%d")
            except ValueError:
                return None

    if isinstance(hora, datetime):
        hora_str = hora.strftime("%H:%M:%S")
    elif isinstance(hora, time):
        hora_str = hora.strftime("%H:%M:%S")
    else:
        hora_str = str(hora or "00:00:00").strip()
        if len(hora_str) == 5:
            hora_str = f"{hora_str}:00"
    if not hora_str:
        hora_str = "00:00:00"
    try:
        parsed = datetime.strptime(f"{base.date().isoformat()} {hora_str[:8]}", "%Y-%m-%d %H:%M:%S")
    except ValueError:
        try:
            parsed = datetime.fromisoformat(f"{base.date().isoformat()}T{hora_str[:8]}")
        except ValueError:
            return None
    return _normalize_datetime(parsed)


def _is_contingencia(ident: Mapping[str, Any]) -> bool:
    tipo_operacion = _maybe_int(ident.get("tipoOperacion"))
    tipo_modelo = _maybe_int(ident.get("tipoModelo"))
    modelo_facturacion = _maybe_int(ident.get("modeloFacturacion"))
    tipo_transmision = _maybe_int(ident.get("tipoTransmision"))
    if tipo_operacion == 2 or tipo_modelo == 2:
        return True
    if modelo_facturacion == 2 and tipo_transmision == 2:
        return True
    return False


def _build_entry(data: Mapping[str, Any]) -> _ContingenciaEntry | None:
    ident = _extract_identificacion(data)
    if not ident:
        return None
    if not _is_contingencia(ident):
        return None

    codigo = ident.get("codigoGeneracion") or data.get("codigoGeneracion")
    if not codigo:
        return None
    codigo_upper = str(codigo).strip().upper()
    if not codigo_upper:
        return None

    tipo_doc = (
        _normalize_tipo_doc(ident.get("tipoDte"))
        or _normalize_tipo_doc(ident.get("tipoDocumento"))
        or _normalize_tipo_doc(data.get("tipoDte"))
    )
    if tipo_doc is None:
        return None

    timestamp = _combine_datetime(
        ident.get("fecEmi")
        or ident.get("fechaEmision")
        or data.get("fecEmi")
        or data.get("fechaEmision"),
        ident.get("horEmi")
        or ident.get("horaEmision")
        or data.get("horEmi")
        or data.get("horaEmision"),
    )
    if timestamp is None:
        return None

    return _ContingenciaEntry(codigo_upper, tipo_doc, timestamp)


def _iter_dtes_from_db(db: Any) -> Iterable[Mapping[str, Any]]:
    if db is None or not hasattr(db, "get_dte_pendientes"):
        return []
    try:
        rows = db.get_dte_pendientes()
    except Exception:
        return []
    extracted: list[Mapping[str, Any]] = []
    for row in rows or []:
        dte_json = None
        if isinstance(row, Mapping):
            dte_json = row.get("dte_json")
        if isinstance(dte_json, Mapping):
            extracted.append(dte_json)
        elif isinstance(dte_json, str):
            try:
                extracted.append(json.loads(dte_json, parse_float=Decimal))
            except Exception:
                continue
    return extracted


def _iter_dtes_from_fs() -> Iterable[Mapping[str, Any]]:
    base = Path(DTES_PENDIENTES_DIR)
    if not base.exists():
        return []
    matches: list[Mapping[str, Any]] = []
    try:
        json_paths = list(base.rglob("documento.json"))
    except Exception:
        return []
    for path in json_paths:
        try:
            with path.open("r", encoding="utf-8") as fh:
                matches.append(json.load(fh, parse_float=Decimal))
        except Exception:
            continue
    return matches


_PROD_KEYWORDS = {"prod", "produccion", "production"}
_TEST_KEYWORDS = {"pruebas", "test", "sandbox"}


def _normalize_ambiente_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, int):
        return f"{value:02d}"

    text = str(value).strip()
    if not text:
        return ""

    normalized = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _get_ambiente() -> str:
    datos = dte._load_datos_negocio()
    ambiente_value = (datos.get("dte_api") or {}).get("ambiente")
    normalized = _normalize_ambiente_value(ambiente_value)

    if not normalized:
        return "00"

    digits_only = "".join(ch for ch in normalized if ch.isdigit())
    if digits_only:
        try:
            number = int(digits_only)
        except ValueError:
            number = None
        if number == 1:
            return "01"
        if number == 0:
            return "00"

    collapsed = "".join(ch for ch in normalized if ch.isalnum())
    if any(keyword in collapsed for keyword in _PROD_KEYWORDS):
        return "01"
    if any(keyword in collapsed for keyword in _TEST_KEYWORDS):
        return "00"

    return "00"


def build_evento_contingencia(
    *,
    tipo_contingencia: int,
    motivo: str | None,
    f_inicio: datetime,
    f_fin: datetime,
    dtes: Sequence[Mapping[str, Any]],
) -> dict:
    """Construye el payload JSON del evento de contingencia.

    Parameters
    ----------
    tipo_contingencia:
        Código CAT-005 entre 1 y 5.
    motivo:
        Texto descriptivo requerido únicamente cuando ``tipo_contingencia``
        es 5.  Para los tipos 1-4 debe omitirse (``None``).
    f_inicio, f_fin:
        Rango horario en el que se emitieron los DTE en contingencia.
    dtes:
        Colección de DTE emitidos en contingencia que se incluirán en el
        detalle del evento.
    """

    if tipo_contingencia not in {1, 2, 3, 4, 5}:
        raise ValueError("tipo_contingencia inválido")

    motivo_text = None
    if tipo_contingencia == 5:
        if not isinstance(motivo, str) or not motivo.strip():
            raise ValueError("motivo requerido para tipo_contingencia 5")
        motivo_text = motivo.strip()
        if len(motivo_text) > 500:
            raise ValueError("motivo excede 500 caracteres")
    elif motivo is not None:
        motivo_text = None

    now = datetime.now(TZ_EL_SALVADOR)
    codigo_generacion = str(uuid4()).upper()

    inicio = _coerce_range_endpoint(f_inicio)
    fin = _coerce_range_endpoint(f_fin)
    if fin < inicio:
        inicio, fin = fin, inicio

    detalle: list[dict[str, Any]] = []
    for item in dtes:
        if not isinstance(item, Mapping):
            continue
        codigo = item.get("codigoGeneracion") or item.get("codigo")
        if not codigo:
            continue
        codigo_upper = str(codigo).strip().upper()
        if not codigo_upper:
            continue
        tipo_doc = (
            _normalize_tipo_doc(item.get("tipoDoc"))
            or _normalize_tipo_doc(item.get("tipoDte"))
            or _normalize_tipo_doc(item.get("tipoDocumento"))
        )
        if tipo_doc is None:
            continue
        detalle.append(
            {
                "codigoGeneracion": codigo_upper,
                "tipoDoc": tipo_doc,
            }
        )

    detalle = detalle[:1000]
    for idx, item in enumerate(detalle, start=1):
        item["noItem"] = idx

    payload = {
        "identificacion": {
            "version": 3,
            "ambiente": _get_ambiente(),
            "codigoGeneracion": codigo_generacion,
            "fTransmision": now.strftime("%Y-%m-%d"),
            "hTransmision": now.strftime("%H:%M:%S"),
        },
        "motivo": {
            "tipo": tipo_contingencia,
            "motivo": motivo_text if tipo_contingencia == 5 else None,
            "fInicio": inicio.strftime("%Y-%m-%d"),
            "hInicio": inicio.strftime("%H:%M:%S"),
            "fFin": fin.strftime("%Y-%m-%d"),
            "hFin": fin.strftime("%H:%M:%S"),
        },
        "detalleDTE": detalle,
    }
    return payload


def collect_contingencia_dtes(
    db: Any,
    f_inicio: datetime,
    f_fin: datetime,
) -> list[dict[str, Any]]:
    """Recopila DTE emitidos en contingencia en el rango especificado."""

    inicio = _coerce_range_endpoint(f_inicio)
    fin = _coerce_range_endpoint(f_fin)
    if fin < inicio:
        inicio, fin = fin, inicio

    registros: dict[str, _ContingenciaEntry] = {}

    for source in (_iter_dtes_from_db(db), _iter_dtes_from_fs()):
        for dte_data in source:
            if not isinstance(dte_data, Mapping):
                continue
            entry = _build_entry(dte_data)
            if entry is None:
                continue
            timestamp = _coerce_datetime(entry.timestamp)
            if timestamp < inicio or timestamp > fin:
                continue
            existing = registros.get(entry.codigo_generacion)
            if existing is None or timestamp < existing.timestamp:
                registros[entry.codigo_generacion] = _ContingenciaEntry(
                    entry.codigo_generacion, entry.tipo_doc, timestamp
                )

    ordenados = sorted(registros.values(), key=lambda e: e.timestamp)
    return [
        {
            "codigoGeneracion": entry.codigo_generacion,
            "tipoDoc": entry.tipo_doc,
            "timestamp": entry.timestamp,
        }
        for entry in ordenados
    ]


def make_event_filename(payload: Mapping[str, Any]) -> str:
    """Genera un nombre de archivo sugerido para el evento."""

    ident = payload.get("identificacion") if isinstance(payload, Mapping) else None
    if not isinstance(ident, Mapping):
        raise ValueError("payload inválido")
    f_transmision = str(ident.get("fTransmision") or "").strip()
    codigo = str(ident.get("codigoGeneracion") or "").strip().upper()
    if not f_transmision or not codigo:
        raise ValueError("payload incompleto para nombre de archivo")
    return f"evento_contingencia_{f_transmision}_{codigo}.json"


def save_evento_contingencia_json(payload: Mapping[str, Any], path: str) -> str:
    """Guarda el payload en disco utilizando JSON estable."""

    content = stable_stringify(payload, indent=2)
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    save_file(str(output_path), content)
    return str(output_path)


__all__ = [
    "build_evento_contingencia",
    "collect_contingencia_dtes",
    "make_event_filename",
    "save_evento_contingencia_json",
]
