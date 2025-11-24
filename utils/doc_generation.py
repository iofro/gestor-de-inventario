import json
import os
import re
import uuid
import logging
from datetime import datetime
from decimal import InvalidOperation
from typing import Any, Callable, Mapping

import dte
from pathlib import Path
from factura_sv import generar_factura_electronica_pdf
from ticket_pdf import generar_ticket_personalizado, generar_ticket_fe_pdf
from dte import generar_ticket_json, generar_dte_json, d4, generar_cabecera_dte_data
from paths import RETENCIONES_DIR, resolve_user_visible_path
from retenciones.builder import serialize_cr
from retenciones.catalogos_retencion import CatalogosRetencion
from retenciones.service import RetencionCRService
from retenciones.validators import validate_cr
from utils.monto import D, d2, monto_a_texto_sv, iva_item, to_base_iva
from utils.docs import (
    get_document_paths,
    build_invoice_json,
    write_pdf_atomically,
    persist_client_json,
)
from utils.jws import sign_and_save
from utils import versioned_dte
from utils.resumen import (
    normalize_condicion_operacion,
    sync_condicion_operacion_flags,
    validate_pagos_basico,
)
from utils.fiscal_extra import normalize_retencion_payload, parse_retencion_values
from utils.sanitize import limpiar_documentos
from utils.stable_json import save_file, stable_stringify


logger = logging.getLogger(__name__)


def _set_last_cr_result(manager, result: Mapping[str, Any] | None) -> None:
    """Persist the latest CR outcome on the manager for UI consumption."""

    try:
        setattr(manager, "last_cr_result", result)
    except Exception:
        pass


def normalize_payment_condition(data: dict) -> dict:
    """Normalize credit payment fields prior to DTE generation.

    The function ensures the UI supplied ``pago_plazo``/``pago_periodo`` values
    adhere to the MH schema expectations. Only the relevant keys are touched so
    the caller can update the persisted ``extra`` payload without affecting any
    other structure.
    """

    cond_raw = data.get("condicion_operacion")
    try:
        condicion = normalize_condicion_operacion(cond_raw)
    except ValueError:
        logger.warning(
            "condicion_operacion inválida %r; normalizando a Contado", cond_raw
        )
        condicion = 1

    data["condicion_operacion"] = condicion
    if condicion == 2:
        unidad_raw = data.get("pago_plazo")
        unidad = str(unidad_raw or "").strip().upper()
        letras_a_codigo = {"D": "01", "M": "02", "A": "03"}
        if unidad in letras_a_codigo:
            data["pago_plazo"] = letras_a_codigo[unidad]
        elif unidad in {"01", "02", "03"}:
            data["pago_plazo"] = unidad
        else:
            raise ValueError("Crédito: unidad inválida (esperado D/M/A o 01/02/03)")

        cantidad_raw = data.get("pago_periodo")
        try:
            cantidad = int(cantidad_raw)
        except (TypeError, ValueError):
            raise ValueError("Crédito: periodo debe ser entero > 0") from None
        if cantidad <= 0:
            raise ValueError("Crédito: periodo debe ser entero > 0")
        data["pago_periodo"] = cantidad
    else:
        data["pago_plazo"] = None
        data["pago_periodo"] = None

    return data


def _path_missing(path: Path) -> bool:
    """Return ``True`` if ``path`` is absent or an empty file."""

    try:
        return not path.exists() or path.stat().st_size <= 0
    except OSError:
        return True


def _ensure_invoice_copies(
    pdf_path: Path,
    json_path: Path,
    json_payload: dict,
    renderer: Callable[[Path], None] | None,
) -> None:
    """Guarantee copies of the invoice PDF and JSON exist at the target paths."""

    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_missing = _path_missing(pdf_path)
    json_missing = _path_missing(json_path)
    logger.info(
        "Verificando copias de factura PDF=%s (missing=%s) JSON=%s (missing=%s)",
        pdf_path,
        pdf_missing,
        json_path,
        json_missing,
    )
    if pdf_missing and renderer is not None:

        logger.warning("PDF faltante; intentando regenerar %s", pdf_path)
        try:
            write_pdf_atomically(pdf_path, renderer)
        except Exception:
            logger.exception("No se pudo regenerar PDF en %s", pdf_path)
            raise

        pdf_missing = _path_missing(pdf_path)

    json_path.parent.mkdir(parents=True, exist_ok=True)
    if json_missing:

        logger.warning("JSON faltante; intentando reescribir %s", json_path)
        try:
            save_file(str(json_path), stable_stringify(json_payload, indent=2))
        except Exception:
            logger.exception("No se pudo garantizar copia JSON en %s", json_path)
            raise

        json_missing = _path_missing(json_path)
    try:
        folder_contents = sorted(p.name for p in pdf_path.parent.iterdir())
    except Exception:
        folder_contents = None
    logger.info(
        "Resultado verificación copias -> PDF missing=%s JSON missing=%s; contenido %s: %s",
        pdf_missing,
        json_missing,
        pdf_path.parent,
        folder_contents,
    )


_RET_CATALOGOS: CatalogosRetencion | None | bool = None


def _get_retencion_catalogos() -> CatalogosRetencion | None:
    global _RET_CATALOGOS
    if _RET_CATALOGOS is False:
        return None
    if _RET_CATALOGOS is None:
        try:
            _RET_CATALOGOS = CatalogosRetencion()
        except Exception as exc:
            logger.warning("CAT-006 (retención) no disponible: %s", exc)
            _RET_CATALOGOS = False
            return None
    return _RET_CATALOGOS if isinstance(_RET_CATALOGOS, CatalogosRetencion) else None


def _valid_geo_code(value: Any) -> bool:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if not digits:
        return False
    try:
        number = int(digits)
    except ValueError:
        return False
    return 1 <= number <= 22


def _normalize_geo_code(value: Any) -> str | None:
    """Return two-digit geo code if valid, otherwise None."""

    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if not digits:
        return None
    try:
        number = int(digits)
    except ValueError:
        return None
    if 1 <= number <= 22:
        return f"{number:02d}"
    return None


