from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing
from reportlab.graphics import renderPDF
from datetime import datetime
import json
import os

from jinja2 import Environment, FileSystemLoader

import utils.catalogos as catalogos
from paths import DATOS_NEGOCIO_PATH
from factura_sv import build_qr_url, format_direccion

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
_jinja_env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=False)


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
    """Genera un ticket de Factura Electrónica amigable para impresión."""

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

    dte_json = dte_data.get("dteJson", {})
    ident = dte_json.get("identificacion", {})
    emisor = dte_json.get("emisor", {})
    receptor = dte_json.get("receptor", {})
    resumen = dte_json.get("resumen", {})

    codigo_generacion = ident.get("codigoGeneracion", "")
    numero_control = ident.get("numeroControl", "")
    tipo_modelo = catalogos.get_value("CAT-003", str(ident.get("tipoModelo", "")), "") or ""
    tipo_operacion = catalogos.get_value("CAT-004", str(ident.get("tipoOperacion", "")), "") or ""
    fec_emi = ident.get("fecEmi", "")
    hor_emi = ident.get("horEmi", "")
    sello = dte_data.get("selloRecibido") or "—"
    qr_url = build_qr_url(dte_json) if dte_json else None

    emisor_nombre = (
        emisor.get("nombre")
        or emisor.get("nombreComercial")
        or datos_negocio.get("nombreComercial", "")
    )
    emisor_nit = emisor.get("nit") or datos_negocio.get("nit", "")
    emisor_nrc = emisor.get("nrc") or datos_negocio.get("nrc", "")
    emisor_act = emisor.get("descActividad") or datos_negocio.get("descActividad", "")
    emisor_dir = format_direccion(emisor.get("direccion") or datos_negocio.get("direccion"))

    if receptor.get("tipoDocumento") == "37":
        receptor_tipo_doc = "Otro"
        receptor_numero = "—"
        receptor_nombre = "CONSUMIDOR FINAL"
    else:
        receptor_tipo_doc = receptor.get("tipoDocumento", "")
        receptor_numero = receptor.get("numDocumento", "")
        receptor_nombre = receptor.get("nombre", "")
    rec_dir_obj = receptor.get("direccion") or {}
    receptor_direccion = (
        rec_dir_obj.get("complemento") if isinstance(rec_dir_obj, dict) else rec_dir_obj
    ) or ""
    receptor_correo = receptor.get("correo") or ""

    items = []
    for item in dte_json.get("cuerpoDocumento", []):
        qty = float(item.get("cantidad", 0))
        unidad_code = str(item.get("uniMedida", ""))
        unidad = "Unidad" if unidad_code == "59" else catalogos.get_value("CAT-014", unidad_code, "") or ""
        desc = str(item.get("descripcion", ""))
        if len(desc) > 40:
            desc = desc[:37] + "..."
        precio = float(item.get("precioUni", 0))
        subtotal = float(
            item.get("montoTotal")
            or item.get("ventaGravada")
            or item.get("ventaExenta")
            or item.get("ventaNoSuj")
            or 0
        )
        items.append(
            {
                "cantidad": ("{0:.4f}".format(qty)).rstrip("0").rstrip("."),
                "unidad": unidad,
                "descripcion": desc,
                "precio": f"{precio:.2f}",
                "subtotal": f"{subtotal:.2f}",
            }
        )

    sumatoria_ventas = resumen.get("totalVenta") or resumen.get("totalGravada")
    iva_retenido = resumen.get("ivaRetenido") or resumen.get("ivaPerci1") or ""
    retencion_renta = resumen.get("retencionRenta") or ""
    monto_total = resumen.get("montoTotalOperacion") or ""
    total_pagar = resumen.get("totalPagar") or monto_total
    condicion_operacion = catalogos.get_value(
        "CAT-016", str(resumen.get("condicionOperacion", "")), ""
    ) or ""

    context = {
        "codigo_generacion": codigo_generacion,
        "numero_control": numero_control,
        "tipo_modelo": tipo_modelo,
        "tipo_operacion": tipo_operacion,
        "fec_emi": fec_emi,
        "hor_emi": hor_emi,
        "sello": sello,
        "qr_url": qr_url or "",
        "emisor_nombre": emisor_nombre,
        "emisor_nit": emisor_nit,
        "emisor_nrc": emisor_nrc,
        "emisor_actividad": emisor_act,
        "emisor_direccion": emisor_dir,
        "receptor_tipo_doc": receptor_tipo_doc,
        "receptor_numero": receptor_numero,
        "receptor_nombre": receptor_nombre,
        "receptor_direccion": receptor_direccion,
        "receptor_correo": receptor_correo,
        "items": items,
        "sumatoria_ventas": (
            f"{float(sumatoria_ventas):.2f}" if sumatoria_ventas is not None else None
        ),
        "iva_retenido": f"{float(iva_retenido):.2f}" if iva_retenido else "",
        "retencion_renta": f"{float(retencion_renta):.2f}" if retencion_renta else "",
        "monto_total": f"{float(monto_total):.2f}" if monto_total else "",
        "total_pagar": f"{float(total_pagar):.2f}" if total_pagar else "",
        "condicion_operacion": condicion_operacion,
    }

    template = _jinja_env.get_template("ticket_fe_01.html")
    rendered = template.render(**context)
    lines = [line for line in rendered.splitlines() if line.strip()]

    width = 80 * mm
    line_height = 4 * mm
    extra = 30 * mm if qr_url else 0
    height = 20 * mm + line_height * len(lines) + extra
    c = canvas.Canvas(archivo, pagesize=(width, height))
    y = height - 10 * mm
    c.setFont("Courier", 8)
    for line in lines:
        c.drawString(5 * mm, y, line)
        y -= line_height

    if qr_url:
        qr_size = 20 * mm
        qr_code = qr.QrCodeWidget(qr_url)
        bounds = qr_code.getBounds()
        w = bounds[2] - bounds[0]
        h = bounds[3] - bounds[1]
        d = Drawing(qr_size, qr_size, transform=[qr_size / w, 0, 0, qr_size / h, 0, 0])
        d.add(qr_code)
        qr_x = (width - qr_size) / 2
        qr_y = max(5 * mm, y - qr_size)
        renderPDF.draw(d, c, qr_x, qr_y)
        c.linkURL(qr_url, (qr_x, qr_y, qr_x + qr_size, qr_y + qr_size), relative=0)

    c.showPage()
    c.save()


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

    width = 80 * mm
    line_height = 4 * mm
    base_height = 60 * mm

    if dte_data is None:
        dte_data = {}

    sello = dte_data.get("selloRecibido", "falta")
    firma = dte_data.get("firmaElectronica", "falta")
    dte_json = dte_data.get("dteJson", {})
    qr_url = build_qr_url(dte_json) if dte_json else None

    def _flatten(data, prefix=""):
        lines = []
        if isinstance(data, dict):
            for k, v in data.items():
                key = f"{prefix}{k}"
                if isinstance(v, dict):
                    lines.extend(_flatten(v, key + "."))
                else:
                    lines.append(f"{key}: {v}")
        return lines

    dte_lines = _flatten(dte_data.get("dteJson", {}))
    extra_count = 2 + len(dte_lines)

    height = base_height + len(detalles) * 6 * mm + extra_count * line_height + 40 * mm
    page_size = (width, height)

    c = canvas.Canvas(archivo, pagesize=page_size)
    y = height - 10 * mm

    # Opcional: logo centrado arriba
    if logo_path and os.path.exists(logo_path):
        logo_w = 20 * mm
        c.drawImage(
            logo_path,
            (width - logo_w) / 2,
            y - 20 * mm,
            width=logo_w,
            preserveAspectRatio=True,
        )
        y -= 22 * mm

    # Encabezado con datos de DTE
    c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(width / 2, y, "DOCUMENTO TRIBUTARIO ELECTRÓNICO")
    y -= 4 * mm
    c.drawCentredString(width / 2, y, "FACTURA")
    y -= 5 * mm
    c.setFont("Helvetica", 7)
    c.drawCentredString(width / 2, y, "------------------- DATOS DEL EMISOR ------------------")
    y -= 4 * mm
    c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(width / 2, y, _with_falta(datos_negocio.get("nombreComercial")))
    y -= 4 * mm
    nit = datos_negocio.get("nit")
    c.setFont("Helvetica", 7)
    c.drawCentredString(width / 2, y, f"NIT: {_with_falta(nit)}")
    y -= 4 * mm
    nrc = datos_negocio.get("nrc")
    c.drawCentredString(width / 2, y, f"NRC: {_with_falta(nrc)}")
    y -= 4 * mm
    giro = datos_negocio.get("descActividad")
    c.drawCentredString(width / 2, y, f"Actividad Económica: {_with_falta(giro)}")
    y -= 4 * mm
    direccion = datos_negocio.get("direccion", {}).get("complemento")
    c.drawCentredString(width / 2, y, f"Dirección: {_with_falta(direccion)}")
    y -= 5 * mm
    c.setFont("Helvetica-Bold", 7)
    c.drawCentredString(width / 2, y, "DATOS DE FACTURA")
    y -= 4 * mm
    c.setFont("Helvetica", 7)
    c.drawCentredString(width / 2, y, "Código de Generación:")
    y -= 3 * mm
    c.drawCentredString(width / 2, y, "Número de control:")
    y -= 4 * mm
    c.drawCentredString(width / 2, y, "Tipo Modelo: 1")
    y -= 3 * mm
    c.drawCentredString(width / 2, y, "Tipo Operación: 1")
    y -= 3 * mm
    c.drawCentredString(width / 2, y, f"Fecha y hora de Generación: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    y -= 5 * mm
    c.line(5 * mm, y, width - 5 * mm, y)
    y -= 4 * mm

    c.setFont("Helvetica-Bold", 7)
    c.drawString(5 * mm, y, "DETALLE")
    c.drawRightString(width - 5 * mm, y, "TOTAL")
    y -= 3 * mm
    c.line(5 * mm, y, width - 5 * mm, y)
    y -= 4 * mm

    c.setFont("Helvetica", 7)
    for d in detalles:
        desc = _with_falta(d.get("descripcion"))
        qty = d.get("cantidad", 0)
        pu = d.get("precio_unitario", 0)
        total = qty * pu
        c.drawString(5 * mm, y, f"{desc} x{qty}")
        c.drawRightString(width - 5 * mm, y, f"{total:.2f}")
        y -= 4 * mm

    c.line(5 * mm, y, width - 5 * mm, y)
    y -= 5 * mm
    c.setFont("Helvetica-Bold", 9)
    c.drawRightString(width - 5 * mm, y, f"Total: {venta.get('total', 0):.2f}")

    y -= 6 * mm
    c.setFont("Helvetica", 6)
    c.drawString(5 * mm, y, f"Sello recibido: {_with_falta(sello)}")
    y -= line_height
    c.drawString(5 * mm, y, f"Firma electr\xf3nica: {_with_falta(firma)}")
    y -= line_height
    for line in dte_lines:
        c.drawString(5 * mm, y, _with_falta(line))
        y -= line_height
    y -= line_height
    if qr_url:
        qr_size = 20 * mm
        qr_code = qr.QrCodeWidget(qr_url)
        bounds = qr_code.getBounds()
        w = bounds[2] - bounds[0]
        h = bounds[3] - bounds[1]
        d = Drawing(qr_size, qr_size, transform=[qr_size / w, 0, 0, qr_size / h, 0, 0])
        d.add(qr_code)
        qr_x = (width - qr_size) / 2
        qr_y = max(5 * mm, y - qr_size)
        renderPDF.draw(d, c, qr_x, qr_y)
        c.linkURL(qr_url, (qr_x, qr_y, qr_x + qr_size, qr_y + qr_size), relative=0)

    c.showPage()
    c.save()
