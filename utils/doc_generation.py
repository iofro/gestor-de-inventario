import json
import os
import uuid
import logging
from datetime import datetime

import dte
from factura_sv import generar_factura_electronica_pdf
from ticket_pdf import generar_ticket_personalizado, generar_ticket_fe_pdf
from dte import generar_ticket_json, generar_dte_json, d4, generar_cabecera_dte_data
from utils.monto import D, d2, monto_a_texto_sv, iva_item, to_base_iva
from utils.docs import get_document_paths, build_invoice_json
from utils.jws import sign_and_save
from utils import versioned_dte
from utils.resumen import normalize_condicion_operacion, validate_pagos_basico
from utils.sanitize import limpiar_documentos


logger = logging.getLogger(__name__)


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
    ambiente = venta_data.get("ambiente") or extra.get("ambiente") or "00"
    if ambiente not in ("00", "01"):
        amb_cfg = str(ambiente).lower()
        ambiente = "01" if amb_cfg.startswith("produc") else "00"

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
    resumen = json_data.get("resumen", {})
    venta_data.update(
        {
            "sumas": resumen.get("sumas", 0),
            "descuentos": resumen.get("descuentos", 0),
            "iva": resumen.get("iva", 0),
            "subtotal": resumen.get("subtotal", 0),
            "ventas_exentas": resumen.get("ventasExentas", 0),
            "ventas_no_sujetas": resumen.get("ventasNoSujetas", 0),
            "total": resumen.get("totalPagar", 0),
        }
    )
    if not venta_data.get("total_letras"):
        try:
            venta_data["total_letras"] = monto_a_texto_sv(venta_data.get("total", 0))
        except Exception:
            venta_data["total_letras"] = ""

    venta_data["codigo_generacion"] = codigo_generacion
    venta_data["numero_control"] = numero_control

    file_path, json_path = get_document_paths(
        venta_data.get("fecha"), cliente_nombre, numero_control or venta_id, doc_key
    )

    generar_factura_electronica_pdf(
        venta_data,
        detalles,
        cliente or {},
        distribuidor or {},
        tipo_doc,
        archivo=file_path,
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
        _, jws_token = sign_and_save(json_data, json_path, return_token=True)
    except Exception:
        pass
    try:
        pend_json_path = dte.save_dte_json(json_data, filename=os.path.basename(json_path))
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
    if not os.path.exists(json_path):
        raise IOError(f"No se pudo guardar JSON en {json_path}")
    manager.db.add_factura_pdf(venta_id, tipo_doc, file_path)
    return file_path


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
    dte_data = dict(extra)
    dte_data["dteJson"] = ticket_json
    if ticket_json.get("identificacion", {}).get("tipoDte") == "01" and extra.get("es_ticket"):
        generar_ticket_fe_pdf(venta, detalles, filename, dte_data=dte_data)
    else:
        generar_ticket_personalizado(venta, detalles, filename, dte_data=dte_data)
    if not os.path.exists(json_path):
        raise IOError(f"No se pudo guardar JSON en {json_path}")
    manager.db.add_ticket_pdf(venta_id, filename)
    return filename