def _append_retencion_apendice(doc: Mapping[str, Any], retencion_block: Mapping[str, Any]) -> None:
    try:
        enabled, base_dec, reten_dec, codigo, tasa_pct, geo_emisor, geo_receptor = parse_retencion_values(retencion_block)
    except Exception:
        return
    if not enabled:
        return
    apendice_list = []
    existing = doc.get("apendice")
    if isinstance(existing, list):
        apendice_list = list(existing)
        apendice_list = [
            item
            for item in apendice_list
            if not (isinstance(item, dict) and str(item.get("campo") or "").upper().startswith("RET_"))
        ]
    base_text = f"{base_dec:.2f}"
    tasa_text = f"{tasa_pct:.3f}%"
    entries = [
        {"campo": "RET_COD", "etiqueta": "Código retención IVA", "valor": str(codigo)},
        {"campo": "RET_TASA", "etiqueta": "Tasa retención IVA", "valor": tasa_text[:150]},
        {"campo": "RET_BASE", "etiqueta": "Base sujeta retención", "valor": base_text[:150]},
        {"campo": "RET_MONTO", "etiqueta": "IVA retenido", "valor": f"{reten_dec:.2f}"},
    ]
    if geo_emisor:
        entries.append({"campo": "RET_GEOE", "etiqueta": "Geo emisor", "valor": str(geo_emisor)})
    if geo_receptor:
        entries.append({"campo": "RET_GEORE", "etiqueta": "Geo receptor", "valor": str(geo_receptor)})
    apendice_list.extend(entries)
    doc["apendice"] = apendice_list


def _cr_output_path(payload: Mapping[str, Any]) -> Path:
    ident = payload.get("identificacion") or {}
    numero = str(ident.get("numeroControl") or ident.get("numero_control") or "CR").replace("-", "")
    fecha = str(ident.get("fecEmi") or "").replace("-", "")
    name = f"CR_{fecha or '0000'}_{numero or 'retencion'}.json"
    base = Path(RETENCIONES_DIR)
    base.mkdir(parents=True, exist_ok=True)
    return base / name


def _persist_cr_json(payload: Mapping[str, Any]) -> Path:
    path = _cr_output_path(payload)
    content = serialize_cr(payload, indent=2)
    save_file(str(path), content)
    visible = resolve_user_visible_path(str(path))
    try:
        import hashlib

        sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
    except Exception:
        sha = None
    logger.info("CR guardado en %s sha256=%s", visible, sha)
    return Path(visible)


def _maybe_generate_cr(
    manager,
    venta_id: int,
    factura_json: Mapping[str, Any],
    retencion_block: Mapping[str, Any] | None,
    ambiente: str,
) -> Mapping[str, Any] | None:
    def _skipped(reason: str, **extra: Any) -> Mapping[str, Any]:
        result: dict[str, Any] = {"status": "skipped", "venta_id": venta_id, "reason": reason}
        for key, value in extra.items():
            if value is not None:
                result[key] = value
        return result

    if not retencion_block:
        return None
    tipo_origen = str((factura_json.get("identificacion") or {}).get("tipoDte") or "").zfill(2)
    if tipo_origen != "03":
        logger.info("CR omitido: tipoDte origen %s no admite retención", tipo_origen)
        return _skipped("CR-07 solo para DTE 03", tipo_dte=tipo_origen)
    if not hasattr(manager, "db") or not all(
        hasattr(manager.db, attr)
        for attr in ("insert_retencion_cr", "get_retencion_cr", "update_retencion_cr_response")
    ):
        logger.debug("DB sin soporte de retenciones; se omite CR para venta %s", venta_id)
        return _skipped("CR omitido: DB sin soporte de retención")
    try:
        enabled, base_dec, reten_dec, codigo, tasa_pct, geo_emisor, geo_receptor = parse_retencion_values(retencion_block)
    except Exception as exc:
        raise ValueError(f"Retención de IVA inválida: {exc}") from exc
    if not enabled or base_dec <= D("0") or tasa_pct <= D("0"):
        logger.info("Retención desactivada: enabled=%s base=%s tasa=%s", enabled, base_dec, tasa_pct)
        return _skipped("CR omitido: retención desactivada", enabled=enabled)
    catalogos = _get_retencion_catalogos()
    if catalogos is None:
        raise ValueError("Catálogo CAT-006 no disponible para retención")
    try:
        codigo_mh = catalogos.ensure("CAT-006", codigo, field="retencion.codigoRetencionMH")
    except Exception as exc:
        raise ValueError(f"Código de retención fuera de catálogo CAT-006: {exc}") from exc
    geo_emisor_norm = _normalize_geo_code(geo_emisor)
    geo_receptor_norm = _normalize_geo_code(geo_receptor)
    tasa_dec = tasa_pct / D("100")
    if tasa_pct <= D("0.5"):
        tasa_dec = tasa_pct
    emisor_override = None
    receptor_override = None
    emisor_dir = dict((factura_json.get("emisor") or {}).get("direccion") or {})
    receptor_dir = dict((factura_json.get("receptor") or {}).get("direccion") or {})
    if geo_emisor_norm is None:
        geo_emisor_norm = _normalize_geo_code(emisor_dir.get("departamento")) or _normalize_geo_code(emisor_dir.get("municipio"))
    if geo_receptor_norm is None:
        geo_receptor_norm = _normalize_geo_code(receptor_dir.get("departamento")) or _normalize_geo_code(receptor_dir.get("municipio"))
    if geo_emisor_norm:
        emisor_dir["departamento"] = geo_emisor_norm
        emisor_dir["municipio"] = geo_emisor_norm
        emisor_override = {"direccion": emisor_dir}
    if geo_receptor_norm:
        receptor_dir["departamento"] = geo_receptor_norm
        receptor_dir["municipio"] = geo_receptor_norm
        receptor_override = {"direccion": receptor_dir}
    try:
        service = RetencionCRService(manager.db, catalogos=catalogos)
        payload = service.prepare_cr(
            venta_id,
            factura=factura_json,
            tasa=tasa_dec,
            codigo_retencion=codigo_mh,
            base_sujeta=base_dec,
            ambiente=ambiente,
            emisor_override=emisor_override,
            receptor_override=receptor_override,
        )
        validate_cr(payload, catalogos=catalogos)
        path = _persist_cr_json(payload)
        record = manager.db.get_retencion_cr(venta_id) or {}
        estado = str(record.get("estado") or "PENDIENTE").upper()
        logger.info(
            "CR.SAVE venta_id=%s db_id=%s path=%s",
            venta_id,
            record.get("id"),
            path,
        )
        return {
            "status": "created",
            "venta_id": venta_id,
            "payload": payload,
            "path": str(path),
            "db_id": record.get("id"),
            "estado": estado,
        }
    except ValueError as exc:
        existing = None
        try:
            existing = manager.db.get_retencion_cr(venta_id)
        except Exception:
            existing = None
        message = str(exc)
        if message.startswith("Ya existe un CR-07") or "Ya existe un CR" in message:
            path = None
            estado_dup = None
            if existing:
                try:
                    stored_payload = json.loads(existing.get("payload_json") or "{}")
                except Exception:
                    stored_payload = {}
                try:
                    path = _cr_output_path(stored_payload)
                except Exception:
                    path = None
                estado_dup = existing.get("estado")
            logger.info("CR duplicado omitido: %s", message)
            return {
                "status": "duplicate",
                "venta_id": venta_id,
                "message": message,
                "path": str(path) if path else None,
                "db_id": existing.get("id") if existing else None,
                "estado": estado_dup or "PENDIENTE",
            }
        if "CR-07 solo para DTE 03" in message:
            logger.info("CR omitido: %s", message)
            return _skipped(message, tipo_dte=tipo_origen)
        raise
    except Exception as exc:
        logger.exception("No se pudo generar CR para venta %s", venta_id)
        raise ValueError("No se pudo generar comprobante de retención") from exc


