from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.graphics import renderPDF
from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing
from reportlab.lib.units import mm
from reportlab.lib import colors

from utils.pdf_utils import draw_wrapped_text
from factura_sv import build_qr_value


def generar_cabecera_dte(
    codigo_generacion: str,
    numero_control: str,
    sello_recepcion: str,
    modelo_facturacion: str,
    tipo_transmision: str,
    fecha_generacion: str,
    nit_emisor: str = "",
    fecha_emision: str | None = None,
    tipo_dte: str = "01",
    ambiente: str = "pruebas",
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
    c.setFont("Helvetica", 10)

    col_margin = 15
    qr_size = 15 * mm
    available_w = width - 2 * 40 - qr_size - 2 * col_margin
    box_w = available_w / 2
    box_h = 30

    box_y = row_y - box_h

    # --- Caja izquierda ---
    c.setLineWidth(0.7)
    c.setStrokeColor(colors.white)
    c.roundRect(40, box_y, box_w, box_h, 6, stroke=1, fill=0)
    c.setStrokeColor(colors.black)
    text_y = box_y + box_h - 10
    max_w = box_w - 10
    text_y = draw_wrapped_text(
        c,
        f"Código Generación: {codigo_generacion}",
        45,
        text_y,
        max_w,
        10,
    )
    text_y = draw_wrapped_text(
        c,
        f"Número Control: {numero_control}",
        45,
        text_y,
        max_w,
        10,
    )
    text_y = draw_wrapped_text(
        c,
        f"Sello Recepción: {sello_recepcion}",
        45,
        text_y,
        max_w,
        10,
    )

    # QR en el centro
    qr_x = 40 + box_w + col_margin + 3
    qr_y = box_y + (box_h - qr_size) / 2
    qr_value = build_qr_value(
        1 if ambiente == "produccion" else 2,
        codigo_generacion,
        tipo_dte,
        numero_control,
    )
    qr_code = qr.QrCodeWidget(qr_value)
    bounds = qr_code.getBounds()
    w = bounds[2] - bounds[0]
    h = bounds[3] - bounds[1]
    d = Drawing(qr_size, qr_size, transform=[qr_size / w, 0, 0, qr_size / h, 0, 0])
    d.add(qr_code)
    renderPDF.draw(d, c, qr_x, qr_y)

    # --- Caja derecha ---
    right_x = 40 + box_w + col_margin + qr_size + col_margin
    c.setStrokeColor(colors.white)
    c.roundRect(right_x, box_y, box_w, box_h, 6, stroke=1, fill=0)
    c.setStrokeColor(colors.black)
    text_y = box_y + box_h - 10
    max_w = box_w - 10
    text_y = draw_wrapped_text(
        c,
        f"Modelo Facturación: {modelo_facturacion}",
        right_x + 5,
        text_y,
        max_w,
        10,
    )
    text_y = draw_wrapped_text(
        c,
        f"Tipo Transmisión: {tipo_transmision}",
        right_x + 5,
        text_y,
        max_w,
        10,
    )
    text_y = draw_wrapped_text(
        c,
        f"Fecha Generación: {fecha_generacion}",
        right_x + 5,
        text_y,
        max_w,
        10,
    )

    c.save()


if __name__ == "__main__":
    generar_cabecera_dte(
        codigo_generacion="ABCDEF1234567890",
        numero_control="DTE-001",
        sello_recepcion="SELLO1234567890",
        modelo_facturacion="1 - Facturación previo",
        tipo_transmision="1 - Transmisión normal",
        fecha_generacion="01/07/2025, 11:15 AM",
        nit_emisor="06140020001001",
        fecha_emision="2025-07-30",
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
        nit_emisor="06140020001001",
        fecha_emision="2025-07-30",
        tipo_documento="CREDITO FISCAL",
        archivo="cabecera_credito_fiscal.pdf",
    )
