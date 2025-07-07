from reportlab.lib.pagesizes import letter, landscape
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    SimpleDocTemplate,
    Table,
    TableStyle,
    Paragraph,
    Spacer,
)
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT
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


def generar_estado_cuenta_pdf(db, modo="cliente", archivo="estado_cuenta.pdf", **kwargs):
    """Genera un PDF de estado de cuenta similar al ejemplo de ventas."""
    fecha_inicio = kwargs.get("fecha_inicio", "")
    fecha_fin = kwargs.get("fecha_fin", "")

    doc = SimpleDocTemplate(
        archivo,
        pagesize=landscape(letter),
        leftMargin=36,
        rightMargin=36,
        topMargin=28,
        bottomMargin=28,
    )
    styles = getSampleStyleSheet()
    style_title = ParagraphStyle(
        "title",
        parent=styles["Heading1"],
        alignment=TA_CENTER,
        fontSize=14,
        fontName="Helvetica-Bold",
        spaceAfter=2,
    )
    style_subtitle = ParagraphStyle(
        "subtitle",
        parent=styles["Normal"],
        alignment=TA_CENTER,
        fontSize=10,
        fontName="Helvetica",
        spaceAfter=8,
    )
    style_header = ParagraphStyle(
        "header",
        parent=styles["Normal"],
        alignment=TA_LEFT,
        fontSize=10,
        fontName="Helvetica-Bold",
        spaceAfter=10,
    )
    style_group = ParagraphStyle(
        "group",
        parent=styles["Normal"],
        alignment=TA_LEFT,
        fontSize=9,
        fontName="Helvetica-Bold",
        spaceAfter=4,
    )

    elements = [
        Paragraph("FARMACIA SANTA CATALINA", style_title),
        Paragraph(
            f"Estado de cuenta desde: {fecha_inicio} al {fecha_fin}", style_subtitle
        ),
        Spacer(1, 2),
    ]

    col_widths = [70, 60, 55, 120, 50, 60, 60, 50, 55]
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

    if modo == "vendedor":
        vid = kwargs.get("vendedor_id")
        vendedor = (db.get_trabajador(vid) or {}) if vid else {}
        elements.append(
            Paragraph(
                f"{vendedor.get('nombre','')} — {vendedor.get('codigo','')}",
                style_header,
            )
        )

        ventas = db.get_estado_cuenta(vid, "vendedor", fecha_inicio, fecha_fin)
        grupos = {}
        for v in ventas:
            cid = v.get("cliente_id")
            cli = (db.get_cliente(cid) or {}) if cid else {}
            key = cid or 0
            data = grupos.setdefault(
                key,
                {
                    "nombre": cli.get("nombre", ""),
                    "dui": cli.get("dui") or cli.get("nit", ""),
                    "ventas": [],
                },
            )
            detalles = db.get_detalles_venta(v["id"])
            for d in detalles:
                total = d.get("cantidad", 0) * d.get("precio_unitario", 0)
                com = d.get("comision", 0)
                porc = f"{(com / total * 100) if total else 0:.2f}%"
                data["ventas"].append(
                    {
                        "comprobante": f"FA-{v['id']:06d}",
                        "valor_fact": v.get("total", 0),
                        "facturo": v.get("fecha", "")[:10],
                        "item": d.get("descripcion", ""),
                        "cantidad": d.get("cantidad", 0),
                        "p_unitario": d.get("precio_unitario", 0),
                        "total": total,
                        "porc_comision": porc,
                        "comision": com,
                    }
                )

        for g in grupos.values():
            elements.append(
                Paragraph(
                    f"CLIENTE: {g['nombre']} - {g['dui']}", style_group
                )
            )
            data = [headers]
            total_cli = 0
            total_com = 0
            for v in g["ventas"]:
                total_cli += v["total"]
                total_com += v["comision"]
                data.append(
                    [
                        v["comprobante"],
                        f"{v['valor_fact']:.2f}",
                        v["facturo"],
                        v["item"][:30],
                        f"{v['cantidad']:.2f}",
                        f"{v['p_unitario']:.6f}",
                        f"{v['total']:.2f}",
                        v["porc_comision"],
                        f"{v['comision']:.2f}",
                    ]
                )
            if not g["ventas"]:
                data.append([""] * len(headers))
            table = Table(data, colWidths=col_widths, repeatRows=1)
            table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f5f5f5")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#222")),
                        ("ALIGN", (0, 0), (3, -1), "LEFT"),
                        ("ALIGN", (4, 1), (-1, -1), "RIGHT"),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("FONTSIZE", (0, 0), (-1, 0), 9),
                        ("FONTSIZE", (0, 1), (-1, -1), 8),
                        ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
                        ("TOPPADDING", (0, 0), (-1, 0), 3),
                        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ]
                )
            )
            elements.append(table)
            if g["ventas"]:
                total_tabla = Table(
                    [
                        [
                            "",
                            "",
                            "",
                            "",
                            "",
                            "TOTAL:",
                            f"{total_cli:.2f}",
                            "",
                            f"{total_com:.2f}",
                        ]
                    ],
                    colWidths=col_widths,
                )
                total_tabla.setStyle(
                    TableStyle(
                        [
                            ("SPAN", (0, 0), (5, 0)),
                            ("ALIGN", (6, 0), (6, 0), "RIGHT"),
                            ("ALIGN", (8, 0), (8, 0), "RIGHT"),
                            ("FONTNAME", (5, 0), (8, 0), "Helvetica-Bold"),
                            ("FONTSIZE", (5, 0), (8, 0), 9),
                            ("TEXTCOLOR", (5, 0), (8, 0), colors.HexColor("#1a237e")),
                        ]
                    )
                )
                elements.append(total_tabla)
            elements.append(Spacer(1, 10))

    elif modo == "cliente":
        cid = kwargs.get("cliente_id")
        cliente = (db.get_cliente(cid) or {}) if cid else {}
        elements.append(
            Paragraph(
                f"{cliente.get('nombre','')} — {cliente.get('codigo','')}",
                style_header,
            )
        )

        ventas = db.get_estado_cuenta(cid, "cliente", fecha_inicio, fecha_fin)
        grupos = {}
        for v in ventas:
            vid = v.get("vendedor_id")
            vend = (db.get_trabajador(vid) or {}) if vid else {}
            key = vid or 0
            data = grupos.setdefault(
                key,
                {
                    "nombre": vend.get("nombre", ""),
                    "codigo": vend.get("codigo", ""),
                    "ventas": [],
                },
            )
            detalles = db.get_detalles_venta(v["id"])
            for d in detalles:
                total = d.get("cantidad", 0) * d.get("precio_unitario", 0)
                com = d.get("comision", 0)
                porc = f"{(com / total * 100) if total else 0:.2f}%"
                data["ventas"].append(
                    {
                        "comprobante": f"FA-{v['id']:06d}",
                        "valor_fact": v.get("total", 0),
                        "facturo": v.get("fecha", "")[:10],
                        "item": d.get("descripcion", ""),
                        "cantidad": d.get("cantidad", 0),
                        "p_unitario": d.get("precio_unitario", 0),
                        "total": total,
                        "porc_comision": porc,
                        "comision": com,
                    }
                )

        for g in grupos.values():
            elements.append(
                Paragraph(
                    f"VENDEDOR: {g['nombre']} - {g['codigo']}", style_group
                )
            )
            data = [headers]
            total_cli = 0
            total_com = 0
            for v in g["ventas"]:
                total_cli += v["total"]
                total_com += v["comision"]
                data.append(
                    [
                        v["comprobante"],
                        f"{v['valor_fact']:.2f}",
                        v["facturo"],
                        v["item"][:30],
                        f"{v['cantidad']:.2f}",
                        f"{v['p_unitario']:.6f}",
                        f"{v['total']:.2f}",
                        v["porc_comision"],
                        f"{v['comision']:.2f}",
                    ]
                )
            if not g["ventas"]:
                data.append([""] * len(headers))
            table = Table(data, colWidths=col_widths, repeatRows=1)
            table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f5f5f5")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#222")),
                        ("ALIGN", (0, 0), (3, -1), "LEFT"),
                        ("ALIGN", (4, 1), (-1, -1), "RIGHT"),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("FONTSIZE", (0, 0), (-1, 0), 9),
                        ("FONTSIZE", (0, 1), (-1, -1), 8),
                        ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
                        ("TOPPADDING", (0, 0), (-1, 0), 3),
                        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ]
                )
            )
            elements.append(table)
            if g["ventas"]:
                total_tabla = Table(
                    [
                        [
                            "",
                            "",
                            "",
                            "",
                            "",
                            "TOTAL:",
                            f"{total_cli:.2f}",
                            "",
                            f"{total_com:.2f}",
                        ]
                    ],
                    colWidths=col_widths,
                )
                total_tabla.setStyle(
                    TableStyle(
                        [
                            ("SPAN", (0, 0), (5, 0)),
                            ("ALIGN", (6, 0), (6, 0), "RIGHT"),
                            ("ALIGN", (8, 0), (8, 0), "RIGHT"),
                            ("FONTNAME", (5, 0), (8, 0), "Helvetica-Bold"),
                            ("FONTSIZE", (5, 0), (8, 0), 9),
                            ("TEXTCOLOR", (5, 0), (8, 0), colors.HexColor("#1a237e")),
                        ]
                    )
                )
                elements.append(total_tabla)
            elements.append(Spacer(1, 10))

    else:
        resumen = db.get_estado_cuenta_vendedores(
            fecha_inicio=fecha_inicio, fecha_fin=fecha_fin
        )
        data = [["Vendedor", "Total Ventas"]]
        for r in resumen:
            vend = db.get_trabajador(r.get("vendedor_id"))
            nombre = vend.get("nombre", "") if vend else str(r.get("vendedor_id"))
            data.append([nombre, f"{r.get('total_ventas',0):.2f}"])
        table = Table(data, colWidths=[200, 80])
        table.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                    ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ]
            )
        )
        elements.append(table)

    def _footer(canvas_doc, doc):
        canvas_doc.saveState()
        canvas_doc.setFont("Helvetica", 8)
        canvas_doc.drawRightString(
            doc.pagesize[0] - doc.rightMargin,
            18,
            f"{datetime.now().strftime('%d/%m/%Y')} Página {doc.page}",
        )
        canvas_doc.restoreState()

    doc.build(elements, onFirstPage=_footer, onLaterPages=_footer)