def log_venta_vs_dte(manager, venta_id):
    """Log line-by-line comparisons between Venta and DTE calculations.

    This helper runs both the Venta calculation (used for PDF generation)
    and the DTE calculation for the given ``venta_id`` and emits detailed
    logging for each line.  It highlights per-line differences greater than
    ``0.01`` and checks basic invariants for totals.
    """

    venta = next((v for v in manager.db.get_ventas() if v["id"] == venta_id), None)
    if not venta:
        logger.error("Venta %s no encontrada", venta_id)
        return

    credito_info = manager.db.get_venta_credito_fiscal(venta_id)
    tipo_dte = "03" if credito_info else "01"

    detalles = manager.db.get_detalles_venta(venta_id)
    json_data = generar_dte_json(manager.db, venta_id, tipo_dte=tipo_dte)
    dte_items = json_data.get("cuerpoDocumento", [])

    tot_pf = D("0")
    tot_base = D("0")
    tot_iva = D("0")
    tot_pf_dte = D("0")
    tot_base_dte = D("0")
    tot_iva_dte = D("0")
    last_gravada_idx = None

    for idx, d in enumerate(detalles):
        qty = D(str(d.get("cantidad") or 0))
        unit = D(str(d.get("precio_unitario") or 0))
        pf_line = d4(qty * unit)
        desc = D(str(d.get("descuento") or 0))
        if d.get("descuento_tipo") == "%":
            desc_line = d4(pf_line * desc / D("100"))
        else:
            desc_line = d4(desc)
        pf_neto = d4(pf_line - desc_line)
        base = D(
            str(
                d.get("ventas_gravadas")
                or d.get("ventas_exentas")
                or d.get("ventas_no_sujetas")
                or 0
            )
        )
        iva = D(str(d.get("iva") or 0))
        if base > 0:
            last_gravada_idx = idx
        logger.info(
            "Venta idx=%s qty=%s pf_unit=%.4f desc=%.4f pf_line=%.4f "
            "desc_line=%.4f pf_neto=%.4f base=%.4f iva=%.4f",
            idx + 1,
            qty,
            unit,
            desc,
            pf_line,
            desc_line,
            pf_neto,
            base,
            iva,
        )
        tot_pf += pf_neto
        tot_base += base
        tot_iva += iva

        if idx < len(dte_items):
            item = dte_items[idx]
            dte_qty = D(str(item.get("cantidad") or 0))
            dte_unit = D(str(item.get("precioUni") or 0))
            pf_line_dte = d4(dte_qty * dte_unit)
            desc_dte = D(str(item.get("montoDescu") or 0))
            pf_neto_dte = d4(pf_line_dte - desc_dte)
            base_dte = D(
                str(
                    item.get("ventaGravada")
                    or item.get("ventaExenta")
                    or item.get("ventaNoSuj")
                    or 0
                )
            )
            iva_dte = iva_item(base_dte)
            logger.info(
                "DTE   idx=%s qty=%s pf_unit=%.4f desc=%.4f pf_line=%.4f "
                "desc_line=%.4f pf_neto=%.4f base=%.4f iva=%.4f",
                idx + 1,
                dte_qty,
                dte_unit,
                desc_dte,
                pf_line_dte,
                desc_dte,
                pf_neto_dte,
                base_dte,
                iva_dte,
            )
            tot_pf_dte += pf_neto_dte
            tot_base_dte += base_dte
            tot_iva_dte += iva_dte
            diff_pf = abs(pf_neto - pf_neto_dte)
            diff_base = abs(base - base_dte)
            diff_iva = abs(iva - iva_dte)
            if max(diff_pf, diff_base, diff_iva) > D("0.01"):
                logger.warning(
                    "Diferencia idx=%s pf=%.4f base=%.4f iva=%.4f",
                    idx + 1,
                    diff_pf,
                    diff_base,
                    diff_iva,
                )

    total_venta = D(str(venta.get("total") or 0))
    if d2(tot_pf) != d2(total_venta):
        logger.warning(
            "Invariante Venta falló: sum pf_neto=%s total=%s",
            d2(tot_pf),
            d2(total_venta),
        )
    if d2(tot_base + tot_iva) != d2(tot_pf):
        logger.warning(
            "Invariante Venta base+iva=%s pf=%s",
            d2(tot_base + tot_iva),
            d2(tot_pf),
        )
        diff = d2(tot_pf) - d2(tot_base + tot_iva)
        if abs(diff) == D("0.01") and last_gravada_idx is not None:
            logger.warning(
                "Ajustar IVA de línea %s en %.2f",
                last_gravada_idx + 1,
                float(diff),
            )

    if d2(tot_pf_dte) != d2(total_venta):
        logger.warning(
            "Invariante DTE falló: sum pf_neto=%s total=%s",
            d2(tot_pf_dte),
            d2(total_venta),
        )
    if d2(tot_base_dte + tot_iva_dte) != d2(tot_pf_dte):
        logger.warning(
            "Invariante DTE base+iva=%s pf=%s",
            d2(tot_base_dte + tot_iva_dte),
            d2(tot_pf_dte),
        )

