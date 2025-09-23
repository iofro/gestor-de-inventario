"""Utilities to render DTE tickets as thermal PDFs.

This module exposes :func:`render_ticket_pdf` which takes a DTE payload and
returns the resulting PDF as ``bytes``.  The goal is to produce a clean ticket
layout without leaking internal structures from the JSON payload.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from io import BytesIO
from typing import Any, Dict, List, Tuple

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas

from factura_sv import build_qr_url
from utils.catalogos import (
    CAT_DEPTOS,
    CAT_MUNI44,
    FORMA_PAGO,
    MODELO,
    OPERACION,
    TIPO_DOC_REC,
)

try:  # pragma: no cover - defensive import
    from dte import _DEPARTAMENTOS as DTE_DEPARTAMENTOS
    from dte import _MUNICIPIOS_POR_DEPTO as DTE_MUNICIPIOS
except Exception:  # pragma: no cover - fallback when running minimal envs
    DTE_DEPARTAMENTOS = {}
    DTE_MUNICIPIOS = {}

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


PAGO_LABELS = {code.zfill(2): value.upper() for code, value in FORMA_PAGO.items()}


# ---------------------------------------------------------------------------
# Public API


def render_ticket_pdf(
    payload: Dict[str, Any], accepted: bool, sello: str | None = None
) -> bytes:
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
    receptor = payload.get("receptor", {})
    resumen = payload.get("resumen", {})
    items = payload.get("cuerpoDocumento", []) or []

    # ------------------------------------------------------------------ helpers
    page_width = 80 * mm
    margin_x = 4 * mm
    margin_top = 8 * mm
    margin_bottom = 6 * mm
    content_width = page_width - 2 * margin_x

    def _wrap_text(text: str, width: float, font: str, size: float) -> List[str]:
        lines: List[str] = []
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
                    and pdfmetrics.stringWidth(candidate, font, size) > width
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

    def _format_section_heading(title: str) -> str:
        title = title.strip().upper()
        filler = "-" * 11
        return f"{filler} {title} {filler}"

    def _map_modelo(code: Any) -> str:
        try:
            value = MODELO.get(int(code))
        except Exception:
            value = None
        if value:
            return value.title()
        return str(code or "")

    def _map_operacion(code: Any) -> str:
        try:
            value = OPERACION.get(int(code))
        except Exception:
            value = None
        if value:
            return value.title()
        return str(code or "")

    def _format_address(data: Dict[str, Any]) -> str:
        if not isinstance(data, dict):
            return ""
        complemento = data.get("complemento") or ""
        dep_raw = data.get("departamento")
        muni_raw = data.get("municipio")
        dep_code = None
        muni_code = None
        if dep_raw is not None:
            dep_code = f"{dep_raw}".zfill(2)
        if muni_raw is not None:
            muni_code = f"{muni_raw}".zfill(2)

        dep_name = (
            DTE_DEPARTAMENTOS.get(dep_code)
            or CAT_DEPTOS.get(dep_code)
            or ""
        )
        muni_name = ""
        if dep_code and muni_code:
            muni_name = DTE_MUNICIPIOS.get(dep_code, {}).get(muni_code, "")
        if not muni_name and muni_code:
            muni_info = CAT_MUNI44.get(muni_code)
            if muni_info:
                if dep_code and dep_code in muni_info:
                    muni_name = muni_info[dep_code]
                else:
                    muni_name = next(iter(muni_info.values()))

        parts: List[str] = []
        if complemento:
            parts.append(str(complemento))
        if muni_name and dep_name:
            parts.append(f"{muni_name.upper()}, {dep_name}")
        elif muni_name:
            parts.append(muni_name.upper())
        elif dep_name:
            parts.append(dep_name)
        return ", ".join(part for part in parts if part)

    def _format_document_line(rec: Dict[str, Any]) -> Tuple[str, str] | None:
        doc_number = rec.get("numDocumento") or rec.get("numeroDocumento")
        if not doc_number:
            return None
        doc_type = rec.get("tipoDocumento") or rec.get("tipoDoc")
        label = None
        if doc_type is not None:
            label = TIPO_DOC_REC.get(str(doc_type).zfill(2))
        if not label:
            label = "Documento"
        return f"{label}:", str(doc_number)

    def _to_money(value: Any) -> str:
        return money(value)

    def _item_totals(it: Dict[str, Any]) -> Decimal:
        for key in ("montoTotal", "ventaGravada", "ventaExenta", "ventaNoSuj"):
            val = it.get(key)
            if val not in (None, ""):
                return _to_decimal(val)
        cantidad = _to_decimal(it.get("cantidad", 0))
        precio = _to_decimal(it.get("precioUni", 0))
        return cantidad * precio

    def _iva_total() -> Decimal:
        total_iva = resumen.get("totalIva")
        if total_iva not in (None, ""):
            return _to_decimal(total_iva)
        iva_sum = Decimal("0")
        for it in items:
            iva_item = it.get("ivaItem") or it.get("tributoIva")
            if iva_item not in (None, ""):
                iva_sum += _to_decimal(iva_item)
        if iva_sum > 0:
            return iva_sum
        q = Decimal("0.01")
        calculated = Decimal("0")
        for it in items:
            gravada = _to_decimal(it.get("ventaGravada"))
            if gravada > 0:
                calculated += (gravada * Decimal("0.13")).quantize(
                    q, rounding=ROUND_HALF_UP
                )
        return calculated

    # ----------------------------------------------------------------- build data
    elements: List[Dict[str, Any]] = []

    def add_text(
        text: str,
        *,
        size: float = 8,
        bold: bool = False,
        align: str = "left",
        spacing_before: float = 0,
        spacing_after: float = 4,
    ) -> None:
        font = "Helvetica-Bold" if bold else "Helvetica"
        lines = _wrap_text(text, content_width, font, size)
        elements.append(
            {
                "type": "text",
                "lines": lines,
                "font": font,
                "size": size,
                "align": align,
                "leading": size + 2,
                "spacing_before": spacing_before,
                "spacing_after": spacing_after,
            }
        )

    def add_pair(
        label: str,
        value: str,
        *,
        size: float = 8,
        bold_value: bool = False,
        spacing_before: float = 0,
        spacing_after: float = 2,
    ) -> None:
        elements.append(
            {
                "type": "pair",
                "label": str(label),
                "value": str(value),
                "size": size,
                "bold_value": bold_value,
                "spacing_before": spacing_before,
                "spacing_after": spacing_after,
                "leading": size + 2,
            }
        )

    def add_hr(spacing_before: float = 4, spacing_after: float = 4) -> None:
        elements.append(
            {
                "type": "hr",
                "spacing_before": spacing_before,
                "spacing_after": spacing_after,
            }
        )

    col_widths = [0.10, 0.55, 0.15, 0.20]
    col_widths = [w * content_width for w in col_widths]

    def add_table_header() -> None:
        elements.append(
            {
                "type": "table_header",
                "labels": ["CANT.", "DESCRIPCIÓN", "P. UNIT.", "TOTAL"],
                "font": "Helvetica-Bold",
                "size": 8,
                "leading": 10,
                "spacing_before": 4,
                "spacing_after": 2,
            }
        )

    def add_table_row(item: Dict[str, Any]) -> None:
        cantidad = q(item.get("cantidad", 0))
        precio = _to_money(item.get("precioUni", 0))
        total = _to_money(_item_totals(item))
        descripcion = str(item.get("descripcion", ""))
        desc_lines = _wrap_text(
            descripcion, col_widths[1], "Helvetica", 8
        )
        row_height = (8 + 2) * len(desc_lines)
        elements.append(
            {
                "type": "table_row",
                "cantidad": cantidad,
                "precio": precio,
                "total": total,
                "desc_lines": desc_lines,
                "leading": 10,
                "size": 8,
                "row_height": row_height,
                "spacing_before": 0,
                "spacing_after": 2,
            }
        )

    def add_qr_block(url: str) -> None:
        qr_size = min(50 * mm, content_width)
        elements.append(
            {
                "type": "qr",
                "url": url,
                "size": qr_size,
                "spacing_before": 6,
                "spacing_after": 0,
            }
        )

    # Title ----------------------------------------------------------------------
    add_text(
        "DOCUMENTO TRIBUTARIO ELECTRÓNICO — FACTURA",
        size=11,
        bold=True,
        align="center",
        spacing_after=6,
    )

    # Emisor ---------------------------------------------------------------------
    add_text(_format_section_heading("Datos del Emisor"), align="center", size=8, bold=True)
    emisor_nombre = emisor.get("nombreComercial") or emisor.get("nombre")
    if emisor_nombre:
        add_text(str(emisor_nombre), bold=True, align="center", size=9, spacing_after=2)
    if emisor.get("nit"):
        add_text(f"NIT: {emisor.get('nit')}", size=8)
    if emisor.get("nrc"):
        add_text(f"NRC: {emisor.get('nrc')}", size=8)
    sucursal = emisor.get("sucursal") or emisor.get("nombreEstablecimiento")
    if not sucursal:
        sucursal = emisor.get("codEstableMH") or emisor.get("codEstable")
    if sucursal:
        add_text(f"Sucursal: {sucursal}", size=8)
    actividad = emisor.get("descActividad") or emisor.get("actividadEconomica")
    if actividad:
        add_text(f"Actividad Económica: {actividad}", size=8)
    direccion = _format_address(emisor.get("direccion", {}))
    if direccion:
        add_text(f"Dirección: {direccion}", size=8)

    # Datos de factura -----------------------------------------------------------
    add_text(_format_section_heading("Datos de Factura"), align="center", size=8, bold=True)
    if ident.get("codigoGeneracion"):
        add_text(
            f"Código de Generación: {ident.get('codigoGeneracion')}",
            size=8,
        )
    if ident.get("numeroControl"):
        add_text(f"Número de control: {ident.get('numeroControl')}", size=8)
    sello = sello or payload.get("selloRecibido") or ident.get("selloRecibido")
    if sello:
        add_text(f"Sello de Recepción: {sello}", size=8)
    modelo = _map_modelo(ident.get("tipoModelo"))
    if modelo:
        add_text(f"Modelo de Facturación: {modelo}", size=8)
    operacion = _map_operacion(ident.get("tipoOperacion"))
    if operacion:
        add_text(f"Tipo de Transmisión: {operacion}", size=8)
    fecha = ident.get("fecEmi")
    hora = ident.get("horEmi")
    if fecha or hora:
        add_text(
            f"Fecha y hora de Generación: {fecha or ''} {hora or ''}".strip(),
            size=8,
        )

    # Receptor -------------------------------------------------------------------
    add_text(_format_section_heading("Datos del Receptor"), align="center", size=8, bold=True)
    add_pair("Nombre:", receptor.get("nombre") or "", size=8)
    if receptor.get("nit"):
        add_pair("NIT:", receptor.get("nit"), size=8)
    doc_line = _format_document_line(receptor)
    if doc_line:
        add_pair(doc_line[0], doc_line[1], size=8)
    if receptor.get("nrc"):
        add_pair("NRC:", receptor.get("nrc"), size=8)
    direccion_rec = _format_address(receptor.get("direccion", {}))
    if direccion_rec:
        add_text(f"Dirección: {direccion_rec}", size=8)
    correo_rec = receptor.get("correo")
    if correo_rec:
        add_pair("Correo:", correo_rec, size=8)

    # Detalle --------------------------------------------------------------------
    add_text(_format_section_heading("Detalle de Factura"), align="center", size=8, bold=True)
    add_table_header()
    for item in items:
        add_table_row(item)

    # Sumarios -------------------------------------------------------------------
    add_hr(spacing_before=2, spacing_after=2)
    add_pair("Suma Ventas No Sujetas:", _to_money(resumen.get("totalNoSuj", 0)))
    add_pair("Suma Ventas Exentas:", _to_money(resumen.get("totalExenta", 0)))
    add_pair("Suma Ventas Gravadas:", _to_money(resumen.get("totalGravada", 0)))
    add_pair(
        "Sumatoria Total de Operaciones:",
        _to_money(resumen.get("subTotalVentas", 0)),
    )
    add_pair(
        "Monto global Desc. a ventas no sujetas:",
        _to_money(resumen.get("descuNoSuj", 0)),
    )
    add_pair(
        "Monto global Desc. a ventas exentas:",
        _to_money(resumen.get("descuExenta", 0)),
    )
    add_pair(
        "Monto global Desc. a ventas gravadas:",
        _to_money(resumen.get("descuGravada", 0)),
    )
    add_pair("Tributo (IVA):", _to_money(_iva_total()))
    add_pair("Sub-Total:", _to_money(resumen.get("subTotal", 0)))
    iva_percibido = _to_decimal(resumen.get("ivaPerci1"))
    if iva_percibido > 0:
        add_pair("IVA Percibido:", _to_money(iva_percibido))
    iva_retenido = _to_decimal(resumen.get("ivaRete1"))
    if iva_retenido > 0:
        add_pair("IVA Retenido:", _to_money(iva_retenido))
    add_pair(
        "Monto Total de la Operación:",
        _to_money(resumen.get("montoTotalOperacion", 0)),
    )
    total_no_afectos = (
        resumen.get("totalOtrosMontosNoAfectos")
        or resumen.get("totalOtrosMontosNoAfectos1")
        or resumen.get("totalOtros")
        or 0
    )
    add_pair(
        "Total otros montos no afectos:",
        _to_money(total_no_afectos),
    )
    add_pair(
        "Total a pagar:",
        _to_money(resumen.get("totalPagar", resumen.get("montoTotalOperacion", 0))),
        bold_value=True,
    )
    total_letras = resumen.get("totalLetras")
    if total_letras:
        add_text(f"TOTAL EN LETRAS: {total_letras}", size=8, bold=True)

    # Pagos y otros --------------------------------------------------------------
    pagos = resumen.get("pagos") or []
    if pagos:
        pago = pagos[0]
        code = str(pago.get("codigo")).zfill(2)
        label = PAGO_LABELS.get(code, FORMA_PAGO.get(code, "Otros")).upper()
        add_text(f"Forma de pago: {label}", size=8, spacing_before=4)
        if pago.get("montoPago") not in (None, ""):
            add_pair("Monto pago:", _to_money(pago.get("montoPago")), size=8)
        if pago.get("referencia"):
            add_pair("Referencia:", pago.get("referencia"), size=8)
        if pago.get("plazo"):
            add_pair("Plazo:", pago.get("plazo"), size=8)
        if pago.get("periodo"):
            add_pair("Periodo:", pago.get("periodo"), size=8)

    # QR -------------------------------------------------------------------------
    qr_url = None
    if ident.get("codigoGeneracion"):
        try:
            qr_url = build_qr_url(payload)
        except Exception:
            qr_url = None
    if qr_url:
        add_qr_block(qr_url)

    # ----------------------------------------------------------------- rendering
    def _elements_height() -> float:
        total = margin_top + margin_bottom
        for el in elements:
            total += el.get("spacing_before", 0)
            if el["type"] == "text":
                total += el["leading"] * len(el["lines"])
            elif el["type"] == "pair":
                total += el["leading"]
            elif el["type"] == "hr":
                total += 1
            elif el["type"] == "table_header":
                total += el["leading"]
            elif el["type"] == "table_row":
                total += el["row_height"]
            elif el["type"] == "qr":
                total += el["size"]
            total += el.get("spacing_after", 0)
        return total

    height = _elements_height()
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=(page_width, height))
    y = height - margin_top

    def _draw_text(el: Dict[str, Any]) -> None:
        nonlocal y
        y -= el.get("spacing_before", 0)
        font = el["font"]
        size = el["size"]
        leading = el["leading"]
        c.setFont(font, size)
        for line in el["lines"]:
            y -= leading
            if el["align"] == "center":
                c.drawCentredString(page_width / 2, y + (leading - size) / 2, line)
            elif el["align"] == "right":
                c.drawRightString(page_width - margin_x, y + (leading - size) / 2, line)
            else:
                c.drawString(margin_x, y + (leading - size) / 2, line)
        y -= el.get("spacing_after", 0)

    def _draw_pair(el: Dict[str, Any]) -> None:
        nonlocal y
        y -= el.get("spacing_before", 0)
        size = el["size"]
        leading = el["leading"]
        y -= leading
        c.setFont("Helvetica", size)
        c.drawString(margin_x, y + (leading - size) / 2, el["label"])
        font_value = "Helvetica-Bold" if el.get("bold_value") else "Helvetica"
        c.setFont(font_value, size)
        c.drawRightString(
            page_width - margin_x, y + (leading - size) / 2, el["value"]
        )
        y -= el.get("spacing_after", 0)

    def _draw_hr(el: Dict[str, Any]) -> None:
        nonlocal y
        y -= el.get("spacing_before", 0)
        y -= 1
        c.setLineWidth(0.4)
        c.line(margin_x, y, page_width - margin_x, y)
        y -= el.get("spacing_after", 0)

    def _draw_table_header(el: Dict[str, Any]) -> None:
        nonlocal y
        y -= el.get("spacing_before", 0)
        leading = el["leading"]
        size = el["size"]
        y -= leading
        x = margin_x
        c.setFont(el["font"], size)
        for idx, label in enumerate(el["labels"]):
            if idx == 1:
                c.drawString(x, y + (leading - size) / 2, label)
            else:
                c.drawRightString(
                    x + col_widths[idx] - 2,
                    y + (leading - size) / 2,
                    label,
                )
            x += col_widths[idx]
        y -= el.get("spacing_after", 0)

    def _draw_table_row(el: Dict[str, Any]) -> None:
        nonlocal y
        y -= el.get("spacing_before", 0)
        leading = el["leading"]
        size = el["size"]
        row_height = el["row_height"]
        y -= row_height
        row_top = y + row_height
        base_offset = (leading - size) / 2

        qty_y = row_top - leading + base_offset
        price_y = qty_y
        total_y = qty_y
        x = margin_x
        c.setFont("Helvetica", size)
        c.drawRightString(x + col_widths[0] - 2, qty_y, el["cantidad"])
        x += col_widths[0]

        desc_lines = el["desc_lines"]
        for idx, line in enumerate(desc_lines):
            line_y = row_top - leading * (idx + 1) + base_offset
            c.drawString(x, line_y, line)
        x += col_widths[1]

        c.drawRightString(x + col_widths[2] - 2, price_y, el["precio"])
        x += col_widths[2]
        c.drawRightString(x + col_widths[3] - 2, total_y, el["total"])

        y -= el.get("spacing_after", 0)

    def _draw_qr(el: Dict[str, Any]) -> None:
        nonlocal y
        y -= el.get("spacing_before", 0)
        size = el["size"]
        qr_code = qr.QrCodeWidget(el["url"])
        bounds = qr_code.getBounds()
        w = bounds[2] - bounds[0]
        h = bounds[3] - bounds[1]
        drawing = Drawing(
            size,
            size,
            transform=[size / w, 0, 0, size / h, 0, 0],
        )
        drawing.add(qr_code)
        qr_x = (page_width - size) / 2
        qr_y = y - size
        renderPDF.draw(drawing, c, qr_x, qr_y)
        c.linkURL(el["url"], (qr_x, qr_y, qr_x + size, qr_y + size), relative=0)
        y = qr_y - el.get("spacing_after", 0)

    draw_map = {
        "text": _draw_text,
        "pair": _draw_pair,
        "hr": _draw_hr,
        "table_header": _draw_table_header,
        "table_row": _draw_table_row,
        "qr": _draw_qr,
    }

    for element in elements:
        draw_map[element["type"]](element)

    c.showPage()
    c.save()
    return buffer.getvalue()
