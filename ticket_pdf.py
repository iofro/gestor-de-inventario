from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from io import BytesIO
from typing import Any, Iterable, Mapping

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfgen import canvas
from reportlab.platypus import Flowable, Image, Paragraph, Spacer, Table, TableStyle
from xml.sax.saxutils import escape
import json
import os

from utils.catalogos import DTE_TIPOS, FORMA_PAGO

from paths import DATOS_NEGOCIO_PATH
from factura_sv import build_qr_url


PT_PER_MM = 72 / 25.4


def mm(value: float) -> float:
    return value * PT_PER_MM


TICKET_WIDTH_MM = 58
MARGINS = {
    "left": mm(3),
    "right": mm(3),
    "top": mm(3),
    "bottom": mm(10),
}
TICKET_WIDTH_PT = mm(TICKET_WIDTH_MM)
CONTENT_WIDTH_PT = TICKET_WIDTH_PT - (MARGINS["left"] + MARGINS["right"])
MIN_PAGE_HEIGHT_PT = mm(180)
BLOCK_SPACING = mm(2.5)
QR_MAX_SIZE = mm(48)

TICKET_STYLES = {
    "doc_label": ParagraphStyle(
        "DocLabel",
        fontName="Helvetica-Bold",
        fontSize=16,
        leading=20,
        alignment=TA_CENTER,
    ),
    "business_name": ParagraphStyle(
        "BusinessName",
        fontName="Helvetica-Bold",
        fontSize=14,
        leading=17,
        alignment=TA_CENTER,
    ),
    "center_text": ParagraphStyle(
        "CenterText",
        fontName="Helvetica",
        fontSize=11,
        leading=14,
        alignment=TA_CENTER,
    ),
    "section_header": ParagraphStyle(
        "SectionHeader",
        fontName="Helvetica-Bold",
        fontSize=14,
        leading=17,
        alignment=TA_LEFT,
    ),
    "kv_label": ParagraphStyle(
        "KVLabel",
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=14,
        alignment=TA_LEFT,
    ),
    "kv_value": ParagraphStyle(
        "KVValue",
        fontName="Helvetica",
        fontSize=11,
        leading=14,
        alignment=TA_RIGHT,
    ),
    "table_header": ParagraphStyle(
        "TableHeader",
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=15,
        alignment=TA_LEFT,
    ),
    "table_header_right": ParagraphStyle(
        "TableHeaderRight",
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=15,
        alignment=TA_RIGHT,
    ),
    "table_cell": ParagraphStyle(
        "TableCell",
        fontName="Helvetica",
        fontSize=11,
        leading=14,
        alignment=TA_LEFT,
    ),
    "table_cell_right": ParagraphStyle(
        "TableCellRight",
        fontName="Helvetica",
        fontSize=11,
        leading=14,
        alignment=TA_RIGHT,
    ),
    "table_desc": ParagraphStyle(
        "TableDesc",
        fontName="Helvetica",
        fontSize=11,
        leading=14,
        alignment=TA_LEFT,
    ),
    "totals_label": ParagraphStyle(
        "TotalsLabel",
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=14,
        alignment=TA_LEFT,
    ),
    "totals_value": ParagraphStyle(
        "TotalsValue",
        fontName="Helvetica",
        fontSize=11,
        leading=14,
        alignment=TA_RIGHT,
    ),
    "total_pay_label": ParagraphStyle(
        "TotalPayLabel",
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=16,
        alignment=TA_LEFT,
    ),
    "total_pay_value": ParagraphStyle(
        "TotalPayValue",
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=16,
        alignment=TA_RIGHT,
    ),
    "small_center": ParagraphStyle(
        "SmallCenter",
        fontName="Helvetica",
        fontSize=10,
        leading=12,
        alignment=TA_CENTER,
    ),
}


class QRFlowable(Flowable):
    """Flowable to render a QR code centered within the content width."""

    def __init__(self, url: str, size: float):
        super().__init__()
        self.url = url
        self.size = size
        qr_code = qr.QrCodeWidget(url)
        bounds = qr_code.getBounds()
        width = bounds[2] - bounds[0]
        height = bounds[3] - bounds[1]
        scale = min(size / width, size / height)
        self.drawing = Drawing(size, size, transform=[scale, 0, 0, scale, 0, 0])
        self.drawing.add(qr_code)
        self._available_width = size

    def wrap(self, availWidth, availHeight):
        self._available_width = availWidth
        return self.size, self.size

    def draw(self):
        x = (self._available_width - self.size) / 2
        renderPDF.draw(self.drawing, self.canv, x, 0)
        self.canv.linkURL(self.url, (x, 0, x + self.size, self.size), relative=0)


