from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from datetime import datetime
import json
import os
from paths import DATOS_NEGOCIO_PATH


def _with_falta(value):
    """Return ``"falta"`` when *value* is falsy."""
    return "falta" if not value else str(value)


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
    c.drawCentredString(width / 2, y, datos_negocio.get("nombreComercial", "TICKET"))
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


def generar_ticket_personalizado(
    venta,
    detalles,
    archivo="ticket_nicolas.pdf",
    datos_negocio=None,
    logo_path=None,
    dte_data=None,
):
    """Genera un ticket con un formato personalizado.

    Parameters
    ----------
    venta : dict
        Datos de la venta.
    detalles : list[dict]
        Lineas de la venta.
    archivo : str, optional
        Ruta del PDF de salida.
    datos_negocio : dict, optional
        Datos de encabezado del negocio.
    logo_path : str, optional
        Ruta opcional a un logo para mostrar en la cabecera.
    dte_data : dict, optional
        Diccionario con información del DTE. Puede contener las claves
        ``selloRecibido``, ``firmaElectronica`` y ``dteJson``.
    """

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

    if dte_data is None:
        dte_data = {}

    sello = dte_data.get("selloRecibido", "falta")
    firma = dte_data.get("firmaElectronica", "falta")

    def _flatten(data, prefix=""):
        lines = []
        if isinstance(data, dict):
            for k, v in data.items():
                key = f"{prefix}{k}"
                if isinstance(v, dict):
                    lines.extend(_flatten(v, key + "."))
                else:
                    lines.append(f"{key}: {v}")
        return lines

    dte_lines = _flatten(dte_data.get("dteJson", {}))
    extra_count = 2 + len(dte_lines)

    height = base_height + len(detalles) * 6 * mm + extra_count * line_height + 40 * mm
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

    # Encabezado con datos de DTE
    c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(width / 2, y, "DOCUMENTO TRIBUTARIO ELECTRÓNICO")
    y -= 4 * mm
    c.drawCentredString(width / 2, y, "FACTURA")
    y -= 5 * mm
    c.setFont("Helvetica", 7)
    c.drawCentredString(width / 2, y, "------------------- DATOS DEL EMISOR ------------------")
    y -= 4 * mm
    c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(width / 2, y, _with_falta(datos_negocio.get("nombreComercial")))
    y -= 4 * mm
    nit = datos_negocio.get("nit")
    c.setFont("Helvetica", 7)
    c.drawCentredString(width / 2, y, f"NIT: {_with_falta(nit)}")
    y -= 4 * mm
    nrc = datos_negocio.get("nrc")
    c.drawCentredString(width / 2, y, f"NRC: {_with_falta(nrc)}")
    y -= 4 * mm
    giro = datos_negocio.get("descActividad")
    c.drawCentredString(width / 2, y, f"Actividad Económica: {_with_falta(giro)}")
    y -= 4 * mm
    direccion = datos_negocio.get("direccion", {}).get("complemento")
    c.drawCentredString(width / 2, y, f"Dirección: {_with_falta(direccion)}")
    y -= 5 * mm
    c.setFont("Helvetica-Bold", 7)
    c.drawCentredString(width / 2, y, "DATOS DE FACTURA")
    y -= 4 * mm
    c.setFont("Helvetica", 7)
    c.drawCentredString(width / 2, y, "Código de Generación:")
    y -= 3 * mm
    c.drawCentredString(width / 2, y, "Número de control:")
    y -= 4 * mm
    c.drawCentredString(width / 2, y, "Tipo Modelo: 1")
    y -= 3 * mm
    c.drawCentredString(width / 2, y, "Tipo Operación: 1")
    y -= 3 * mm
    c.drawCentredString(width / 2, y, f"Fecha y hora de Generación: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
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
        desc = _with_falta(d.get("descripcion"))
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

    y -= 6 * mm
    c.setFont("Helvetica", 6)
    c.drawString(5 * mm, y, f"Sello recibido: {_with_falta(sello)}")
    y -= line_height
    c.drawString(5 * mm, y, f"Firma electr\xf3nica: {_with_falta(firma)}")
    y -= line_height
    for line in dte_lines:
        c.drawString(5 * mm, y, _with_falta(line))
        y -= line_height

    c.showPage()
    c.save()
