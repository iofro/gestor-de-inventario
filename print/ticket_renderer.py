"""Utilities to render DTE tickets as thermal PDFs.

This module exposes :func:`render_ticket_pdf` which takes a DTE payload and
returns the resulting PDF as ``bytes``.  The goal is to produce a clean ticket
layout without leaking internal structures from the JSON payload.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from io import BytesIO
from typing import Any, Dict

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from factura_sv import build_qr_url

# ---------------------------------------------------------------------------
# Formatting helpers used inside the renderer


def _to_decimal(value: Any) -> Decimal:
    """Return ``value`` as :class:`~decimal.Decimal`.

    ``value`` can be an int, float, Decimal or string.  Missing values are
    treated as ``Decimal('0')``.  This helper makes the rest of the code more
    robust when dealing with different numeric types coming from JSON.
    """

    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


def money(value: Any) -> str:
    """Format ``value`` as a monetary string with two decimals."""

    q = Decimal("0.01")
    return f"{_to_decimal(value).quantize(q, rounding=ROUND_HALF_UP):,.2f}"


def q(value: Any) -> str:
    """Format a quantity removing trailing zeros."""

    d = _to_decimal(value)
    s = f"{d.normalize():f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


PAGO_LABELS = {
    "01": "Efectivo",
    "02": "Cheque",
    "03": "Tarjeta",
    "04": "Transferencia",
    "05": "Depósito",
    "99": "Otro",
}


# ---------------------------------------------------------------------------
# Public API


def render_ticket_pdf(payload: Dict[str, Any], accepted: bool) -> bytes:
    """Render ``payload`` into a thermal ticket PDF.

    Parameters
    ----------
    payload:
        Mapping with DTE information.  It is assumed to already contain all
        fiscal data; this function only performs presentation tweaks.
    accepted:
        ``True`` when the DTE has been accepted by the Ministry of Finance.

    Returns
    -------
    bytes
        The generated PDF contents.
    """

    ident = payload.get("identificacion", {})
    emisor = payload.get("emisor", {})
    resumen = payload.get("resumen", {})
    items = payload.get("cuerpoDocumento", []) or []

    # Prepare table lines for items ------------------------------------------------
    item_lines = []
    for it in items:
        descripcion = str(it.get("descripcion", ""))
        cantidad = q(it.get("cantidad", 0))
        precio = money(it.get("precioUni", 0))
        line_total = (
            it.get("montoTotal")
            or it.get("ventaGravada")
            or it.get("ventaExenta")
            or it.get("ventaNoSuj")
            or 0
        )
        item_lines.append(
            {
                "left": f"{descripcion} x{cantidad} @ {precio}",
                "right": money(line_total),
            }
        )

    # Totals ----------------------------------------------------------------------
    sub_total = resumen.get("subTotal")
    total_iva = resumen.get("totalIva")
    total_pagar = resumen.get("montoTotalOperacion")

    total_lines = []
    if sub_total and _to_decimal(sub_total) != _to_decimal(total_pagar):
        total_lines.append(("SubTotal", money(sub_total)))
    if total_iva and _to_decimal(total_iva) > 0:
        total_lines.append(("IVA (13%)", money(total_iva)))
    total_lines.append(("TOTAL", money(total_pagar)))

    # Pagos -----------------------------------------------------------------------
    pagos = resumen.get("pagos") or []
    pago_line = None
    if pagos:
        p = pagos[0]
        label = PAGO_LABELS.get(str(p.get("codigo")).zfill(2), "Otro")
        monto = money(p.get("montoPago", 0))
        pago_line = f"Pago: {label} {monto}"

    # Consulta pública URL --------------------------------------------------------
    url_consulta = None
    if accepted and ident.get("codigoGeneracion") and ident.get("fecEmi"):
        try:
            url_consulta = build_qr_url(payload)
        except Exception:
            url_consulta = None

    # ------------------------------------------------------------------ Build PDF
    buffer = BytesIO()
    width = 80 * mm
    margin = 5 * mm
    line_height = 4 * mm

    # Count lines to calculate page height
    lines_count = 0
    # encabezado
    lines_count += 2
    # emisor block
    lines_count += 4
    # identificacion block
    lines_count += 1  # fecha/hora
    if accepted and ident.get("numeroControl"):
        lines_count += 1
    if accepted and ident.get("codigoGeneracion"):
        lines_count += 1
    # items
    lines_count += len(item_lines)
    # totals
    lines_count += len(total_lines)
    # pago line
    if pago_line:
        lines_count += 1
    # consulta pública block
    if url_consulta:
        lines_count += 2  # label + url
    # footer line
    lines_count += 1

    # Each hr consumes small space (we have 5 separators)
    hr_count = 5
    if not pago_line:
        hr_count -= 1
    if not url_consulta:
        hr_count -= 1

    qr_extra = 25 * mm if url_consulta else 0
    height = margin * 2 + line_height * lines_count + hr_count * 2 + qr_extra

    c = canvas.Canvas(buffer, pagesize=(width, height))
    y = height - margin

    def draw_center(text: str, size: int = 10, bold: bool = False, muted: bool = False):
        nonlocal y
        font = "Helvetica-Bold" if bold else "Helvetica"
        c.setFont(font, size)
        if muted:
            c.setFillGray(0.3)
        else:
            c.setFillGray(0)
        c.drawCentredString(width / 2, y, text)
        y -= line_height

    def draw_left_right(left: str, right: str, bold_left: bool = False, bold_right: bool = False):
        nonlocal y
        font_left = "Helvetica-Bold" if bold_left else "Helvetica"
        font_right = "Helvetica-Bold" if bold_right else "Helvetica"
        c.setFont(font_left, 10)
        c.drawString(margin, y, left)
        c.setFont(font_right, 10)
        c.drawRightString(width - margin, y, right)
        y -= line_height

    def draw_hr():
        nonlocal y
        y -= 1
        c.setLineWidth(0.5)
        c.line(margin, y, width - margin, y)
        y -= 1

    # Header ---------------------------------------------------------------------
    draw_center("DOCUMENTO TRIBUTARIO ELECTRÓNICO", size=11, bold=True)
    draw_center("FACTURA (Ticket)", size=11, bold=True)
    draw_hr()

    # Emisor block ---------------------------------------------------------------
    draw_center(str(emisor.get("nombreComercial", "")), size=11, bold=True)
    nit = emisor.get("nit", "")
    nrc = emisor.get("nrc", "")
    draw_center(f"NIT: {nit}   NRC: {nrc}", muted=True)
    giro = emisor.get("descActividad", "")
    draw_center(f"Actividad: {giro}", muted=True)
    direccion = emisor.get("direccion", {}).get("complemento", "")
    draw_center(f"Dir: {direccion}", muted=True)
    draw_hr()

    # Identification block -------------------------------------------------------
    draw_left_right("Fecha/Hora:", f"{ident.get('fecEmi', '')} {ident.get('horEmi', '')}")
    if accepted and ident.get("numeroControl"):
        draw_left_right("No. Control:", str(ident.get("numeroControl")))
    if accepted and ident.get("codigoGeneracion"):
        draw_left_right("Código Gen.:", str(ident.get("codigoGeneracion")))
    draw_hr()

    # Items ----------------------------------------------------------------------
    for line in item_lines:
        draw_left_right(line["left"], line["right"])
    draw_hr()

    # Totals ---------------------------------------------------------------------
    for idx, (label, value) in enumerate(total_lines):
        bold = label == "TOTAL"
        draw_left_right(label, value, bold_left=bold, bold_right=bold)

    # Pagos ----------------------------------------------------------------------
    if pago_line:
        draw_hr()
        draw_left_right(pago_line, "")

    # Consulta pública -----------------------------------------------------------
    if url_consulta:
        draw_hr()
        draw_center("Consulta pública", muted=True)
        draw_center(url_consulta)
        # Insert QR ---------------------------------------------------------------
        qr_size = 20 * mm
        qr_code = qr.QrCodeWidget(url_consulta)
        bounds = qr_code.getBounds()
        w = bounds[2] - bounds[0]
        h = bounds[3] - bounds[1]
        d = Drawing(qr_size, qr_size, transform=[qr_size / w, 0, 0, qr_size / h, 0, 0])
        d.add(qr_code)
        qr_x = (width - qr_size) / 2
        qr_y = y - qr_size - 2
        renderPDF.draw(d, c, qr_x, qr_y)
        y = qr_y - 2

    draw_hr()
    draw_center("¡Gracias por su compra!", muted=True)

    c.showPage()
    c.save()
    return buffer.getvalue()
