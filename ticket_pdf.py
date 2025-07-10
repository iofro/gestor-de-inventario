from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
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
