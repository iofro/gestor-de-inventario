from pathlib import Path
import logging

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, Table, TableStyle
from reportlab.lib import colors
from reportlab.graphics import renderPDF
from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing
from reportlab.lib.units import mm
from reportlab.lib.styles import ParagraphStyle

from utils.pdf_utils import (
    draw_wrapped_text,
    draw_text_with_ellipsis,
    ellipsize_text,
    wrap_text_lines,
)
import utils.catalogos as catalogos
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode
import ast
import json
import os
from datetime import datetime
from paths import DATOS_NEGOCIO_PATH
from utils import resource_path
from utils.inventario import obtener_info_lote, formatear_fecha_vencimiento_ui
from xml.sax.saxutils import escape


def build_qr_url(dte: dict) -> str:
    """Return the public consultation URL for a DTE."""

    ident = dte.get("identificacion", {}) if isinstance(dte, dict) else {}
    ambiente = str(ident.get("ambiente", "00")).strip()
    ambiente = "01" if ambiente == "01" else "00"
    codigo = ident.get("codigoGeneracion")
    fecha = ident.get("fecEmi") or ident.get("fechaEmi")
    base_url = "https://admin.factura.gob.sv/consultaPublica"
    params = {"ambiente": ambiente, "codGen": codigo, "fechaEmi": fecha}
    return base_url + "?" + urlencode(params)


def format_direccion(direccion):
    """Format a ``direccion`` into "Municipio, complemento".

    ``direccion`` can be either a mapping with ``departamento`` and
    ``municipio`` codes plus a ``complemento`` field or a plain string. When a
    string is provided it is returned unchanged.
    """

    if not direccion:
        return ""

    if isinstance(direccion, str):
        return direccion

    departamento = str(direccion.get("departamento", "")).zfill(2)
    municipio = str(direccion.get("municipio", "")).zfill(2)
    complemento = direccion.get("complemento", "")
    if isinstance(complemento, dict):
        complemento = format_direccion(complemento)
    elif not isinstance(complemento, str):
        complemento = str(complemento)
    codigo_municipio = f"{departamento}{municipio}" if departamento or municipio else ""
    nombre_municipio = catalogos.get_value("CAT-013", codigo_municipio) or ""
    parts = [p for p in (nombre_municipio, complemento) if p]
    return ", ".join(parts)


def _metadata_desde_inventario(detalle: dict) -> dict[str, str | None]:
    """Obtener información de lote, vencimiento y registro para un detalle."""

    def _parse_extra(raw):
        if raw in (None, ""):
            return None
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, (bytes, bytearray)):
            try:
                raw = raw.decode("utf-8")
            except Exception:
                return None
        if isinstance(raw, str):
            text = raw.strip()
            if not text:
                return None
            try:
                return json.loads(text)
            except Exception:
                try:
                    return ast.literal_eval(text)
                except Exception:
                    return None
        return None

    def _clean_text(value):
        if value is None:
            return None
        if isinstance(value, str):
            text = value.strip()
            return text or None
        text = str(value).strip()
        return text or None

    def _to_int(value):
        if value in (None, ""):
            return None
        try:
            return int(str(value))
        except (TypeError, ValueError):
            return None

    extra_data = _parse_extra(detalle.get("extra"))

    nested_candidates: list[dict] = []
    if isinstance(extra_data, dict):
        nested_candidates.append(extra_data)
        lotes_value = extra_data.get("lotes")
        if isinstance(lotes_value, list):
            for item in lotes_value:
                if isinstance(item, dict):
                    nested_candidates.append(item)
                    break
    if isinstance(detalle, dict):
        nested_candidates.append(detalle)

    def _first(keys: tuple[str, ...]):
        for source in nested_candidates:
            if not isinstance(source, dict):
                continue
            for key in keys:
                if key in source and source[key] not in (None, ""):
                    return source[key]
        return None

    lote_id = _to_int(_first(("lote_id", "loteId")))
    producto_id = _to_int(_first(("producto_id", "productoId")))
    codigo_lote = _clean_text(_first(("codigo_lote", "lote", "codigo")))
    registro_extra = _clean_text(
        _first(("registro_sanitario", "registroSanitario", "registro"))
    )
    vencimiento_extra = _first(("fecha_vencimiento", "fechaVencimiento", "vencimiento"))

    proveedor_info: dict[str, object] | None = None
    if any(value is not None for value in (lote_id, codigo_lote, producto_id)):
        proveedor_info = obtener_info_lote(
            lote_id=lote_id,
            codigo_lote=codigo_lote,
            producto_id=producto_id,
        )

    metadata: dict[str, str | None] = {"lote": None, "vencimiento": None, "registro": None}

    if isinstance(proveedor_info, dict):
        lote_val = _clean_text(
            proveedor_info.get("lote")
            if "lote" in proveedor_info
            else proveedor_info.get("codigo_lote")
        )
        registro_val = _clean_text(
            proveedor_info.get("registro")
            if "registro" in proveedor_info
            else proveedor_info.get("registro_sanitario")
        )
        vencimiento_val = proveedor_info.get("vencimiento")

        if lote_val:
            metadata["lote"] = lote_val
        if registro_val:
            metadata["registro"] = registro_val

        vencimiento_formateado = formatear_fecha_vencimiento_ui(vencimiento_val)
        if vencimiento_formateado:
            metadata["vencimiento"] = vencimiento_formateado
        else:
            vencimiento_texto = _clean_text(vencimiento_val)
            if vencimiento_texto:
                metadata["vencimiento"] = vencimiento_texto

    if metadata["lote"] is None:
        metadata["lote"] = codigo_lote
    if metadata["registro"] is None:
        metadata["registro"] = registro_extra
    if metadata["vencimiento"] is None:
        vencimiento_formateado = formatear_fecha_vencimiento_ui(vencimiento_extra)
        if vencimiento_formateado:
            metadata["vencimiento"] = vencimiento_formateado
        else:
            metadata["vencimiento"] = _clean_text(vencimiento_extra)

    return metadata


