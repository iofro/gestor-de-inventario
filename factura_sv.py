from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, Table, TableStyle
from reportlab.lib import colors
from reportlab.graphics import renderPDF
from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing
from reportlab.lib.units import mm
from reportlab.lib.styles import ParagraphStyle

from utils.pdf_utils import draw_wrapped_text, draw_text_with_ellipsis, ellipsize_text
import utils.catalogos as catalogos
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode
import json
import os
from datetime import datetime
from paths import DATOS_NEGOCIO_PATH
from utils import resource_path
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

    if tipo_operacion == 2:
        c.setFont("Helvetica-Bold", 12)
        c.setFillColor(colors.red)
        c.drawCentredString(width / 2, header_y - 18, "TRANSMISIÓN DIFERIDA")
        c.setFillColor(colors.black)

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

    receptor_line_count = 4  # encabezado + nombre + DUI + NIT
    receptor_extra = 1  # línea "Giro/Orden" o espaciado
    if mostrar_datos_receptor_completos:
        receptor_extra += 1  # línea "Condición pago"
    receptor_line_count += receptor_extra
    receptor_line_count += 1  # Dirección
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

    descripcion_style = ParagraphStyle(
        name="DescripcionItem",
        fontName=body_fontname,
        fontSize=body_fontsize,
        leading=body_fontsize + 2,
        spaceAfter=0,
        spaceBefore=0,
    )
    meta_fontsize = max(body_fontsize - 1, 6)

    def _normalize_text(value):
        if value is None:
            return None
        if isinstance(value, str):
            text = value.strip()
            return text or None
        return str(value)

    def _parse_json_value(raw_value):
        if raw_value in (None, ""):
            return None
        if isinstance(raw_value, (dict, list)):
            return raw_value
        if isinstance(raw_value, (bytes, bytearray)):
            try:
                raw_value = raw_value.decode("utf-8")
            except Exception:
                return None
        if isinstance(raw_value, str):
            text = raw_value.strip()
            if not text:
                return None
            try:
                parsed = json.loads(text)
            except Exception:
                return None
            if isinstance(parsed, (dict, list)):
                return parsed
        return None

    def _search_nested(data, key_candidates):
        if isinstance(data, dict):
            for key in key_candidates:
                if key in data:
                    value = data[key]
                    normalized = _normalize_text(value)
                    if normalized is not None:
                        return value
            for value in data.values():
                found = _search_nested(value, key_candidates)
                if found is not None:
                    return found
        elif isinstance(data, list):
            for item in data:
                found = _search_nested(item, key_candidates)
                if found is not None:
                    return found
        return None

    def _format_fecha_vencimiento(value):
        text = _normalize_text(value)
        if not text:
            return None
        trimmed = text
        if "T" in trimmed:
            trimmed = trimmed.split("T", 1)[0]
        trimmed = trimmed.strip()
        if len(trimmed) > 10:
            trimmed = trimmed[:10]
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                dt = datetime.strptime(trimmed, fmt)
            except ValueError:
                continue
            else:
                return dt.strftime("%d/%m/%Y")
        return text

    tabla_data = [tabla_columnas]
    for d in detalles:
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

        extra_raw = d.get("extra")
        extra_data = _parse_json_value(extra_raw)

        def _pick_value(key_candidates):
            direct_value = _search_nested(d, key_candidates)
            if direct_value not in (None, ""):
                return direct_value
            if extra_data is not None:
                return _search_nested(extra_data, key_candidates)
            return None

        lote_val = _normalize_text(
            _pick_value(["codigo_lote", "codigoLote", "lote", "loteCodigo"])
        )
        registro_val = _normalize_text(
            _pick_value(["registro_sanitario", "registroSanitario"])
        )
        venc_raw = _pick_value([
            "fecha_vencimiento",
            "fechaVencimiento",
            "vencimiento",
            "fecha_vto",
        ])
        venc_val = _format_fecha_vencimiento(venc_raw)

        meta_segments = []
        if lote_val:
            meta_segments.append(f"Lote: {lote_val}")
        if venc_val:
            meta_segments.append(f"Vencimiento: {venc_val}")
        if registro_val:
            meta_segments.append(f"Registro Sanitario: {registro_val}")

        meta_text = " ".join(meta_segments)
        if meta_text:
            meta_text = ellipsize_text(
                meta_text,
                body_fontname,
                meta_fontsize,
                descripcion_col_width,
            )
            paragraph_text = (
                f"{escape(descripcion)}"  # description already ellipsized
                f"<br/><font color='#555555' size='{meta_fontsize}'>{escape(meta_text)}</font>"
            )
        else:
            paragraph_text = escape(descripcion)

        descripcion_cell = Paragraph(paragraph_text, descripcion_style)

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

        tabla_data.append(fila)


    header_row = tabla_data[0]
    body_rows = tabla_data[1:]

    table_style = TableStyle([
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
    ])

    if len(tabla_data) > 1:
        table_style.add(
            'VALIGN',
            (descripcion_col_idx, 1),
            (descripcion_col_idx, -1),
            'TOP',
        )

    bloque_totales_x = 30
    bloque_totales_w = 555
    bloque_totales_y = 80
    bloque_totales_h = 150
    columna_totales_w = 320
    x_linea = bloque_totales_x + columna_totales_w

    def build_table(rows_subset):
        data = [header_row] + rows_subset
        table = Table(data, colWidths=col_widths, repeatRows=1)
        table.setStyle(table_style)
        return table

    def table_height(rows_subset):
        table = build_table(rows_subset)
        _, height_used = table.wrap(0, 0)
        return height_used

    def rows_that_fit(max_height, rows):
        if max_height <= 0:
            return 0
        count = 0
        while count < len(rows):
            subset = rows[: count + 1]
            if table_height(subset) <= max_height:
                count += 1
            else:
                break
        return count

    available_height_last = tabla_y - (bloque_totales_y + bloque_totales_h + 20)
    available_height_standard = tabla_y - (y_margin + 40)
    available_height_last = max(available_height_last, 0)
    available_height_standard = max(available_height_standard, 0)

    remaining_rows = body_rows[:]
    table_pages_rows = []

    while remaining_rows:
        if table_height(remaining_rows) <= available_height_last:
            table_pages_rows.append(remaining_rows[:])
            remaining_rows = []
        else:
            count = rows_that_fit(available_height_standard, remaining_rows)
            if count <= 0:
                count = 1
            table_pages_rows.append(remaining_rows[:count])
            remaining_rows = remaining_rows[count:]

    if not table_pages_rows:
        table_pages_rows.append([])

    total_pages = len(table_pages_rows)

    for page_index, rows_chunk in enumerate(table_pages_rows):
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
