from pathlib import Path
import re
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

from utils.pdf_utils import draw_wrapped_text, draw_text_with_ellipsis, ellipsize_text
import utils.catalogos as catalogos
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode
import ast
import json
import os
from datetime import datetime
from paths import DATOS_NEGOCIO_PATH
from utils import resource_path
from xml.sax.saxutils import escape


class _MetaTracer:
    def __init__(self, enabled: bool):
        self.enabled = enabled
        self.rows = []

    def add_row(self, row):
        if not self.enabled:
            return
        self.rows.append(row)

    def dump(self, path="./.debug/pdf_meta_items.json"):
        if not self.enabled:
            return
        import os, json

        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.rows, f, ensure_ascii=False, indent=2)


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

    trace_enabled = os.environ.get("PDF_META_TRACE") == "1"
    force_raw_venc = os.environ.get("PDF_META_FORCE_RAW_VENC") == "1"
    tracer = _MetaTracer(enabled=os.environ.get("PDF_META_DUMP") == "1")

    if os.environ.get("PDF_META_DEBUG") == "1":
        if not logging.getLogger().handlers:
            logging.basicConfig(level=logging.DEBUG)
        logging.getLogger(__name__).setLevel(logging.DEBUG)

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

    blob_tagged_pattern = re.compile(
        r"(?i)\b(venc(?:e|imiento)?|caduc(?:a|idad)?|exp(?:iry|iraci[oó]n)?|fv|vto)\b\s*[:=\-]?\s*([0-9A-Za-z./_-]{2,20})"
    )
    blob_plain_date_pattern = re.compile(r"\b20\d{2}[-/]\d{1,2}[-/]\d{1,2}\b")

    def _normalize_text(value):
        if value is None:
            return None
        if isinstance(value, str):
            text = value.strip()
            return text or None
        return str(value)

    def _clean_venc_candidate_text(candidate: str | None) -> str | None:
        if not candidate:
            return candidate
        cleaned = candidate.strip()
        if not cleaned:
            return cleaned
        cleaned = re.sub(r"^[\s:=\-]+", "", cleaned)
        cleaned = re.sub(r"^(?:[A-Za-z]{1,6})\s*[:=]\s*(?=[0-9])", "", cleaned)
        leftover_tokens = ("iry", "ry", "y", "miento", "imiento", "cion", "ción")
        for token in leftover_tokens:
            cleaned = re.sub(
                rf"^(?:{token})\s*[:=\-]?\s*(?=[0-9])",
                "",
                cleaned,
                flags=re.IGNORECASE,
            )
        return cleaned.strip()

    def _format_path(path: tuple[str, ...] | None) -> str:
        if not path:
            return "<root>"
        return ".".join(path)

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
            parsed = None
            try:
                parsed = json.loads(text)
            except Exception:
                if text[:1] in "[{" and text[-1:] in "]}":
                    try:
                        parsed = ast.literal_eval(text)
                    except Exception:
                        parsed = None
            if isinstance(parsed, (dict, list)):
                return parsed
        return None

    def _format_fecha_vencimiento(value, *, path: tuple[str, ...] | None = None, value_type: str | None = None):
        text = _normalize_text(value)
        if not text:
            if trace_enabled and logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "[meta:trace] normalize skip empty candidate path=%s type=%s",
                    _format_path(path),
                    value_type,
                )
            return None

        base = text.strip()
        if "T" in base:
            base = base.split("T", 1)[0]
        base = base.strip()

        if trace_enabled and logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "[meta:trace] normalize candidate path=%s type=%s raw=%r",
                _format_path(path),
                value_type,
                base,
            )

        label_pattern = re.compile(
            r"(?i)\b(?:fecha\s*(?:de)?\s*)?(?:venc(?:imiento)?|vence|vto|f\s*\.?\s*v\.?|fv|caduc(?:idad|a)?|expir(?:a|aci\u00f3n)?)\b"
        )
        cleaned = label_pattern.sub("", base)
        cleaned = re.sub(r"(?i)\bde\b", " ", cleaned)
        cleaned = cleaned.strip(" .:-\t")

        def _normalize_year(year_str: str) -> int:
            year_int = int(year_str)
            if year_int < 100:
                return 2000 + year_int
            return year_int

        month_map = {
            "ene": 1,
            "enero": 1,
            "feb": 2,
            "febrero": 2,
            "mar": 3,
            "marzo": 3,
            "abr": 4,
            "abril": 4,
            "may": 5,
            "mayo": 5,
            "jun": 6,
            "junio": 6,
            "jul": 7,
            "julio": 7,
            "ago": 8,
            "agosto": 8,
            "sep": 9,
            "sept": 9,
            "set": 9,
            "septiembre": 9,
            "setiembre": 9,
            "oct": 10,
            "octubre": 10,
            "nov": 11,
            "noviembre": 11,
            "dic": 12,
            "diciembre": 12,
        }

        def _parse_spanish_month(candidate: str) -> str | None:
            if not candidate:
                return None

            def _month_from_word(word: str) -> int | None:
                normalized = (
                    word.strip()
                    .lower()
                    .replace(".", "")
                    .replace("á", "a")
                    .replace("é", "e")
                    .replace("í", "i")
                    .replace("ó", "o")
                    .replace("ú", "u")
                )
                return month_map.get(normalized) or month_map.get(normalized[:3])

            pattern_day = re.compile(
                r"(?i)\b(\d{1,2})(?:\s*(?:de|del)\s+|\s+)([a-z\u00e1\u00e9\u00ed\u00f3\u00fa\u00f1\.]+)(?:\s*(?:de)?\s+|\s+)(\d{2,4})\b"
            )
            match_day = pattern_day.search(candidate)
            if match_day:
                day = int(match_day.group(1))
                month_word = match_day.group(2)
                month = _month_from_word(month_word)
                if not month:
                    return None
                year = _normalize_year(match_day.group(3))
                try:
                    dt = datetime(year, month, day)
                except ValueError:
                    return None
                return dt.strftime("%d/%m/%Y")

            pattern_month = re.compile(
                r"(?i)\b([a-z\u00e1\u00e9\u00ed\u00f3\u00fa\u00f1\.]+)(?:\s*(?:de)?\s+|\s+)(\d{2,4})\b"
            )
            match_month = pattern_month.search(candidate)
            if match_month:
                month_word = match_month.group(1)
                month = _month_from_word(month_word)
                if not month:
                    return None
                year = _normalize_year(match_month.group(2))
                try:
                    dt = datetime(year, month, 1)
                except ValueError:
                    return None
                return dt.strftime("%d/%m/%Y")

            return None

        def _try_patterns(candidate: str) -> str | None:
            if not candidate:
                return None
            normalized_candidate = candidate.strip()
            if not normalized_candidate:
                return None

            iso_match = re.search(r"(\d{4})[\\/\-.](\d{1,2})[\\/\-.](\d{1,2})", normalized_candidate)
            if iso_match:
                year, month, day = map(int, iso_match.groups())
                try:
                    dt = datetime(year, month, day)
                except ValueError:
                    pass
                else:
                    return dt.strftime("%d/%m/%Y")

            dmy_match = re.search(r"(\d{1,2})[\\/\-.](\d{1,2})[\\/\-.](\d{2,4})", normalized_candidate)
            if dmy_match:
                day, month, year_raw = dmy_match.groups()
                year = _normalize_year(year_raw)
                try:
                    dt = datetime(year, int(month), int(day))
                except ValueError:
                    pass
                else:
                    return dt.strftime("%d/%m/%Y")

            month_year_match = re.search(r"\b(\d{1,2})[\\/\-.](\d{2,4})\b", normalized_candidate)
            if month_year_match:
                month_raw, year_raw = month_year_match.groups()
                month = int(month_raw)
                if 1 <= month <= 12:
                    year = _normalize_year(year_raw)
                    try:
                        dt = datetime(year, month, 1)
                    except ValueError:
                        pass
                    else:
                        return dt.strftime("%d/%m/%Y")

            spanish_formatted = _parse_spanish_month(normalized_candidate)
            if spanish_formatted:
                return spanish_formatted

            digits_only = re.sub(r"[^0-9]", "", normalized_candidate)
            if len(digits_only) == 8:
                if digits_only.startswith("19") or digits_only.startswith("20"):
                    year = int(digits_only[:4])
                    month = int(digits_only[4:6])
                    day = int(digits_only[6:])
                else:
                    day = int(digits_only[:2])
                    month = int(digits_only[2:4])
                    year = _normalize_year(digits_only[4:])
                try:
                    dt = datetime(year, month, day)
                except ValueError:
                    pass
                else:
                    return dt.strftime("%d/%m/%Y")

            return None

        candidates: list[str] = []
        seen: set[str] = set()

        def _add_candidate(value: str | None):
            if not value:
                return
            candidate = value.strip()
            if not candidate:
                return
            if candidate not in seen:
                seen.add(candidate)
                candidates.append(candidate)

        _add_candidate(cleaned)
        _add_candidate(base)
        for chunk in (cleaned, base):
            if not chunk:
                continue
            for part in re.split(r"[|,;\n]\s*", chunk):
                _add_candidate(part)
            if re.search(r"[a-zA-Z]", chunk):
                _add_candidate(re.sub(r"[-_/]", " ", chunk))
            normalized_chunk = chunk.replace("\\", "/").replace("-", "/").replace(".", "/")
            _add_candidate(normalized_chunk)

        for candidate in candidates:
            parsed = _try_patterns(candidate)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("[meta] fecha candidato %r -> %r", candidate, parsed)
            if parsed:
                return parsed

        epoch_match = re.fullmatch(r"\d{10}|\d{13}", cleaned)
        if epoch_match:
            ts = int(epoch_match.group(0))
            if len(epoch_match.group(0)) == 13:
                ts = ts // 1000
            try:
                dt = datetime.utcfromtimestamp(ts)
                return dt.strftime("%d/%m/%Y")
            except Exception:
                pass

        six = re.fullmatch(r"(\d{6})", re.sub(r"\D", "", cleaned))
        if six:
            raw = six.group(1)
            try:
                d, m, y = int(raw[:2]), int(raw[2:4]), int(raw[4:])
                y = 2000 + y if y < 100 else y
                return datetime(y, m, d).strftime("%d/%m/%Y")
            except Exception:
                try:
                    y, m, d = int(raw[:2]), int(raw[2:4]), int(raw[4:])
                    y = 2000 + y if y < 100 else y
                    return datetime(y, m, d).strftime("%d/%m/%Y")
                except Exception:
                    pass

        m_ym = re.search(r"\b(\d{4})[\\/.-](\d{1,2})\b", cleaned)
        if m_ym:
            y, mo = int(m_ym.group(1)), int(m_ym.group(2))
            if 1 <= mo <= 12:
                try:
                    return datetime(y, mo, 1).strftime("%d/%m/%Y")
                except Exception:
                    pass

        digits_only = re.sub(r"\D", "", cleaned)

        m_14 = re.fullmatch(r"\d{14}", digits_only)
        if m_14:
            raw = digits_only
            try:
                y, mo, d = int(raw[0:4]), int(raw[4:6]), int(raw[6:8])
                return datetime(y, mo, d).strftime("%d/%m/%Y")
            except Exception:
                pass

        m_yymm6 = re.fullmatch(r"\d{6}", digits_only)
        if m_yymm6:
            raw = digits_only
            try:
                y, mo = int(raw[0:4]), int(raw[4:6])
                if 1 <= mo <= 12:
                    return datetime(y, mo, 1).strftime("%d/%m/%Y")
            except Exception:
                pass
            try:
                mo, y = int(raw[0:2]), int(raw[2:6])
                if 1 <= mo <= 12:
                    return datetime(y, mo, 1).strftime("%d/%m/%Y")
            except Exception:
                pass

        m_mmyy4 = re.fullmatch(r"\d{4}", digits_only)
        if m_mmyy4:
            raw = digits_only
            try:
                mo, yy = int(raw[0:2]), int(raw[2:4])
                if 1 <= mo <= 12:
                    y = 2000 + yy if yy < 100 else yy
                    return datetime(y, mo, 1).strftime("%d/%m/%Y")
            except Exception:
                pass
            try:
                yy, mo = int(raw[0:2]), int(raw[2:4])
                if 1 <= mo <= 12:
                    y = 2000 + yy if yy < 100 else yy
                    return datetime(y, mo, 1).strftime("%d/%m/%Y")
            except Exception:
                pass

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("[meta] no parse match, devuelvo crudo: %r", text)

        if trace_enabled and logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "[meta:trace] normalize result path=%s -> %r",
                _format_path(path),
                None,
            )

        return None

    def _collect_item_metadata(*sources):
        metadata: dict[str, str | None] = {
            "lote": None,
            "vencimiento": None,
            "registro": None,
        }

        diag: dict[str, object] = {
            "where_found": None,
            "raw_value": None,
            "normalized_value": None,
            "all_candidates": [],
            "blob_first_match": None,
        }

        date_tokens = ("venc", "caduc", "expir", "vence", "vto", "fv")

        alias_map = {
            "lote": {"lote", "batch", "lote_producto"},
            "vencimiento": {
                "vencimiento",
                "fecha_vencimiento",
                "fvto",
                "f_venc",
                "vto",
                "fechavencimiento",
                "fechavenc",
                "fv",
                "fvenc",
                "vence",
                "vence_el",
                "venceel",
                "caducidad",
                "fecha_caducidad",
                "fechacaducidad",
                "expiry",
                "expirationdate",
                "expiration_date",
                "exp_date",
                "exp",
            },
            "registro": {"registro_sanitario", "reg_sanitario", "regsan", "registro"},
        }
        alias_lookup = {}
        alias_compact_lookup = {}
        for canonical, aliases in alias_map.items():
            for alias in aliases:
                alias_norm = alias.lower()
                alias_lookup[alias_norm] = canonical
                alias_compact_lookup[re.sub(r"[^a-z0-9]", "", alias_norm)] = canonical

        def _register_venc_candidate(
            path: tuple[str, ...] | None,
            raw: str,
            normalized: str | None,
            value_type: str | None,
        ):
            if trace_enabled and logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "[meta:trace] venc candidate path=%s type=%s raw=%r normalized=%r",
                    _format_path(path),
                    value_type,
                    raw,
                    normalized,
                )
            candidates = diag.setdefault("all_candidates", [])
            candidates.append(raw)
            if not diag.get("where_found") and path:
                diag["where_found"] = _format_path(path)
            diag["raw_value"] = raw
            if normalized:
                diag["normalized_value"] = normalized

        def _assign(
            field: str,
            value: str,
            *,
            formatter=None,
            path: tuple[str, ...] | None = None,
            value_type: str | None = None,
            raw_value: str | None = None,
        ):
            text = _normalize_text(value)
            if not text:
                return
            original_text = text
            formatted = None
            if formatter is not None:
                formatted = formatter(text, path=path, value_type=value_type)
                if formatted:
                    text = formatted
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "[meta] assign %s <- %r (formatted=%r)",
                    field,
                    value,
                    (formatted if formatter else None),
                )
            if field == "vencimiento":
                raw_for_register = raw_value if raw_value is not None else original_text
                _register_venc_candidate(path, raw_for_register, formatted, value_type)
                if formatted:
                    text = formatted
                elif force_raw_venc:
                    text = raw_for_register or text
                else:
                    text = formatted or text
            existing = metadata[field]
            if existing:
                if existing == text:
                    return
                if existing.isdigit() and not text.isdigit():
                    metadata[field] = text
                    return
                if len(text) > len(existing):
                    metadata[field] = text
            else:
                metadata[field] = text

        def _parse_pattern_text(text: str, *, path: tuple[str, ...] | None, value_type: str | None):
            if not text:
                return
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("[meta] pattern probe: %r", text)
            venc_label_core = r"f\s*\.?\s*v\.?|fv|vto|venc(?:\.|imiento)?|vence(?:\s*el)?|exp(?:iry|ir(?:a|aci\u00f3n)?)|caduc(?:a|idad)?"
            lot_match = re.search(r"(?i)\b(?:lote|batch)\b\s*[:=]\s*([^|,;\n]+)", text)
            if lot_match:
                lot_val = lot_match.group(1).strip()
                lot_val = re.split(
                    rf"(?i)\b(?:{venc_label_core}|reg(?:istro)?(?:\s*(?:san(?:itario)?|san\.?|sanit\.?))?)\b",
                    lot_val,
                    maxsplit=1,
                )[0].strip(" :")
                if lot_val:
                    _assign("lote", lot_val, path=path, value_type=value_type)
            venc_label = rf"(?i)\b(?:{venc_label_core})\b"

            m = re.search(venc_label + r"\s*[:=\-]?\s*([^\|,;\n]+)", text)
            if m:
                cand = m.group(1).strip()
                cand = re.split(r"(?i)\b(lote|reg(?:istro)?(?:\s*san(?:itario)?)?)\b", cand, maxsplit=1)[0].strip(" :.-")
                raw_cand = cand
                cand = _clean_venc_candidate_text(cand) or cand
                _assign(
                    "vencimiento",
                    cand,
                    formatter=_format_fecha_vencimiento,
                    path=path,
                    value_type=value_type,
                    raw_value=raw_cand,
                )

            if not metadata.get("vencimiento"):
                m_compact = re.search(
                    venc_label + r"\s*[:=\-]?\s*([0-9A-Za-z./_-]{2,20})",
                    text,
                )
                if m_compact:
                    raw_cand = m_compact.group(1)
                    cand = _clean_venc_candidate_text(raw_cand) or raw_cand
                    _assign(
                        "vencimiento",
                        cand,
                        formatter=_format_fecha_vencimiento,
                        path=path,
                        value_type=value_type,
                        raw_value=raw_cand,
                    )

            if not metadata.get("vencimiento"):
                m2 = re.search(venc_label + r".{0,10}\b(\d{6}|\d{8}|\d{10}|\d{13})\b", text)
                if m2:
                    raw_cand = m2.group(1)
                    cand = _clean_venc_candidate_text(raw_cand) or raw_cand
                    _assign(
                        "vencimiento",
                        cand,
                        formatter=_format_fecha_vencimiento,
                        path=path,
                        value_type=value_type,
                        raw_value=raw_cand,
                    )
            fecha_key_match = re.search(
                r"(?i)fecha[\s_]*venc(?:imiento)?[\s\"']*[:=]\s*[\"']?([^\"'|,;\n]+)",
                text,
            )
            if fecha_key_match:
                raw_cand = fecha_key_match.group(1).strip()
                cand = _clean_venc_candidate_text(raw_cand) or raw_cand
                _assign(
                    "vencimiento",
                    cand,
                    formatter=_format_fecha_vencimiento,
                    path=path,
                    value_type=value_type,
                    raw_value=raw_cand,
                )
            reg_match = re.search(
                r"(?i)reg(?:istro)?(?:\s*(?:san(?:itario)?|san\.?|sanit\.?))?\s*[:=]\s*([^|,;\n]+)",
                text,
            )
            if reg_match:
                _assign("registro", reg_match.group(1).strip(), path=path, value_type=value_type)

            if not metadata.get("vencimiento"):
                unlabeled = re.findall(r"\b(?:\d{4}[\\/.-]\d{1,2}|\d{1,2}[\\/.-]\d{1,2}[\\/.-]\d{2,4})\b", text)
                for match_value in unlabeled:
                    _assign(
                        "vencimiento",
                        match_value,
                        formatter=_format_fecha_vencimiento,
                        path=path,
                        value_type=value_type,
                    )

        def _traverse(obj, flags: frozenset[str] = frozenset(), path: tuple[str, ...] = ()): 
            if obj is None:
                return
            if isinstance(obj, (bytes, bytearray)):
                try:
                    obj = obj.decode("utf-8")
                except Exception:
                    return

            if isinstance(obj, str):
                stripped = obj.strip()
                if not stripped:
                    return
                parsed_json = _parse_json_value(stripped)
                if parsed_json is not None and parsed_json is not obj:
                    _traverse(parsed_json, flags, path)
                    return
                _parse_pattern_text(stripped, path=path, value_type="str")
                return

            if isinstance(obj, list):
                for idx, item in enumerate(obj):
                    _traverse(item, flags, path + (f"[{idx}]",))
                return

            if not isinstance(obj, dict):
                return

            for key, value in obj.items():
                key_lower = str(key).lower()
                key_compact = re.sub(r"[^a-z0-9]", "", key_lower)
                next_flags = set(flags)
                canonical_key = alias_lookup.get(key_lower) or alias_compact_lookup.get(key_compact)

                is_lote_key = bool(re.search(r"lote(?![a-z])", key_lower)) or canonical_key == "lote"
                if is_lote_key:
                    if key_compact.endswith("id") or key_compact in {"idlote", "loteid"}:
                        is_lote_key = False
                if is_lote_key:
                    next_flags.add("lote")
                if canonical_key == "vencimiento" or any(
                    token in key_lower or token in key_compact for token in date_tokens
                ):
                    next_flags.add("vencimiento")
                if canonical_key == "registro" or ("registro" in key_lower and "san" in key_lower):
                    next_flags.add("registro")

                if isinstance(value, dict) and "$date" in value:
                    raw = value["$date"]
                    parsed = _format_fecha_vencimiento(
                        str(raw),
                        path=path + (str(key), "$date"),
                        value_type=type(raw).__name__,
                    )
                    if parsed:
                        _assign(
                            "vencimiento",
                            str(raw),
                            formatter=lambda *_args, **_kwargs: parsed,
                            path=path + (str(key), "$date"),
                            value_type=type(raw).__name__,
                        )
                    _traverse(value, frozenset(next_flags), path + (str(key),))
                    continue

                if isinstance(value, (dict, list)):
                    _traverse(value, frozenset(next_flags), path + (str(key),))
                    continue

                if isinstance(value, (bytes, bytearray)):
                    try:
                        value = value.decode("utf-8")
                    except Exception:
                        continue

                parsed_nested = _parse_json_value(value)
                if parsed_nested is not None and parsed_nested is not value:
                    _traverse(parsed_nested, frozenset(next_flags), path + (str(key),))
                    continue

                text = _normalize_text(value)
                if not text:
                    continue

                assign_lote = is_lote_key or "lote" in next_flags or canonical_key == "lote"
                assign_venc = (
                    canonical_key == "vencimiento"
                    or any(token in key_lower or token in key_compact for token in date_tokens)
                    or "vencimiento" in next_flags
                )
                assign_registro = (
                    canonical_key == "registro"
                    or ("registro" in key_lower and "san" in key_lower)
                    or "registro" in next_flags
                )

                if assign_lote:
                    _assign("lote", text, path=path + (str(key),), value_type=type(value).__name__)
                if assign_venc:
                    _assign(
                        "vencimiento",
                        text,
                        formatter=_format_fecha_vencimiento,
                        path=path + (str(key),),
                        value_type=type(value).__name__,
                    )
                if assign_registro:
                    _assign("registro", text, path=path + (str(key),), value_type=type(value).__name__)

                _parse_pattern_text(text, path=path + (str(key),), value_type=type(value).__name__)

        for source in sources:
            source_label = None
            source_value = source
            if isinstance(source, tuple) and len(source) == 2:
                source_label, source_value = source
            path_prefix: tuple[str, ...] = ()
            if source_label:
                path_prefix = (str(source_label),)
            _traverse(source_value, frozenset(), path_prefix)

        return metadata, diag

    row_groups: list[list[tuple[list, bool, str | None]]] = []
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

        extra_raw = d.get("extra")
        extra_data = _parse_json_value(extra_raw)

        parsed_extra_preview = None
        if extra_data is not None:
            try:
                parsed_extra_preview = json.dumps(extra_data, ensure_ascii=False)
            except (TypeError, ValueError):
                parsed_extra_preview = repr(extra_data)

        if trace_enabled and logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "[meta:trace] detalle %d extra raw type=%s preview=%s",
                idx,
                type(extra_raw).__name__,
                (repr(extra_raw)[:200] if extra_raw is not None else "<none>"),
            )
            if parsed_extra_preview is not None:
                logger.debug(
                    "[meta:trace] detalle %d extra parsed type=%s preview=%s",
                    idx,
                    type(extra_data).__name__,
                    parsed_extra_preview[:200],
                )

        metadata, metadata_diag = _collect_item_metadata(
            (f"detalles[{idx}]", d),
            (f"detalles[{idx}].extra_parsed", extra_data),
            (f"detalles[{idx}].extra", extra_raw),
        )
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "[meta] detalle '%s' -> %s | extra=%r",
                d.get("descripcion", ""),
                metadata,
                d.get("extra"),
            )
        if trace_enabled and logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "[meta:trace] detalle %d diag=%s",
                idx,
                {
                    "where": metadata_diag.get("where_found"),
                    "raw": metadata_diag.get("raw_value"),
                    "norm": metadata_diag.get("normalized_value"),
                    "candidates": metadata_diag.get("all_candidates"),
                },
            )
        where_found = metadata_diag.get("where_found")
        raw_venc = metadata_diag.get("raw_value")
        candidates_list = metadata_diag.setdefault("all_candidates", [])
        blob_match = metadata_diag.get("blob_first_match")

        if not metadata.get("vencimiento"):
            blob_sources: list[str] = []
            descripcion_src = d.get("descripcion")
            if isinstance(descripcion_src, str) and descripcion_src.strip():
                blob_sources.append(descripcion_src)
            if isinstance(extra_raw, (bytes, bytearray)):
                try:
                    extra_text = extra_raw.decode("utf-8", errors="ignore")
                except Exception:
                    extra_text = ""
                if extra_text:
                    blob_sources.append(extra_text)
            elif isinstance(extra_raw, str) and extra_raw.strip():
                blob_sources.append(extra_raw)
            if extra_data is not None:
                try:
                    blob_sources.append(json.dumps(extra_data, ensure_ascii=False))
                except (TypeError, ValueError):
                    blob_sources.append(str(extra_data))
            blob_text = " | ".join(part for part in blob_sources if part)
            if blob_text:
                raw_candidate = None
                raw_candidate_original = None
                for match in blob_tagged_pattern.finditer(blob_text):
                    candidate_val = match.group(2)
                    cleaned_candidate = _clean_venc_candidate_text(candidate_val)
                    if cleaned_candidate and any(ch.isdigit() for ch in cleaned_candidate):
                        blob_match = match.group(0)
                        raw_candidate = cleaned_candidate
                        raw_candidate_original = candidate_val
                        break
                if raw_candidate is None:
                    plain_match = blob_plain_date_pattern.search(blob_text)
                    if plain_match:
                        blob_match = plain_match.group(0)
                        raw_candidate = plain_match.group(0)
                        raw_candidate_original = plain_match.group(0)
                if raw_candidate:
                    candidates_list.append(raw_candidate)
                    normalized_blob = _format_fecha_vencimiento(
                        raw_candidate,
                        path=("blob",),
                        value_type="str",
                    )
                    if trace_enabled and logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "[meta:trace] blob candidate detalle %d raw=%r normalized=%r",
                            idx,
                            raw_candidate,
                            normalized_blob,
                        )
                    if normalized_blob:
                        metadata["vencimiento"] = normalized_blob
                        metadata_diag["normalized_value"] = normalized_blob
                    elif force_raw_venc:
                        metadata["vencimiento"] = raw_candidate_original or raw_candidate
                    else:
                        metadata["vencimiento"] = raw_candidate
                    if raw_candidate:
                        raw_venc = raw_candidate_original or raw_candidate
                        metadata_diag["raw_value"] = raw_candidate_original or raw_candidate
                    if not where_found:
                        where_found = f"detalles[{idx}].blob"
                        metadata_diag["where_found"] = where_found
                    metadata_diag["blob_first_match"] = blob_match

        lote_val = metadata.get("lote")
        venc_val = metadata.get("vencimiento")
        registro_val = metadata.get("registro")

        if metadata_diag.get("normalized_value") is None and venc_val and re.fullmatch(r"\d{2}/\d{2}/\d{4}", str(venc_val)):
            metadata_diag["normalized_value"] = venc_val

        extra_raw_type = type(extra_raw).__name__
        if isinstance(extra_raw, (bytes, bytearray)):
            try:
                extra_preview_text = extra_raw.decode("utf-8", errors="ignore")
            except Exception:
                extra_preview_text = repr(extra_raw)
        elif isinstance(extra_raw, str):
            extra_preview_text = extra_raw
        elif extra_raw is None:
            extra_preview_text = ""
        else:
            extra_preview_text = str(extra_raw)
        extra_raw_preview = extra_preview_text[:200]

        meta_segments = []
        if lote_val:
            meta_segments.append(f"Lote: {lote_val}")
        if venc_val:
            meta_segments.append(f"Vencimiento: {venc_val}")
        if registro_val:
            meta_segments.append(f"Registro Sanitario: {registro_val}")

        meta_text = "   ".join(meta_segments)

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

        overlay_text = None
        if trace_enabled:
            overlay_parts = [f"Lote={lote_val or '-'}"]
            overlay_venc = venc_val or raw_venc or "-"
            overlay_parts.append(f"Venc={overlay_venc}")
            if where_found:
                overlay_parts.append(f"path={where_found}")
            if registro_val:
                overlay_parts.append(f"Reg={registro_val}")
            overlay_text = "TRACE: " + "  ".join(overlay_parts)

        group_rows: list[tuple[list, bool, str | None]] = [(fila, False, overlay_text)]

        if meta_text:
            meta_html_segments = [escape(segment) for segment in meta_segments]
            meta_html = "&nbsp;&nbsp;&nbsp;".join(meta_html_segments)
            meta_cell = Paragraph(meta_html, meta_paragraph_style)
            meta_row = [""] * len(tabla_columnas)
            meta_row[descripcion_col_idx] = meta_cell
            group_rows.append((meta_row, True, None))

            if logger.isEnabledFor(logging.DEBUG) and venc_val:
                logger.debug(
                    "Detalle '%s' vencimiento detectado: %s",
                    descripcion,
                    venc_val,
                )

        tracer.add_row(
            {
                "index": idx,
                "descripcion": d.get("descripcion"),
                "extra_raw_type": extra_raw_type,
                "extra_raw_preview": extra_raw_preview,
                "where_found": where_found or None,
                "raw_value": raw_venc or None,
                "normalized_value": metadata_diag.get("normalized_value") or None,
                "blob_first_match": blob_match or None,
                "all_candidates": list(candidates_list),
            }
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
        data_rows = [row for row, _, _ in rows_subset]
        data = [header_row] + data_rows
        table = Table(data, colWidths=col_widths, repeatRows=1)
        commands = list(base_style_commands)
        for idx, (_, is_meta, _) in enumerate(rows_subset, start=1):
            if is_meta:
                commands.extend([
                    (
                        'SPAN',
                        (descripcion_col_idx, idx),
                        (-1, idx),
                    ),
                    (
                        'FONTNAME',
                        (descripcion_col_idx, idx),
                        (-1, idx),
                        body_fontname,
                    ),
                    (
                        'FONTSIZE',
                        (descripcion_col_idx, idx),
                        (-1, idx),
                        meta_fontsize,
                    ),
                    (
                        'TEXTCOLOR',
                        (descripcion_col_idx, idx),
                        (-1, idx),
                        meta_text_color,
                    ),
                    (
                        'ALIGN',
                        (descripcion_col_idx, idx),
                        (-1, idx),
                        'LEFT',
                    ),
                    (
                        'LEFTPADDING',
                        (descripcion_col_idx, idx),
                        (-1, idx),
                        table_padding + 2,
                    ),
                    (
                        'RIGHTPADDING',
                        (descripcion_col_idx, idx),
                        (-1, idx),
                        table_padding,
                    ),
                    (
                        'LINEABOVE',
                        (descripcion_col_idx, idx),
                        (-1, idx),
                        0.4,
                        colors.HexColor("#d0d0d0"),
                    ),
                    (
                        'TOPPADDING',
                        (descripcion_col_idx, idx),
                        (-1, idx),
                        max(table_padding - 3, 2),
                    ),
                    (
                        'BOTTOMPADDING',
                        (descripcion_col_idx, idx),
                        (-1, idx),
                        max(table_padding - 2, 2),
                    ),
                    (
                        'VALIGN',
                        (descripcion_col_idx, idx),
                        (-1, idx),
                        'TOP',
                    ),
                ])
        table.setStyle(TableStyle(commands))
        return table

    def table_height(rows_subset):
        table = build_table(rows_subset)
        _, height_used = table.wrap(0, 0)
        return height_used

    def groups_that_fit(max_height, groups):
        if max_height <= 0:
            return 0
        included_rows: list[tuple[list, bool, str | None]] = []
        count = 0
        for group in groups:
            test_rows = included_rows + group
            if table_height(test_rows) <= max_height:
                included_rows = test_rows
                count += 1
            else:
                break
        return count

    available_height_last = tabla_y - (bloque_totales_y + bloque_totales_h + 20)
    available_height_standard = tabla_y - (y_margin + 40)
    available_height_last = max(available_height_last, 0)
    available_height_standard = max(available_height_standard, 0)

    remaining_groups = [group[:] for group in row_groups]
    table_pages_groups: list[list[tuple[list, bool, str | None]]] = []

    while remaining_groups:
        flat_remaining = [row for group in remaining_groups for row in group]
        if table_height(flat_remaining) <= available_height_last:
            table_pages_groups.append(flat_remaining)
            remaining_groups = []
        else:
            count_groups = groups_that_fit(available_height_standard, remaining_groups)
            if count_groups <= 0:
                count_groups = 1
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
        if trace_enabled:
            row_heights = getattr(table, "_rowHeights", None)
            if row_heights:
                y_cursor = tabla_y - row_heights[0]
                x_right = tabla_x + sum(col_widths) - table_padding
                for idx_table, (_, is_meta, overlay) in enumerate(rows_chunk, start=1):
                    row_height = row_heights[idx_table]
                    row_bottom = y_cursor - row_height
                    y_cursor = row_bottom
                    if not overlay or is_meta:
                        continue
                    c.saveState()
                    c.setFillGray(0.5)
                    c.setFont("Helvetica", 6)
                    text_y = max(row_bottom + 2, row_bottom + row_height * 0.2)
                    c.drawRightString(x_right, text_y, overlay)
                    c.restoreState()
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

    tracer.dump()

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
