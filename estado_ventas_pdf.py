from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.platypus import Table, TableStyle


def generar_estado_ventas_vendedor_pdf(fecha_inicio, fecha_fin, vendedor_codigo, ventas_por_cliente, vendedor_nombre="", archivo=None):
    """Genera un PDF con el estado de ventas por vendedor.

    Parameters
    ----------
    fecha_inicio : str
        Fecha de inicio del rango en formato ``YYYY-MM-DD`` o similar.
    fecha_fin : str
        Fecha de fin del rango en formato ``YYYY-MM-DD`` o similar.
    vendedor_codigo : str
        Código del vendedor.
    ventas_por_cliente : list
        Lista de diccionarios. Cada elemento representa un cliente y debe tener
        la clave ``cliente`` con la información del cliente y ``ventas`` con la
        lista de ventas de dicho cliente.
    vendedor_nombre : str, optional
        Nombre del vendedor, por defecto ``""``.
    archivo : str, optional
        Ruta donde guardar el PDF. Si se omite se usa la convención
        ``estado_ventas_[codigo]_[fecha_inicio]_[fecha_fin].pdf``.
    """

    if archivo is None:
        archivo = f"estado_ventas_{vendedor_codigo}_{fecha_inicio}_{fecha_fin}.pdf"

    c = canvas.Canvas(archivo, pagesize=letter)
    width, height = letter
    line_h = 12
    top_margin = 40
    bottom_margin = 50
    page = 1
    y = height - top_margin

    def draw_header():
        nonlocal y
        c.setFont("Helvetica-Bold", 14)
        c.drawCentredString(width / 2, height - top_margin, "FARMACIA SANTA CATALINA")
        c.setFont("Helvetica", 10)
        titulo = (
            f"Reporte de VENTAS por VENDEDOR desde: {fecha_inicio} al {fecha_fin}"
        )
        c.drawCentredString(width / 2, height - top_margin - line_h, titulo)
        vend_line = f"{vendedor_nombre} — {vendedor_codigo}".strip()
        c.setFont("Helvetica-Bold", 10)
        c.drawCentredString(width / 2, height - top_margin - 2 * line_h, vend_line)
        y = height - top_margin - 3 * line_h - 10

    def draw_footer():
        c.setFont("Helvetica", 8)
        c.drawString(40, 30, datetime.now().strftime("%d/%m/%Y"))
        c.drawRightString(width - 40, 30, f"Página {page}")

    def new_page():
        nonlocal page, y
        draw_footer()
        c.showPage()
        page += 1
        draw_header()

    draw_header()

    if not ventas_por_cliente:
        c.setFont("Helvetica", 10)
        msg = "No hay ventas registradas para este vendedor en el período seleccionado."
        c.drawCentredString(width / 2, y, msg)
        draw_footer()
        c.save()
        return archivo

    headers = [
        "Comprobante",
        "Valor Fact",
        "Facturó",
        "ITEM",
        "Cantidad",
        "P. Unitario",
        "Total",
        "% Comisión",
        "Comisión",
    ]
    col_widths = [70, 60, 60, 170, 50, 60, 60, 60, 60]

    for bloque in ventas_por_cliente:
        cliente = bloque.get("cliente", {})
        ventas = bloque.get("ventas", [])
        cli_line = f"{cliente.get('nombre', '')} - {cliente.get('dui') or cliente.get('nit', '')}"
        table_data = [headers]
        total_cli = 0
        total_com = 0
        for v in ventas:
            total_cli += float(v.get("total", 0))
            total_com += float(v.get("comision", 0))
            table_data.append([
                v.get("comprobante", ""),
                f"{float(v.get('valor_fact', 0)):.2f}",
                v.get("facturo", ""),
                v.get("item", ""),
                f"{float(v.get('cantidad', 0)):.2f}",
                f"{float(v.get('precio_unitario', 0)):.6f}",
                f"{float(v.get('total', 0)):.2f}",
                f"{float(v.get('porcentaje_comision', 0)):.2f}%",
                f"{float(v.get('comision', 0)):.2f}",
            ])

        table = Table(table_data, colWidths=col_widths, repeatRows=1)
        table.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.black),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                    ("ALIGN", (0, 0), (3, -1), "LEFT"),
                    ("ALIGN", (4, 1), (-1, -1), "RIGHT"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ]
            )
        )
        w, h = table.wrap(0, 0)
        needed = line_h + h + line_h
        if y - needed < bottom_margin:
            new_page()
        c.setFont("Helvetica-Bold", 9)
        c.drawString(40, y, "CLIENTE: " + cli_line)
        y -= line_h
        table.drawOn(c, 40, y - h)
        y -= h
        c.setFont("Helvetica-Bold", 8)
        c.drawRightString(width - 40, y, f"Total: {total_cli:.2f}  Comisión: {total_com:.2f}")
        y -= line_h
        if y < bottom_margin:
            new_page()

    draw_footer()
    c.save()
    return archivo
