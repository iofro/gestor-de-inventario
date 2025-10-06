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

    top = height - 50
    c.setFont("Helvetica-Bold", 16)
    c.drawCentredString(width / 2, top, "DOCUMENTO TRIBUTARIO ELECTRÓNICO")

    top -= 20
    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(width / 2, top, tipo_documento.upper())

    # Reduce the vertical gap between the title block and the header boxes so
    # the left-side information sits a little higher on the page without
    # colliding with the titles.
    row_y = top - 25
    c.setFont("Helvetica", 10)

    col_margin = 15
    qr_size = 15 * mm
    available_w = width - 2 * 40 - qr_size - 2 * col_margin
    box_w = available_w / 2
    box_h = 30

    box_y = row_y - box_h
    left_box_y = box_y + 6

    # --- Caja izquierda ---
    c.setLineWidth(0.7)
    c.setStrokeColor(colors.white)
    c.roundRect(40, left_box_y, box_w, box_h, 6, stroke=1, fill=0)
    c.setStrokeColor(colors.black)
    text_y = left_box_y + box_h - 10
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

    # --- Caja derecha ---
    right_x = 40 + box_w + col_margin + qr_size + col_margin
    c.setStrokeColor(colors.white)
    c.roundRect(right_x, box_y, box_w, box_h, 6, stroke=1, fill=0)
    c.setStrokeColor(colors.black)
    text_y = box_y + box_h - 10
    max_w = box_w - 10
    text_y = draw_wrapped_text(
        c,
        f"Tipo Modelo: {tipo_modelo}",
        right_x + 5,
        text_y,
        max_w,
        10,
    )
    text_y = draw_wrapped_text(
        c,
        f"Tipo Operación: {tipo_operacion}",
        right_x + 5,
        text_y,
        max_w,
        10,
    )
    if tipo_contingencia is not None:
        text_y = draw_wrapped_text(
            c,
            f"Contingencia: {tipo_contingencia}",
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
