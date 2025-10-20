"""Utilidades compartidas para el Plan B de notas electrónicas.

Este módulo encapsula la lógica para reconstruir el DTE de origen
aprovechando distintas fuentes (snapshot, JSON original y datos de
configuración) y ejecutar las validaciones previas requeridas por los
generadores de notas de crédito y débito.
"""

from __future__ import annotations

import json
import logging
import os
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Iterable, Mapping, Sequence

from paths import DTES_DIR
from utils.fecha import TZ_EL_SALVADOR, fecha_ddmmaaaa
from utils.snapshot import Snapshot, SnapshotNotFoundError, normalize_snapshot
from utils.stable_json import hash_json
from utils.versioned_dte import ensure_version

try:  # pragma: no cover - para anotaciones de tipo
    from typing import TYPE_CHECKING
except ImportError:  # pragma: no cover
    TYPE_CHECKING = False

if TYPE_CHECKING:  # pragma: no cover
    from db import DB


_SECTIONS = (
    "emisor",
    "receptor",
    "documentoRelacionado",
    "identificacion",
    "resumen",
    "cuerpoDocumento",
)


@dataclass(slots=True)
class OrigenResult:
    """Resultado de la preparación del DTE de origen."""

    data: dict[str, Any]
    section_sources: dict[str, str]
    source_used: str
    snapshot: Snapshot | None
    json_path: str | None
    json_payload: dict[str, Any] | None
    json_used: bool
    config_used: bool
    detalles: dict[str, Any]
    venta_extra: dict[str, Any]
    expected_ident: dict[str, str]


def prepare_dte_origen(
    *,
    db: "DB",
    nota: Mapping[str, Any],
    venta: Mapping[str, Any] | None,
    venta_id: int | None,
    tipo_doc: str,
    ambiente: str,
    strict: bool,
    usar_fallback_json: bool,
    nota_id: int | None,
    regenerate: Callable[[], Mapping[str, Any]] | None,
    logger: logging.Logger,
) -> OrigenResult:
    """Obtiene y fusiona la información del DTE de origen."""

    detalles = _parse_mapping(nota.get("detalles"))
    venta_extra = _parse_mapping(venta.get("extra") if venta else None)

    snapshot = db.get_snapshot_by_venta(venta_id) if venta_id is not None else None
    snapshot_payload = normalize_snapshot(snapshot.payload) if snapshot else None

    json_path = None
    json_payload: dict[str, Any] | None = None
    if usar_fallback_json:
        json_path = _resolve_json_path(db, venta_id, detalles, venta, venta_extra)
        if json_path:
            json_payload = _load_json_payload(json_path, logger)

    if snapshot is None and strict:
        if json_payload is None or not usar_fallback_json:
            raise SnapshotNotFoundError(venta_id or 0, nota_id)
        logger.warning(
            "STRICT_SNAPSHOT activo sin snapshot; usando respaldo JSON nota_id=%s venta_id=%s",
            nota_id,
            venta_id,
        )

    config_payload: dict[str, Any] | None = None
    if regenerate is not None:
        try:
            regenerated = regenerate()
        except Exception:  # pragma: no cover - se reporta en logs
            logger.exception(
                "No se pudo regenerar el DTE base desde la configuración", extra={"nota_id": nota_id}
            )
        else:
            if isinstance(regenerated, Mapping):
                try:
                    config_payload = normalize_snapshot(regenerated)
                except TypeError:
                    config_payload = None

    sources: list[tuple[str, dict[str, Any]]] = []
    if snapshot_payload:
        sources.append(("snapshot", snapshot_payload))
    if json_payload:
        sources.append(("json", json_payload))
    if config_payload:
        sources.append(("config", config_payload))

    if not sources:
        if strict:
            raise SnapshotNotFoundError(venta_id or 0, nota_id)
        raise RuntimeError("No se encontraron datos para el DTE de origen")

    source_used = sources[0][0]
    base_payload = deepcopy(sources[0][1])
    section_sources: dict[str, str] = {}
    json_used = source_used == "json"
    config_used = source_used == "config"

    for section in _SECTIONS:
        first_name, first_value = _first_section_with_data(sources, section)
        if first_name is None or first_value is None:
            section_sources[section] = ""
            base_payload.pop(section, None)
            continue
        section_sources[section] = first_name
        if section not in base_payload or not _has_content(base_payload.get(section)):
            base_payload[section] = deepcopy(first_value)

        target_section = base_payload.get(section)
        for name, payload in sources:
            if name == first_name:
                continue
            updated = _merge_section(target_section, payload.get(section))
            if updated:
                if name == "json":
                    json_used = True
                elif name == "config":
                    config_used = True

    ident = _ensure_mapping(base_payload.get("identificacion"))
    base_payload["identificacion"] = ident
    ident["ambiente"] = str(ambiente)
    codigo = ident.get("codigoGeneracion")
    if isinstance(codigo, str):
        ident["codigoGeneracion"] = codigo.strip().upper()
    numero = ident.get("numeroControl")
    if isinstance(numero, str):
        ident["numeroControl"] = numero.strip().upper()

    _ensure_documento_relacionado(base_payload, section_sources, tipo_doc)

    expected_ident = _collect_expected_ident(
        snapshot_payload,
        json_payload,
        config_payload,
        detalles,
        venta_extra,
    )

    return OrigenResult(
        data=base_payload,
        section_sources=section_sources,
        source_used=source_used,
        snapshot=snapshot,
        json_path=json_path,
        json_payload=json_payload,
        json_used=json_used,
        config_used=config_used,
        detalles=detalles,
        venta_extra=venta_extra,
        expected_ident=expected_ident,
    )


