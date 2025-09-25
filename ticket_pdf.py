from __future__ import annotations

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing
from reportlab.graphics import renderPDF
import json
import os

from print.ticket_renderer import PAGO_LABELS, money, q, render_ticket_pdf

from paths import DATOS_NEGOCIO_PATH
from factura_sv import build_qr_url


def _with_falta(value):
    """Return ``"falta"`` when *value* is falsy."""
    return "falta" if not value else str(value)


def generar_ticket_pdf(
    venta,
    detalles,
    archivo="ticket.pdf",
    datos_negocio=None,
    dte_data=None,
):
    """Genera un PDF sencillo tipo ticket para una venta.

    Si ``dte_data`` contiene información de DTE (por ejemplo ``dteJson``), se
    calcula automáticamente la URL del código QR con :func:`build_qr_url` y se
    inserta como código y enlace en el PDF generado.
    """

    if datos_negocio is None:
        datos_negocio = {}
        if os.path.exists(DATOS_NEGOCIO_PATH):
            try:
                with open(DATOS_NEGOCIO_PATH, "r", encoding="utf-8") as f:
                    datos_negocio = json.load(f)
            except Exception:
                datos_negocio = {}

    qr_url = None
    if dte_data:
        dte_json = dte_data.get("dteJson", dte_data)
        qr_url = build_qr_url(dte_json)

    page_width = 58 * mm
    margin = 5 * mm
    content_width = page_width - 2 * margin
    header_size = 14
    body_size = 11
    leading = body_size + 4

    def _wrap_text(text: str) -> list[str]:
        lines: list[str] = []
        for paragraph in str(text or "").splitlines():
            paragraph = paragraph.strip()
            if not paragraph:
                continue
            words = paragraph.split()
            current = ""
            for word in words:
                candidate = f"{current} {word}".strip()
                if not candidate:
                    continue
                if (
                    current
                    and pdfmetrics.stringWidth(candidate, "Helvetica", body_size)
                    > content_width
                ):
                    lines.append(current)
                    current = word
                else:
                    current = candidate
            if current:
                lines.append(current)
        if not lines:
            lines.append("")
        return lines

    line_count = 4  # fecha, título de detalle y separadores básicos
    line_count += sum(len(_wrap_text(d.get("descripcion", ""))) + 1 for d in detalles)
    line_count += 2  # total y espacio adicional
    if qr_url:
        line_count += int((30 * mm) / leading) + 2

    height = margin * 2 + header_size + line_count * leading
    c = canvas.Canvas(archivo, pagesize=(page_width, height))
    y = height - margin

    c.setFont("Helvetica-Bold", header_size)
    c.drawCentredString(
        page_width / 2, y, datos_negocio.get("nombreComercial", "TICKET")
    )
    y -= header_size + 6
    c.setFont("Helvetica", body_size)
    c.drawString(margin, y, f"Fecha: {venta.get('fecha', '')}")
    y -= leading
    c.setFont("Helvetica-Bold", body_size)
    c.drawString(margin, y, "Detalles:")
    y -= leading

    for d in detalles:
        desc = d.get("descripcion", "")
        qty = d.get("cantidad", 0)
        pu = d.get("precio_unitario", 0)
        total = qty * pu
        desc_lines = _wrap_text(desc)
        c.setFont("Helvetica", body_size)
        for line in desc_lines:
            c.drawString(margin, y, line)
            y -= leading
        c.setFont("Helvetica", body_size)
        c.drawString(margin, y, f"x{qty} @ {pu:.2f}")
        c.setFont("Helvetica-Bold", body_size)
        c.drawRightString(page_width - margin, y, f"{total:.2f}")
        y -= leading

    y -= leading / 2
    c.setFont("Helvetica-Bold", body_size)
    c.drawRightString(page_width - margin, y, f"Total: {venta.get('total', 0):.2f}")
    y -= leading

    if qr_url:
        qr_size = min(30 * mm, content_width)
        qr_code = qr.QrCodeWidget(qr_url)
        bounds = qr_code.getBounds()
        w = bounds[2] - bounds[0]
        h = bounds[3] - bounds[1]
        d = Drawing(
            qr_size,
            qr_size,
            transform=[qr_size / w, 0, 0, qr_size / h, 0, 0],
        )
        d.add(qr_code)
        qr_x = (page_width - qr_size) / 2
        qr_y = max(margin, y - qr_size)
        renderPDF.draw(d, c, qr_x, qr_y)
        c.linkURL(qr_url, (qr_x, qr_y, qr_x + qr_size, qr_y + qr_size), relative=0)

    c.showPage()
    c.save()