def _load_datos_negocio(datos_negocio: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if datos_negocio is not None:
        return datos_negocio

    resultado: dict[str, Any] = {}
    if os.path.exists(DATOS_NEGOCIO_PATH):
        try:
            with open(DATOS_NEGOCIO_PATH, "r", encoding="utf-8") as fh:
                resultado = json.load(fh)
        except Exception:
            resultado = {}
    return resultado


def _build_ticket_flowables(
    datos_negocio: Mapping[str, Any],
    venta: Mapping[str, Any] | None,
    detalles: Iterable[Mapping[str, Any]] | None,
    dte_json: Mapping[str, Any] | None,
    sello: str | None,
    firma: str | None,
    qr_url: str | None,
) -> list[Flowable]:
    flowables: list[Flowable] = []
    venta = venta or {}
    dte_json = dte_json or {}
    detalles_lista = list(detalles or [])
    if not detalles_lista:
        detalles_lista = list(dte_json.get("cuerpoDocumento") or [])

    ident = dte_json.get("identificacion", {}) or {}
    receptor = dte_json.get("receptor", {}) or {}
    titulo = document_title_label(ident)

    flowables.append(
        Paragraph(
            f"DOCUMENTO TRIBUTARIO ELECTRÓNICO — {escape(titulo)}",
            TICKET_STYLES["doc_label"],
        )
    )
    flowables.append(Spacer(1, BLOCK_SPACING))

    emisor_json = dte_json.get("emisor", {}) or {}
    nombre_emisor = (
        datos_negocio.get("nombreComercial")
        or datos_negocio.get("nombre")
        or datos_negocio.get("razonSocial")
        or emisor_json.get("nombreComercial")
        or emisor_json.get("nombre")
        or emisor_json.get("razonSocial")
        or ""
    )
    if nombre_emisor:
        flowables.append(
            Paragraph(escape(nombre_emisor.strip()), TICKET_STYLES["business_name"])
        )
    nit = (
        datos_negocio.get("nit")
        or emisor_json.get("nit")
        or ""
    )
    nrc = (
        datos_negocio.get("nrc")
        or emisor_json.get("nrc")
        or ""
    )
    if nit or nrc:
        flowables.append(
            Paragraph(
                escape(f"NIT: {_with_falta(nit)}   NRC: {_with_falta(nrc)}"),
                TICKET_STYLES["center_text"],
            )
        )
    giro = (
        datos_negocio.get("descActividad")
        or datos_negocio.get("actividad")
        or emisor_json.get("descActividad")
        or emisor_json.get("actividad")
        or ""
    )
    if giro:
        flowables.append(
            Paragraph(
                escape(f"Actividad: {_with_falta(giro)}"), TICKET_STYLES["center_text"]
            )
        )
    direccion = datos_negocio.get("direccion") or emisor_json.get("direccion") or {}
    direccion_txt = (
        direccion.get("complemento")
        or direccion.get("direccion")
        or direccion.get("descripcion")
        or ""
    )
    if direccion_txt:
        flowables.append(
            Paragraph(
                escape(f"Dirección: {_with_falta(direccion_txt)}"),
                TICKET_STYLES["center_text"],
            )
        )

    flowables.append(Spacer(1, BLOCK_SPACING))

    kv_rows = [
        ("Fecha:", _with_falta(venta.get("fecha") or ident.get("fecEmi") or "")),
        ("No. Control:", _with_falta(ident.get("numeroControl"))),
        ("Código Gen.:", _with_falta(ident.get("codigoGeneracion"))),
        ("Cliente:", _with_falta(receptor.get("nombre") or venta.get("cliente"))),
        (
            "Documento:",
            _with_falta(
                receptor.get("nit")
                or receptor.get("dui")
                or receptor.get("numDocumento")
                or venta.get("documento")
            ),
        ),
    ]
    kv_data = [
        [
            Paragraph(escape(label), TICKET_STYLES["kv_label"]),
            Paragraph(escape(str(value)), TICKET_STYLES["kv_value"]),
        ]
        for label, value in kv_rows
    ]
    kv_table = Table(kv_data, colWidths=[CONTENT_WIDTH_PT * 0.45, CONTENT_WIDTH_PT * 0.55])
    kv_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), mm(0.5)),
                ("BOTTOMPADDING", (0, 0), (-1, -1), mm(0.5)),
            ]
        )
    )
    flowables.append(kv_table)
    flowables.append(Spacer(1, BLOCK_SPACING))

    flowables.append(Paragraph("Detalle de productos", TICKET_STYLES["section_header"]))
    flowables.append(Spacer(1, mm(1.5)))

    qty_width = mm(10)
    unit_width = mm(18)
    total_width = mm(20)
    desc_width = max(CONTENT_WIDTH_PT - qty_width - unit_width - total_width, mm(20))

    items_data = [
        [
            Paragraph("Cant.", TICKET_STYLES["table_header"]),
            Paragraph("Descripción", TICKET_STYLES["table_header"]),
            Paragraph("P. Unit.", TICKET_STYLES["table_header_right"]),
            Paragraph("Total", TICKET_STYLES["table_header_right"]),
        ]
    ]
    for entry in detalles_lista:
        qty = q(entry.get("cantidad") or entry.get("cantidadUniMedida") or entry.get("uniCantidad") or 0)
        desc = _with_falta(entry.get("descripcion"))
        unit = money(
            entry.get("precio_unitario")
            or entry.get("precioUnitario")
            or entry.get("precioUnit")
            or entry.get("precioUni")
            or entry.get("precio")
            or 0
        )
        line_total = _calculate_item_total(entry)
        items_data.append(
            [
                Paragraph(escape(qty), TICKET_STYLES["table_cell"]),
                Paragraph(escape(desc), TICKET_STYLES["table_desc"]),
                Paragraph(escape(unit), TICKET_STYLES["table_cell_right"]),
                Paragraph(escape(money(line_total)), TICKET_STYLES["table_cell_right"]),
            ]
        )

    items_table = Table(
        items_data,
        colWidths=[qty_width, desc_width, unit_width, total_width],
        hAlign="LEFT",
    )
    items_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), mm(0.6)),
                ("BOTTOMPADDING", (0, 0), (-1, -1), mm(0.6)),
                ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.black),
            ]
        )
    )
    flowables.append(items_table)
    flowables.append(Spacer(1, BLOCK_SPACING))

    flowables.append(Paragraph("Totales", TICKET_STYLES["section_header"]))
    flowables.append(Spacer(1, mm(1)))

    sub_total = sum(_calculate_item_total(entry) for entry in detalles_lista)
    total = venta.get("total")
    if total is None:
        total = _to_decimal(sub_total)
    total = _to_decimal(total)
    iva = venta.get("iva")
    if iva is None:
        iva = max(total - _to_decimal(sub_total), Decimal("0"))
    else:
        iva = _to_decimal(iva)

    totals_data = [
        [
            Paragraph("Sub-total", TICKET_STYLES["totals_label"]),
            Paragraph(money(sub_total), TICKET_STYLES["totals_value"]),
        ],
        [
            Paragraph("IVA", TICKET_STYLES["totals_label"]),
            Paragraph(money(iva), TICKET_STYLES["totals_value"]),
        ],
        [
            Paragraph("Total a pagar", TICKET_STYLES["total_pay_label"]),
            Paragraph(money(total), TICKET_STYLES["total_pay_value"]),
        ],
    ]
    totals_table = Table(
        totals_data,
        colWidths=[CONTENT_WIDTH_PT * 0.55, CONTENT_WIDTH_PT * 0.45],
    )
    totals_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), mm(0.6)),
                ("BOTTOMPADDING", (0, 0), (-1, -1), mm(0.6)),
            ]
        )
    )
    flowables.append(totals_table)

    forma_pago = venta.get("forma_pago")
    pago_monto = money(total)
    pagos_resumen = dte_json.get("resumen", {}).get("pagos") or []
    if not forma_pago and pagos_resumen:
        pago = pagos_resumen[0]
        code = str(pago.get("codigo") or "").zfill(2)
        forma_pago = PAGO_LABELS.get(code, "Otro")
        pago_monto = money(pago.get("montoPago") or total)
    if forma_pago:
        flowables.append(Spacer(1, BLOCK_SPACING))
        flowables.append(Paragraph("Pago", TICKET_STYLES["section_header"]))
        pagos_table = Table(
            [
                [
                    Paragraph(
                        escape(f"Pago: {_with_falta(forma_pago)}"),
                        TICKET_STYLES["kv_label"],
                    ),
                    Paragraph(escape(pago_monto), TICKET_STYLES["kv_value"]),
                ]
            ],
            colWidths=[CONTENT_WIDTH_PT * 0.55, CONTENT_WIDTH_PT * 0.45],
        )
        pagos_table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), mm(0.6)),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), mm(0.6)),
                ]
            )
        )
        flowables.append(pagos_table)

    if sello or firma:
        flowables.append(Spacer(1, BLOCK_SPACING))
    if sello:
        flowables.append(
            Paragraph(
                escape(f"Sello recibido: {_with_falta(sello)}"),
                TICKET_STYLES["small_center"],
            )
        )
    if firma:
        flowables.append(
            Paragraph(
                escape(f"Firma electrónica: {_with_falta(firma)}"),
                TICKET_STYLES["small_center"],
            )
        )

    if qr_url:
        flowables.append(Spacer(1, BLOCK_SPACING))
        flowables.append(QRFlowable(qr_url, min(QR_MAX_SIZE, CONTENT_WIDTH_PT)))

    return flowables