def prevalidate_dte_origen(
    data: Mapping[str, Any],
    *,
    ambiente: str,
    nota_tipo: str,
    logger: logging.Logger,
) -> None:
    """Ejecuta las validaciones previas antes de generar/enviar la nota."""

    missing: list[str] = []

    emisor = _ensure_mapping(data.get("emisor"))
    if not emisor:
        missing.append("emisor")
    else:
        for field in (
            "nit",
            "nrc",
            "codActividad",
            "descActividad",
            "nombre",
            "nombreComercial",
            "tipoEstablecimiento",
            "telefono",
            "correo",
        ):
            if _is_missing_field(emisor.get(field)):
                missing.append(f"emisor.{field}")
        direccion = _ensure_mapping(emisor.get("direccion"))
        if not direccion:
            missing.append("emisor.direccion")
        else:
            for field in ("departamento", "municipio", "complemento"):
                if _is_missing_field(direccion.get(field)):
                    missing.append(f"emisor.direccion.{field}")

    receptor = _ensure_mapping(data.get("receptor"))
    if not receptor:
        missing.append("receptor")
    else:
        if _is_missing_field(receptor.get("nombre")):
            missing.append("receptor.nombre")
        identificadores = (
            receptor.get("nit"),
            receptor.get("nrc"),
            receptor.get("numeroDocumento"),
            receptor.get("numDocumento"),
        )
        if not any(not _is_missing_field(value) for value in identificadores):
            missing.append("receptor.identificacion")
        if not _is_missing_field(receptor.get("nrc")):
            for field in ("codActividad", "descActividad"):
                if _is_missing_field(receptor.get(field)):
                    missing.append(f"receptor.{field}")

    doc_rel = data.get("documentoRelacionado")
    if not (
        isinstance(doc_rel, Sequence)
        and not isinstance(doc_rel, (str, bytes, bytearray))
        and doc_rel
    ):
        missing.append("documentoRelacionado")
    else:
        rel = _ensure_mapping(doc_rel[0])
        tipo = str(rel.get("tipoDocumento") or "").zfill(2)
        numero_doc = str(rel.get("numeroDocumento") or "").strip()
        fecha_rel = rel.get("fechaEmision")
        if tipo not in _allowed_tipo_rel(nota_tipo):
            missing.append("documentoRelacionado.tipoDocumento")
        if len(numero_doc) < 8:
            missing.append("documentoRelacionado.numeroDocumento")
        if _is_missing_field(fecha_rel):
            missing.append("documentoRelacionado.fechaEmision")

    identificacion = _ensure_mapping(data.get("identificacion"))
    numero_control_missing = False
    if not identificacion:
        missing.append("identificacion")
    else:
        ambiente_val = str(identificacion.get("ambiente") or "").zfill(2)
        if ambiente_val not in {"00", "01"}:
            missing.append("identificacion.ambiente")
        elif ambiente_val != str(ambiente).zfill(2):
            missing.append("identificacion.ambiente")
        codigo = identificacion.get("codigoGeneracion")
        numero = identificacion.get("numeroControl")
        if _is_missing_field(codigo) and _is_missing_field(numero):
            missing.append("identificacion.codigoGeneracion")
        if _is_missing_field(numero):
            missing.append("identificacion.numeroControl")
            numero_control_missing = True
        if _is_missing_field(identificacion.get("fecEmi")) and _is_missing_field(
            identificacion.get("fechaEmision")
        ):
            missing.append("identificacion.fecEmi")

    resumen = _ensure_mapping(data.get("resumen"))
    if not resumen:
        missing.append("resumen")
    else:
        if _is_missing_field(resumen.get("montoTotalOperacion")) and _is_missing_field(
            resumen.get("totalPagar")
        ):
            missing.append("resumen.montoTotalOperacion")

    cuerpo = data.get("cuerpoDocumento")
    if not isinstance(cuerpo, Sequence) or not cuerpo:
        missing.append("cuerpoDocumento")

    if missing:
        logger.error("Pre-validación fallida: %s", ", ".join(missing))
        if numero_control_missing:
            raise ValueError("Falta numeroControl del DTE origen")
        if len(missing) == 1:
            raise ValueError(f"Falta {missing[0]}")
        raise ValueError("Faltan campos: " + ", ".join(missing))

    logger.info("Pre-validación completada sin errores")