def _resolve_logo_path(datos_negocio: dict) -> str | None:
    """Return the preferred logo path if available."""

    candidates = []
    for key in ("logo_path", "logoPath", "logo"):
        value = datos_negocio.get(key)
        if isinstance(value, str) and value.strip():
            candidates.append(value.strip())

    default_logo = resource_path("logoinventario.jpg")
    if default_logo.exists():
        candidates.append(str(default_logo))

    user_dir = Path(DATOS_NEGOCIO_PATH).resolve().parent

    for raw in candidates:
        expanded = os.path.expanduser(raw)
        paths_to_try = [expanded]
        if not os.path.isabs(expanded):
            paths_to_try.append(str(user_dir / expanded))
            res_candidate = resource_path(expanded)
            if res_candidate.exists():
                paths_to_try.append(str(res_candidate))
        for candidate in paths_to_try:
            if candidate and os.path.exists(candidate):
                return candidate
    return None


def generar_factura_electronica_pdf(
    venta,
    detalles,
    cliente,
    distribuidor,
    tipo_documento="Crédito Fiscal",
    archivo="factura_electronica.pdf",
    datos_negocio=None,
    codigo_generacion="",
    numero_control="",
    sello_recepcion="",
    tipo_modelo: int = 1,
    tipo_operacion: int = 1,
    fecha_generacion="",
    ambiente: str = "00",
    tipo_contingencia: int | None = None,
    motivo_contin: str | None = None,
    tipo_dte: str | None = None,
    doc_relacionado: dict | None = None,
    motivo: str | None = None,
):

    if datos_negocio is None:
        datos_negocio = {}
        if os.path.exists(DATOS_NEGOCIO_PATH):
            try:
                with open(DATOS_NEGOCIO_PATH, "r", encoding="utf-8") as f:
                    datos_negocio = json.load(f)
            except Exception:
                datos_negocio = {}
    ambiente_cfg = datos_negocio.get("dte_api", {}).get("ambiente")
    if ambiente not in ("00", "01") and ambiente_cfg:
        ambiente_cfg = ambiente_cfg.lower()
        ambiente = "01" if ambiente_cfg.startswith("produc") else "00"

    if not tipo_dte:
        tipo_dte = "01" if tipo_documento.upper() == "CONSUMIDOR FINAL" else "03"

    if not codigo_generacion or not numero_control:
        raise ValueError("codigo_generacion and numero_control are required")

    if not fecha_generacion or str(fecha_generacion).strip().lower() in {"none", "null"}:
        fecha_generacion = datetime.now().strftime("%d/%m/%Y, %I:%M %p")
    try:
        fecha_emision = datetime.strptime(
            fecha_generacion.split(",")[0].strip(), "%d/%m/%Y"
        ).strftime("%Y-%m-%d")
    except Exception:
        fecha_emision = datetime.now().strftime("%Y-%m-%d")

    c = canvas.Canvas(archivo, pagesize=letter)
    width, height = letter
    x_margin = 30
    y_margin = 30


    top = height - 45
    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(width / 2, top, "DOCUMENTO TRIBUTARIO ELECTRÓNICO")

    top -= 16
    c.setFont("Helvetica-Bold", 11)
    titulo = tipo_documento.upper()
    if tipo_dte and tipo_documento.lower().startswith("nota de cr"):
        titulo = f"NOTA DE CRÉDITO ({tipo_dte})"
    elif tipo_dte and tipo_documento.lower().startswith("nota de d"):
        titulo = f"NOTA DE DÉBITO ({tipo_dte})"
    c.drawCentredString(width / 2, top, titulo)

    c.setFont("Helvetica", 9)

    header_gap = 22
    header_h = 90
    header_y = top - header_gap - header_h
    header_w = width - 2 * x_margin

    c.setLineWidth(0.7)
    c.setStrokeColor(colors.white)
    c.roundRect(x_margin, header_y, header_w, header_h, 8, stroke=1, fill=0)
    c.setStrokeColor(colors.black)

    logo_slot_w = 90
    inner_padding = 10
    logo_height = header_h - 2 * inner_padding
    logo_path = _resolve_logo_path(datos_negocio)
    if logo_path:
        logo_x = x_margin + inner_padding
        logo_y = header_y + header_h - logo_height - inner_padding
        c.drawImage(
            logo_path,
            logo_x,
            logo_y,
            width=logo_slot_w,
            height=logo_height,
            preserveAspectRatio=True,
            mask="auto",
        )

    qr_size = 26 * mm
    qr_x = x_margin + header_w - qr_size - inner_padding
    qr_y = header_y + (header_h - qr_size) / 2
    qr_url = build_qr_url(
        {"identificacion": {
            "ambiente": ambiente,
            "codigoGeneracion": codigo_generacion,
            "fecEmi": fecha_emision,
        }}
    )
    qr_code = qr.QrCodeWidget(qr_url)
    bounds = qr_code.getBounds()
    w = bounds[2] - bounds[0]
    h = bounds[3] - bounds[1]
    d = Drawing(qr_size, qr_size, transform=[qr_size / w, 0, 0, qr_size / h, 0, 0])
    d.add(qr_code)
    renderPDF.draw(d, c, qr_x, qr_y)
    c.linkURL(qr_url, (qr_x, qr_y, qr_x + qr_size, qr_y + qr_size), relative=0)

    text_x = x_margin + logo_slot_w + 2 * inner_padding
    text_right_limit = qr_x - inner_padding
    text_width = max(10, text_right_limit - text_x)
    text_y = header_y + header_h - inner_padding - 2
    line_height = 12

    text_y = draw_wrapped_text(
        c,
        f"Código Generación: {codigo_generacion}",
        text_x,
        text_y,
        text_width,
        line_height,
    )
    text_y = draw_wrapped_text(
        c,
        f"Número Control: {numero_control}",
        text_x,
        text_y,
        text_width,
        line_height,
    )
    text_y = draw_wrapped_text(
        c,
        f"Sello Recepción: {sello_recepcion}",
        text_x,
        text_y,
        text_width,
        line_height,
    )
    text_y = draw_wrapped_text(
        c,
        f"Fecha Generación: {fecha_generacion}",
        text_x,
        text_y,
        text_width,
        line_height,
    )

    text_y -= 4
    text_y = draw_wrapped_text(
        c,
        f"Tipo Modelo: {tipo_modelo}",
        text_x,
        text_y,
        text_width,
        line_height,
    )
    text_y = draw_wrapped_text(
        c,
        f"Tipo Operación: {tipo_operacion}",
        text_x,
        text_y,
        text_width,
        line_height,
    )
    if tipo_contingencia is not None:
        draw_wrapped_text(
            c,
            f"Contingencia: {tipo_contingencia}",
            text_x,
            text_y,
            text_width,
            line_height,
        )

    # Información del documento relacionado y motivo
    doc_y = header_y - 12
    if doc_relacionado or motivo:
        c.setFont("Helvetica-Bold", 9)
        c.drawString(x_margin, doc_y, "DOCUMENTO RELACIONADO:")
        c.setFont("Helvetica", 8)
        doc_y -= 12
        if doc_relacionado:
            t = doc_relacionado.get("tipo", "")
            num = doc_relacionado.get("numero_control", "")
            c.drawString(x_margin, doc_y, f"Tipo: {t}  Número Control: {num}")
            doc_y -= 12
            cod = doc_relacionado.get("codigo_generacion", "")
            fec = doc_relacionado.get("fecha", "")
            c.drawString(x_margin, doc_y, f"Código Generación: {cod}  Fecha: {fec}")
            doc_y -= 12
        if motivo:
            doc_y = draw_wrapped_text(c, f"Motivo: {motivo}", x_margin, doc_y, width - 2 * x_margin, 12)
        doc_y -= 8
    else:
        doc_y = qr_y

    # Posiciones base para los cuadros de emisor y receptor
    # Mantenemos un espacio de 20 puntos debajo del bloque anterior para acercarlos al encabezado
    encabezado_y = doc_y - 20

    # --- Datos del EMISOR (izquierda) y RECEPTOR (derecha) ---

    box_w = (width - 2 * x_margin - 10) // 2
    line_h = 12

    telefono = datos_negocio.get('telefono', '')
    correo_emisor = datos_negocio.get('correo') or datos_negocio.get('email_usuario', '')

    extra_info = venta.get("extra")
    if isinstance(extra_info, str):
        try:
            extra_info = json.loads(extra_info)
        except Exception:
            extra_info = {}
    elif not isinstance(extra_info, dict):
        extra_info = {}

    def _clean_field(primary_value, fallback_value):
        for candidate in (primary_value, fallback_value):
            if candidate in (None, ""):
                continue
            text = str(candidate).strip()
            if text:
                return text
        return ""

    venta_a_cuenta_text = _clean_field(
        venta.get("venta_a_cuenta_de"), extra_info.get("venta_a_cuenta_de")
    )
    documento_venta_a_cuenta_text = _clean_field(
        venta.get("documento_venta_a_cuenta"),
        extra_info.get("documento_venta_a_cuenta"),
    )

    emisor_lines = [
        f"Nombre: {datos_negocio.get('nombre', '')}",
        f"NIT: {datos_negocio.get('nit', '')}  NRC: {datos_negocio.get('nrc', '')}",
        f"Giro: {datos_negocio.get('descActividad', '')}",
        f"Dirección: {format_direccion(datos_negocio.get('direccion'))}",
    ]
    if telefono:
        emisor_lines.append(f"Número Teléfono: {telefono}")
    if correo_emisor:
        emisor_lines.append(f"Correo Electrónico: {correo_emisor}")

    emisor_line_count = 1 + len(emisor_lines)  # incluye encabezado

    notas_tipo = ("nota de crédito", "nota de débito", "nota de remisión")
    tipo_documento_normalizado = tipo_documento.lower().strip()
    mostrar_datos_receptor_completos = (
        tipo_documento == "Crédito Fiscal"
        or tipo_documento_normalizado in notas_tipo
    )

    direccion_cliente = cliente.get("direccion")
    if isinstance(direccion_cliente, dict):
        cliente_dir = direccion_cliente
    else:
        cliente_dir = {
            "departamento": cliente.get("departamento"),
            "municipio": cliente.get("municipio"),
            "complemento": direccion_cliente,
        }
    direccion = format_direccion(cliente_dir)
    nombre_comercial = cliente.get("nombreComercial") or ""
    correo_receptor = cliente.get("email") or cliente.get("correo") or ""

    direccion_line_count = 1
    direccion_extra_padding = 0.0
    if tipo_documento in {"Consumidor Final", "Crédito Fiscal"}:
        direccion_lines = wrap_text_lines(
            f"Dirección: {direccion}",
            "Helvetica",
            8,
            box_w - 10,
        )
        direccion_line_count = max(1, len(direccion_lines))
        if direccion_line_count > 1:
            direccion_extra_padding = 0.25

    receptor_line_count = 4  # encabezado + nombre + DUI + NIT
    if nombre_comercial:
        receptor_line_count += 1
    if correo_receptor:
        receptor_line_count += 1
    receptor_extra = 1  # línea "Giro/Orden" o espaciado
    if mostrar_datos_receptor_completos:
        receptor_extra += 1  # línea "Condición pago"
    receptor_line_count += receptor_extra
    receptor_line_count += direccion_line_count + direccion_extra_padding
    if venta_a_cuenta_text or documento_venta_a_cuenta_text:
        receptor_line_count += 1

    box_h_emisor = 14 + line_h * emisor_line_count
    box_h_receptor = 14 + line_h * receptor_line_count
    box_h = max(box_h_emisor, box_h_receptor)

    box_y = encabezado_y - box_h
    emisor_x = x_margin
    receptor_x = emisor_x + box_w + 10
    emisor_text_width = box_w - 10
    receptor_col_width = box_w / 2 - 10
    receptor_nombre_width = box_w - 10

    c.setLineWidth(0.7)
    c.roundRect(emisor_x, box_y, box_w, box_h, 6, stroke=1, fill=0)
    c.roundRect(receptor_x, box_y, box_w, box_h, 6, stroke=1, fill=0)

    text_y = box_y + box_h - 14
    c.setFont("Helvetica-Bold", 8)
    c.drawString(emisor_x + 5, text_y, "EMISOR:")
    c.setFont("Helvetica", 8)
    text_y -= 12
    draw_text_with_ellipsis(
        c,
        f"Nombre: {datos_negocio.get('nombre', '')}",
        emisor_x + 5,
        text_y,
        emisor_text_width,
    )
    text_y -= 12
    draw_text_with_ellipsis(
        c,
        f"NIT: {datos_negocio.get('nit', '')}  NRC: {datos_negocio.get('nrc', '')}",
        emisor_x + 5,
        text_y,
        emisor_text_width,
    )
    text_y -= 12
    draw_text_with_ellipsis(
        c,
        f"Giro: {datos_negocio.get('descActividad', '')}",
        emisor_x + 5,
        text_y,
        emisor_text_width,
    )
    text_y -= 12
    direccion_emisor = format_direccion(datos_negocio.get("direccion"))
    text_y = draw_wrapped_text(
        c,
        f"Dirección: {direccion_emisor}",
        emisor_x + 5,
        text_y,
        emisor_text_width,
        line_h,
    )
    if telefono:
        draw_text_with_ellipsis(
            c,
            f"Número Teléfono: {telefono}",
            emisor_x + 5,
            text_y,
            emisor_text_width,
        )
        text_y -= 12
    if correo_emisor:
        draw_text_with_ellipsis(
            c,
            f"Correo Electrónico: {correo_emisor}",
            emisor_x + 5,
            text_y,
            emisor_text_width,
        )
        text_y -= 12

    text_y = box_y + box_h - 14
    c.setFont("Helvetica-Bold", 8)
    c.drawString(receptor_x + 5, text_y, "RECEPTOR:")
    c.setFont("Helvetica", 8)

    left_x = receptor_x + 5
    right_x = receptor_x + box_w / 2 + 5

    text_y -= line_h
    draw_text_with_ellipsis(
        c,
        f"Nombre: {cliente.get('nombre', '')}",
        left_x,
        text_y,
        receptor_nombre_width,
    )

    if nombre_comercial:
        text_y -= line_h
        draw_text_with_ellipsis(
            c,
            f"Nombre comercial: {nombre_comercial}",
            left_x,
            text_y,
            receptor_nombre_width,
        )

    if correo_receptor:
        text_y -= line_h
        draw_text_with_ellipsis(
            c,
            f"Correo electrónico: {correo_receptor}",
            left_x,
            text_y,
            receptor_nombre_width,
        )

    text_y -= line_h
    draw_text_with_ellipsis(
        c,
        f"DUI: {cliente.get('dui', '')}",
        left_x,
        text_y,
        receptor_col_width,
    )
    if mostrar_datos_receptor_completos:
        draw_text_with_ellipsis(
            c,
            f"NRC: {cliente.get('nrc', '')}",
            right_x,
            text_y,
            receptor_col_width,
        )

    text_y -= line_h
    draw_text_with_ellipsis(
        c,
        f"NIT: {cliente.get('nit', '')}",
        left_x,
        text_y,
        receptor_col_width,
    )
    if mostrar_datos_receptor_completos:
        draw_text_with_ellipsis(
            c,
            f"No. Remisión: {venta.get('no_remision', '')}",
            right_x,
            text_y,
            receptor_col_width,
        )

    if mostrar_datos_receptor_completos:
        text_y -= line_h
        draw_text_with_ellipsis(
            c,
            f"Giro: {cliente.get('giro', '')}",
            left_x,
            text_y,
            receptor_col_width,
        )
        draw_text_with_ellipsis(
            c,
            f"Orden No.: {venta.get('orden_no', '')}",
            right_x,
            text_y,
            receptor_col_width,
        )

        text_y -= line_h
        draw_text_with_ellipsis(
            c,
            f"Condición pago: {venta.get('condicion_pago', '')}",
            left_x,
            text_y,
            receptor_col_width,
        )
    else:
        text_y -= line_h

    text_y -= line_h
    text_y = draw_wrapped_text(
        c,
        f"Dirección: {direccion}",
        left_x,
        text_y,
        box_w - 10,
        line_h,
    )

    if venta_a_cuenta_text or documento_venta_a_cuenta_text:
        spacing = max(line_h - 4, 4)
        text_y -= spacing
        if venta_a_cuenta_text:
            draw_text_with_ellipsis(
                c,
                f"Venta a cta de: {venta_a_cuenta_text}",
                left_x,
                text_y,
                receptor_col_width,
            )
        if documento_venta_a_cuenta_text:
            draw_text_with_ellipsis(
                c,
                f"DUI/NIT: {documento_venta_a_cuenta_text}",
                right_x,
                text_y,
                receptor_col_width,
            )

    # Posición inicial para la tabla de productos
    tabla_x = x_margin
    tabla_y = box_y - 20
    tipo_norm = (tipo_documento or "").strip().lower()
    is_consumidor_final = tipo_norm.startswith("consumidor final")

    table_padding = 6
    body_fontname = "Helvetica"
    body_fontsize = 8

    if is_consumidor_final:
        tabla_columnas = [
            "Cantidad",
            "Descripción",
            "Precio Unitario",
            "No sujetas",
            "Exentas",
            "Gravadas",
        ]
        col_widths = [44, 170, 90, 60, 60, 90]
    else:
        tabla_columnas = [
            "Cantidad",
            "Descripción",
            "Precio Unitario",
            "IVA",
            "No sujetas",
            "Exentas",
            "Gravadas",
        ]
        col_widths = [44, 150, 90, 50, 60, 60, 70]

    descripcion_col_idx = tabla_columnas.index("Descripción")
    descripcion_col_width = max(col_widths[descripcion_col_idx] - 2 * table_padding, 0)
    descripcion_left_offset = sum(col_widths[:descripcion_col_idx]) if descripcion_col_idx > 0 else 0

    descripcion_style = ParagraphStyle(
        name="DescripcionItem",
        fontName=body_fontname,
        fontSize=body_fontsize,
        leading=body_fontsize + 2,
        spaceAfter=0,
        spaceBefore=0,
    )
    meta_fontsize = min(max(body_fontsize, 9), 10)
    meta_text_color = colors.HexColor("#555555")
    meta_paragraph_style = ParagraphStyle(
        name="MetadataItem",
        fontName=body_fontname,
        fontSize=meta_fontsize,
        leading=meta_fontsize + 2,
        textColor=meta_text_color,
        spaceAfter=0,
        spaceBefore=0,
    )

    logger = logging.getLogger(__name__)


    row_groups: list[list[tuple[list, bool]]] = []
    for idx, d in enumerate(detalles):
        cantidad = Decimal(str(d.get("cantidad") or 0))
        precio_unitario = Decimal(str(d.get("precio_unitario") or 0))
        descuento = Decimal(str(d.get("descuento") or 0))
        if str(d.get("descuento_tipo")).strip() == "%":
            descuento = (cantidad * precio_unitario * descuento) / Decimal("100")
        gravada_total = cantidad * precio_unitario - descuento

        descripcion = ellipsize_text(
            d.get("descripcion", ""),
            body_fontname,
            body_fontsize,
            descripcion_col_width,
        )

        metadata = _metadata_desde_inventario(d)

        lote_val = metadata.get("lote")
        venc_val = metadata.get("vencimiento")
        registro_val = metadata.get("registro")

        meta_segments = []
        if lote_val:
            meta_segments.append(f"Lote: {lote_val}")
        if venc_val:
            meta_segments.append(f"Vencimiento: {venc_val}")
        if registro_val:
            meta_segments.append(f"Registro Sanitario: {registro_val}")

        descripcion_html = escape(descripcion)
        descripcion_cell = Paragraph(descripcion_html, descripcion_style)

        fila = [
            str(d.get("cantidad", "")),
            descripcion_cell,
            f"{float(precio_unitario):.4f}",
        ]

        if not is_consumidor_final:
            fila.append(f"{d.get('iva', 0):.2f}")

        ventas_no_suj = d.get("ventas_no_sujetas", 0) or 0
        ventas_exentas = d.get("ventas_exentas", 0) or 0
        ventas_gravadas = d.get("ventas_gravadas", 0) or 0

        fila.extend(
            [
                f"{float(ventas_no_suj):.2f}",
                f"{float(ventas_exentas):.2f}",
                f"{(gravada_total if is_consumidor_final else float(ventas_gravadas)):.2f}",
            ]
        )

        group_rows: list[tuple[list, bool]] = [(fila, False)]

        if meta_segments:
            meta_html_segments = [escape(segment) for segment in meta_segments]
            meta_html = "&nbsp;&nbsp;&nbsp;".join(meta_html_segments)
            meta_cell = Paragraph(meta_html, meta_paragraph_style)
            meta_row = [""] * len(tabla_columnas)
            meta_row[0] = meta_cell
            group_rows.append((meta_row, True))
            if logger.isEnabledFor(logging.DEBUG) and venc_val:
                logger.debug(
                    "Detalle '%s' vencimiento detectado: %s",
                    descripcion,
                    venc_val,
                )

        row_groups.append(group_rows)


    header_row = tabla_columnas

    base_style_commands = [
        ('GRID', (0, 0), (-1, -1), 0.7, colors.black),
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
        ('ALIGN', (0, 0), (0, -1), 'CENTER'),
        ('ALIGN', (2, 0), (-1, -1), 'RIGHT'),
        ('ALIGN', (1, 0), (1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('FONTSIZE', (0, 0), (-1, -1), body_fontsize),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTNAME', (0, 1), (-1, -1), body_fontname),
        ('LEFTPADDING', (0, 0), (-1, -1), table_padding),
        ('RIGHTPADDING', (0, 0), (-1, -1), table_padding),
    ]

    if row_groups:
        base_style_commands.append(
            ('VALIGN', (descripcion_col_idx, 1), (descripcion_col_idx, -1), 'TOP')
        )

    bloque_totales_x = 30
    bloque_totales_w = 555
    bloque_totales_y = 80
    bloque_totales_h = 150
    columna_totales_w = 320
    x_linea = bloque_totales_x + columna_totales_w

    def build_table(rows_subset):
        data_rows = [row for row, _ in rows_subset]
        data = [header_row] + data_rows
        table = Table(data, colWidths=col_widths, repeatRows=1)
        commands = list(base_style_commands)
        for idx, (_, is_meta) in enumerate(rows_subset, start=1):
            if is_meta:
                commands.extend([
                    (
                        'SPAN',
                        (0, idx),
                        (-1, idx),
                    ),
                    (
                        'FONTNAME',
                        (0, idx),
                        (-1, idx),
                        body_fontname,
                    ),
                    (
                        'FONTSIZE',
                        (0, idx),
                        (-1, idx),
                        meta_fontsize,
                    ),
                    (
                        'TEXTCOLOR',
                        (0, idx),
                        (-1, idx),
                        meta_text_color,
                    ),
                    (
                        'ALIGN',
                        (0, idx),
                        (-1, idx),
                        'LEFT',
                    ),
                    (
                        'LEFTPADDING',
                        (0, idx),
                        (-1, idx),
                        table_padding + descripcion_left_offset + 2,
                    ),
                    (
                        'RIGHTPADDING',
                        (0, idx),
                        (-1, idx),
                        table_padding,
                    ),
                    (
                        'LINEABOVE',
                        (0, idx),
                        (-1, idx),
                        0.4,
                        colors.HexColor("#d0d0d0"),
                    ),
                    (
                        'TOPPADDING',
                        (0, idx),
                        (-1, idx),
                        max(table_padding - 3, 2),
                    ),
                    (
                        'BOTTOMPADDING',
                        (0, idx),
                        (-1, idx),
                        max(table_padding - 2, 2),
                    ),
                    (
                        'VALIGN',
                        (0, idx),
                        (-1, idx),
                        'TOP',
                    ),
                ])
        table.setStyle(TableStyle(commands))
        return table

    def table_height(rows_subset):
        table = build_table(rows_subset)
        # Usar las mismas dimensiones que el canvas para evitar subestimar la altura real.
        _, height_used = table.wrap(width, height)
        return height_used

    def groups_that_fit(max_height, groups):
        if max_height <= 0:
            return 0
        included_rows: list[tuple[list, bool]] = []
        count = 0
        for group in groups:
            test_rows = included_rows + group
            if table_height(test_rows) <= max_height:
                included_rows = test_rows
                count += 1
            else:
                break
        return count

    # Reservamos un espacio fijo para el bloque de totales en la última página.
    footer_reserved_height = bloque_totales_y + bloque_totales_h + 20
    available_height_last = max(tabla_y - footer_reserved_height, 0)
    available_height_standard = max(tabla_y - (y_margin + 40), 0)

    remaining_groups = [group[:] for group in row_groups]
    table_pages_groups: list[list[tuple[list, bool]]] = []

    while remaining_groups:
        flat_remaining = [row for group in remaining_groups for row in group]
        if table_height(flat_remaining) <= available_height_last:
            table_pages_groups.append(flat_remaining)
            remaining_groups = []
            break

        # Página intermedia: llenamos hasta el alto disponible, pero dejamos al menos
        # un grupo para la última página que respeta el espacio del footer.
        count_groups = groups_that_fit(available_height_standard, remaining_groups)
        count_groups = max(count_groups, 1)
        if count_groups >= len(remaining_groups):
            count_groups = len(remaining_groups) - 1
        count_groups = max(count_groups, 1)

        chunk_groups = remaining_groups[:count_groups]
        table_pages_groups.append([row for group in chunk_groups for row in group])
        remaining_groups = remaining_groups[count_groups:]

    if not table_pages_groups:
        table_pages_groups.append([])

    total_pages = len(table_pages_groups)

    for page_index, rows_chunk in enumerate(table_pages_groups):
        if page_index > 0:
            c.showPage()
            top = height - 45
            c.setFont("Helvetica-Bold", 14)
            c.drawCentredString(width / 2, top, "DOCUMENTO TRIBUTARIO ELECTRÓNICO")
            top -= 16
            c.setFont("Helvetica-Bold", 11)
            c.drawCentredString(width / 2, top, titulo)

        table = build_table(rows_chunk)
        _, table_height_used = table.wrapOn(c, width, height)
        table.drawOn(c, tabla_x, tabla_y - table_height_used)
        current_bottom = tabla_y - table_height_used

        if page_index == total_pages - 1:
            c.setLineWidth(0.7)
            c.roundRect(bloque_totales_x, bloque_totales_y, bloque_totales_w, bloque_totales_h, 6, stroke=1, fill=0)

            c.setLineWidth(0.5)
            c.line(x_linea, bloque_totales_y + 8, x_linea, bloque_totales_y + bloque_totales_h - 8)

            texto_y = bloque_totales_y + bloque_totales_h - 18
            salto = 18

            def _venta_monto(*keys, default=0.0):
                for key in keys:
                    valor = venta.get(key)
                    if valor in (None, ""):
                        continue
                    if isinstance(valor, (int, float)):
                        return float(valor)
                    try:
                        return float(Decimal(str(valor)))
                    except (InvalidOperation, ValueError, TypeError):
                        continue
                return float(default)

            total_sumas = _venta_monto("sumas", "subTotalVentas")
            total_descuentos = _venta_monto("descuentos", "totalDescu")
            total_iva = _venta_monto("totalIva", "iva")
            if not is_consumidor_final and abs(total_iva) < 0.005:
                total_iva_detalles = Decimal("0")
                for detalle in detalles:
                    valor_iva = detalle.get("iva")
                    if valor_iva in (None, ""):
                        continue
                    try:
                        total_iva_detalles += Decimal(str(valor_iva))
                    except (InvalidOperation, ValueError, TypeError):
                        continue
                total_iva = float(total_iva_detalles)
            subtotal = _venta_monto("subTotal", "subtotal", "subTotalVentas")
            total_exentas = _venta_monto("ventas_exentas", "totalExenta")
            total_no_sujetas = _venta_monto("ventas_no_sujetas", "totalNoSuj")
            total_pagar = _venta_monto("total", "totalPagar", "montoTotalOperacion")

            c.setFont("Helvetica", 9)
            c.drawString(x_linea + 10, texto_y, "SUMA DE VENTAS:")
            c.drawRightString(bloque_totales_x + bloque_totales_w - 10, texto_y, f"{total_sumas:.2f}")

            texto_y -= salto
            c.setFont("Helvetica-Bold", 9)
            c.drawString(x_linea + 10, texto_y, "Descuentos y rebajas:")
            c.setFont("Helvetica", 9)
            c.drawRightString(bloque_totales_x + bloque_totales_w - 10, texto_y, f"{total_descuentos:.2f}")

            texto_y -= salto
            if not is_consumidor_final:
                c.setFont("Helvetica-Bold", 9)
                c.drawString(x_linea + 10, texto_y, "IVA 13%:")
                c.setFont("Helvetica", 9)
                c.drawRightString(bloque_totales_x + bloque_totales_w - 10, texto_y, f"{total_iva:.2f}")
                texto_y -= salto

            c.setFont("Helvetica-Bold", 9)
            c.drawString(x_linea + 10, texto_y, "Subtotal:")
            c.setFont("Helvetica", 9)
            c.drawRightString(bloque_totales_x + bloque_totales_w - 10, texto_y, f"{subtotal:.2f}")

            texto_y -= salto
            c.setFont("Helvetica-Bold", 9)
            c.drawString(x_linea + 10, texto_y, "Exentas:")
            c.setFont("Helvetica", 9)
            c.drawRightString(bloque_totales_x + bloque_totales_w - 10, texto_y, f"{total_exentas:.2f}")

            texto_y -= salto
            c.setFont("Helvetica-Bold", 9)
            c.drawString(x_linea + 10, texto_y, "No sujetas:")
            c.setFont("Helvetica", 9)
            c.drawRightString(bloque_totales_x + bloque_totales_w - 10, texto_y, f"{total_no_sujetas:.2f}")

            texto_y -= salto + 10
            c.setFont("Helvetica-Bold", 10)
            c.drawString(x_linea + 10, texto_y, "Total a pagar:")
            c.setFont("Helvetica-Bold", 10)
            c.drawRightString(bloque_totales_x + bloque_totales_w - 10, texto_y, f"{total_pagar:.2f}")

            c.setFont("Helvetica-Bold", 11)
            c.drawString(bloque_totales_x + 10, bloque_totales_y + bloque_totales_h - 18, "Valor en letras:")
            c.setFont("Helvetica", 11)
            draw_wrapped_text(
                c,
                f"{venta.get('total_letras', '')}",
                bloque_totales_x + 120,
                bloque_totales_y + bloque_totales_h - 18,
                columna_totales_w - 130,
                14,
            )
        else:
            c.setFont("Helvetica-Oblique", 8)
            c.drawRightString(width - x_margin, current_bottom - 10, "Continúa en la siguiente página...")

        c.setFont("Helvetica", 8)
        c.drawCentredString(width / 2, 20, f"Página {page_index + 1} de {total_pages}")

    c.save()


def generar_nota_credito_pdf(
    venta,
    detalles,
    cliente,
    distribuidor,
    archivo="nota_credito.pdf",
    datos_negocio=None,
    doc_relacionado=None,
    motivo=None,
    **kwargs,
):
    """Genera un PDF para una Nota de Cr\u00e9dito."""
    venta_neg = {k: (-abs(v) if isinstance(v, (int, float)) else v) for k, v in venta.items()}
    det_neg = []
    for d in detalles:
        dn = d.copy()
        for key in ("cantidad", "precio_unitario", "ventas_gravadas", "ventas_exentas", "ventas_no_sujetas"):
            if key in dn and isinstance(dn[key], (int, float)):
                dn[key] = -abs(dn[key])
        det_neg.append(dn)

    generar_factura_electronica_pdf(
        venta_neg,
        det_neg,
        cliente,
        distribuidor,
        "Nota de Cr\u00e9dito",
        archivo=archivo,
        datos_negocio=datos_negocio,
        tipo_dte="05",
        doc_relacionado=doc_relacionado,
        motivo=motivo,
        **kwargs,
    )


def generar_nota_debito_pdf(
    venta,
    detalles,
    cliente,
    distribuidor,
    archivo="nota_debito.pdf",
    datos_negocio=None,
    doc_relacionado=None,
    motivo=None,
    **kwargs,
):
    """Genera un PDF para una Nota de Débito."""
    generar_factura_electronica_pdf(
        venta,
        detalles,
        cliente,
        distribuidor,
        "Nota de Débito",
        archivo=archivo,
        datos_negocio=datos_negocio,
        tipo_dte="06",
        doc_relacionado=doc_relacionado,
        motivo=motivo,
        **kwargs,
    )


def generar_nota_remision_pdf(
    venta,
    detalles,
    cliente,
    distribuidor,
    archivo="nota_remision.pdf",
    datos_negocio=None,
    **kwargs,
):
    """Genera un PDF para una Nota de Remisión."""
    generar_factura_electronica_pdf(
        venta,
        detalles,
        cliente,
        distribuidor,
        "Nota de Remisión",
        archivo=archivo,
        datos_negocio=datos_negocio,
        **kwargs,
    )
