from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.platypus import Table, TableStyle
from reportlab.lib import colors
from reportlab.graphics import renderPDF
from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing
from reportlab.lib.units import mm

from utils.pdf_utils import draw_wrapped_text
import utils.catalogos as catalogos
from dte import generar_cabecera_dte_data
from db import DB
from urllib.parse import urlencode
import json
import os
from datetime import datetime
from paths import DATOS_NEGOCIO_PATH


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

    tipo_dte = "01" if tipo_documento.upper() == "CONSUMIDOR FINAL" else "03"

    if not codigo_generacion or not numero_control or not fecha_generacion:
        cab = generar_cabecera_dte_data(
            tipo_modelo,
            tipo_operacion,
            tipo_dte,
            DB(),
            tipo_contingencia=tipo_contingencia,
            motivo_contin=motivo_contin,
            ambiente=ambiente,
        )
        codigo_generacion = codigo_generacion or cab["codigo_generacion"]
        numero_control = numero_control or cab["numero_control"]
        fecha_generacion = fecha_generacion or cab["fecha_generacion"]
        sello_recepcion = sello_recepcion or cab["sello_recepcion"]

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


    top = height - 50
    c.setFont("Helvetica-Bold", 16)
    c.drawCentredString(width / 2, top, "DOCUMENTO TRIBUTARIO ELECTRÓNICO")

    top -= 20
    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(width / 2, top, tipo_documento.upper())


    row_y = top - 40
    c.setFont("Helvetica", 10)

    # --- Configuración de columnas para las cajas y el QR ---
    spacing = 10
    col_margin = 15
    qr_size = 30 * mm
    available_w = width - 2 * x_margin - qr_size - 2 * col_margin
    box_w = available_w / 2
    box_h = 40

    # Posición inferior de las cajas de cabecera
    box_y = row_y - box_h

    # --- Caja izquierda con datos de generación ---
    c.setLineWidth(0.7)
    c.setStrokeColor(colors.white)
    c.roundRect(x_margin, box_y, box_w, box_h, 6, stroke=1, fill=0)
    c.setStrokeColor(colors.black)
    text_y = box_y + box_h - 12
    max_w = box_w - 10
    text_y = draw_wrapped_text(
        c,
        f"Código Generación: {codigo_generacion}",
        x_margin + 5,
        text_y,
        max_w,
        12,
    )
    text_y = draw_wrapped_text(
        c,
        f"Número Control: {numero_control}",
        x_margin + 5,
        text_y,
        max_w,
        12,
    )
    text_y = draw_wrapped_text(
        c,
        f"Sello Recepción: {sello_recepcion}",
        x_margin + 5,
        text_y,
        max_w,
        12,
    )

    # --- Código QR ---
    qr_x = x_margin + box_w + col_margin + 5
    qr_y = box_y + (box_h - qr_size) / 2
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
    c.setFont("Helvetica", 6)
    c.drawCentredString(qr_x + qr_size / 2, qr_y - 10, qr_url)

    # --- Caja derecha con datos de operación ---
    right_x = x_margin + box_w + col_margin + qr_size + col_margin
    c.setStrokeColor(colors.white)
    c.roundRect(right_x, box_y, box_w, box_h, 6, stroke=1, fill=0)
    c.setStrokeColor(colors.black)
    text_y = box_y + box_h - 12
    max_w = box_w - 10
    text_y = draw_wrapped_text(
        c,
        f"Tipo Modelo: {tipo_modelo}",
        right_x + 5,
        text_y,
        max_w,
        12,
    )
    text_y = draw_wrapped_text(
        c,
        f"Tipo Operación: {tipo_operacion}",
        right_x + 5,
        text_y,
        max_w,
        12,
    )
    if tipo_contingencia is not None:
        text_y = draw_wrapped_text(
            c,
            f"Contingencia: {tipo_contingencia}",
            right_x + 5,
            text_y,
            max_w,
            12,
        )
    text_y = draw_wrapped_text(
        c,
        f"Fecha Generación: {fecha_generacion}",
        right_x + 5,
        text_y,
        max_w,
        12,
    )

    if tipo_operacion == 2:
        c.setFont("Helvetica-Bold", 12)
        c.setFillColor(colors.red)
        c.drawCentredString(width / 2, box_y - 15, "TRANSMISIÓN DIFERIDA")
        c.setFillColor(colors.black)

    # Posiciones base para los cuadros de emisor y receptor
    # Mantenemos un espacio de 20 puntos debajo del código QR para acercarlos al encabezado
    encabezado_y = qr_y - 20

    # --- Datos del EMISOR (izquierda) y RECEPTOR (derecha) ---

    box_w = (width - 2 * x_margin - 10) // 2
    line_h = 12

    telefono = datos_negocio.get('telefono', '')
    correo_emisor = datos_negocio.get('correo') or datos_negocio.get('email_usuario', '')

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

    receptor_line_count = 4  # encabezado + nombre + DUI + NIT
    receptor_extra = 1  # línea "Giro/Orden" o espaciado
    if tipo_documento == "Crédito Fiscal":
        receptor_extra += 1  # línea "Condición pago"
    receptor_line_count += receptor_extra
    receptor_line_count += 1  # Dirección
    if venta.get('venta_a_cuenta_de') or venta.get('documento_venta_a_cuenta'):
        receptor_line_count += 1

    box_h_emisor = 14 + line_h * emisor_line_count
    box_h_receptor = 14 + line_h * receptor_line_count
    box_h = max(box_h_emisor, box_h_receptor)

    box_y = encabezado_y - box_h
    emisor_x = x_margin
    receptor_x = emisor_x + box_w + 10

    c.setLineWidth(0.7)
    c.roundRect(emisor_x, box_y, box_w, box_h, 6, stroke=1, fill=0)
    c.roundRect(receptor_x, box_y, box_w, box_h, 6, stroke=1, fill=0)

    text_y = box_y + box_h - 14
    c.setFont("Helvetica-Bold", 8)
    c.drawString(emisor_x + 5, text_y, "EMISOR:")
    c.setFont("Helvetica", 8)
    text_y -= 12
    c.drawString(emisor_x + 5, text_y, f"Nombre: {datos_negocio.get('nombre', '')}")
    text_y -= 12
    c.drawString(emisor_x + 5, text_y, f"NIT: {datos_negocio.get('nit', '')}  NRC: {datos_negocio.get('nrc', '')}")
    text_y -= 12
    c.drawString(emisor_x + 5, text_y, f"Giro: {datos_negocio.get('descActividad', '')}")
    text_y -= 12
    direccion_emisor = format_direccion(datos_negocio.get("direccion"))
    text_y = draw_wrapped_text(
        c,
        f"Dirección: {direccion_emisor}",
        emisor_x + 5,
        text_y,
        box_w - 10,
        line_h,
    )
    if telefono:
        c.drawString(emisor_x + 5, text_y, f"Número Teléfono: {telefono}")
        text_y -= 12
    if correo_emisor:
        c.drawString(emisor_x + 5, text_y, f"Correo Electrónico: {correo_emisor}")
        text_y -= 12

    text_y = box_y + box_h - 14
    c.setFont("Helvetica-Bold", 8)
    c.drawString(receptor_x + 5, text_y, "RECEPTOR:")
    c.setFont("Helvetica", 8)

    left_x = receptor_x + 5
    right_x = receptor_x + box_w / 2 + 5

    text_y -= line_h
    c.drawString(left_x, text_y, f"Nombre: {cliente.get('nombre', '')}")

    text_y -= line_h
    c.drawString(left_x, text_y, f"DUI: {cliente.get('dui', '')}")
    if tipo_documento == "Crédito Fiscal":
        c.drawString(right_x, text_y, f"NRC: {cliente.get('nrc', '')}")

    text_y -= line_h
    c.drawString(left_x, text_y, f"NIT: {cliente.get('nit', '')}")
    if tipo_documento == "Crédito Fiscal":
        c.drawString(right_x, text_y, f"No. Remisión: {venta.get('no_remision', '')}")

    if tipo_documento == "Crédito Fiscal":
        text_y -= line_h
        c.drawString(left_x, text_y, f"Giro: {cliente.get('giro', '')}")
        c.drawString(right_x, text_y, f"Orden No.: {venta.get('orden_no', '')}")

        text_y -= line_h
        c.drawString(left_x, text_y, f"Condición pago: {venta.get('condicion_pago', '')}")
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

    if venta.get('venta_a_cuenta_de') or venta.get('documento_venta_a_cuenta'):
        text_y -= line_h
        if venta.get('venta_a_cuenta_de'):
            c.drawString(left_x, text_y, f"Venta a cta de: {venta.get('venta_a_cuenta_de')}")
        if venta.get('documento_venta_a_cuenta'):
            c.drawString(right_x, text_y, f"DUI/NIT: {venta.get('documento_venta_a_cuenta')}")

    # Posición inicial para la tabla de productos
    tabla_x = x_margin
    tabla_y = box_y - 20
    row_h = 18
    tabla_columnas = ["Cantidad", "Descripción", "Precio Unitario", "No sujetas", "Exentas", "Gravadas"]
    tabla_data = [tabla_columnas]
    for d in detalles:
        tabla_data.append([
            str(d.get("cantidad", "")),
            d.get("descripcion", ""),
            f"{d.get('precio_unitario', 0):.4f}",
            f"{d.get('ventas_no_sujetas', 0):.2f}",
            f"{d.get('ventas_exentas', 0):.2f}",
            f"{d.get('ventas_gravadas', 0):.2f}",
        ])

    tabla = Table(tabla_data, colWidths=[44, 200, 70, 60, 60, 70], repeatRows=1)
    tabla.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.7, colors.black),
        ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
        ('ALIGN', (0,0), (0,-1), 'CENTER'),  # Cantidad centrado
        ('ALIGN', (2,0), (-1,-1), 'RIGHT'),  # Números a la derecha
        ('ALIGN', (1,0), (1,-1), 'LEFT'),    # Descripción a la izquierda
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('FONTSIZE', (0,0), (-1,-1), 8),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTNAME', (0,1), (-1,-1), 'Helvetica'),
    ]))

    # Dibuja la tabla
    tabla.wrapOn(c, width, height)
    tabla.drawOn(c, tabla_x, tabla_y - row_h * (len(tabla_data)))

    # --- Suma de ventas (justo debajo de la tabla, antes de los totales) ---
    suma_y = tabla_y - row_h * (len(tabla_data)) - 10
    # c.setFont("Helvetica-Bold", 9)
    # c.drawRightString(tabla_x + 434, suma_y, f"SUMA DE VENTAS: {venta.get('sumas', 0):.2f}")

    # --- Bloque de totales y valor en letras, alineado y con formato solicitado ---
    bloque_totales_x = 30
    bloque_totales_w = 555
    bloque_totales_y = 80
    bloque_totales_h = 150

    c.setLineWidth(0.7)
    c.roundRect(bloque_totales_x, bloque_totales_y, bloque_totales_w, bloque_totales_h, 6, stroke=1, fill=0)

    # --- Línea vertical separadora ---
    columna_totales_w = 320
    x_linea = bloque_totales_x + columna_totales_w
    c.setLineWidth(0.5)
    c.line(x_linea, bloque_totales_y + 8, x_linea, bloque_totales_y + bloque_totales_h - 8)

    # --- Totales (columna derecha del cuadro, todos alineados) ---
    texto_y = bloque_totales_y + bloque_totales_h - 18
    salto = 18

    c.setFont("Helvetica", 9)
    c.drawString(x_linea + 10, texto_y, f"SUMA DE VENTAS:")
    c.drawRightString(
        bloque_totales_x + bloque_totales_w - 10,
        texto_y,
        f"{venta.get('subTotalVentas', venta.get('sumas', 0)):.2f}",
    )

    texto_y -= salto
    c.setFont("Helvetica-Bold", 9)
    c.drawString(x_linea + 10, texto_y, "Descuentos y rebajas:")
    c.setFont("Helvetica", 9)
    c.drawRightString(
        bloque_totales_x + bloque_totales_w - 10,
        texto_y,
        f"{venta.get('totalDescu', venta.get('descuentos', 0)):.2f}",
    )

    texto_y -= salto
    c.setFont("Helvetica-Bold", 9)
    c.drawString(x_linea + 10, texto_y, "IVA 13%:")
    c.setFont("Helvetica", 9)
    c.drawRightString(
        bloque_totales_x + bloque_totales_w - 10,
        texto_y,
        f"{venta.get('totalIva', venta.get('iva', 0)):.2f}",
    )

    texto_y -= salto
    c.setFont("Helvetica-Bold", 9)
    c.drawString(x_linea + 10, texto_y, "Subtotal:")
    c.setFont("Helvetica", 9)
    c.drawRightString(
        bloque_totales_x + bloque_totales_w - 10,
        texto_y,
        f"{venta.get('subTotal', venta.get('subtotal', 0)):.2f}",
    )

    texto_y -= salto
    c.setFont("Helvetica-Bold", 9)
    c.drawString(x_linea + 10, texto_y, "Exentas:")
    c.setFont("Helvetica", 9)
    c.drawRightString(bloque_totales_x + bloque_totales_w - 10, texto_y, f"{venta.get('ventas_exentas', 0):.2f}")

    texto_y -= salto
    c.setFont("Helvetica-Bold", 9)
    c.drawString(x_linea + 10, texto_y, "No sujetas:")
    c.setFont("Helvetica", 9)
    c.drawRightString(bloque_totales_x + bloque_totales_w - 10, texto_y, f"{venta.get('ventas_no_sujetas', 0):.2f}")

    texto_y -= salto + 10  # Más espacio antes de "Total a pagar"
    c.setFont("Helvetica-Bold", 10)
    c.drawString(x_linea + 10, texto_y, "Total a pagar:")
    c.setFont("Helvetica-Bold", 10)
    c.drawRightString(bloque_totales_x + bloque_totales_w - 10, texto_y, f"{venta.get('total', 0):.2f}")

    # --- Valor en letras (columna izquierda del cuadro, texto más grande y solo el label en negrita) ---
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

    # --- Pie de página ---
    c.setFont("Helvetica", 8)
    c.drawCentredString(width/2, 20, f"Página 1 de 1")

    c.save()


def generar_nota_credito_pdf(
    venta,
    detalles,
    cliente,
    distribuidor,
    archivo="nota_credito.pdf",
    datos_negocio=None,
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
        **kwargs,
    )


def generar_nota_debito_pdf(
    venta,
    detalles,
    cliente,
    distribuidor,
    archivo="nota_debito.pdf",
    datos_negocio=None,
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
