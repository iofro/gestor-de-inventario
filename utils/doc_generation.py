import json
import os
import uuid
import logging

import dte
from factura_sv import generar_factura_electronica_pdf
from ticket_pdf import generar_ticket_personalizado
from dte import generar_ticket_json, generar_dte_json
from utils.monto import monto_a_texto_sv, iva_item, to_base_iva
from utils.docs import get_document_paths, build_invoice_json
from utils.jws import sign_and_save
from utils.resumen import normalize_condicion_operacion, validate_pagos_basico
from utils.sanitize import limpiar_documentos


logger = logging.getLogger(__name__)

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
    fecha_generacion = venta_data.get("fecha_generacion") or extra.get("fechaGeneracion", "")

    if tipo_operacion == 1 and not sello_recepcion:
        sello_recepcion = f"SELLO-{uuid.uuid4().hex[:8]}"
        venta_data["sello_recepcion"] = sello_recepcion
    venta_data["tipo_operacion"] = tipo_operacion
    tipo_modelo = 2 if tipo_operacion == 2 else 1

    tipo_doc = "Crédito Fiscal" if credito_info else "Consumidor Final"
    doc_key = "CreditoFiscal" if credito_info else "ConsumidorFinal"
    cliente_nombre = cliente.get("nombre") if cliente else ""
    try:
        json_data = generar_dte_json(
            manager.db,
            venta_id,
            tipo_dte="03" if credito_info else "01",
            ambiente=ambiente,
            tipo_operacion=tipo_operacion,
            tipo_contingencia=tipo_contingencia,
            motivo_contin=motivo_contin,
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

    ident = json_data.get("identificacion", {})
    codigo_generacion = ident.get("codigoGeneracion")
    numero_control = ident.get("numeroControl")
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
    try:
        jws_path = sign_and_save(json_data, json_path)
        try:
            with open(jws_path, "r", encoding="utf-8") as fh:
                jws_token = fh.read()
            dte._save_signed_dte(json_data, jws_token)
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

    generar_ticket_personalizado(venta, detalles, filename, dte_data=extra)
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
    try:
        sign_and_save(ticket_json, json_path)
    except Exception:
        pass
    if not os.path.exists(json_path):
        raise IOError(f"No se pudo guardar JSON en {json_path}")
    manager.db.add_ticket_pdf(venta_id, filename)
    return filename
