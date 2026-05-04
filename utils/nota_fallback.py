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
from utils.identificacion import is_valid_nit
from utils.sanitize import solo_digitos
from utils.snapshot import Snapshot, SnapshotNotFoundError, normalize_snapshot
from utils.stable_json import hash_json
from utils.versioned_dte import ensure_version

from dte import _load_datos_negocio, _max_nombre_length, normalize_nombre

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


def ensure_emisor_completo(
    emisor: Mapping[str, Any] | None, *, tipo_dte: str = "05"
) -> dict[str, Any]:
    """Return an ``emisor`` dictionary populated with mandatory fields."""

    datos_negocio = _load_datos_negocio() or {}
    result: dict[str, Any] = dict(emisor or {})

    def _clean_text(value: Any) -> str | None:
        if value in (None, ""):
            return None
        if isinstance(value, str):
            text = value.strip()
            return text or None
        return str(value)

    def _valid_nrc(value: Any) -> str | None:
        digits = solo_digitos(value)
        if not digits or digits == "0":
            return None
        if len(digits) < 4:
            return None
        return digits

    def _valid_nit(value: Any) -> str | None:
        digits = solo_digitos(value)
        if digits and is_valid_nit(digits):
            return digits
        return None

    nit = _valid_nit(result.get("nit")) or _valid_nit(datos_negocio.get("nit"))
    if nit:
        result["nit"] = nit

    nrc = _valid_nrc(result.get("nrc")) or _valid_nrc(datos_negocio.get("nrc"))
    if nrc:
        result["nrc"] = nrc

    cod_actividad = (
        _clean_text(result.get("codActividad"))
        or _clean_text(datos_negocio.get("codActividad"))
        or _clean_text(datos_negocio.get("cod_giro"))
    )
    if cod_actividad:
        result["codActividad"] = cod_actividad

    desc_actividad = (
        _clean_text(result.get("descActividad"))
        or _clean_text(datos_negocio.get("descActividad"))
        or _clean_text(datos_negocio.get("desc_giro"))
        or _clean_text(datos_negocio.get("descripcionActividad"))
    )
    if desc_actividad:
        result["descActividad"] = desc_actividad

    nombre_comercial = (
        _clean_text(result.get("nombreComercial"))
        or _clean_text(datos_negocio.get("nombreComercial"))
    )
    if nombre_comercial is not None:
        result["nombreComercial"] = nombre_comercial

    telefono = _clean_text(result.get("telefono")) or _clean_text(
        datos_negocio.get("telefono")
    )
    if telefono:
        result["telefono"] = telefono

    correo = _clean_text(result.get("correo"))
    if correo and "@" not in correo:
        correo = None
    if correo is None:
        fallback_correo = _clean_text(datos_negocio.get("correo"))
        if fallback_correo and "@" in fallback_correo:
            correo = fallback_correo
    if correo:
        result["correo"] = correo

    tipo_est = _clean_text(result.get("tipoEstablecimiento")) or _clean_text(
        datos_negocio.get("tipoEstablecimiento")
    )
    tipo_est = str(tipo_est).zfill(2) if tipo_est else "01"
    result["tipoEstablecimiento"] = tipo_est

    nombre_candidates = (
        result.get("nombre"),
        result.get("razonSocial"),
        datos_negocio.get("razonSocial"),
        datos_negocio.get("denominacionSocial"),
        datos_negocio.get("nombre"),
        datos_negocio.get("nombreComercial"),
    )
    max_length = _max_nombre_length(tipo_dte, "emisor")
    for candidate in nombre_candidates:
        nombre_norm = normalize_nombre(candidate, max_length=max_length)
        if nombre_norm:
            result["nombre"] = nombre_norm
            break

    direccion_actual = result.get("direccion")
    if isinstance(direccion_actual, Mapping):
        direccion = dict(direccion_actual)
    else:
        direccion = {}
    direccion_config = datos_negocio.get("direccion")
    if isinstance(direccion_config, Mapping):
        for field in ("departamento", "municipio", "complemento"):
            if not _clean_text(direccion.get(field)):
                fallback = _clean_text(direccion_config.get(field))
                if fallback:
                    direccion[field] = fallback
    if direccion:
        result["direccion"] = direccion

    for key in ("codEstable", "codEstableMH", "codPuntoVenta", "codPuntoVentaMH"):
        value = _clean_text(result.get(key)) or _clean_text(datos_negocio.get(key))
        if value:
            result[key] = value

    return result