def rebuild_snapshot_from_json(
    db: "DB",
    result: OrigenResult,
    *,
    nota_id: int | None,
    venta_id: int | None,
    logger: logging.Logger,
) -> dict[str, Any]:
    """Regenera la snapshot canónica cuando la fuente primaria fue JSON."""

    if result.source_used != "json" or not result.json_payload:
        return {"rebuilt": False}

    ident = _ensure_mapping(result.data.get("identificacion"))
    codigo = str(ident.get("codigoGeneracion") or "").strip().upper()
    numero = str(ident.get("numeroControl") or "").strip().upper()

    expected_codigo = result.expected_ident.get("codigoGeneracion")
    expected_numero = result.expected_ident.get("numeroControl")

    if expected_codigo and codigo and codigo != expected_codigo.upper():
        conflict = (
            f"codigoGeneracion JSON {codigo} ≠ esperado {expected_codigo.upper()}"
        )
        _registrar_conflicto(db, nota_id, conflict, logger)
        return {"rebuilt": False, "conflict": conflict}
    if expected_numero and numero and numero != expected_numero.upper():
        conflict = (
            f"numeroControl JSON {numero} ≠ esperado {expected_numero.upper()}"
        )
        _registrar_conflicto(db, nota_id, conflict, logger)
        return {"rebuilt": False, "conflict": conflict}

    if not codigo:
        logger.warning("No se pudo regenerar snapshot: falta codigoGeneracion")
        return {"rebuilt": False}

    try:
        version_dir, existing_hash = ensure_version(result.data, DTES_DIR)
    except Exception:  # pragma: no cover - best effort
        logger.exception(
            "No se pudo regenerar snapshot para nota_id=%s venta_id=%s",
            nota_id,
            venta_id,
        )
        return {"rebuilt": False}

    json_path = os.path.join(version_dir, "documento.json")
    timestamp = datetime.now(TZ_EL_SALVADOR).isoformat()
    snapshot_hash = existing_hash or hash_json(result.data)

    detalle_update = {
        "snapshot_path": json_path,
        "snapshot_hash": snapshot_hash,
        "snapshot_regenerado_en": timestamp,
    }
    if nota_id is not None:
        try:
            db.update_nota_detalles(nota_id, detalle_update)
        except Exception:  # pragma: no cover - persist best effort
            logger.exception(
                "No se pudo actualizar detalles de nota %s con snapshot regenerado",
                nota_id,
            )
    if venta_id is not None:
        try:
            db.update_venta_extra(venta_id, {"dteJsonPath": json_path})
        except Exception:  # pragma: no cover
            logger.exception(
                "No se pudo actualizar dteJsonPath de venta %s con snapshot regenerado",
                venta_id,
            )

    logger.info(
        "Snapshot regenerada en %s (hash=%s) para nota_id=%s venta_id=%s",
        json_path,
        snapshot_hash,
        nota_id,
        venta_id,
    )
    return {
        "rebuilt": True,
        "path": json_path,
        "hash": snapshot_hash,
        "timestamp": timestamp,
    }


