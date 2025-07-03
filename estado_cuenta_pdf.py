from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from datetime import datetime


def generar_reporte_vendedor_pdf(
    db,
    vendedor_id,
    fecha_inicio,
    fecha_fin,
    archivo="reporte_vendedor.pdf",
    agrupar_factura=False,
):
    """Genera un PDF con el detalle de ventas por vendedor.

    Parameters
    ----------
    agrupar_factura : bool, optional
        Si ``True`` se mostrará una línea por factura en lugar de detallar
        cada producto.
    """
    vendedor = db.get_trabajador(vendedor_id)
    if not vendedor:
        vendedor = db.get_vendedor(vendedor_id)
    if not vendedor:
        raise ValueError("Vendedor no encontrado")

    ventas = db.get_estado_cuenta(vendedor_id, "vendedor", fecha_inicio, fecha_fin)

    # Agrupar por cliente
    grouped = {}
    for venta in ventas:
        cid = venta.get("cliente_id")
        if agrupar_factura:
            detalles = db.get_detalles_venta(venta["id"])
            comision = sum(d.get("comision", 0) for d in detalles)
            grouped.setdefault(cid, []).append(
                {
                    "venta_id": venta["id"],
                    "fecha": venta.get("fecha"),
                    "total": venta.get("total", 0),
                    "comision": comision,
                }
            )
            continue
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
    nombre = "{}{}{}".format(
        vendedor.get('nombre', ''),
        " — " if vendedor.get('nombre') and vendedor.get('codigo') else "",
        vendedor.get('codigo', '')
    )
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
            if agrupar_factura:
                total = it.get("total", 0)
                com = it.get("comision", 0)
                total_cliente += total
                total_com += com
                values = [
                    f"FA-{it['venta_id']:06d}",
                    f"{total:.2f}",
                    it.get("fecha", "")[:10],
                    "",
                    "",
                    "",
                    f"{total:.2f}",
                    "",
                    f"{com:.2f}",
                ]
            else:
                total = it.get("cantidad", 0) * it.get("precio_unitario", 0)
                com = it.get("comision", 0)
                total_cliente += total
                total_com += com
                values = [
                    f"FA-{it['venta_id']:06d}",
                    f"{total:.2f}",
                    it.get("fecha", "")[:10],
                    it.get("descripcion", "")[:25],
                    f"{it.get('cantidad', 0):.2f}",
                    f"{it.get('precio_unitario', 0):.6f}",
                    f"{total:.2f}",
                    f"{(com/total*100 if total else 0):.2f}%",
                    f"{com:.2f}",
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


def generar_estado_cuenta_pdf(
    db,
    modo="cliente",
    archivo="estado_cuenta.pdf",
    **kwargs,
):
    """Genera un PDF para estados de cuenta.

    Parameters
    ----------
    incluir_pagos : bool, optional
        Incluir en el listado los pagos realizados por el cliente.
    agrupar_factura : bool, optional
        Al generar el reporte detallado de vendedor, mostrar una única
        línea por cada factura.

    Cuando ``modo`` es ``"vendedor"`` y se solicita ``incluir_detalles`` se
    delega a :func:`generar_reporte_vendedor_pdf` para producir el formato
    detallado por cliente y producto.
    """

    # -- Atajo para el reporte detallado de vendedor -----------------------
    if modo == "vendedor" and kwargs.get("incluir_detalles"):
        vid = kwargs.get("vendedor_id")
        fecha_inicio = kwargs.get("fecha_inicio")
        fecha_fin = kwargs.get("fecha_fin")
        agrupar = kwargs.get("agrupar_factura", False)
        generar_reporte_vendedor_pdf(
            db,
            vid,
            fecha_inicio,
            fecha_fin,
            archivo,
            agrupar_factura=agrupar,
        )
        return

    c = canvas.Canvas(archivo, pagesize=letter)
    width, height = letter
    y = height - 40
    c.setFont("Courier-Bold", 12)
    c.drawCentredString(width / 2, y, "ESTADO DE CUENTA")
    y -= 20

    fecha_inicio = kwargs.get("fecha_inicio")
    fecha_fin = kwargs.get("fecha_fin")
    incluir_pagos = kwargs.get("incluir_pagos", False)
    if modo == "cliente":
        cid = kwargs.get("cliente_id")
        if cid is None:
            resumen = db.get_estado_cuenta_clientes(
                fecha_inicio=fecha_inicio, fecha_fin=fecha_fin
            )
            c.drawString(40, y, "Cliente            Total Compras")
            y -= 14
            for r in resumen:
                cli = db.get_cliente(r.get("cliente_id"))
                nombre = cli.get("nombre", "") if cli else str(r.get("cliente_id"))
                c.drawString(40, y, nombre)
                c.drawRightString(width - 40, y, f"{r.get('total_compras',0):.2f}")
                y -= 14
        else:
            cliente = db.get_cliente(cid) or {}
            if not cliente:
                raise ValueError("Cliente no encontrado")
            c.setFont("Courier", 10)
            c.drawString(40, y, f"Cliente: {cliente.get('nombre','')}")
            y -= 14
            facturas = db.get_estado_cuenta(cid, "cliente", fecha_inicio, fecha_fin)
            c.drawString(40, y, "Fecha       Factura    Total")
            y -= 14


            for f in facturas:
                c.drawString(40, y, f.get("fecha", "")[:10])
                c.drawString(120, y, str(f.get("id")))
                c.drawRightString(width - 40, y, f"{f.get('total',0):.2f}")
                y -= 14
    elif modo == "vendedor":
        vid = kwargs.get("vendedor_id")
        if vid is None:
            resumen = db.get_estado_cuenta_vendedores(
                fecha_inicio=fecha_inicio, fecha_fin=fecha_fin
            )
            c.drawString(40, y, "Vendedor            Total Ventas")
            y -= 14
            for r in resumen:
                vend = db.get_trabajador(r.get("vendedor_id"))
                if vend is None:
                    vend = db.get_vendedor(r.get("vendedor_id"))
                nombre = vend.get("nombre", "") if vend else str(r.get("vendedor_id"))
                c.drawString(40, y, nombre)
                c.drawRightString(width - 40, y, f"{r.get('total_ventas',0):.2f}")
                y -= 14
        else:
            vendedor = db.get_trabajador(vid) or db.get_vendedor(vid)
            if vendedor is None:
                raise ValueError("Vendedor no encontrado")
            c.setFont("Courier", 10)
            c.drawString(40, y, f"Vendedor: {vendedor.get('nombre','')}")
            y -= 14
            ventas = db.get_estado_cuenta(vid, "vendedor", fecha_inicio, fecha_fin)
            c.drawString(40, y, "Fecha       Factura    Total")
            y -= 14
            for v in ventas:
                c.drawString(40, y, v.get("fecha", "")[:10])
                c.drawString(120, y, str(v.get("id")))
                c.drawRightString(width - 40, y, f"{v.get('total',0):.2f}")
                y -= 14
    else:
        resumen = db.get_estado_cuenta_vendedores(fecha_inicio=fecha_inicio, fecha_fin=fecha_fin)
        c.drawString(40, y, "Vendedor            Total Ventas")
        y -= 14
        for r in resumen:
            vend = db.get_trabajador(r.get("vendedor_id"))
            if vend is None:
                vend = db.get_vendedor(r.get("vendedor_id"))
            nombre = vend.get("nombre", "") if vend else str(r.get("vendedor_id"))
            c.drawString(40, y, nombre)
            c.drawRightString(width - 40, y, f"{r.get('total_ventas',0):.2f}")
            y -= 14

    c.drawString(40, 30, datetime.now().strftime("%d/%m/%Y"))
    c.save()
