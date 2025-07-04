from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.platypus import Table, TableStyle
from reportlab.lib import colors
from datetime import date


def _draw_header(c, width, height, vendedor, fecha_inicio, fecha_fin):
    """Draws the common header for each page and returns the starting y position."""
    y = height - 40
    c.setFont("Helvetica-Bold", 16)
    c.drawCentredString(width / 2, y, "FARMACIA SANTA CATALINA")
    y -= 20
    c.setFont("Helvetica-Bold", 11)
    c.drawCentredString(
        width / 2,
        y,
        f"Reporte de VENTAS por VENDEDOR desde: {fecha_inicio} al {fecha_fin}",
    )
    y -= 18
    c.setFont("Helvetica-Bold", 11)
    nombre = vendedor.get("nombre", "")
    codigo = vendedor.get("codigo", "")
    c.drawCentredString(width / 2, y, f"{nombre} — {codigo}")
    return y - 20


def _draw_footer(c, width, fecha, page_num):
    """Draw footer with generation date and page number."""
    c.setFont("Helvetica", 8)
    c.drawString(30, 20, f"Generado: {fecha}")
    c.drawRightString(width - 30, 20, f"Página {page_num}")


def generar_estado_ventas_vendedor_pdf(
    fecha_inicio,
    fecha_fin,
    vendedor,
    ventas_por_cliente,
    archivo=None,
):
    """Generate a PDF report of sales grouped by client for a vendor."""

    if archivo is None:
        codigo = vendedor.get("codigo", "")
        archivo = f"estado_ventas_{codigo}_{fecha_inicio}_{fecha_fin}.pdf"

    c = canvas.Canvas(archivo, pagesize=letter)
    width, height = letter
    page_num = 1
    y = _draw_header(c, width, height, vendedor, fecha_inicio, fecha_fin)

    bottom_margin = 40
    line_height = 16
    fecha_gen = date.today().strftime("%d/%m/%Y")

    if not ventas_por_cliente:
        c.setFont("Helvetica", 10)
        c.drawString(
            30,
            y,
            "No hay ventas registradas para este vendedor en el período seleccionado.",
        )
        _draw_footer(c, width, fecha_gen, page_num)
        c.save()
        return archivo

    for cliente in ventas_por_cliente:
        nombre_cliente = cliente.get("nombre", "")
        dui = cliente.get("dui", "")

        if y - line_height < bottom_margin:
            _draw_footer(c, width, fecha_gen, page_num)
            c.showPage()
            page_num += 1
            y = _draw_header(c, width, height, vendedor, fecha_inicio, fecha_fin)

        c.setFont("Helvetica-Bold", 10)
        c.drawString(30, y, f"CLIENTE: {nombre_cliente} - {dui}")
        y -= line_height

        table_data = [[
            "Comprobante",
            "Valor Fact",
            "Facturó",
            "ITEM",
            "Cantidad",
            "P. Unitario",
            "Total",
            "% Comisión",
            "Comisión",
        ]]

        total_cliente = 0
        total_comision = 0
        for v in cliente.get("ventas", []):
            table_data.append([
                str(v.get("comprobante", "")),
                f"{float(v.get('valor_fact', 0)):.2f}",
                str(v.get("facturo", "")),
                str(v.get("item", "")),
                f"{float(v.get('cantidad', 0)):.2f}",
                f"{float(v.get('p_unitario', 0)):.5f}",
                f"{float(v.get('total', 0)):.2f}",
                f"{float(v.get('pct_comision', 0)):.2f}%",
                f"{float(v.get('comision', 0)):.2f}",
            ])
            total_cliente += float(v.get("total", 0))
            total_comision += float(v.get("comision", 0))

        table = Table(
            table_data,
            colWidths=[70, 55, 55, 150, 50, 55, 55, 55, 55],
            repeatRows=1,
        )
        table.setStyle(
            TableStyle([
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                ("ALIGN", (0, 1), (3, -1), "LEFT"),
                ("ALIGN", (4, 1), (-1, -1), "RIGHT"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
            ])
        )
        w, h = table.wrap(width - 60, height)
        if y - h < bottom_margin:
            _draw_footer(c, width, fecha_gen, page_num)
            c.showPage()
            page_num += 1
            y = _draw_header(c, width, height, vendedor, fecha_inicio, fecha_fin)
        table.drawOn(c, 30, y - h)
        y -= h + 5

        if y - line_height < bottom_margin:
            _draw_footer(c, width, fecha_gen, page_num)
            c.showPage()
            page_num += 1
            y = _draw_header(c, width, height, vendedor, fecha_inicio, fecha_fin)
        c.setFont("Helvetica-Bold", 9)
        c.drawRightString(
            width - 30,
            y,
            f"Total: {total_cliente:.2f}    Comisión: {total_comision:.2f}",
        )
        y -= line_height

    _draw_footer(c, width, fecha_gen, page_num)
    c.save()
    return archivo