def _registrar_conflicto(db: "DB", nota_id: int | None, mensaje: str, logger: logging.Logger) -> None:
    logger.error("Conflicto al regenerar snapshot: %s", mensaje)
    if nota_id is None:
        return
    try:
        db.update_nota_detalles(nota_id, {"snapshot_conflict": mensaje})
    except Exception:  # pragma: no cover - best effort
        logger.exception("No se pudo registrar conflicto de snapshot para nota %s", nota_id)


def _resolve_json_path(
    db: "DB",
    venta_id: int | None,
    detalles: Mapping[str, Any],
    venta: Mapping[str, Any] | None,
    venta_extra: Mapping[str, Any],
) -> str | None:
    candidates: list[str] = []
    candidates.extend(_candidate_paths(detalles))
    candidates.extend(_candidate_paths(venta_extra))
    if venta:
        candidates.extend(_candidate_paths(venta))
    if venta_id is not None:
        try:
            pdf_path = db.get_factura_pdf(venta_id)
        except Exception:  # pragma: no cover - acceso a BD best effort
            pdf_path = None
        if pdf_path:
            candidates.append(os.path.splitext(pdf_path)[0] + ".json")
        try:
            ticket_path = db.get_ticket_pdf(venta_id)
        except Exception:  # pragma: no cover
            ticket_path = None
        if ticket_path:
            candidates.append(os.path.splitext(ticket_path)[0] + ".json")

    seen: set[str] = set()
    for path in candidates:
        try:
            normalized = os.path.abspath(os.fspath(path))
        except (TypeError, ValueError, OSError):
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        if os.path.exists(normalized):
            return normalized
    return None


