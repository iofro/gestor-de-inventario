import os

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.graphics import renderPDF
from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing
from reportlab.lib.units import mm
from reportlab.lib import colors

from utils.pdf_utils import draw_wrapped_text
from factura_sv import build_qr_url
from datetime import datetime
from utils import resource_path


def generar_cabecera_dte(
    codigo_generacion: str,
    numero_control: str,
    sello_recepcion: str,
    tipo_modelo: int,
    tipo_operacion: int,
    fecha_generacion: str,
    tipo_contingencia: int | None = None,
    nit_emisor: str = "",
    fecha_emision: str | None = None,
    tipo_dte: str = "01",
    ambiente: str = "00",
    tipo_documento: str = "CONSUMIDOR FINAL",
    archivo: str = "cabecera_dte.pdf",
):
    """Genera un PDF con la cabecera de un Documento Tributario Electrónico."""
    c = canvas.Canvas(archivo, pagesize=letter)
    width, height = letter

    top = height - 45
    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(width / 2, top, "DOCUMENTO TRIBUTARIO ELECTRÓNICO")

    top -= 16
    c.setFont("Helvetica-Bold", 11)
    c.drawCentredString(width / 2, top, tipo_documento.upper())

    c.setFont("Helvetica", 9)

    header_margin = 40
    header_height = 88
    header_gap = 20
    header_y = top - header_gap - header_height
    header_w = width - 2 * header_margin

    c.setLineWidth(0.7)
    c.setStrokeColor(colors.white)
    c.roundRect(header_margin, header_y, header_w, header_height, 8, stroke=1, fill=0)
    c.setStrokeColor(colors.black)

    logo_slot_w = 90
    inner_padding = 10
    logo_height = header_height - 2 * inner_padding
    logo_path = resource_path("logoinventario.jpg")
    if logo_path and os.path.exists(logo_path):
        logo_x = header_margin + inner_padding
        logo_y = header_y + header_height - logo_height - inner_padding
        c.drawImage(
            str(logo_path),
            logo_x,
            logo_y,
            width=logo_slot_w,
            height=logo_height,
            preserveAspectRatio=True,
            mask="auto",
        )

    qr_size = 26 * mm
    qr_x = header_margin + header_w - qr_size - inner_padding
    qr_y = header_y + (header_height - qr_size) / 2
    if not fecha_emision and fecha_generacion:
        try:
            fecha_emision = datetime.strptime(
                fecha_generacion.split(",")[0].strip(), "%d/%m/%Y"
            ).strftime("%Y-%m-%d")
        except Exception:
            fecha_emision = datetime.now().strftime("%Y-%m-%d")
    dte = {
        "identificacion": {
            "ambiente": ambiente,
            "codigoGeneracion": codigo_generacion,
            "fecEmi": fecha_emision,
        }
    }
    qr_value = build_qr_url(dte)
    qr_code = qr.QrCodeWidget(qr_value)
    bounds = qr_code.getBounds()
    w = bounds[2] - bounds[0]
    h = bounds[3] - bounds[1]
    d = Drawing(qr_size, qr_size, transform=[qr_size / w, 0, 0, qr_size / h, 0, 0])
    d.add(qr_code)
    renderPDF.draw(d, c, qr_x, qr_y)
    c.linkURL(qr_value, (qr_x, qr_y, qr_x + qr_size, qr_y + qr_size), relative=0)

    text_x = header_margin + logo_slot_w + 2 * inner_padding
    text_right_limit = qr_x - inner_padding
    text_width = max(10, text_right_limit - text_x)
    text_y = header_y + header_height - inner_padding - 2
    line_height = 11

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

    c.save()


if __name__ == "__main__":
    generar_cabecera_dte(
        codigo_generacion="ABCDEF1234567890",
        numero_control="DTE-001",
        sello_recepcion="ABCDEF0123456789ABCDEF0123456789ABCDEF01",
        tipo_modelo=1,
        tipo_operacion=1,
        fecha_generacion="01/07/2025, 11:15 AM",
        nit_emisor="06140020001001",
        fecha_emision="2025-07-30",
        tipo_documento="CONSUMIDOR FINAL",
        archivo="cabecera_consumidor_final.pdf",
    )
    generar_cabecera_dte(
        codigo_generacion="ABCDEF1234567890",
        numero_control="DTE-001",
        sello_recepcion="ABCDEF0123456789ABCDEF0123456789ABCDEF01",
        tipo_modelo=1,
        tipo_operacion=1,
        fecha_generacion="01/07/2025, 11:15 AM",
        nit_emisor="06140020001001",
        fecha_emision="2025-07-30",
        tipo_documento="CREDITO FISCAL",
        archivo="cabecera_credito_fiscal.pdf",
    )
