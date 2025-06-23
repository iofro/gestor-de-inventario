from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.graphics.shapes import Drawing
from reportlab.graphics import renderPDF
from reportlab.graphics.barcode import qr
from reportlab.platypus import Table, TableStyle
from reportlab.lib import colors

def generar_factura_electronica_pdf(venta, detalles, cliente, distribuidor, archivo="factura_electronica.pdf"):
    from datetime import datetime

    c = canvas.Canvas(archivo, pagesize=letter)
    width, height = letter
    x_margin = 30
    y_margin = 30

    # --- ENCABEZADO SUPERIOR IZQUIERDA: DATOS FIJOS ---
    encabezado_y = height - y_margin
    encabezado_x = x_margin
    c.setFont("Helvetica-Bold", 14)
    c.drawString(encabezado_x, encabezado_y, "FARMACIA SANTA CATALINA")
    c.setFont("Helvetica-Bold", 10)
    c.drawString(encabezado_x, encabezado_y - 16, "KAROL YAMILETH CRUZ ESCOBAR")
    c.setFont("Helvetica-Bold", 9)
    c.drawString(encabezado_x, encabezado_y - 30, "VENTA DE PRODUCTOS FARMACÉUTICOS Y MEDICINALES")
    c.drawString(encabezado_x, encabezado_y - 42, "SERVICIOS MÉDICOS")
    c.setFont("Helvetica", 8)
    c.drawString(encabezado_x, encabezado_y - 56, "LOCAL. 3. #4-6 B, PASEO CONCEPCIÓN, SANTA TECLA,")
    c.drawString(encabezado_x, encabezado_y - 66, "LA LIBERTAD, EL SALVADOR, C.A.")

    # --- ENCABEZADO SUPERIOR DERECHA: TIPO DE DOCUMENTO ---
    doc_x = width - x_margin - 260
    doc_y = height - y_margin
    c.setFont("Helvetica-Bold", 11)
    c.drawString(doc_x, doc_y, "DOCUMENTO TRIBUTARIO ELECTRÓNICO")
    c.setFont("Helvetica-Bold", 9)
    c.drawString(doc_x, doc_y - 18, "COMPROBANTE DE CRÉDITO FISCAL")
    c.setFont("Helvetica", 7)
    c.drawRightString(width - x_margin, doc_y, f"Ver. {venta.get('version', '3')}")

    # --- Cuadro superior derecho: Datos fiscales + QR + Fecha y hora de generación ---
    # --- Parámetros para alineación perfecta del cuadro derecho ---
    cuadro_w = 220
    cuadro_h = 90
    invisible_col_sep = 0   # Mueve el cuadro un poco más a la derecha
    cuadro_y_offset = 48     # Mueve el cuadro más arriba

    doc_x = width - x_margin - 260  # Donde empieza "DOCUMENTO TRIBUTARIO ELECTRÓNICO"
    cuadro_x = doc_x + invisible_col_sep
    cuadro_y = encabezado_y - 170 + cuadro_y_offset

    c.setLineWidth(0.7)
    c.roundRect(cuadro_x, cuadro_y, cuadro_w, cuadro_h, 6, stroke=1, fill=0)
    c.setFont("Helvetica", 9)
    c.drawString(cuadro_x + 8, cuadro_y + cuadro_h - 18, f"Código de Generación: {venta.get('codigo_generacion', '')}")
    c.drawString(cuadro_x + 8, cuadro_y + cuadro_h - 36, f"N° Control: {venta.get('numero_control', '')}")
    c.drawString(cuadro_x + 8, cuadro_y + cuadro_h - 54, f"Sello de Recepción: {venta.get('sello_recepcion', '')}")
    c.drawString(cuadro_x + 8, cuadro_y + cuadro_h - 72, f"Fecha y hora de generación: {venta.get('fecha', '')}")

    # QR a la derecha del cuadro (ajusta la posición si es necesario)
    qr_data = venta.get('qr', '')
    if qr_data:
        qr_code = qr.QrCodeWidget(qr_data)
        bounds = qr_code.getBounds()
        qr_size = 50
        width_qr = bounds[2] - bounds[0]
        height_qr = bounds[3] - bounds[1]
        d = Drawing(qr_size, qr_size)
        d.add(qr_code)
        d.scale(qr_size / width_qr, qr_size / height_qr)
        renderPDF.draw(d, c, cuadro_x + cuadro_w + 10, cuadro_y + 10)

    # --- Datos del EMISOR (izquierda) --- (OCULTOS, NO SE DIBUJAN, SOLO SE DEJAN EN EL CÓDIGO)
    # emisor_y = cuadro_y - 40
    # c.setFont("Helvetica-Bold", 9)
    # c.drawString(x_margin, emisor_y, "EMISOR:")
    # c.setFont("Helvetica", 9)
    # c.drawString(x_margin, emisor_y - 18, f"Nombre/Razón social: {distribuidor.get('nombre', '')}")
    # c.drawString(x_margin, emisor_y - 36, f"NIT: {distribuidor.get('nit', '')}  NRC: {distribuidor.get('nrc', '')}")
    # c.drawString(x_margin, emisor_y - 54, f"Actividad económica: {distribuidor.get('giro', '')}")
    # c.drawString(x_margin, emisor_y - 72, f"Dirección: {distribuidor.get('direccion', '')}")
    # c.drawString(x_margin, emisor_y - 90, f"Teléfono: {distribuidor.get('telefono', '')}")
    # c.drawString(x_margin, emisor_y - 108, f"Correo electrónico: {distribuidor.get('email', '')}")
    # c.drawString(x_margin, emisor_y - 126, f"Nombre comercial: {distribuidor.get('nombre_comercial', '')}")
    # c.drawString(x_margin, emisor_y - 144, f"Tipo de establecimiento: {distribuidor.get('tipo_establecimiento', '')}")

    # --- CUADRO DE INFORMACIÓN ANTES DE LA TABLA DE PRODUCTOS ---
    cuadro_info_x = x_margin
    cuadro_info_y = cuadro_y - 25  # Ajusta según tu diseño
    cuadro_info_w = width - 2 * x_margin
    cuadro_info_h = 90

    c.setLineWidth(0.7)
    c.roundRect(cuadro_info_x, cuadro_info_y - cuadro_info_h, cuadro_info_w, cuadro_info_h, 6, stroke=1, fill=0)

    # Columnas
    col1_x = cuadro_info_x + 10
    col2_x = cuadro_info_x + cuadro_info_w // 3 + 10
    col3_x = cuadro_info_x + 2 * (cuadro_info_w // 3) + 10
    row_y = cuadro_info_y - 16

    # --- Columna izquierda ---
    c.setFont("Helvetica-Bold", 8)
    c.drawString(col1_x, row_y, "Cliente:")
    c.setFont("Helvetica", 8)
    c.drawString(col1_x + 50, row_y, cliente.get("nombre", ""))
    c.setFont("Helvetica-Bold", 8)
    c.drawString(col1_x, row_y - 14, "Dirección:")
    c.setFont("Helvetica", 8)
    c.drawString(col1_x + 50, row_y - 14, cliente.get("direccion", ""))
    c.setFont("Helvetica-Bold", 8)
    c.drawString(col1_x, row_y - 28, "NIT:")
    c.setFont("Helvetica", 8)
    c.drawString(col1_x + 50, row_y - 28, cliente.get("nit", ""))
    c.setFont("Helvetica-Bold", 8)
    c.drawString(col1_x, row_y - 42, "NRC:")
    c.setFont("Helvetica", 8)
    c.drawString(col1_x + 50, row_y - 42, cliente.get("nrc", ""))
    c.setFont("Helvetica-Bold", 8)
    c.drawString(col1_x, row_y - 56, "Giro:")
    c.setFont("Helvetica", 8)
    c.drawString(col1_x + 30, row_y - 56, cliente.get("giro", ""))

    # --- Columna central ---
    c.setFont("Helvetica-Bold", 8)
    c.drawString(col2_x, row_y, "Cond. de pago:")
    c.setFont("Helvetica", 8)
    c.drawString(col2_x + 70, row_y, venta.get("condicion_pago", ""))
    c.setFont("Helvetica-Bold", 8)
    c.drawString(col2_x, row_y - 14, "No Rem:")
    c.setFont("Helvetica", 8)
    c.drawString(col2_x + 50, row_y - 14, venta.get("no_remision", ""))
    c.setFont("Helvetica-Bold", 8)
    c.drawString(col2_x, row_y - 28, "Orden No:")
    c.setFont("Helvetica", 8)
    c.drawString(col2_x + 60, row_y - 28, venta.get("orden_no", ""))
    c.setFont("Helvetica-Bold", 8)
    c.drawString(col2_x, row_y - 42, "Vendedor:")
    c.setFont("Helvetica", 8)
    c.drawString(col2_x + 50, row_y - 42, venta.get("vendedor_nombre", ""))

    # --- Columna derecha ---
    c.setFont("Helvetica-Bold", 8)
    c.drawString(col3_x, row_y, "Vta a Cta de:")
    c.setFont("Helvetica", 8)
    c.drawString(col3_x + 60, row_y, venta.get("venta_a_cuenta_de", ""))
    c.setFont("Helvetica-Bold", 8)
    c.drawString(col3_x, row_y - 14, "Fecha:")
    c.setFont("Helvetica", 8)
    fecha = venta.get("fecha", "")
    try:
        fecha_solo = datetime.strptime(fecha, "%Y-%m-%d %H:%M:%S").strftime("%d/%m/%Y")
    except Exception:
        fecha_solo = fecha
    c.drawString(col3_x + 40, row_y - 14, fecha_solo)

    # --- Tabla central de productos tipo Excel ---
    tabla_x = x_margin
    tabla_y = cuadro_info_y - cuadro_info_h - 30
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
    c.drawString(x_linea + 10, texto_y, "Monto total de operación:")
    c.setFont("Helvetica", 9)
    c.drawRightString(bloque_totales_x + bloque_totales_w - 10, texto_y, f"{venta.get('total_operacion', '')}")

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