def generate_invoice_pdf(manager, venta_id):
    """Generate and store the invoice PDF for the given sale."""
    venta = next((v for v in manager.db.get_ventas() if v["id"] == venta_id), None)
    if not venta:
        return None

    _set_last_cr_result(manager, None)

    credito_info = manager.db.get_venta_credito_fiscal(venta_id)
    detalles = manager.db.get_detalles_venta(venta_id)

    venta_data = dict(venta)
    credit_extra: dict[str, Any] = {}
    is_credito_fiscal = bool(credito_info)
    if credito_info:
        credito_payload = dict(credito_info)
        raw_credit_extra = credito_payload.pop("extra", None)
        if isinstance(raw_credit_extra, str):
            try:
                credit_extra = json.loads(raw_credit_extra)
            except Exception:
                credit_extra = {}
        elif isinstance(raw_credit_extra, dict):
            credit_extra = dict(raw_credit_extra)
        venta_data.update(credito_payload)

    # Parse extra information early to know if prices include IVA
    extra = venta_data.get("extra") or {}
    if isinstance(extra, str):
        try:
            extra = json.loads(extra)
        except Exception:
            extra = {}
    elif isinstance(extra, Mapping):
        extra = dict(extra)
    else:
        extra = {}

    if credit_extra:
        merged_extra = dict(credit_extra)
        merged_extra.update(extra)
        extra = merged_extra

    venta_data["extra"] = extra
    retencion_block = normalize_retencion_payload(extra.get("_ui_retencion")) if extra else None
    if not is_credito_fiscal:
        retencion_block = None
    if retencion_block:
        extra["_ui_retencion"] = retencion_block
    precios_incluyen_iva = bool(extra.get("precios_incluyen_iva"))

    condicion_operacion = (
        extra.get("condicion_operacion")
        or extra.get("condicionOperacion")
        or venta_data.get("condicion_operacion")
    )
    pagos_raw = extra.get("pagos")
    pago_plazo = extra.get("pago_plazo")
    pago_periodo = extra.get("pago_periodo")
    if isinstance(pagos_raw, list) and pagos_raw:
        first_pago = pagos_raw[0]
        if isinstance(first_pago, dict):
            if pago_plazo in (None, ""):
                pago_plazo = first_pago.get("plazo")
            if pago_periodo in (None, ""):
                pago_periodo = first_pago.get("periodo")
    try:
        normalized_payment = normalize_payment_condition(
            {
                "condicion_operacion": condicion_operacion,
                "pago_plazo": pago_plazo,
                "pago_periodo": pago_periodo,
            }
        )
    except ValueError as exc:
        logger.error("Validación de condición de pago inválida: %s", exc)
        raise

    condicion_norm = normalized_payment.get("condicion_operacion", 1)
    if condicion_norm not in {1, 2, 3}:
        condicion_norm = 1
    original_cond_camel = extra.get("condicionOperacion")
    original_cond_snake = extra.get("condicion_operacion")
    condicion_changed = (
        original_cond_snake != condicion_norm
        or original_cond_camel != condicion_norm
    )
    if condicion_changed:
        sync_condicion_operacion_flags(extra, condicion_norm)
    pagos_updated = False
    payment_fields_changed = False
    if condicion_norm == 2:
        if not (isinstance(pagos_raw, list) and pagos_raw and isinstance(pagos_raw[0], dict)):
            raise ValueError("Crédito: pagos no detallados correctamente")
        plazo_code = normalized_payment["pago_plazo"]
        periodo_val = normalized_payment["pago_periodo"]
        if extra.get("pago_plazo") != plazo_code:
            extra["pago_plazo"] = plazo_code
            payment_fields_changed = True
        if extra.get("pago_periodo") != periodo_val:
            extra["pago_periodo"] = periodo_val
            payment_fields_changed = True
        first_pago = pagos_raw[0]
        if first_pago.get("plazo") != plazo_code:
            first_pago["plazo"] = plazo_code
            pagos_updated = True
        if first_pago.get("periodo") != periodo_val:
            first_pago["periodo"] = periodo_val
            pagos_updated = True
        referencia_val = first_pago.get("referencia")
        if extra.get("pago_referencia") != referencia_val:
            extra["pago_referencia"] = referencia_val
            payment_fields_changed = True
    else:
        if extra.get("pago_plazo") not in (None, ""):
            extra["pago_plazo"] = None
            payment_fields_changed = True
        if extra.get("pago_periodo") not in (None, ""):
            extra["pago_periodo"] = None
            payment_fields_changed = True
        if extra.get("pago_referencia") not in (None, ""):
            extra["pago_referencia"] = None
            payment_fields_changed = True
        if isinstance(pagos_raw, list) and pagos_raw and isinstance(pagos_raw[0], dict):
            first_pago = pagos_raw[0]
            if first_pago.get("plazo") not in (None, ""):
                first_pago["plazo"] = None
                pagos_updated = True
            if first_pago.get("periodo") not in (None, ""):
                first_pago["periodo"] = None
                pagos_updated = True
            if first_pago.get("referencia") not in (None, ""):
                first_pago["referencia"] = None
                pagos_updated = True
    if condicion_changed or pagos_updated or payment_fields_changed:
        try:
            manager.db.update_venta_extra(
                venta_id,
                {
                    "condicionOperacion": extra.get("condicionOperacion"),
                    "condicion_operacion": extra.get("condicion_operacion"),
                    "pagos": extra.get("pagos"),
                    "pago_plazo": extra.get("pago_plazo"),
                    "pago_periodo": extra.get("pago_periodo"),
                    "pago_referencia": extra.get("pago_referencia"),
                },
            )
        except Exception:
            logger.debug("No se pudo actualizar pagos normalizados", exc_info=True)

    if venta_data.get("vendedor_id"):
        trabajador = manager.db.get_trabajador(venta_data["vendedor_id"])
        if trabajador:
            venta_data["vendedor_nombre"] = trabajador.get("nombre", "")

    for d in detalles:
        unit = d.get("precio_unitario", 0)
        cantidad = d.get("cantidad", 0)
        line_total = unit * cantidad
        desc = d.get("descuento", 0)
        if d.get("descuento_tipo") == "%":
            desc = line_total * d.get("descuento", 0) / 100
        line_total_desc = line_total - desc
        iva_item_val = d.get("iva", 0)
        tipo = d.get("tipo_fiscal", "").lower()
        if tipo == "venta exenta":
            d["ventas_exentas"] = line_total_desc
        elif tipo == "venta no sujeta":
            d["ventas_no_sujetas"] = line_total_desc
        else:
            if precios_incluyen_iva:
                if iva_item_val:
                    base = line_total_desc - iva_item_val
                else:
                    base_dec, iva_dec = to_base_iva(line_total_desc)
                    base = float(base_dec)
                    iva_item_val = float(iva_dec)
                    d["iva"] = iva_item_val
            else:
                base = line_total_desc
                if credito_info and not iva_item_val:
                    iva_item_val = float(iva_item(base))
                    d["iva"] = iva_item_val
            d["ventas_gravadas"] = base


    cliente = None
    if venta.get("cliente_id"):
        cliente = next((c for c in manager._clientes if c["id"] == venta["cliente_id"]), None)
    distribuidor = None
    if venta.get("Distribuidor_id"):
        distribuidor = next(
            (d for d in manager._Distribuidores if d["id"] == venta["Distribuidor_id"]),
            None,
        )

    if not venta_data.get("venta_a_cuenta_de"):
        venta_data["venta_a_cuenta_de"] = extra.get("venta_a_cuenta_de", "")
    if not venta_data.get("documento_venta_a_cuenta"):
        venta_data["documento_venta_a_cuenta"] = extra.get("documento_venta_a_cuenta", "")
    sello_recepcion = venta_data.get("sello_recepcion") or extra.get("selloRecibido", "")
    default_tipo = 2 if dte.get_default_modo_transmision() == "contingencia" else 1
    tipo_operacion = (
        venta_data.get("tipo_operacion")
        or extra.get("tipoOperacion")
        or default_tipo
    )
    wants_contingencia = tipo_operacion == 2
    tipo_contingencia = (
        venta_data.get("tipo_contingencia") or extra.get("tipoContingencia")
    )
    motivo_contin = venta_data.get("motivo_contin") or extra.get("motivoContin")
    if tipo_operacion == 2:
        cfg = dte._load_datos_negocio().get("dte_api", {})
        if tipo_contingencia is None:
            tipo_contingencia = cfg.get("tipo_contingencia")
        if motivo_contin is None:
            motivo_contin = cfg.get("motivo_contin")
        if tipo_contingencia is None:
            logger.warning(
                "Tipo de operación 'contingencia' requiere 'tipo_contingencia'; se "
                "cambiará a modo normal"
            )
            tipo_operacion = 1
    ambiente_cfg = venta_data.get("ambiente") or extra.get("ambiente")

    def _normalize_ambiente_label(value):
        if value is None:
            return None
        label = str(value).strip().lower()
        if not label:
            return None
        if label in {"00", "0", "pruebas", "test", "testing", "sandbox"}:
            return "pruebas"
        if label in {"01", "1", "produccion", "producción", "production"}:
            return "produccion"
        return label

    ambiente = _normalize_ambiente_label(ambiente_cfg)
    if ambiente is None:
        try:
            ambiente = _normalize_ambiente_label(
                (dte._load_dte_api_config() or {}).get("ambiente")
            )
        except Exception:
            ambiente = None
    if ambiente is None:
        ambiente = "pruebas"

    if tipo_operacion == 1 and not sello_recepcion:
        sello_recepcion = f"SELLO-{uuid.uuid4().hex[:8]}"
        venta_data["sello_recepcion"] = sello_recepcion
    venta_data["tipo_operacion"] = tipo_operacion
    tipo_modelo = 2 if tipo_operacion == 2 else 1

    tipo_doc = "Crédito Fiscal" if credito_info else "Consumidor Final"
    doc_key = "CreditoFiscal" if credito_info else "ConsumidorFinal"
    cliente_nombre = cliente.get("nombre") if cliente else ""

    # Reutilizar códigos existentes si están presentes en ``extra``
    codigo_generacion = extra.get("codigoGeneracion")
    numero_control = extra.get("numeroControl")
    correlativo = extra.get("correlativo")
    fecha_generacion = extra.get("fechaGeneracion")
    if codigo_generacion and numero_control and correlativo:
        cabecera = {
            "codigo_generacion": codigo_generacion,
            "numero_control": numero_control,
            "correlativo": correlativo,
            "sello_recepcion": None,
            "tipo_modelo": tipo_modelo,
            "tipo_operacion": tipo_operacion,
            "tipo_contingencia": tipo_contingencia,
            "motivo_contin": motivo_contin,
            "fecha_generacion": fecha_generacion
            or datetime.now().strftime("%d/%m/%Y, %I:%M %p"),
            "ambiente": ambiente,
        }
    else:
        cabecera = generar_cabecera_dte_data(
            tipo_modelo,
            tipo_operacion,
            "03" if credito_info else "01",
            manager.db,
            tipo_contingencia=tipo_contingencia,
            motivo_contin=motivo_contin,
            ambiente=ambiente,
        )
        codigo_generacion = cabecera["codigo_generacion"]
        numero_control = cabecera["numero_control"]
        correlativo = cabecera.get("correlativo")
        fecha_generacion = cabecera["fecha_generacion"]
        try:
            manager.db.update_venta_extra(
                venta_id,
                {
                    "codigoGeneracion": codigo_generacion,
                    "numeroControl": numero_control,
                    "correlativo": correlativo,
                    "fechaGeneracion": fecha_generacion,
                },
            )
        except Exception:
            pass
        extra["codigoGeneracion"] = codigo_generacion
        extra["numeroControl"] = numero_control
        extra["correlativo"] = correlativo
        extra["fechaGeneracion"] = fecha_generacion

    sello_recepcion = sello_recepcion or cabecera["sello_recepcion"]
    venta_data["sello_recepcion"] = sello_recepcion
    tipo_modelo = cabecera["tipo_modelo"]
    tipo_operacion = cabecera["tipo_operacion"]
    tipo_contingencia = cabecera["tipo_contingencia"]
    motivo_contin = cabecera["motivo_contin"]

    try:
        json_data = generar_dte_json(
            manager.db,
            venta_id,
            tipo_dte="03" if credito_info else "01",
            ambiente=ambiente,
            tipo_operacion=tipo_operacion,
            tipo_contingencia=tipo_contingencia,
            motivo_contin=motivo_contin,
            codigo_generacion=codigo_generacion,
            numero_control=numero_control,
            correlativo=cabecera.get("correlativo"),
            tipo_modelo=tipo_modelo,
        )
    except AttributeError as exc:
        logger.warning(
            "Fallo generar_dte_json; se utilizará build_invoice_json",
            exc_info=True,
        )
        cliente_norm = dict(cliente or {})
        try:
            limpiar_documentos(cliente_norm)
            dir_info = cliente_norm.get("direccion")
            if isinstance(dir_info, dict):
                cliente_norm["direccion"] = dte._build_receptor_direccion(dir_info)
        except Exception:
            logger.debug("Normalización de receptor fallida", exc_info=True)
        json_data = build_invoice_json(venta_data, cliente_norm, detalles)
    except ValueError:
        logger.exception("Error al generar el DTE real")
        raise
    resumen = json_data.get("resumen", {}) or {}

    sello_norm = str(sello_recepcion or "").strip()
    if sello_norm and re.fullmatch(r"[0-9A-Fa-f]{40}", sello_norm):
        sello_upper = sello_norm.upper()
        if json_data.get("selloRecibido") != sello_upper:
            json_data["selloRecibido"] = sello_upper
        respuesta = json_data.get("respuesta")
        if isinstance(respuesta, dict):
            if respuesta.get("selloRecibido") != sello_upper:
                respuesta["selloRecibido"] = sello_upper
                json_data["respuesta"] = respuesta

    if retencion_block:
        try:
            _, _, reten_dec, _, _, _, _ = parse_retencion_values(retencion_block)
            if reten_dec > D("0"):
                resumen["ivaRete1"] = float(D(str(resumen.get("ivaRete1", reten_dec)))) if resumen else float(reten_dec)
        except Exception:
            logger.debug("No se pudo sincronizar ivaRete1 con retención", exc_info=True)
        _append_retencion_apendice(json_data, retencion_block)


    def _resumen_value(*keys):
        for key in keys:
            if key in resumen:
                value = resumen[key]
                if value not in (None, ""):
                    return value
        return None

    def _normalize(value):
        if isinstance(value, (int, float)):
            return float(value)
        try:
            return float(D(str(value)))
        except (InvalidOperation, ValueError, TypeError):
            return None

    def _update(keys, *source_keys):
        value = _resumen_value(*source_keys)
        if value is None:
            return
        normalized = _normalize(value)
        if normalized is None:
            return
        for key in keys:
            venta_data[key] = normalized

    _update(("subTotalVentas",), "subTotalVentas")
    _update(("sumas",), "sumas", "subTotalVentas")
    _update(("descuentos", "totalDescu"), "descuentos", "totalDescu")

    iva_value = _resumen_value("totalIva", "iva", "ivaPerci1")
    if iva_value is None:
        tributos = resumen.get("tributos")
        if isinstance(tributos, list):
            total = None
            for tributo in tributos:
                if not isinstance(tributo, dict):
                    continue
                valor = tributo.get("valor")
                if valor in (None, ""):
                    continue
                monto = _normalize(valor)
                if monto is None:
                    continue
                total = (total or 0.0) + monto
            if total is not None:
                iva_value = total
    iva_normalized = _normalize(iva_value) if iva_value is not None else None
    if iva_normalized is not None:
        venta_data["iva"] = iva_normalized
        venta_data["totalIva"] = iva_normalized

    _update(("subTotal", "subtotal"), "subTotal", "subtotal", "subTotalVentas")
    _update(("ventas_exentas", "totalExenta"), "totalExenta", "ventasExentas", "ventas_exentas")
    _update(("ventas_no_sujetas", "totalNoSuj"), "totalNoSuj", "ventasNoSujetas", "ventas_no_sujetas")
    _update(("ventas_gravadas", "totalGravada"), "totalGravada", "ventas_gravadas")
    _update(("total", "totalPagar"), "totalPagar", "total", "montoTotalOperacion")

    dte_items = json_data.get("cuerpoDocumento")

    def _normalize_item_value(value):
        if value in (None, ""):
            return None
        try:
            return float(D(str(value)))
        except (InvalidOperation, ValueError, TypeError):
            return None

    if isinstance(dte_items, list) and detalles:
        index_by_num: dict[int, int] = {}
        for idx, detalle in enumerate(detalles):
            num_val = None
            for key in ("numItem", "num_item", "numero", "num", "item"):
                raw = detalle.get(key)
                if raw in (None, ""):
                    continue
                try:
                    num_val = int(str(raw).strip())
                except (ValueError, TypeError):
                    continue
                else:
                    break
            if num_val is not None:
                index_by_num.setdefault(num_val, idx)

        used_indices: set[int] = set()

        def _pick_index(item: dict) -> int | None:
            num_raw = item.get("numItem")
            if num_raw not in (None, ""):
                try:
                    num_int = int(str(num_raw).strip())
                except (ValueError, TypeError):
                    num_int = None
                if num_int is not None:
                    idx = index_by_num.get(num_int)
                    if idx is not None and idx not in used_indices:
                        return idx
            for candidate in range(len(detalles)):
                if candidate not in used_indices:
                    return candidate
            return None

        for item in dte_items:
            if not isinstance(item, dict):
                continue
            idx = _pick_index(item)
            if idx is None:
                continue
            used_indices.add(idx)
            detalle = detalles[idx]

            cantidad = _normalize_item_value(item.get("cantidad"))
            if cantidad is not None:
                detalle["cantidad"] = cantidad

            precio = _normalize_item_value(item.get("precioUni"))
            if precio is not None:
                detalle["precio_unitario"] = precio

            descuento = _normalize_item_value(item.get("montoDescu"))
            if descuento is not None:
                detalle["descuento"] = descuento
                if descuento and str(detalle.get("descuento_tipo", "")).strip() == "%":
                    detalle["descuento_tipo"] = "$"

            for dest, src in (
                ("ventas_gravadas", "ventaGravada"),
                ("ventas_exentas", "ventaExenta"),
                ("ventas_no_sujetas", "ventaNoSuj"),
            ):
                value = _normalize_item_value(item.get(src))
                if value is not None:
                    detalle[dest] = value

            iva_val = _normalize_item_value(item.get("ivaItem"))
            if iva_val is None:
                base_val = detalle.get("ventas_gravadas")
                if base_val is None:
                    base_val = _normalize_item_value(item.get("ventaGravada"))
                if base_val is not None:
                    try:
                        iva_val = float(iva_item(D(str(base_val))))
                    except (InvalidOperation, ValueError, TypeError):
                        iva_val = None
            if iva_val is not None:
                detalle["iva"] = iva_val

    if not venta_data.get("total_letras"):
        try:
            venta_data["total_letras"] = monto_a_texto_sv(venta_data.get("total", 0))
        except Exception:
            venta_data["total_letras"] = ""

    venta_data["codigo_generacion"] = codigo_generacion
    venta_data["numero_control"] = numero_control

    file_path_str, json_path_str = get_document_paths(
        venta_data.get("fecha"), cliente_nombre, numero_control or venta_id, doc_key
    )
    file_path = Path(file_path_str)
    json_path = Path(json_path_str)

    def _render_invoice_pdf(output_path: Path) -> None:
        generar_factura_electronica_pdf(
            venta_data,
            detalles,
            cliente or {},
            distribuidor or {},
            tipo_doc,
            archivo=str(output_path),
            codigo_generacion=codigo_generacion,
            numero_control=numero_control,
            sello_recepcion=sello_recepcion,
            tipo_modelo=tipo_modelo,
            tipo_operacion=tipo_operacion,
            fecha_generacion=fecha_generacion,
            ambiente=ambiente,
            tipo_contingencia=tipo_contingencia,
            motivo_contin=motivo_contin,
        )

    logger.info(
        "Intentando generar PDF en %s con renderer=%s",
        file_path,
        _render_invoice_pdf,
    )
    logger.info("Generando PDF de factura en %s", file_path)
    write_pdf_atomically(file_path, _render_invoice_pdf)
    try:
        pdf_size = file_path.stat().st_size
    except OSError:
        logger.warning("No se pudo obtener tamaño de PDF en %s", file_path, exc_info=True)
        pdf_size = None
    else:
        logger.info("PDF de factura escrito en %s (%s bytes)", file_path, pdf_size)
    if tipo_operacion == 2:
        manager.db.add_dte_pendiente(venta_id, json_data, "2")
    elif wants_contingencia:
        manager.db.add_dte_pendiente(venta_id, json_data, "2")
    try:
        resumen = json_data.get("resumen", {})
        condicion = normalize_condicion_operacion(
            resumen.get("condicionOperacion")
        )
        resumen["condicionOperacion"] = condicion
        validate_pagos_basico(resumen, condicion)
        json_data["resumen"] = resumen
    except ValueError as exc:
        logger.error("ERROR: DTE inválido: %s", exc)
        raise ValueError(f"DTE inválido: {exc}") from exc
    if retencion_block:
        cr_result = _maybe_generate_cr(manager, venta_id, json_data, retencion_block, ambiente)
        _set_last_cr_result(manager, cr_result)
    jws_token = None
    try:
        _, jws_token = sign_and_save(json_data, str(json_path), return_token=True)
    except Exception:
        logger.exception("Fallo al firmar y guardar JSON en %s", json_path)
        jws_token = None
    try:
        persist_client_json(json_path, json_data, firma=jws_token)
    except Exception:
        logger.exception(
            "No se pudo generar la versión para cliente del JSON en %s", json_path
        )
    try:
        pend_json_path = dte.save_dte_json(json_data, filename=json_path.name)
        version_dir = os.path.dirname(pend_json_path)
        if jws_token:
            try:
                sobre = dte.construir_sobre_recepcion(jws_token, json_data)
                if sobre.get("estado") != "Error":
                    versioned_dte.save_estado(version_dir, sobre)
            except Exception:
                pass
        try:
            manager.db.update_venta_extra(venta_id, {"dteJsonPath": pend_json_path})
        except Exception:
            pass
    except Exception:
        pass
    _ensure_invoice_copies(file_path, json_path, json_data, _render_invoice_pdf)
    try:
        ensured_contents = sorted(p.name for p in file_path.parent.iterdir())
    except Exception:
        ensured_contents = None
    logger.info(
        "Estado post _ensure_invoice_copies -> PDF missing=%s JSON missing=%s; contenido %s: %s",
        _path_missing(file_path),
        _path_missing(json_path),
        file_path.parent,
        ensured_contents,
    )
    if _path_missing(file_path):
        try:
            contents = sorted(p.name for p in file_path.parent.iterdir())
        except Exception:
            contents = None
        logger.error(
            "No se encontró PDF en %s; contenido de la carpeta: %s",
            file_path,
            contents,
        )
        raise IOError(f"No se pudo guardar PDF en {file_path}")
    if _path_missing(json_path):
        try:
            contents = sorted(p.name for p in json_path.parent.iterdir())
        except Exception:
            contents = None
        logger.error(
            "No se encontró JSON en %s; contenido de la carpeta: %s",
            json_path,
            contents,
        )

        raise IOError(f"No se pudo guardar JSON en {json_path}")
    try:
        json_size = json_path.stat().st_size
    except OSError:
        logger.warning("No se pudo obtener tamaño de JSON en %s", json_path, exc_info=True)
    else:
        logger.info("JSON de factura escrito en %s (%s bytes)", json_path, json_size)
    manager.db.add_factura_pdf(venta_id, tipo_doc, str(file_path))
    return str(file_path)


