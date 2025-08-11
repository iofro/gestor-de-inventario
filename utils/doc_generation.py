import json
import os
import uuid

from factura_sv import generar_factura_electronica_pdf
from ticket_pdf import generar_ticket_personalizado
from dte import generar_ticket_json
from utils.monto import monto_a_texto_sv
from utils.docs import get_document_paths, build_invoice_json
from utils.jws import get_cert_config, sign_and_save, CONFIG_NEGOCIO_PATH


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

    if venta_data.get("vendedor_id"):
        trabajador = manager.db.get_trabajador(venta_data["vendedor_id"])
        if trabajador:
            venta_data["vendedor_nombre"] = trabajador.get("nombre", "")

    sumas = descuentos = 0
    ventas_exentas = ventas_no_sujetas = iva = 0
    for d in detalles:
        base_total = d.get("precio_unitario", 0) * d.get("cantidad", 0)
        desc = d.get("descuento", 0)
        if d.get("descuento_tipo") == "%":
            desc = base_total * d.get("descuento", 0) / 100
        base = base_total - desc
        iva_item = d.get("iva", 0)
        tipo = d.get("tipo_fiscal", "").lower()
        if tipo == "venta exenta":
            d["ventas_exentas"] = base
            ventas_exentas += base
        elif tipo == "venta no sujeta":
            d["ventas_no_sujetas"] = base
            ventas_no_sujetas += base
        else:
            d["ventas_gravadas"] = base
            sumas += base_total
            descuentos += desc
            iva += iva_item

    subtotal = (sumas - descuentos) + iva
    total = subtotal + ventas_exentas + ventas_no_sujetas
    venta_data.update(
        {
            "sumas": sumas,
            "descuentos": descuentos,
            "iva": iva,
            "ventas_exentas": ventas_exentas,
            "ventas_no_sujetas": ventas_no_sujetas,
            "subtotal": subtotal,
            "total": total,
        }
    )
    if not venta_data.get("total_letras"):
        try:
            venta_data["total_letras"] = monto_a_texto_sv(total)
        except Exception:
            venta_data["total_letras"] = ""

    cliente = None
    if venta.get("cliente_id"):
        cliente = next((c for c in manager._clientes if c["id"] == venta["cliente_id"]), None)
    distribuidor = None
    if venta.get("Distribuidor_id"):
        distribuidor = next(
            (d for d in manager._Distribuidores if d["id"] == venta["Distribuidor_id"]),
            None,
        )

    extra = venta_data.get("extra") or {}
    if isinstance(extra, str):
        try:
            extra = json.loads(extra)
        except Exception:
            extra = {}
    if not venta_data.get("venta_a_cuenta_de"):
        venta_data["venta_a_cuenta_de"] = extra.get("venta_a_cuenta_de", "")
    if not venta_data.get("documento_venta_a_cuenta"):
        venta_data["documento_venta_a_cuenta"] = extra.get("documento_venta_a_cuenta", "")
    dte_json = extra.get("dteJson") or extra.get("dte_json") or {}
    ident = dte_json.get("identificacion", {})
    codigo_generacion = venta_data.get("codigo_generacion") or ident.get("codigoGeneracion", "")
    numero_control = venta_data.get("numero_control") or dte_json.get("numeroControl", "")
    sello_recepcion = venta_data.get("sello_recepcion") or extra.get("selloRecibido", "")
    modelo_facturacion = venta_data.get("modelo_facturacion") or ident.get("modeloFacturacion", "")
    if not modelo_facturacion:
        modelo_facturacion = "1 - Facturación previo"
    tipo_transmision = venta_data.get("tipo_transmision") or ident.get("tipoTransmision", "")
    if not tipo_transmision:
        tipo_transmision = "1 - Transmisión normal"
    fecha_generacion = venta_data.get("fecha_generacion") or ident.get("fecGeneracion", "")

    if tipo_transmision.startswith("1") and not sello_recepcion:
        sello_recepcion = f"SELLO-{uuid.uuid4().hex[:8]}"
        venta_data["sello_recepcion"] = sello_recepcion
    venta_data["tipo_transmision"] = tipo_transmision

    tipo_doc = "Crédito Fiscal" if credito_info else "Consumidor Final"
    doc_key = "CreditoFiscal" if credito_info else "ConsumidorFinal"
    cliente_nombre = cliente.get("nombre") if cliente else ""
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
        modelo_facturacion=modelo_facturacion,
        tipo_transmision=tipo_transmision,
        fecha_generacion=fecha_generacion,
    )
    json_data = build_invoice_json(venta_data, cliente or {}, detalles)
    with open(json_path, 'w', encoding='utf-8') as fh:
        json.dump(json_data, fh, ensure_ascii=False, indent=2)
    if tipo_transmision.startswith("2"):
        manager.db.add_dte_pendiente(venta_id, json_data, tipo_transmision)
    if not os.path.exists(json_path):
        raise IOError(f"No se pudo guardar JSON en {json_path}")
    cert_path, key_path, cert_pass = get_cert_config(CONFIG_NEGOCIO_PATH)
    if cert_path:
        try:
            sign_and_save(json_data, json_path, cert_path, cert_pass, key_path)
        except Exception:
            pass
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

    cliente = None
    if venta.get("cliente_id"):
        cliente = next((c for c in manager._clientes if c["id"] == venta["cliente_id"]), None)
    cliente_nombre = cliente.get("nombre") if cliente else ""

    filename, json_path = get_document_paths(
        venta.get("fecha"), cliente_nombre, venta_id, "Ticket"
    )

    generar_ticket_personalizado(venta, detalles, filename, dte_data=extra)
    if hasattr(manager.db, "cursor"):
        ticket_json = generar_ticket_json(manager.db, venta_id)
    else:
        venta_data = dict(venta)
        if not venta_data.get("codigo_generacion"):
            venta_data["codigo_generacion"] = uuid.uuid4().hex
        if not venta_data.get("numero_control"):
            venta_data["numero_control"] = uuid.uuid4().hex[:8].upper()
        ticket_json = build_invoice_json(venta_data, cliente or {}, detalles)
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(ticket_json, fh, ensure_ascii=False, indent=2)
    if not os.path.exists(json_path):
        raise IOError(f"No se pudo guardar JSON en {json_path}")
    cert_path, key_path, cert_pass = get_cert_config(CONFIG_NEGOCIO_PATH)
    if cert_path:
        try:
            sign_and_save(ticket_json, json_path, cert_path, cert_pass, key_path)
        except Exception:
            pass
    manager.db.add_ticket_pdf(venta_id, filename)
    return filename