def generar_ticket_fe_pdf(
    venta,
    detalles,
    archivo="ticket_fe.pdf",
    datos_negocio=None,
    dte_data=None,
):
    """Genera un ticket de Factura Electrónica utilizando ``render_ticket_pdf``.

    ``dte_data`` debe contener al menos la clave ``dteJson`` con el payload
    del DTE.  Cuando ``selloRecibido`` está presente se considera que el DTE fue
    aceptado y se mostrará la URL de consulta pública.
    """

    if dte_data is None:
        dte_data = {}

    payload = dte_data.get("dteJson", {})
    accepted = bool(dte_data.get("selloRecibido"))
    pdf_bytes = render_ticket_pdf(payload, accepted, sello=dte_data.get("selloRecibido"))

    with open(archivo, "wb") as fh:
        fh.write(pdf_bytes)


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

    if dte_data is None:
        dte_data = {}

    sello = dte_data.get("selloRecibido")
    firma = dte_data.get("firmaElectronica")
    dte_json = dte_data.get("dteJson", {})
    qr_url = build_qr_url(dte_json) if dte_json else None
    ident = dte_json.get("identificacion", {})
    receptor = dte_json.get("receptor", {})

    width, height = letter
    margin = 15 * mm
    line_height = 5 * mm

    c = canvas.Canvas(archivo, pagesize=letter)
    y = height - margin

    # Logo opcional centrado en la parte superior
    if logo_path and os.path.exists(logo_path):
        logo_w = 30 * mm
        c.drawImage(
            logo_path,
            (width - logo_w) / 2,
            y - logo_w,
            width=logo_w,
            preserveAspectRatio=True,
        )
        y -= logo_w + line_height

    def draw_center(text: str, size: int = 10, bold: bool = False):
        nonlocal y
        font = "Helvetica-Bold" if bold else "Helvetica"
        c.setFont(font, size)
        c.drawCentredString(width / 2, y, text)
        y -= line_height

    def draw_left_right(left: str, right: str, size: int = 10, bold_left: bool = False, bold_right: bool = False):
        nonlocal y
        font_left = "Helvetica-Bold" if bold_left else "Helvetica"
        font_right = "Helvetica-Bold" if bold_right else "Helvetica"
        c.setFont(font_left, size)
        c.drawString(margin, y, left)
        c.setFont(font_right, size)
        c.drawRightString(width - margin, y, right)
        y -= line_height

    def draw_hr():
        nonlocal y
        y -= 1
        c.setLineWidth(0.5)
        c.line(margin, y, width - margin, y)
        y -= 1

    # Encabezado ---------------------------------------------------------------
    draw_center("DOCUMENTO TRIBUTARIO ELECTRÓNICO — FACTURA", size=14, bold=True)
    draw_hr()

    # Datos del emisor --------------------------------------------------------
    draw_center(_with_falta(datos_negocio.get("nombreComercial")), size=12, bold=True)
    nit = datos_negocio.get("nit")
    nrc = datos_negocio.get("nrc")
    draw_center(f"NIT: {_with_falta(nit)}   NRC: {_with_falta(nrc)}", size=10)
    giro = datos_negocio.get("descActividad")
    draw_center(f"Actividad: {_with_falta(giro)}", size=9)
    direccion = datos_negocio.get("direccion", {}).get("complemento")
    draw_center(f"Dirección: {_with_falta(direccion)}", size=9)
    draw_hr()

    # Datos de factura y receptor ---------------------------------------------
    fecha = venta.get("fecha") or ident.get("fecEmi", "")
    draw_left_right("Fecha:", _with_falta(fecha))
    draw_left_right("No. Control:", _with_falta(ident.get("numeroControl")))
    draw_left_right("Código Gen.:", _with_falta(ident.get("codigoGeneracion")))
    draw_left_right("Cliente:", _with_falta(receptor.get("nombre")))
    doc = receptor.get("nit") or receptor.get("dui") or receptor.get("numDocumento")
    draw_left_right("Documento:", _with_falta(doc))
    draw_hr()

    # Tabla de ítems ---------------------------------------------------------
    c.setFont("Helvetica-Bold", 10)
    x_qty = margin
    x_desc = margin + 25 * mm
    x_unit = width - margin - 40 * mm
    x_total = width - margin
    c.drawString(x_qty, y, "Cant.")
    c.drawString(x_desc, y, "Descripción")
    c.drawRightString(x_unit, y, "P. Unit.")
    c.drawRightString(x_total, y, "Total")
    y -= line_height
    draw_hr()

    c.setFont("Helvetica", 10)
    for d in detalles:
        qty = q(d.get("cantidad", 0))
        desc = _with_falta(d.get("descripcion"))
        pu = money(d.get("precio_unitario", 0))
        line_total = (
            d.get("monto_total")
            or d.get("venta_gravada")
            or d.get("ventas_gravadas")
            or d.get("cantidad", 0) * d.get("precio_unitario", 0)
        )
        c.drawString(x_qty, y, qty)
        c.drawString(x_desc, y, desc)
        c.drawRightString(x_unit, y, pu)
        c.drawRightString(x_total, y, money(line_total))
        y -= line_height

    draw_hr()

    # Totales -----------------------------------------------------------------
    sub_total = sum(
        d.get("monto_total")
        or d.get("venta_gravada")
        or d.get("ventas_gravadas")
        or d.get("cantidad", 0) * d.get("precio_unitario", 0)
        for d in detalles
    )
    total = venta.get("total", sub_total)
    iva = venta.get("iva")
    if iva is None:
        iva = max(total - sub_total, 0)
    draw_left_right("Sub-total", money(sub_total))
    draw_left_right("IVA", money(iva))
    draw_left_right("Total a pagar", money(total), bold_left=True, bold_right=True)

    # Formas de pago ----------------------------------------------------------
    forma_pago = venta.get("forma_pago")
    pago_monto = money(total)
    pagos = dte_json.get("resumen", {}).get("pagos") or []
    if not forma_pago and pagos:
        p = pagos[0]
        code = str(p.get("codigo")).zfill(2)
        forma_pago = PAGO_LABELS.get(code, "Otro")
        pago_monto = money(p.get("montoPago", total))
    if forma_pago:
        draw_hr()
        draw_left_right(f"Pago: {forma_pago}", pago_monto)

    # Información fiscal ------------------------------------------------------
    if sello:
        draw_hr()
        draw_center(f"Sello recibido: {_with_falta(sello)}", size=8)
    if firma:
        draw_center(f"Firma electrónica: {_with_falta(firma)}", size=8)

    # Código QR ---------------------------------------------------------------
    if qr_url:
        qr_size = 30 * mm
        qr_code = qr.QrCodeWidget(qr_url)
        bounds = qr_code.getBounds()
        w = bounds[2] - bounds[0]
        h = bounds[3] - bounds[1]
        d = Drawing(qr_size, qr_size, transform=[qr_size / w, 0, 0, qr_size / h, 0, 0])
        d.add(qr_code)
        qr_x = (width - qr_size) / 2
        qr_y = margin
        renderPDF.draw(d, c, qr_x, qr_y)
        c.linkURL(qr_url, (qr_x, qr_y, qr_x + qr_size, qr_y + qr_size), relative=0)

    c.showPage()
    c.save()
