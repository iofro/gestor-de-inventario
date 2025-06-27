from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from datetime import datetime


def generar_reporte_vendedor_pdf(db, vendedor_id, fecha_inicio, fecha_fin, archivo="reporte_vendedor.pdf"):
    """Genera un PDF con el detalle de ventas por vendedor."""
    vendedor = db.get_trabajador(vendedor_id)
    if not vendedor:
        raise ValueError("Vendedor no encontrado")

    ventas = db.get_estado_cuenta(vendedor_id, "vendedor", fecha_inicio, fecha_fin)

    # Agrupar por cliente
    grouped = {}
    for venta in ventas:
        cid = venta.get("cliente_id")
        detalles = db.get_detalles_venta(venta["id"])
        for d in detalles:
            d["fecha"] = venta.get("fecha")
            d["venta_id"] = venta["id"]
            d["cliente_id"] = cid
            grouped.setdefault(cid, []).append(d)

    c = canvas.Canvas(archivo, pagesize=letter)
    width, height = letter
    y = height - 40

    c.setFont("Courier-Bold", 12)
    c.drawCentredString(width / 2, y, "FARMACIA SANTA CATALINA")
    y -= 14
    c.setFont("Courier", 10)
    titulo = f"Reporte de VENTAS por VENDEDOR desde: {fecha_inicio} al {fecha_fin}"
    c.drawCentredString(width / 2, y, titulo)
    y -= 14
    nombre = f"{vendedor.get('nombre','')} — {vendedor.get('codigo','')}"
    c.setFont("Courier-Bold", 10)
    c.drawCentredString(width / 2, y, nombre)
    y -= 20

    for cid, items in grouped.items():
        cliente = db.get_cliente(cid) if cid else {}
        cli_line = f"{cliente.get('nombre','')} - {cliente.get('dui') or cliente.get('nit','')}"
        c.setFont("Courier-Bold", 9)
        c.drawString(40, y, "CLIENTE: " + cli_line)
        y -= 12
        headers = [
            "Comprobante", "Valor Fact", "Facturó", "ITEM", "Cantidad",
            "P. Unitario", "Total", "% Comisión", "Comisión"
        ]
        col_x = [40, 100, 150, 210, 370, 430, 480, 530, 580]
        c.setFont("Courier-Bold", 8)
        for hx, text in zip(col_x, headers):
            c.drawString(hx, y, text)
        y -= 10
        c.setFont("Courier", 8)
        total_cliente = 0
        total_com = 0
        for it in items:
            if y < 60:
                c.showPage()
                y = height - 40
            total = it.get("cantidad",0) * it.get("precio_unitario",0)
            com = it.get("comision",0)
            total_cliente += total
            total_com += com
            values = [
                f"FA-{it['venta_id']:06d}",
                f"{total:.2f}",
                it.get("fecha","")[:10],
                it.get("descripcion","")[:25],
                f"{it.get('cantidad',0):.2f}",
                f"{it.get('precio_unitario',0):.6f}",
                f"{total:.2f}",
                f"{(com/total*100 if total else 0):.2f}%",
                f"{com:.2f}"
            ]
            for hx, text in zip(col_x, values):
                c.drawString(hx, y, str(text))
            y -= 10
        c.setFont("Courier-Bold", 8)
        c.drawRightString(width - 40, y, f"Total: {total_cliente:.2f}  Comisión: {total_com:.2f}")
        y -= 20

    c.setFont("Courier", 8)
    c.drawString(40, 30, datetime.now().strftime("%d/%m/%Y"))
    c.drawRightString(width - 40, 30, "Página 1")
    c.save()
