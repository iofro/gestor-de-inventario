import json
import os
import uuid
import logging
from datetime import datetime
from decimal import InvalidOperation
from typing import Callable

import dte
from pathlib import Path
from factura_sv import generar_factura_electronica_pdf
from ticket_pdf import generar_ticket_personalizado, generar_ticket_fe_pdf
from dte import generar_ticket_json, generar_dte_json, d4, generar_cabecera_dte_data
from utils.monto import D, d2, monto_a_texto_sv, iva_item, to_base_iva
from utils.docs import get_document_paths, build_invoice_json, write_pdf_atomically
from utils.jws import sign_and_save
from utils import versioned_dte
from utils.resumen import normalize_condicion_operacion, validate_pagos_basico
from utils.sanitize import limpiar_documentos
from utils.stable_json import save_file, stable_stringify


logger = logging.getLogger(__name__)


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

    credito_info = manager.db.get_venta_credito_fiscal(venta_id)
    detalles = manager.db.get_detalles_venta(venta_id)

    venta_data = dict(venta)
    if credito_info:
        venta_data.update(credito_info)

    # Parse extra information early to know if prices include IVA
    extra = venta_data.get("extra") or {}
    if isinstance(extra, str):
        try:
            extra = json.loads(extra)
        except Exception:
            extra = {}
    venta_data["extra"] = extra
    precios_incluyen_iva = bool(extra.get("precios_incluyen_iva"))

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
        manager.db.add_dte_pendiente(venta_id, json_data, str(tipo_operacion))
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
    jws_token = None
    try:
        _, jws_token = sign_and_save(json_data, str(json_path), return_token=True)
    except Exception:
        logger.exception("Fallo al firmar y guardar JSON en %s", json_path)
        jws_token = None
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


def generate_ticket_pdf(manager, venta_id):
    """Generate and store the ticket PDF for the given sale."""
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
    if tipo_dte == "01" and extra.get("es_ticket"):
        generar_ticket_fe_pdf(venta, detalles, filename, dte_data=dte_data)
    else:
        generar_ticket_personalizado(venta, detalles, filename, dte_data=dte_data)
    if not os.path.exists(json_path):
        raise IOError(f"No se pudo guardar JSON en {json_path}")
    manager.db.add_ticket_pdf(venta_id, filename)
    return filename
