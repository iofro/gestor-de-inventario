from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from io import BytesIO
from typing import Any, Iterable, Mapping

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
import json
import os

from utils.catalogos import DTE_TIPOS, FORMA_PAGO

from paths import DATOS_NEGOCIO_PATH
from factura_sv import build_qr_url


def _to_decimal(value: Any) -> Decimal:
    """Return *value* converted to :class:`~decimal.Decimal`."""

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

    quantize = Decimal("0.01")
    return f"{_to_decimal(value).quantize(quantize, rounding=ROUND_HALF_UP):,.2f}"


def q(value: Any) -> str:
    """Format a quantity removing trailing zeros."""

    dec = _to_decimal(value)
    normalized = f"{dec.normalize():f}"
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return normalized


def document_title_label(ident: Mapping[str, Any] | None) -> str:
    """Return a label describing the DTE document type."""

    tipo_dte = ""
    if ident and isinstance(ident, Mapping):
        tipo_dte = str(ident.get("tipoDte") or "").zfill(2)

    if tipo_dte == "01":
        return "CONSUMIDOR FINAL"
    if tipo_dte == "03":
        return "CRÉDITO FISCAL"

    label = DTE_TIPOS.get(tipo_dte)
    if label:
        return label.upper()
    return "FACTURA"


PAGO_LABELS = {code.zfill(2): value.upper() for code, value in FORMA_PAGO.items()}
PAGO_LABELS["01"] = "EFECTIVO"


