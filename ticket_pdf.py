from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
import json
import os

DATOS_NEGOCIO_PATH = os.path.join(os.path.dirname(__file__), "datos_negocio.json")


def generar_ticket_pdf(venta, detalles, archivo="ticket.pdf", datos_negocio=None):
    """Genera un PDF sencillo tipo ticket para una venta."""
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
    y = height - 40

    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(width / 2, y, datos_negocio.get("nombre_comercial", "TICKET"))
    y -= 20
    c.setFont("Helvetica", 10)
    c.drawString(40, y, f"Fecha: {venta.get('fecha', '')}")
    y -= 20
    c.drawString(40, y, "Detalles:")
    y -= 14

    for d in detalles:
        desc = d.get("descripcion", "")
        qty = d.get("cantidad", 0)
        pu = d.get("precio_unitario", 0)
        total = qty * pu
        c.drawString(40, y, f"{desc} x{qty} @ {pu:.2f}")
        c.drawRightString(width - 40, y, f"{total:.2f}")
        y -= 14
        if y < 60:
            c.showPage()
            y = height - 40

    y -= 10
    c.setFont("Helvetica-Bold", 12)
    c.drawRightString(width - 40, y, f"Total: {venta.get('total', 0):.2f}")

    c.showPage()
    c.save()


def generar_ticket_formato_nicolas(
    venta,
    detalles,
    archivo="ticket_nicolas.pdf",
    datos_negocio=None,
    logo_path=None,
):
    """Genera un ticket con el formato especial de la Farmacia Nicolás."""

    if datos_negocio is None:
        datos_negocio = {}
        if os.path.exists(DATOS_NEGOCIO_PATH):
            try:
                with open(DATOS_NEGOCIO_PATH, "r", encoding="utf-8") as f:
                    datos_negocio = json.load(f)
            except Exception:
                datos_negocio = {}

    width = 80 * mm
    line_height = 4 * mm
    base_height = 60 * mm
    height = base_height + len(detalles) * 6 * mm + 40 * mm
    page_size = (width, height)

    c = canvas.Canvas(archivo, pagesize=page_size)
    y = height - 10 * mm

    # Opcional: logo centrado arriba
    if logo_path and os.path.exists(logo_path):
        logo_w = 20 * mm
        c.drawImage(
            logo_path,
            (width - logo_w) / 2,
            y - 20 * mm,
            width=logo_w,
            preserveAspectRatio=True,
        )
        y -= 22 * mm

    c.setFont("Helvetica-Bold", 9)
    c.drawCentredString(width / 2, y, datos_negocio.get("nombre_comercial", ""))
    y -= 5 * mm
    c.setFont("Helvetica", 8)
    giro = datos_negocio.get("giro")
    if giro:
        c.drawCentredString(width / 2, y, giro)
        y -= 4 * mm
    direccion = datos_negocio.get("direccion")
    if direccion:
        c.drawCentredString(width / 2, y, direccion)
        y -= 4 * mm

    c.drawCentredString(width / 2, y, f"Fecha: {venta.get('fecha', '')}")
    y -= 5 * mm
    c.line(5 * mm, y, width - 5 * mm, y)
    y -= 4 * mm

    c.setFont("Helvetica-Bold", 7)
    c.drawString(5 * mm, y, "DETALLE")
    c.drawRightString(width - 5 * mm, y, "TOTAL")
    y -= 3 * mm
    c.line(5 * mm, y, width - 5 * mm, y)
    y -= 4 * mm

    c.setFont("Helvetica", 7)
    for d in detalles:
        desc = d.get("descripcion", "")
        qty = d.get("cantidad", 0)
        pu = d.get("precio_unitario", 0)
        total = qty * pu
        c.drawString(5 * mm, y, f"{desc} x{qty}")
        c.drawRightString(width - 5 * mm, y, f"{total:.2f}")
        y -= 4 * mm

    c.line(5 * mm, y, width - 5 * mm, y)
    y -= 5 * mm
    c.setFont("Helvetica-Bold", 9)
    c.drawRightString(width - 5 * mm, y, f"Total: {venta.get('total', 0):.2f}")

    c.showPage()
    c.save()
