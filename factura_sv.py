from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.platypus import Table, TableStyle
from reportlab.lib import colors
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
):

    if datos_negocio is None:
        datos_negocio = {}
        if os.path.exists(DATOS_NEGOCIO_PATH):
            try:
                with open(DATOS_NEGOCIO_PATH, "r", encoding="utf-8") as f:
                    datos_negocio = json.load(f)
            except Exception:
                datos_negocio = {}

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

    # Posiciones base para los cuadros de emisor y receptor
    encabezado_y = height - y_margin

    # --- Datos del EMISOR (izquierda) y RECEPTOR (derecha) ---

    box_w = (width - 2 * x_margin - 10) // 2
    box_h = 100
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
    telefono = datos_negocio.get('telefono_fijo') or datos_negocio.get('telefono_movil', '')
    c.drawString(emisor_x + 5, text_y, f"Número Teléfono: {telefono}")
    text_y -= 12
    correo_emisor = datos_negocio.get('email') or datos_negocio.get('email_usuario', '')
    c.drawString(emisor_x + 5, text_y, f"Correo Electrónico: {correo_emisor}")

    text_y = box_y + box_h - 14
    c.setFont("Helvetica-Bold", 8)
    c.drawString(receptor_x + 5, text_y, "RECEPTOR:")
    c.setFont("Helvetica", 8)
    text_y -= 12
    c.drawString(receptor_x + 5, text_y, f"Nombre: {cliente.get('nombre', '')}")
    text_y -= 12
    c.drawString(receptor_x + 5, text_y, f"DUI: {cliente.get('dui', '')}")
    text_y -= 12
    c.drawString(receptor_x + 5, text_y, f"NIT: {cliente.get('nit', '')}  NRC: {cliente.get('nrc', '')}")
    text_y -= 12
    c.drawString(receptor_x + 5, text_y, f"Giro: {cliente.get('giro', '')}")
    text_y -= 12
    c.drawString(receptor_x + 5, text_y, f"Dirección: {cliente.get('direccion', '')}")

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
            f"{d.get('precio_unitario', 0):.2f}",
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
    c.drawString(x_linea + 10, texto_y, "Descuentos y rebajas globales:")
    c.setFont("Helvetica", 9)
    c.drawRightString(bloque_totales_x + bloque_totales_w - 10, texto_y, f"{venta.get('descuentos_globales', '')}")

    texto_y -= salto
    c.setFont("Helvetica-Bold", 9)
    c.drawString(x_linea + 10, texto_y, "Subtotal:")
    c.setFont("Helvetica", 9)
    c.drawRightString(bloque_totales_x + bloque_totales_w - 10, texto_y, f"{venta.get('subtotal', '')}")

    texto_y -= salto
    c.setFont("Helvetica-Bold", 9)
    c.drawString(x_linea + 10, texto_y, "IVA 13%:")
    c.setFont("Helvetica", 9)
    c.drawRightString(bloque_totales_x + bloque_totales_w - 10, texto_y, f"{venta.get('iva', '')}")

    texto_y -= salto + 10  # Más espacio antes de "Total a pagar"
    c.setFont("Helvetica-Bold", 10)
    c.drawString(x_linea + 10, texto_y, "Total a pagar:")
    c.setFont("Helvetica-Bold", 10)
    c.drawRightString(bloque_totales_x + bloque_totales_w - 10, texto_y, f"{venta.get('total', '')}")

    # --- Valor en letras (columna izquierda del cuadro, texto más grande y solo el label en negrita) ---
    c.setFont("Helvetica-Bold", 11)
    c.drawString(bloque_totales_x + 10, bloque_totales_y + bloque_totales_h - 18, "Valor en letras:")
    c.setFont("Helvetica", 11)
    c.drawString(bloque_totales_x + 120, bloque_totales_y + bloque_totales_h - 18, f"{venta.get('total_letras', '')}")

    # --- Pie de página ---
    c.setFont("Helvetica", 8)
    c.drawCentredString(width/2, 20, f"Página 1 de 1")

    c.save()
