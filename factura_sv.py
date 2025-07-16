from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.platypus import Table, TableStyle
from reportlab.lib import colors
from reportlab.graphics import renderPDF
from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing
from reportlab.lib.units import mm

from utils.pdf_utils import draw_wrapped_text
from dte import generar_cabecera_dte_data
import json
import os

DATOS_NEGOCIO_PATH = os.path.join(os.path.dirname(__file__), "datos_negocio.json")


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
    modelo_facturacion="1 - Facturación previo",
    tipo_transmision="",
    fecha_generacion="",
):

    if datos_negocio is None:
        datos_negocio = {}
        if os.path.exists(DATOS_NEGOCIO_PATH):
            try:
                with open(DATOS_NEGOCIO_PATH, "r", encoding="utf-8") as f:
                    datos_negocio = json.load(f)
            except Exception:
                datos_negocio = {}

    if not codigo_generacion or not numero_control or not fecha_generacion:
        cab = generar_cabecera_dte_data(modelo_facturacion, tipo_transmision)
        codigo_generacion = codigo_generacion or cab["codigo_generacion"]
        numero_control = numero_control or cab["numero_control"]
        fecha_generacion = fecha_generacion or cab["fecha_generacion"]
        sello_recepcion = sello_recepcion or cab["sello_recepcion"]

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
    qr_value = f"{numero_control}|{codigo_generacion}"
    qr_code = qr.QrCodeWidget(qr_value)
    bounds = qr_code.getBounds()
    w = bounds[2] - bounds[0]
    h = bounds[3] - bounds[1]
    d = Drawing(qr_size, qr_size, transform=[qr_size / w, 0, 0, qr_size / h, 0, 0])
    d.add(qr_code)
    renderPDF.draw(d, c, qr_x, qr_y)

    # --- Caja derecha con modelo de facturación ---
    right_x = x_margin + box_w + col_margin + qr_size + col_margin
    c.setStrokeColor(colors.white)
    c.roundRect(right_x, box_y, box_w, box_h, 6, stroke=1, fill=0)
    c.setStrokeColor(colors.black)
    text_y = box_y + box_h - 12
    max_w = box_w - 10
    text_y = draw_wrapped_text(
        c,
        f"Modelo Facturación: {modelo_facturacion}",
        right_x + 5,
        text_y,
        max_w,
        12,
    )
    text_y = draw_wrapped_text(
        c,
        f"Tipo Transmisión: {tipo_transmision}",
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

    # Posiciones base para los cuadros de emisor y receptor
    # Mantenemos un espacio de 20 puntos debajo del código QR para acercarlos al encabezado
    encabezado_y = qr_y - 20

    # --- Datos del EMISOR (izquierda) y RECEPTOR (derecha) ---

    box_w = (width - 2 * x_margin - 10) // 2
    line_h = 12

    telefono = datos_negocio.get('telefono_fijo') or datos_negocio.get('telefono_movil', '')
    correo_emisor = datos_negocio.get('email') or datos_negocio.get('email_usuario', '')

    emisor_lines = [
        f"Nombre: {datos_negocio.get('razon_social', '')}",
        f"NIT: {datos_negocio.get('nit', '')}  NRC: {datos_negocio.get('nrc', '')}",
        f"Giro: {datos_negocio.get('giro', '')}",
        f"Dirección: {datos_negocio.get('direccion', '')}",
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
    c.drawString(emisor_x + 5, text_y, f"Nombre: {datos_negocio.get('razon_social', '')}")
    text_y -= 12
    c.drawString(emisor_x + 5, text_y, f"NIT: {datos_negocio.get('nit', '')}  NRC: {datos_negocio.get('nrc', '')}")
    text_y -= 12
    c.drawString(emisor_x + 5, text_y, f"Giro: {datos_negocio.get('giro', '')}")
    text_y -= 12
    c.drawString(emisor_x + 5, text_y, f"Dirección: {datos_negocio.get('direccion', '')}")
    text_y -= 12
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
    c.drawString(left_x, text_y, f"Dirección: {cliente.get('direccion', '')}")

    if venta.get('venta_a_cuenta_de') or venta.get('documento_venta_a_cuenta'):
        text_y -= line_h
        if venta.get('venta_a_cuenta_de'):
            c.drawString(left_x, text_y, f"Venta a cta de: {venta.get('venta_a_cuenta_de')}")
        if venta.get('documento_venta_a_cuenta'):
            c.drawString(right_x, text_y, f"DUI/NIT: {venta.get('documento_venta_a_cuenta')}")

    # Posición inicial para la tabla de productos
    tabla_x = x_margin
    tabla_y = box_y - 40
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
    c.drawRightString(bloque_totales_x + bloque_totales_w - 10, texto_y, f"{venta.get('sumas', 0):.2f}")

    texto_y -= salto
    c.setFont("Helvetica-Bold", 9)
    c.drawString(x_linea + 10, texto_y, "Descuentos y rebajas:")
    c.setFont("Helvetica", 9)
    c.drawRightString(bloque_totales_x + bloque_totales_w - 10, texto_y, f"{venta.get('descuentos', 0):.2f}")

    texto_y -= salto
    c.setFont("Helvetica-Bold", 9)
    c.drawString(x_linea + 10, texto_y, "IVA 13%:")
    c.setFont("Helvetica", 9)
    c.drawRightString(bloque_totales_x + bloque_totales_w - 10, texto_y, f"{venta.get('iva', 0):.2f}")

    texto_y -= salto
    c.setFont("Helvetica-Bold", 9)
    c.drawString(x_linea + 10, texto_y, "Subtotal:")
    c.setFont("Helvetica", 9)
    c.drawRightString(bloque_totales_x + bloque_totales_w - 10, texto_y, f"{venta.get('subtotal', 0):.2f}")

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
    c.drawString(bloque_totales_x + 120, bloque_totales_y + bloque_totales_h - 18, f"{venta.get('total_letras', '')}")

    # --- Pie de página ---
    c.setFont("Helvetica", 8)
    c.drawCentredString(width/2, 20, f"Página 1 de 1")

    c.save()
