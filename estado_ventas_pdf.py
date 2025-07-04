from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.platypus import Table, TableStyle
from reportlab.lib import colors
from datetime import datetime


def _draw_header(c, width, height, vendedor, fecha_inicio, fecha_fin):
    """Dibuja el encabezado principal y retorna la coordenada y inicial."""
    y = height - 40
    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(width / 2, y, "FARMACIA SANTA CATALINA")
    y -= 16
    c.setFont("Helvetica-Bold", 10)
    titulo = f"Reporte de VENTAS por VENDEDOR desde: {fecha_inicio} al {fecha_fin}"
    c.drawCentredString(width / 2, y, titulo)
    y -= 14
    nombre = f"{vendedor.get('nombre','')} — {vendedor.get('codigo','')}"
    c.setFont("Helvetica-Bold", 10)
    c.drawCentredString(width / 2, y, nombre)
    y -= 20
    return y


def _draw_footer(c, width, page_number):
    """Dibuja la fecha de generación y la numeración de página."""
    fecha_gen = datetime.now().strftime("%d/%m/%Y")
    c.setFont("Helvetica", 8)
    c.drawString(40, 30, fecha_gen)
    c.drawRightString(width - 40, 30, f"Página {page_number}")


def generar_estado_ventas_pdf(vendedor, fecha_inicio, fecha_fin, ventas_por_cliente, archivo):
    """Genera un reporte de ventas por vendedor en formato PDF."""
    c = canvas.Canvas(archivo, pagesize=letter)
    width, height = letter

    page = 1
    y = _draw_header(c, width, height, vendedor, fecha_inicio, fecha_fin)

    margin_bottom = 50
    row_height = 14

    for cliente in ventas_por_cliente:
        nombre_cli = cliente.get('nombre', '')
        dui_cli = cliente.get('dui', '')
        ventas = cliente.get('ventas', [])

        # Altura requerida para este bloque
        rows = len(ventas) + 1  # +1 for header
        required = row_height * (rows + 3)  # cliente line + table + total
        if y - required < margin_bottom:
            _draw_footer(c, width, page)
            c.showPage()
            page += 1
            y = _draw_header(c, width, height, vendedor, fecha_inicio, fecha_fin)

        c.setFont("Helvetica-Bold", 9)
        c.drawString(40, y, f"CLIENTE: {nombre_cli} - {dui_cli}")
        y -= row_height

        headers = [
            "Comprobante", "Valor Fact", "Facturó", "ITEM",
            "Cantidad", "P. Unitario", "Total", "% Comisión", "Comisión"
        ]
        data = [headers]
        total_monto = 0
        total_comision = 0
        for v in ventas:
            total_monto += v.get('total', 0)
            total_comision += v.get('comision', 0)
            data.append([
                v.get('comprobante', ''),
                f"{v.get('valor_fact', 0):.2f}",
                v.get('facturo', ''),
                v.get('item', '')[:30],
                f"{v.get('cantidad', 0):.2f}",
                f"{v.get('p_unitario', 0):.6f}",
                f"{v.get('total', 0):.2f}",
                v.get('porc_comision', ''),
                f"{v.get('comision', 0):.2f}",
            ])

        col_widths = [70, 60, 55, 120, 50, 60, 60, 50, 55]
        table = Table(data, colWidths=col_widths, repeatRows=1)
        table.setStyle(TableStyle([
            ('GRID', (0,0), (-1,-1), 0.5, colors.black),
            ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
            ('ALIGN', (0,0), (0,-1), 'LEFT'),
            ('ALIGN', (1,1), (-1,-1), 'RIGHT'),
            ('ALIGN', (3,1), (3,-1), 'LEFT'),
            ('ALIGN', (7,1), (7,-1), 'RIGHT'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTSIZE', (0,0), (-1,-1), 8),
        ]))
        table_h = row_height * rows
        table.wrapOn(c, width, height)
        table.drawOn(c, 40, y - table_h + 4)
        y -= table_h + 4

        c.setFont("Helvetica-Bold", 8)
        c.drawRightString(width - 40, y, f"Total: {total_monto:.2f}   Comisión: {total_comision:.2f}")
        y -= row_height*2

    _draw_footer(c, width, page)
    c.save()