def _calculate_item_total(entry: Mapping[str, Any]) -> Decimal:
    """Return the total amount for an item entry."""

    for key in (
        "montoTotal",
        "montoTotalOperacion",
        "ventaGravada",
        "ventaExenta",
        "ventaNoSuj",
        "subTotal",
        "ventas_gravadas",
    ):
        if entry.get(key) is not None:
            value = _to_decimal(entry.get(key))
            if value != 0:
                return value

    qty = _to_decimal(
        entry.get("cantidad")
        or entry.get("cantidadUniMedida")
        or entry.get("uniCantidad")
        or 0
    )
    unit = _to_decimal(
        entry.get("precio_unitario")
        or entry.get("precioUnitario")
        or entry.get("precioUnit")
        or entry.get("precioUni")
        or entry.get("precio")
        or 0
    )
    return (qty * unit).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def render_ticket_pdf(
    payload: Mapping[str, Any],
    accepted: bool,
    sello: str | None = None,
) -> bytes:
    """Render a ticket PDF directly using ReportLab.

    The implementation keeps a compact thermal layout while avoiding
    additional HTML rendering engines or native dependencies.
    """

    buffer = BytesIO()
    width = 58 * mm
    height = 280 * mm
    margin = 4 * mm
    line_height = 5 * mm
    c = canvas.Canvas(buffer, pagesize=(width, height))
    y = height - margin

    def ensure_space(lines: int = 1, extra: float = 0.0) -> None:
        nonlocal y
        required = lines * line_height + extra + margin
        if y - required < margin:
            c.showPage()
            y = height - margin

    def draw_center(text: str, size: int = 9, bold: bool = False) -> None:
        nonlocal y
        ensure_space()
        font = "Helvetica-Bold" if bold else "Helvetica"
        c.setFont(font, size)
        c.drawCentredString(width / 2, y, text)
        y -= line_height

    def draw_left(text: str, size: int = 8, bold: bool = False) -> None:
        nonlocal y
        ensure_space()
        font = "Helvetica-Bold" if bold else "Helvetica"
        c.setFont(font, size)
        c.drawString(margin, y, text)
        y -= line_height

    def draw_left_right(left: str, right: str, size: int = 8, bold: bool = False) -> None:
        nonlocal y
        ensure_space()
        font = "Helvetica-Bold" if bold else "Helvetica"
        c.setFont(font, size)
        c.drawString(margin, y, left)
        c.drawRightString(width - margin, y, right)
        y -= line_height

    def draw_rule() -> None:
        nonlocal y
        ensure_space(extra=1)
        y -= 1
        c.setLineWidth(0.4)
        c.line(margin, y, width - margin, y)
        y -= 1

    ident = payload.get("identificacion", {}) or {}
    emisor = payload.get("emisor", {}) or {}
    receptor = payload.get("receptor", {}) or {}
    items: Iterable[Mapping[str, Any]] = payload.get("cuerpoDocumento") or []
    resumen = payload.get("resumen", {}) or {}
    pagos = resumen.get("pagos") or []

    draw_center("DOCUMENTO TRIBUTARIO", size=10, bold=True)
    draw_center("ELECTRÓNICO —", size=10, bold=True)
    draw_center(document_title_label(ident), size=10, bold=True)
    draw_rule()

    nombre_emisor = (
        emisor.get("nombreComercial")
        or emisor.get("nombre")
        or emisor.get("razonSocial")
        or ""
    )
    if nombre_emisor:
        draw_center(nombre_emisor.strip(), size=9, bold=True)
    nit = str(emisor.get("nit") or "").strip()
    nrc = str(emisor.get("nrc") or "").strip()
    if nit or nrc:
        draw_center(f"NIT: {nit or '—'}   NRC: {nrc or '—'}", size=8)
    giro = str(emisor.get("descActividad") or emisor.get("actividad") or "").strip()
    if giro:
        draw_center(f"Actividad: {giro}", size=7)
    direccion = emisor.get("direccion", {}) or {}
    direccion_txt = str(direccion.get("complemento") or direccion.get("direccion") or "").strip()
    if direccion_txt:
        draw_center(direccion_txt, size=7)
    draw_rule()

    fecha = ident.get("fecEmi") or payload.get("fecha") or ""
    hora = ident.get("horEmi") or ""
    fecha_hora = " ".join(v for v in (str(fecha).strip(), str(hora).strip()) if v)
    if fecha_hora:
        draw_left(f"Fecha: {fecha_hora}", bold=True)
    numero_control = ident.get("numeroControl")
    if numero_control:
        draw_left(f"Número de control: {numero_control}")
    codigo_generacion = ident.get("codigoGeneracion")
    if codigo_generacion:
        draw_left(f"Código de generación: {codigo_generacion}")

    receptor_nombre = (
        receptor.get("nombre")
        or receptor.get("razonSocial")
        or receptor.get("denominacionSocial")
        or ""
    )
    if receptor_nombre:
        draw_left(f"Cliente: {receptor_nombre}")
    doc = (
        receptor.get("numDocumento")
        or receptor.get("numeroDocumento")
        or receptor.get("nit")
        or receptor.get("dui")
        or ""
    )
    if doc:
        draw_left(f"Documento: {doc}")
    draw_rule()

    draw_left("DETALLE DE FACTURA", bold=True)
    for entry in items:
        descripcion = (
            entry.get("descripcion")
            or entry.get("nombre")
            or entry.get("detalle")
            or ""
        )
        descripcion = str(descripcion).strip() or "—"
        qty = q(
            entry.get("cantidad")
            or entry.get("cantidadUniMedida")
            or entry.get("uniCantidad")
            or 0
        )
        unit = money(
            entry.get("precio_unitario")
            or entry.get("precioUnitario")
            or entry.get("precioUnit")
            or entry.get("precioUni")
            or entry.get("precio")
            or 0
        )
        total_line = money(_calculate_item_total(entry))

        draw_left(descripcion)
        draw_left_right(f"  {qty} x {unit}", total_line)

    draw_rule()

    subtotal = _to_decimal(
        resumen.get("subTotal")
        or resumen.get("totalGravada")
        or resumen.get("totalGravadaConIva")
        or 0
    )
    if subtotal == 0:
        subtotal = sum((_calculate_item_total(entry) for entry in items), Decimal("0"))

    total = _to_decimal(
        resumen.get("montoTotalOperacion")
        or resumen.get("totalPagar")
        or resumen.get("totalCompra")
        or 0
    )
    if total == 0:
        total = subtotal

    iva = _to_decimal(resumen.get("totalIva") or resumen.get("iva") or (total - subtotal))

    draw_left_right("Sub-total", money(subtotal))
    draw_left_right("IVA", money(iva))
    draw_left_right("Total a pagar", money(total), bold=True)

    forma_pago = None
    monto_pago = total
    if pagos:
        pago = pagos[0]
        codigo = str(pago.get("codigo") or "").zfill(2)
        forma_pago = PAGO_LABELS.get(codigo, "OTRO")
        monto_pago = _to_decimal(pago.get("montoPago") or monto_pago)

    if forma_pago or resumen.get("condicionOperacion"):
        draw_rule()
        draw_left("FORMA DE PAGO", bold=True)
        if forma_pago:
            draw_left_right(forma_pago, money(monto_pago))
        condicion = resumen.get("condicionOperacion")
        if condicion is not None:
            draw_left(str(condicion).upper())

    if accepted and sello:
        draw_rule()
        draw_left(f"Sello de Recepción: {sello}")
    elif not accepted:
        draw_rule()
        draw_left("Documento en proceso de validación")

    qr_url = None
    if accepted:
        try:
            qr_url = build_qr_url(payload)
        except Exception:
            qr_url = None

    if qr_url:
        ensure_space(extra=35)
        qr_size = 30 * mm
        qr_code = qr.QrCodeWidget(qr_url)
        bounds = qr_code.getBounds()
        w = bounds[2] - bounds[0]
        h = bounds[3] - bounds[1]
        drawing = Drawing(
            qr_size,
            qr_size,
            transform=[qr_size / w, 0, 0, qr_size / h, 0, 0],
        )
        drawing.add(qr_code)
        qr_x = (width - qr_size) / 2
        qr_y = y - qr_size - 5
        renderPDF.draw(drawing, c, qr_x, qr_y)
        c.linkURL(qr_url, (qr_x, qr_y, qr_x + qr_size, qr_y + qr_size), relative=0)
        y = qr_y - line_height

    c.save()
    return buffer.getvalue()


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

    if qr_url:
        qr_size = 20 * mm
        qr_code = qr.QrCodeWidget(qr_url)
        bounds = qr_code.getBounds()
        w = bounds[2] - bounds[0]
        h = bounds[3] - bounds[1]
        d = Drawing(qr_size, qr_size, transform=[qr_size / w, 0, 0, qr_size / h, 0, 0])
        d.add(qr_code)
        if y < qr_size + 60:
            c.showPage()
            y = height - 40
        qr_x = (width - qr_size) / 2
        qr_y = y - qr_size - 20
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
    titulo = document_title_label(ident)
    draw_center(
        f"DOCUMENTO TRIBUTARIO ELECTRÓNICO — {titulo}",
        size=14,
        bold=True,
    )
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