def _candidate_paths(data: Mapping[str, Any] | None) -> Iterable[str]:
    if not isinstance(data, Mapping):
        return []
    candidates: list[str] = []
    for key in ("json_path", "jsonPath", "json", "dteJsonPath", "sourceJson"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            candidates.append(value.strip())
    factura = data.get("factura")
    if isinstance(factura, Mapping):
        candidates.extend(_candidate_paths(factura))
    return candidates


def _parse_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except Exception:
            return {}
        if isinstance(parsed, Mapping):
            return dict(parsed)
    return {}


def _load_json_payload(path: str, logger: logging.Logger) -> dict[str, Any] | None:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except Exception:
        logger.exception("No se pudo leer respaldo JSON en %s", path)
        return None
    payload = _extract_payload(raw)
    if not isinstance(payload, Mapping):
        logger.warning("JSON en %s no contiene un DTE válido", path)
        return None
    return normalize_snapshot(payload)


def _extract_payload(raw: Any) -> Mapping[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    for key in ("dteJson", "dte_json", "dte"):
        nested = raw.get(key)
        if isinstance(nested, Mapping):
            raw = nested
            break
    return raw if isinstance(raw, Mapping) else None


def _first_section_with_data(
    sources: Sequence[tuple[str, Mapping[str, Any]]],
    section: str,
) -> tuple[str | None, Any | None]:
    for name, payload in sources:
        value = payload.get(section)
        if _has_content(value):
            return name, value
    return None, None


def _merge_section(target: Any, source: Any) -> bool:
    if isinstance(target, Mapping) and isinstance(source, Mapping):
        return _merge_dict(target, source)
    if isinstance(target, list) and isinstance(source, Sequence):
        return _merge_list(target, source)
    return False


def _merge_dict(target: Mapping[str, Any], source: Mapping[str, Any]) -> bool:
    changed = False
    target_dict = target  # type: ignore[assignment]
    for key, value in source.items():
        if isinstance(value, Mapping):
            current = target_dict.get(key)
            if isinstance(current, Mapping):
                if _merge_dict(current, value):
                    changed = True
            elif _is_missing_field(current):
                target_dict[key] = deepcopy(value)
                changed = True
        else:
            current = target_dict.get(key)
            if key not in target_dict or _is_missing_field(current):
                target_dict[key] = deepcopy(value)
                changed = True
    return changed


def _merge_list(target: list[Any], source: Sequence[Any]) -> bool:
    changed = False
    for idx, item in enumerate(source):
        if isinstance(item, Mapping):
            if idx < len(target) and isinstance(target[idx], Mapping):
                if _merge_dict(target[idx], item):
                    changed = True
            elif idx < len(target) and _is_missing_field(target[idx]):
                target[idx] = deepcopy(item)
                changed = True
            elif idx >= len(target):
                target.append(deepcopy(item))
                changed = True
        else:
            if idx >= len(target):
                target.append(deepcopy(item))
                changed = True
    return changed


def _has_content(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Mapping):
        return any(_has_content(v) for v in value.values())
    if isinstance(value, Sequence):
        return bool(len(value))
    return True


def _ensure_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _is_missing_field(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, set)):
        return len(value) == 0
    if isinstance(value, Mapping):
        return len(value) == 0
    return False


def _collect_expected_ident(*sources: Mapping[str, Any] | None) -> dict[str, str]:
    expected: dict[str, str] = {}
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        ident = source.get("identificacion") if "identificacion" in source else source
        if isinstance(ident, Mapping):
            codigo = ident.get("codigoGeneracion") or ident.get("codigo_generacion")
            numero = ident.get("numeroControl") or ident.get("numero_control")
            ambiente = ident.get("ambiente")
            if codigo:
                expected["codigoGeneracion"] = str(codigo).strip().upper()
            if numero:
                expected["numeroControl"] = str(numero).strip().upper()
            if ambiente:
                expected["ambiente"] = str(ambiente)
        codigo = source.get("codigoGeneracion")
        numero = source.get("numeroControl")
        if codigo:
            expected["codigoGeneracion"] = str(codigo).strip().upper()
        if numero:
            expected["numeroControl"] = str(numero).strip().upper()
    return expected


def _allowed_tipo_rel(nota_tipo: str) -> set[str]:
    if nota_tipo == "debito":
        return {"01", "03", "07"}
    return {"01", "02", "03", "04", "05", "06", "07"}


def _ensure_documento_relacionado(
    payload: dict[str, Any],
    section_sources: dict[str, str],
    tipo_doc: str,
) -> None:
    doc_rel = payload.get("documentoRelacionado")
    if isinstance(doc_rel, Mapping):
        payload["documentoRelacionado"] = [dict(doc_rel)]
        return
    if isinstance(doc_rel, Sequence) and not isinstance(doc_rel, (str, bytes, bytearray)):
        if doc_rel:
            return
    derived = _derive_documento_relacionado(payload, tipo_doc)
    if derived:
        payload["documentoRelacionado"] = derived
        section_sources["documentoRelacionado"] = (
            section_sources.get("documentoRelacionado") or "derivado"
        )


def _derive_documento_relacionado(
    payload: Mapping[str, Any],
    tipo_doc: str,
) -> list[dict[str, Any]] | None:
    ident = _ensure_mapping(payload.get("identificacion"))
    if not ident:
        return None
    codigo = ident.get("codigoGeneracion")
    numero_control = ident.get("numeroControl")
    numero_documento = str(codigo or numero_control or "").strip()
    if not numero_documento:
        return None
    tipo_generacion = 2 if codigo else 1
    tipo_rel = _normalize_doc_rel_tipo(ident.get("tipoDte"), tipo_doc, payload)
    fecha_rel = _format_doc_rel_fecha(
        ident.get("fechaEmision") or ident.get("fecEmi")
    )
    if not fecha_rel:
        return None
    return [
        {
            "tipoDocumento": tipo_rel,
            "tipoGeneracion": tipo_generacion,
            "numeroDocumento": numero_documento,
            "fechaEmision": fecha_rel,
        }
    ]


def _normalize_doc_rel_tipo(tipo_dte: Any, tipo_doc: str, payload: Mapping[str, Any]) -> str:
    tipo: str | None
    if isinstance(tipo_dte, int):
        tipo = f"{tipo_dte:02d}"
    elif isinstance(tipo_dte, str):
        stripped = tipo_dte.strip()
        if stripped.isdigit() and len(stripped) <= 2:
            tipo = f"{int(stripped):02d}"
        elif stripped:
            tipo = stripped.zfill(2) if len(stripped) <= 2 else stripped
        else:
            tipo = None
    else:
        tipo = None

    if not tipo:
        tipo = str(tipo_doc or "").strip()
    if not tipo:
        receptor = _ensure_mapping(payload.get("receptor"))
        tipo = "03" if receptor.get("nrc") else "01"
    if tipo.isdigit() and len(tipo) <= 2:
        return f"{int(tipo):02d}"
    return tipo


def _format_doc_rel_fecha(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        formatted = fecha_ddmmaaaa(value)
        if formatted:
            return formatted
        return value.strip() or None
    return fecha_ddmmaaaa(value)


__all__ = [
    "OrigenResult",
    "prepare_dte_origen",
    "prevalidate_dte_origen",
    "rebuild_snapshot_from_json",
]
