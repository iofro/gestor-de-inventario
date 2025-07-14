from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.graphics import renderPDF
from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing
from reportlab.lib.units import mm


def generar_cabecera_dte(
    codigo_generacion: str,
    numero_control: str,
    sello_recepcion: str,
    modelo_facturacion: str,
    tipo_transmision: str,
    fecha_generacion: str,
    tipo_documento: str = "CONSUMIDOR FINAL",
    archivo: str = "cabecera_dte.pdf",
):
    """Genera un PDF con la cabecera de un Documento Tributario Electrónico."""
    c = canvas.Canvas(archivo, pagesize=letter)
    width, height = letter

    top = height - 50
    c.setFont("Helvetica-Bold", 16)
    c.drawCentredString(width / 2, top, "DOCUMENTO TRIBUTARIO ELECTRÓNICO")

    top -= 20
    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(width / 2, top, tipo_documento.upper())

    row_y = top - 40

    # Información izquierda
    c.setFont("Helvetica", 10)
    left_x = 40
    y = row_y
    c.drawString(left_x, y, f"Código Generación: {codigo_generacion}")
    y -= 14
    c.drawString(left_x, y, f"Número Control: {numero_control}")
    y -= 14
    c.drawString(left_x, y, f"Sello Recepción: {sello_recepcion}")

    # Información derecha
    right_x = width - 40
    y = row_y
    c.drawRightString(right_x, y, f"Modelo Facturación: {modelo_facturacion}")
    y -= 14
    c.drawRightString(right_x, y, f"Tipo Transmisión: {tipo_transmision}")
    y -= 14
    c.drawRightString(right_x, y, f"Fecha Generación: {fecha_generacion}")

    # Código QR en el centro
    qr_value = codigo_generacion
    qr_code = qr.QrCodeWidget(qr_value)
    bounds = qr_code.getBounds()
    size = 40 * mm
    w = bounds[2] - bounds[0]
    h = bounds[3] - bounds[1]
    d = Drawing(size, size, transform=[size / w, 0, 0, size / h, 0, 0])
    d.add(qr_code)
    renderPDF.draw(d, c, (width - size) / 2, row_y - size + 10)

    c.save()


if __name__ == "__main__":
    generar_cabecera_dte(
        codigo_generacion="ABCDEF1234567890",
        numero_control="DTE-001",
        sello_recepcion="SELLO1234567890",
        modelo_facturacion="1 - Facturación previo",
        tipo_transmision="1 - Transmisión normal",
        fecha_generacion="01/07/2025, 11:15 AM",
        tipo_documento="CONSUMIDOR FINAL",
        archivo="cabecera_consumidor_final.pdf",
    )
    generar_cabecera_dte(
        codigo_generacion="ABCDEF1234567890",
        numero_control="DTE-001",
        sello_recepcion="SELLO1234567890",
        modelo_facturacion="1 - Facturación previo",
        tipo_transmision="1 - Transmisión normal",
        fecha_generacion="01/07/2025, 11:15 AM",
        tipo_documento="CREDITO FISCAL",
        archivo="cabecera_credito_fiscal.pdf",
    )