def _render_ticket_pdf(flowables: list[Flowable]) -> bytes:
    heights: list[float] = []
    total_height = 0.0
    for flowable in flowables:
        _, height = flowable.wrap(CONTENT_WIDTH_PT, 100000)
        heights.append(height)
        total_height += height

    page_height = max(total_height + MARGINS["top"] + MARGINS["bottom"], MIN_PAGE_HEIGHT_PT)

    buffer = BytesIO()
    canv = canvas.Canvas(buffer, pagesize=(TICKET_WIDTH_PT, page_height))
    y = page_height - MARGINS["top"]

    for flowable, height in zip(flowables, heights):
        available_height = y - MARGINS["bottom"]
        if height > available_height and y < page_height - MARGINS["top"]:
            canv.showPage()
            canv.setPageSize((TICKET_WIDTH_PT, page_height))
            y = page_height - MARGINS["top"]
            available_height = y - MARGINS["bottom"]
        flowable.wrapOn(canv, CONTENT_WIDTH_PT, available_height)
        flowable.drawOn(canv, MARGINS["left"], y - height)
        y -= height

    canv.save()
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes


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
    width = mm(58)
    height = mm(280)
    margin = mm(4)
    line_height = mm(5)
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
        qr_size = mm(30)
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
        qr_size = mm(20)
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
    """Genera un ticket de Factura Electrónica con ancho de 58 mm."""

    datos_negocio = _load_datos_negocio(datos_negocio)
    dte_data = dte_data or {}
    dte_json = dte_data.get("dteJson") or {}
    sello = dte_data.get("selloRecibido")
    firma = dte_data.get("firmaElectronica")
    qr_url = build_qr_url(dte_json) if dte_json else None

    flowables = _build_ticket_flowables(
        datos_negocio,
        venta or {},
        detalles,
        dte_json,
        sello,
        firma,
        qr_url,
    )

    pdf_bytes = _render_ticket_pdf(flowables)

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
    """Genera un ticket con un formato personalizado térmico de 58 mm."""

    datos_negocio = _load_datos_negocio(datos_negocio)
    dte_data = dte_data or {}
    dte_json = dte_data.get("dteJson") or {}
    sello = dte_data.get("selloRecibido")
    firma = dte_data.get("firmaElectronica")
    qr_url = build_qr_url(dte_json) if dte_json else None

    flowables: list[Flowable] = []
    if logo_path and os.path.exists(logo_path):
        logo_width = min(mm(30), CONTENT_WIDTH_PT)
        logo = Image(logo_path)
        logo._restrictSize(logo_width, logo_width)
        logo.hAlign = "CENTER"
        flowables.append(logo)
        flowables.append(Spacer(1, BLOCK_SPACING))

    flowables.extend(
        _build_ticket_flowables(
            datos_negocio,
            venta or {},
            detalles,
            dte_json,
            sello,
            firma,
            qr_url,
        )
    )

    pdf_bytes = _render_ticket_pdf(flowables)

    with open(archivo, "wb") as fh:
        fh.write(pdf_bytes)