def generate_ticket_pdf(manager, venta_id, out_path: str | None = None):
    """Generate and store the ticket PDF for a sale."""

    def _handle_ticket_runtime_error(exc: RuntimeError):
        logger.error("No se pudo generar el PDF del ticket: %s", exc, exc_info=True)
        print("[Ticket] No se pudo generar el PDF:", exc)
        return None

    venta = next((v for v in manager.db.get_ventas() if v["id"] == venta_id), None)
    if not venta:
        return None

    detalles = manager.db.get_detalles_venta(venta_id)
    extra = {}
    raw_extra = venta.get("extra") if venta else None
    if raw_extra:
        try:
            extra = json.loads(raw_extra)
        except Exception:
            extra = {}

    default_tipo = 2 if dte.get_default_modo_transmision() == "contingencia" else 1
    tipo_operacion = extra.get("tipoOperacion") or default_tipo
    tipo_contingencia = extra.get("tipoContingencia")
    motivo_contin = extra.get("motivoContin")
    if tipo_operacion == 2:
        cfg = dte._load_datos_negocio().get("dte_api", {})
        if tipo_contingencia is None:
            tipo_contingencia = cfg.get("tipo_contingencia")
        if motivo_contin is None:
            motivo_contin = cfg.get("motivo_contin")
        extra.setdefault("tipoOperacion", 2)
        if tipo_contingencia is not None:
            extra.setdefault("tipoContingencia", tipo_contingencia)
        if motivo_contin is not None:
            extra.setdefault("motivoContin", motivo_contin)

    cliente = None
    if venta.get("cliente_id"):
        cliente = next((c for c in manager._clientes if c["id"] == venta["cliente_id"]), None)
    cliente_nombre = cliente.get("nombre") if cliente else ""

    filename, json_path = get_document_paths(
        venta.get("fecha"), cliente_nombre, venta_id, "Ticket"
    )

    if hasattr(manager.db, "cursor"):
        ticket_json = generar_ticket_json(
            manager.db,
            venta_id,
            tipo_operacion=tipo_operacion,
            tipo_contingencia=tipo_contingencia,
            motivo_contin=motivo_contin,
        )
    else:
        venta_data = dict(venta)
        if tipo_operacion == 2:
            venta_data["tipo_operacion"] = 2
        if not venta_data.get("codigo_generacion"):
            venta_data["codigo_generacion"] = uuid.uuid4().hex
        if not venta_data.get("numero_control"):
            venta_data["numero_control"] = uuid.uuid4().hex[:8].upper()
        ticket_json = build_invoice_json(venta_data, cliente or {}, detalles)
    if tipo_operacion == 2:
        manager.db.add_dte_pendiente(venta_id, ticket_json, "2")
    try:
        resumen = ticket_json.get("resumen", {})
        condicion = normalize_condicion_operacion(
            resumen.get("condicionOperacion")
        )
        resumen["condicionOperacion"] = condicion
        validate_pagos_basico(resumen, condicion)
        ticket_json["resumen"] = resumen
    except ValueError as exc:
        logger.error("ERROR: DTE inválido: %s", exc)
        raise ValueError(f"DTE inválido: {exc}") from exc
    jws_token = None
    try:
        _, jws_token = sign_and_save(ticket_json, json_path, return_token=True)
    except Exception:
        pass
    try:
        pend_json_path = dte.save_dte_json(ticket_json, filename=os.path.basename(json_path))
        version_dir = os.path.dirname(pend_json_path)
        if jws_token:
            try:
                sobre = dte.construir_sobre_recepcion(jws_token, ticket_json)
                if sobre.get("estado") != "Error":
                    versioned_dte.save_estado(version_dir, sobre)
            except Exception:
                pass
        try:
            manager.db.update_venta_extra(venta_id, {"dteJsonPath": pend_json_path})
        except Exception:
            pass
    except Exception:
        pass
    tipo_dte = ticket_json.get("identificacion", {}).get("tipoDte")
    if tipo_dte == "01" and not extra.get("es_ticket"):
        extra["es_ticket"] = True
        try:
            manager.db.update_venta_extra(venta_id, {"es_ticket": True})
        except Exception:
            pass

    dte_data = dict(extra)
    dte_data["dteJson"] = ticket_json
    try:
        if tipo_dte == "01" and extra.get("es_ticket"):
            generar_ticket_fe_pdf(venta, detalles, filename, dte_data=dte_data)
        else:
            generar_ticket_personalizado(venta, detalles, filename, dte_data=dte_data)
    except RuntimeError as exc:
        return _handle_ticket_runtime_error(exc)
    if not os.path.exists(json_path):
        raise IOError(f"No se pudo guardar JSON en {json_path}")
    manager.db.add_ticket_pdf(venta_id, filename)
    return filename
