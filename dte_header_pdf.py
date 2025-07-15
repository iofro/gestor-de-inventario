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

    spacing = 10
    c.setFont("Helvetica", 10)
    y = row_y
    x = 40

    text = f"Código Generación: {codigo_generacion}"
    c.drawString(x, y, text)
    x += c.stringWidth(text, "Helvetica", 10) + spacing

    text = f"Número Control: {numero_control}"
    c.drawString(x, y, text)
    x += c.stringWidth(text, "Helvetica", 10) + spacing

    text = f"Sello Recepción: {sello_recepcion}"
    c.drawString(x, y, text)
    x += c.stringWidth(text, "Helvetica", 10) + spacing

    qr_value = codigo_generacion
    qr_code = qr.QrCodeWidget(qr_value)
    bounds = qr_code.getBounds()
    size = 15 * mm
    w = bounds[2] - bounds[0]
    h = bounds[3] - bounds[1]
    d = Drawing(size, size, transform=[size / w, 0, 0, size / h, 0, 0])
    d.add(qr_code)
    qr_x = x
    qr_y = y - size + 3
    renderPDF.draw(d, c, qr_x, qr_y)
    x += size + spacing

    text = f"Modelo Facturación: {modelo_facturacion}"
    c.drawString(x, y, text)
    x += c.stringWidth(text, "Helvetica", 10) + spacing

    text = f"Tipo Transmisión: {tipo_transmision}"
    c.drawString(x, y, text)
    x += c.stringWidth(text, "Helvetica", 10) + spacing

    text = f"Fecha Generación: {fecha_generacion}"
    c.drawString(x, y, text)

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