def _normalize_ambiente_str(value: Any) -> str | None:
    """Return a canonical representation (``00``/``01``) for ``value`` when possible."""

    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit() and len(text) <= 2:
        return f"{int(text):02d}"
    lowered = text.lower()
    if lowered.startswith("prod"):
        return "01"
    if lowered.startswith("pru"):
        return "00"
    return text


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
    venta_credito_fiscal: dict[str, Any]
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
    venta_credito_fiscal: Mapping[str, Any] | None = None,
    logger: logging.Logger,
) -> OrigenResult:
    """Obtiene y fusiona la información del DTE de origen."""

    detalles = _parse_mapping(nota.get("detalles"))
    venta_extra = _parse_mapping(venta.get("extra") if venta else None)
    venta_cf = _parse_mapping(venta_credito_fiscal)

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
    ambiente_normalizado = _normalize_ambiente_str(ambiente) or "00"
    ident["ambiente"] = ambiente_normalizado
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

    _complete_receptor_from_cliente(
        base_payload,
        db=db,
        nota=nota,
        venta=venta,
        venta_extra=venta_extra,
        logger=logger,
    )
    complete_receptor_from_metadata(
        base_payload,
        nota=nota,
        venta=venta,
        venta_credito_fiscal=venta_cf,
        venta_extra=venta_extra,
        detalles=detalles,
        logger=logger,
    )

    expected_ambiente = _normalize_ambiente_str(expected_ident.get("ambiente"))
    if expected_ambiente and expected_ambiente != ambiente_normalizado:
        logger.info(
            "Ambiente origen %s ≠ solicitado %s; se conserva %s",
            expected_ambiente,
            ambiente_normalizado,
            ambiente_normalizado,
        )
    logger.info(
        "Ambiente consolidado para DTE origen: %s (esperado=%s)",
        ambiente_normalizado,
        expected_ambiente or "desconocido",
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
        venta_credito_fiscal=venta_cf,
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
        numero_control_val = str(numero or "").strip()
        if not numero_control_val:
            logger.error("Pre-validación fallida: Falta numeroControl del DTE origen")
            raise ValueError("Falta numeroControl del DTE origen")
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

    def _is_note_tipo(tipo_val: Any) -> bool:
        text = str(tipo_val or "").strip().lower()
        return "nota" in text

    if venta_id is not None:
        # Priorizamos JSON de factura base (CF/CCF) sobre notas asociadas a la
        # misma venta para evitar mezclar la fuente de una NC/ND previa.
        try:
            rows = db.cursor.execute(
                "SELECT ruta, tipo FROM facturas_pdf WHERE venta_id=? ORDER BY fecha_creacion DESC, id DESC",
                (venta_id,),
            ).fetchall()
        except Exception:  # pragma: no cover - acceso a BD best effort
            rows = []

        base_rows: list[Any] = []
        note_rows: list[Any] = []
        for row in rows:
            try:
                tipo_val = row["tipo"]
                ruta_val = row["ruta"]
            except Exception:
                try:
                    ruta_val = row[0]
                    tipo_val = row[1] if len(row) > 1 else ""
                except Exception:
                    continue
            if not ruta_val:
                continue
            if _is_note_tipo(tipo_val):
                note_rows.append((ruta_val, tipo_val))
            else:
                base_rows.append((ruta_val, tipo_val))

        for ruta_val, _tipo_val in base_rows + note_rows:
            candidates.append(os.path.splitext(os.fspath(ruta_val))[0] + ".json")

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


def _complete_receptor_from_cliente(
    payload: dict[str, Any],
    *,
    db: "DB",
    nota: Mapping[str, Any] | None,
    venta: Mapping[str, Any] | None,
    venta_extra: Mapping[str, Any],
    logger: logging.Logger,
) -> None:
    receptor = _ensure_mapping(payload.get("receptor"))
    if not receptor:
        return

    cliente_id = _extract_cliente_id(venta, nota, venta_extra)
    if cliente_id is None:
        return

    getter = getattr(db, "get_cliente", None)
    if not callable(getter):
        return

    try:
        cliente = getter(cliente_id)
    except Exception:  # pragma: no cover - defensivo
        logger.exception(
            "No se pudo obtener información del cliente %s para completar el receptor",
            cliente_id,
        )
        return

    if not isinstance(cliente, Mapping):
        return

    updated: list[str] = []

    nrc_actual = str(receptor.get("nrc") or "").strip()
    nrc_cliente = _first_not_empty(cliente.get("nrc"))
    if not nrc_actual or nrc_actual == "0":
        receptor["nrc"] = nrc_cliente if nrc_cliente else None
        if nrc_cliente:
            updated.append("nrc")

    cod_cliente = _first_not_empty(
        cliente.get("codActividad"),
        cliente.get("cod_actividad"),
    )
    if _is_missing_field(receptor.get("codActividad")) and cod_cliente:
        receptor["codActividad"] = cod_cliente
        updated.append("codActividad")

    desc_cliente = _first_not_empty(
        cliente.get("descActividad"),
        cliente.get("giro"),
    )
    if _is_missing_field(receptor.get("descActividad")) and desc_cliente:
        receptor["descActividad"] = desc_cliente
        updated.append("descActividad")

    if updated:
        payload["receptor"] = receptor
        logger.info(
            "Receptor completado desde cliente %s con campos: %s",
            cliente_id,
            ", ".join(updated),
        )


def complete_receptor_from_metadata(
    payload: dict[str, Any],
    *,
    nota: Mapping[str, Any] | None,
    venta: Mapping[str, Any] | None,
    venta_credito_fiscal: Mapping[str, Any],
    venta_extra: Mapping[str, Any],
    detalles: Mapping[str, Any],
    logger: logging.Logger,
) -> None:
    receptor = _ensure_mapping(payload.get("receptor"))
    if not receptor:
        return

    sources: list[Mapping[str, Any]] = []

    for raw in (nota, venta, venta_credito_fiscal, venta_extra, detalles):
        if isinstance(raw, Mapping):
            sources.append(raw)
        elif isinstance(raw, str):
            parsed = _parse_mapping(raw)
            if parsed:
                sources.append(parsed)

    expanded: list[Mapping[str, Any]] = []
    for source in sources:
        expanded.append(source)
        extra = source.get("extra") if isinstance(source, Mapping) else None
        if isinstance(extra, Mapping):
            expanded.append(extra)
        elif isinstance(extra, str):
            parsed = _parse_mapping(extra)
            if parsed:
                expanded.append(parsed)

    if not expanded:
        return

    def _walk_mappings(value: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
        seen: set[int] = set()
        stack: list[Mapping[str, Any]] = [value]
        while stack:
            current = stack.pop()
            ident = id(current)
            if ident in seen:
                continue
            seen.add(ident)
            yield current
            for nested in current.values():
                if isinstance(nested, Mapping):
                    stack.append(nested)
                elif isinstance(nested, Sequence) and not isinstance(
                    nested, (str, bytes, bytearray)
                ):
                    for item in nested:
                        if isinstance(item, Mapping):
                            stack.append(item)

    def _find_field(*names: str) -> str | None:
        for source in expanded:
            for mapping in _walk_mappings(source):
                for name in names:
                    if name not in mapping:
                        continue
                    text = _first_not_empty(mapping.get(name))
                    if text:
                        return text
        return None

    updated: list[str] = []

    if _is_missing_field(receptor.get("nrc")):
        nrc_val = _find_field("nrc", "nrcCliente", "numeroRegistro")
        if nrc_val:
            receptor["nrc"] = nrc_val
            updated.append("nrc")

    if _is_missing_field(receptor.get("codActividad")):
        cod_val = _find_field(
            "codActividad",
            "cod_actividad",
            "codigoActividad",
            "actividadEconomica",
            "codigoActividadEconomica",
        )
        if cod_val:
            receptor["codActividad"] = cod_val
            updated.append("codActividad")

    if _is_missing_field(receptor.get("descActividad")):
        desc_val = _find_field(
            "descActividad",
            "descripcionActividad",
            "giro",
            "actividadEconomicaDescripcion",
            "actividad",
            "desc_giro",
        )
        if desc_val:
            receptor["descActividad"] = desc_val
            updated.append("descActividad")

    if updated:
        payload["receptor"] = receptor
        logger.info(
            "Receptor completado desde metadatos (%s)",
            ", ".join(sorted(set(updated))),
        )


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


def _extract_cliente_id(*sources: Mapping[str, Any] | None) -> int | None:
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        for key in ("cliente_id", "clienteId", "cliente"):
            value = source.get(key)
            if isinstance(value, Mapping):
                nested = value.get("id")
                cid = _safe_int(nested)
            else:
                cid = _safe_int(value)
            if cid is not None and cid > 0:
                return cid
    return None


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


def _first_not_empty(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str):
            text = value.strip()
        else:
            text = str(value).strip()
        if text:
            return text
    return None


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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
            ambiente_norm = _normalize_ambiente_str(ambiente)
            if ambiente_norm:
                expected["ambiente"] = ambiente_norm
        codigo = source.get("codigoGeneracion")
        numero = source.get("numeroControl")
        if codigo:
            expected["codigoGeneracion"] = str(codigo).strip().upper()
        if numero:
            expected["numeroControl"] = str(numero).strip().upper()
    ambiente_directo = _normalize_ambiente_str(expected.get("ambiente"))
    if ambiente_directo:
        expected["ambiente"] = ambiente_directo
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
    numero_documento = str(numero_control or "").strip()
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
