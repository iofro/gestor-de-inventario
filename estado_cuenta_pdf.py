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
from xml.sax.saxutils import escape
import json
import os
from paths import (
    DATOS_NEGOCIO_PATH,
    DTES_DIR,
    DTE_FALLIDOS_DIR,
    DTES_PENDIENTES_DIR,
)


def _as_float(value):
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _dte_fecha(payload):
    if not isinstance(payload, dict):
        return ""
    ident = payload.get("identificacion") or {}
    if not isinstance(ident, dict):
        return ""
    return ident.get("fecEmi") or ident.get("fechaEmision") or ""


def _dte_total(payload):
    if not isinstance(payload, dict):
        return None
    resumen = payload.get("resumen") or {}
    if not isinstance(resumen, dict):
        return None
    for key in ("totalPagar", "montoTotalOperacion", "totalOperacion", "total"):
        val = _as_float(resumen.get(key))
        if val is not None:
            return val
    return None


def _summarize_detalles(detalles):
    if not detalles:
        return "", 0.0, 0.0
    nombres = [d.get("descripcion") for d in detalles if d.get("descripcion")]
    qty_total = sum(_as_float(d.get("cantidad")) or 0 for d in detalles)
    total_line = sum(
        (_as_float(d.get("cantidad")) or 0) * (_as_float(d.get("precio_unitario")) or 0)
        for d in detalles
    )
    if nombres:
        if len(nombres) == 1:
            item = nombres[0]
        else:
            item = f"{nombres[0]} +{len(nombres) - 1}"
    else:
        item = ""
    return item, qty_total, total_line


def _summarize_dte_items(payload):
    if not isinstance(payload, dict):
        return "", 0.0
    items = payload.get("cuerpoDocumento") or []
    if not isinstance(items, list):
        return "", 0.0
    nombres = [i.get("descripcion") for i in items if isinstance(i, dict) and i.get("descripcion")]
    qty_total = 0.0
    for i in items:
        if not isinstance(i, dict):
            continue
        qty_total += _as_float(i.get("cantidad")) or 0
    if nombres:
        if len(nombres) == 1:
            item = nombres[0]
        else:
            item = f"{nombres[0]} +{len(nombres) - 1}"
    else:
        item = ""
    return item, qty_total


def _build_venta_summary(venta, detalles, snapshot=None, payload=None):
    if payload is None:
        payload = snapshot.payload if snapshot and hasattr(snapshot, "payload") else {}
    total = _as_float(venta.get("total"))
    if total is None or total == 0:
        total = _dte_total(payload) or 0.0
    fecha = venta.get("fecha") or _dte_fecha(payload)
    item, qty_total, total_line = _summarize_detalles(detalles)
    if not detalles:
        dte_item, dte_qty = _summarize_dte_items(payload)
        if dte_item:
            item = dte_item
        if qty_total == 0 and dte_qty:
            qty_total = dte_qty
        if total_line == 0:
            total_line = total
    if not item:
        item = "VENTA"
    if qty_total == 0:
        qty_total = 1.0 if total else 0.0
    if total_line == 0 and total:
        total_line = total
    p_unitario = total_line / qty_total if qty_total else 0.0
    comision_total = sum(_as_float(d.get("comision")) or 0 for d in detalles)
    porc_com = f"{(comision_total / total * 100) if total else 0:.2f}%"
    return {
        "comprobante": f"FA-{venta['id']:06d}",
        "valor_fact": total,
        "facturo": (fecha or "")[:10],
        "item": item,
        "cantidad": qty_total,
        "p_unitario": p_unitario,
        "total": total,
        "porc_comision": porc_com,
        "comision": comision_total,
        "fecha_sort": fecha or "",
    }


def _dte_comprobante(payload, fallback=None):
    if not isinstance(payload, dict):
        return fallback or ""
    ident = payload.get("identificacion") or {}
    if isinstance(ident, dict):
        numero = ident.get("numeroControl")
        if numero:
            return str(numero)
        codigo = ident.get("codigoGeneracion")
        if codigo:
            return str(codigo)
    return fallback or ""


def _dte_receptor_info(payload):
    if not isinstance(payload, dict):
        return {"nombre": "", "doc": ""}
    receptor = payload.get("receptor") or {}
    if not isinstance(receptor, dict):
        return {"nombre": "", "doc": ""}
    nombre = str(receptor.get("nombre") or receptor.get("nombreComercial") or "").strip()
    doc = (
        str(receptor.get("dui") or receptor.get("nit") or receptor.get("numDocumento") or receptor.get("nrc") or "")
        .strip()
    )
    return {"nombre": nombre, "doc": doc}


def _build_dte_summary(payload, *, numero_control=None, codigo=None):
    total = _dte_total(payload) or 0.0
    fecha = _dte_fecha(payload)
    item, qty_total = _summarize_dte_items(payload)
    if not item:
        item = "VENTA"
    if qty_total == 0:
        qty_total = 1.0 if total else 0.0
    p_unitario = total / qty_total if qty_total else 0.0
    comprobante = numero_control or _dte_comprobante(payload, codigo) or "DTE"
    return {
        "comprobante": comprobante,
        "valor_fact": total,
        "facturo": (fecha or "")[:10],
        "item": item,
        "cantidad": qty_total,
        "p_unitario": p_unitario,
        "total": total,
        "porc_comision": "0.00%",
        "comision": 0.0,
        "fecha_sort": fecha or "",
    }


def _in_date_range(fecha, fecha_inicio, fecha_fin):
    if not fecha:
        return True
    fecha_norm = str(fecha)[:10]
    if fecha_inicio and fecha_norm < fecha_inicio:
        return False
    if fecha_fin and fecha_norm > fecha_fin:
        return False
    return True


def _find_dte_json_path(codigo):
    codigo_norm = (codigo or "").strip().upper()
    if not codigo_norm:
        return ""
    bases = [DTES_DIR, DTE_FALLIDOS_DIR, DTES_PENDIENTES_DIR]
    for base in bases:
        if not base:
            continue
        if not os.path.isdir(base):
            continue
        direct = os.path.join(base, codigo_norm, "documento.json")
        if os.path.isfile(direct):
            return direct
        try:
            for entry in os.listdir(base):
                entry_path = os.path.join(base, entry)
                if not os.path.isdir(entry_path):
                    continue
                candidate = os.path.join(entry_path, codigo_norm, "documento.json")
                if os.path.isfile(candidate):
                    return candidate
        except OSError:
            continue
    return ""


def _load_dte_payload_by_codigo(codigo):
    json_path = _find_dte_json_path(codigo)
    if not json_path:
        return {}
    try:
        with open(json_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _load_snapshot_payload(db, venta_id):
    snapshot = db.get_snapshot_by_venta(venta_id)
    if snapshot and hasattr(snapshot, "payload") and isinstance(snapshot.payload, dict):
        return snapshot.payload
    cursor = getattr(db, "cursor", None)
    if cursor is None:
        return {}
    try:
        row = cursor.execute(
            "SELECT codigo_generacion FROM dte_envios WHERE venta_id=? ORDER BY id DESC LIMIT 1",
            (venta_id,),
        ).fetchone()
    except Exception:
        row = None
    if not row:
        return {}
    try:
        codigo = row["codigo_generacion"]
    except Exception:
        codigo = row[0] if row else None
    return _load_dte_payload_by_codigo(codigo)


def _get_orphan_dtes(db, fecha_inicio, fecha_fin):
    cursor = getattr(db, "cursor", None)
    if cursor is None:
        return []
    try:
        venta_rows = cursor.execute("SELECT id FROM ventas").fetchall()
    except Exception:
        venta_rows = []
    ventas_ids = set()
    for row in venta_rows:
        try:
            vid = row["id"]
        except Exception:
            vid = row[0] if row else None
        if vid is not None:
            ventas_ids.add(vid)

    try:
        rows = cursor.execute(
            """
            SELECT id, venta_id, codigo_generacion, numero_control, fecha_hora
            FROM dte_envios
            WHERE codigo_generacion IS NOT NULL
            ORDER BY id DESC
            """
        ).fetchall()
    except Exception:
        rows = []
    seen = set()
    resultado = []
    for row in rows:
        try:
            venta_id = row["venta_id"]
            codigo = row["codigo_generacion"]
            numero_control = row["numero_control"]
        except Exception:
            venta_id = row[1] if len(row) > 1 else None
            codigo = row[2] if len(row) > 2 else None
            numero_control = row[3] if len(row) > 3 else None
        codigo_norm = (codigo or "").strip().upper()
        if not codigo_norm or codigo_norm in seen:
            continue
        seen.add(codigo_norm)
        if venta_id is not None and venta_id in ventas_ids:
            continue
        payload = _load_dte_payload_by_codigo(codigo_norm)
        if not payload:
            continue
        fecha = _dte_fecha(payload)
        if not _in_date_range(fecha, fecha_inicio, fecha_fin):
            continue
        resultado.append(
            {
                "codigo": codigo_norm,
                "numero_control": numero_control,
                "payload": payload,
            }
        )
    return resultado


def _fetch_ventas_rango(db, fecha_inicio, fecha_fin):
    cursor = getattr(db, "cursor", None)
    if cursor is None:
        return []
    query = "SELECT id, fecha, total, cliente_id, vendedor_id FROM ventas WHERE 1=1"
    params = []
    if fecha_inicio:
        query += " AND date(fecha) >= date(?)"
        params.append(fecha_inicio)
    if fecha_fin:
        query += " AND date(fecha) <= date(?)"
        params.append(fecha_fin)
    try:
        rows = cursor.execute(query, params).fetchall()
    except Exception:
        return []
    return [dict(row) for row in rows]


def _cliente_group_info(db, venta, payload):
    cid = venta.get("cliente_id")
    if cid:
        cli = db.get_cliente(cid) if cid else {}
        nombre = cli.get("nombre", "") if cli else ""
        doc = (cli.get("dui") or cli.get("nit") or "") if cli else ""
        return ("cliente", cid), nombre, doc
    rec = _dte_receptor_info(payload)
    nombre = rec.get("nombre") or "SIN CLIENTE"
    doc = rec.get("doc") or ""
    key = doc or nombre
    return ("dte", key), nombre, doc


def _vendedor_group_info(db, venta):
    vid = venta.get("vendedor_id")
    if vid:
        vend = db.get_trabajador(vid) or {}
        nombre = vend.get("nombre", "") if vend else ""
        codigo = vend.get("codigo", "") if vend else ""
        return ("vendedor", vid), nombre, codigo
    return ("sin_vendedor", "SIN VENDEDOR"), "SIN VENDEDOR", ""


def generar_reporte_vendedor_pdf(
    db,
    vendedor_id,
    fecha_inicio,
    fecha_fin,
    archivo="reporte_vendedor.pdf",
    datos_negocio=None,
):
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

    if datos_negocio is None:
        datos_negocio = {}
        if os.path.exists(DATOS_NEGOCIO_PATH):
            try:
                with open(DATOS_NEGOCIO_PATH, "r", encoding="utf-8") as f:
                    datos_negocio = json.load(f)
            except Exception:
                datos_negocio = {}

    c = canvas.Canvas(archivo, pagesize=letter)
    width, height = letter
    y = height - 40

    c.setFont("Courier-Bold", 12)
    c.drawCentredString(width / 2, y, datos_negocio.get("nombreComercial", ""))
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


def generar_estado_cuenta_pdf(
    db,
    modo="cliente",
    archivo="estado_cuenta.pdf",
    datos_negocio=None,
    **kwargs,
):
    """Genera un PDF de estado de cuenta similar al ejemplo de ventas."""
    fecha_inicio = kwargs.get("fecha_inicio", "")
    fecha_fin = kwargs.get("fecha_fin", "")

    if datos_negocio is None:
        datos_negocio = {}
        if os.path.exists(DATOS_NEGOCIO_PATH):
            try:
                with open(DATOS_NEGOCIO_PATH, "r", encoding="utf-8") as f:
                    datos_negocio = json.load(f)
            except Exception:
                datos_negocio = {}

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
    style_cell = ParagraphStyle(
        "cell",
        parent=styles["Normal"],
        alignment=TA_LEFT,
        fontSize=8,
        fontName="Helvetica",
        leading=9,
        wordWrap="CJK",
    )

    def _cell(text):
        safe = escape(str(text) if text is not None else "")
        safe = safe.replace("\n", "<br/>")
        return Paragraph(safe, style_cell)

    def _row_from_summary(summary):
        return [
            _cell(summary["comprobante"]),
            f"{summary['valor_fact']:.2f}",
            _cell(summary["facturo"]),
            _cell(summary["item"]),
            f"{summary['cantidad']:.2f}",
            f"{summary['p_unitario']:.6f}",
            f"{summary['total']:.2f}",
            summary["porc_comision"],
            f"{summary['comision']:.2f}",
        ]

    elements = [
        Paragraph(datos_negocio.get("nombreComercial", ""), style_title),
        Paragraph(
            f"Estado de cuenta desde: {fecha_inicio} al {fecha_fin}", style_subtitle
        ),
        Spacer(1, 2),
    ]

    col_widths = [70, 60, 55, 120, 50, 60, 60, 60, 55]
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
            payload = _load_snapshot_payload(db, v.get("id"))
            key, nombre, doc_id = _cliente_group_info(db, v, payload)
            data = grupos.setdefault(
                key,
                {
                    "nombre": nombre,
                    "dui": doc_id,
                    "ventas": [],
                },
            )
            detalles = db.get_detalles_venta(v["id"])
            data["ventas"].append(
                _build_venta_summary(v, detalles, payload=payload)
            )

        if not grupos:
            data = [headers, ["" for _ in headers]]
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

        for g in grupos.values():
            elements.append(
                Paragraph(
                    f"CLIENTE: {g['nombre']} - {g['dui']}", style_group
                )
            )
            data = [headers]
            total_cli = 0
            total_com = 0
            ventas_ordenadas = sorted(
                g["ventas"], key=lambda v: v.get("fecha_sort", ""), reverse=True
            )
            for v in ventas_ordenadas:
                total_cli += v["total"]
                total_com += v["comision"]
                data.append(_row_from_summary(v))
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
        if not cid:
            clientes = db.get_clientes()
            any_rows = False
            included_ids = set()
            for cli in clientes:
                cli_id = cli.get("id")
                ventas = db.get_estado_cuenta(cli_id, "cliente", fecha_inicio, fecha_fin)
                if not ventas:
                    continue
                for v in ventas:
                    vid_val = v.get("id")
                    if vid_val is not None:
                        included_ids.add(vid_val)
                any_rows = True
                elements.append(
                    Paragraph(
                        f"{cli.get('nombre','')} — {cli.get('codigo','')}",
                        style_header,
                    )
                )
                grupos = {}
                for v in ventas:
                    key, nombre, codigo = _vendedor_group_info(db, v)
                    data = grupos.setdefault(
                        key,
                        {
                            "nombre": nombre,
                            "codigo": codigo,
                            "ventas": [],
                        },
                    )
                    detalles = db.get_detalles_venta(v["id"])
                    payload = _load_snapshot_payload(db, v.get("id"))
                    data["ventas"].append(
                        _build_venta_summary(v, detalles, payload=payload)
                    )

                if not grupos:
                    data = [headers, ["" for _ in headers]]
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

                for g in grupos.values():
                    elements.append(
                        Paragraph(
                            f"VENDEDOR: {g['nombre']} - {g['codigo']}", style_group
                        )
                    )
                    data = [headers]
                    total_cli = 0
                    total_com = 0
                    ventas_ordenadas = sorted(
                        g["ventas"], key=lambda v: v.get("fecha_sort", ""), reverse=True
                    )
                    for v in ventas_ordenadas:
                        total_cli += v["total"]
                        total_com += v["comision"]
                        data.append(_row_from_summary(v))
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
                elements.append(Spacer(1, 8))

            ventas_todas = _fetch_ventas_rango(db, fecha_inicio, fecha_fin)
            ventas_restantes = [
                v for v in ventas_todas if v.get("id") not in included_ids
            ]
            dtes_huerfanos = _get_orphan_dtes(db, fecha_inicio, fecha_fin)
            if ventas_restantes or dtes_huerfanos:
                any_rows = True
                elements.append(
                    Paragraph(
                        "SIN CLIENTE",
                        style_header,
                    )
                )
                grupos = {}
                for v in ventas_restantes:
                    key, nombre, codigo = _vendedor_group_info(db, v)
                    data = grupos.setdefault(
                        key,
                        {
                            "nombre": nombre,
                            "codigo": codigo,
                            "ventas": [],
                        },
                    )
                    detalles = db.get_detalles_venta(v["id"])
                    payload = _load_snapshot_payload(db, v.get("id"))
                    data["ventas"].append(
                        _build_venta_summary(v, detalles, payload=payload)
                    )
                for dte_row in dtes_huerfanos:
                    payload = dte_row.get("payload") or {}
                    key = ("sin_vendedor", "SIN VENDEDOR")
                    data = grupos.setdefault(
                        key,
                        {
                            "nombre": "SIN VENDEDOR",
                            "codigo": "",
                            "ventas": [],
                        },
                    )
                    data["ventas"].append(
                        _build_dte_summary(
                            payload,
                            numero_control=dte_row.get("numero_control"),
                            codigo=dte_row.get("codigo"),
                        )
                    )

                if not grupos:
                    data = [headers, ["" for _ in headers]]
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

                for g in grupos.values():
                    elements.append(
                        Paragraph(
                            f"VENDEDOR: {g['nombre']} - {g['codigo']}", style_group
                        )
                    )
                    data = [headers]
                    total_cli = 0
                    total_com = 0
                    ventas_ordenadas = sorted(
                        g["ventas"], key=lambda v: v.get("fecha_sort", ""), reverse=True
                    )
                    for v in ventas_ordenadas:
                        total_cli += v["total"]
                        total_com += v["comision"]
                        data.append(_row_from_summary(v))
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
                elements.append(Spacer(1, 8))

            if not any_rows:
                data = [headers, ["" for _ in headers]]
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
        else:
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
                key, nombre, codigo = _vendedor_group_info(db, v)
                data = grupos.setdefault(
                    key,
                    {
                        "nombre": nombre,
                        "codigo": codigo,
                        "ventas": [],
                    },
                )
                detalles = db.get_detalles_venta(v["id"])
                payload = _load_snapshot_payload(db, v.get("id"))
                data["ventas"].append(
                    _build_venta_summary(v, detalles, payload=payload)
                )

            if not grupos:
                data = [headers, ["" for _ in headers]]
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

            for g in grupos.values():
                elements.append(
                    Paragraph(
                        f"VENDEDOR: {g['nombre']} - {g['codigo']}", style_group
                    )
                )
                data = [headers]
                total_cli = 0
                total_com = 0
                ventas_ordenadas = sorted(
                    g["ventas"], key=lambda v: v.get("fecha_sort", ""), reverse=True
                )
                for v in ventas_ordenadas:
                    total_cli += v["total"]
                    total_com += v["comision"]
                    data.append(_row_from_summary(v))
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
        vendedores = db.get_trabajadores(solo_vendedores=True)
        if not vendedores:
            vendedores = db.get_trabajadores()
        any_rows = False
        included_ids = set()
        for vend in vendedores:
            vid = vend.get("id")
            ventas = db.get_estado_cuenta(vid, "vendedor", fecha_inicio, fecha_fin)
            if not ventas:
                continue
            for v in ventas:
                vid_val = v.get("id")
                if vid_val is not None:
                    included_ids.add(vid_val)
            any_rows = True
            elements.append(
                Paragraph(
                    f"{vend.get('nombre','')} — {vend.get('codigo','')}",
                    style_header,
                )
            )
            grupos = {}
            for v in ventas:
                payload = _load_snapshot_payload(db, v.get("id"))
                key, nombre, doc_id = _cliente_group_info(db, v, payload)
                data = grupos.setdefault(
                    key,
                    {
                        "nombre": nombre,
                        "dui": doc_id,
                        "ventas": [],
                    },
                )
                detalles = db.get_detalles_venta(v["id"])
                data["ventas"].append(
                    _build_venta_summary(v, detalles, payload=payload)
                )

            if not grupos:
                data = [headers, ["" for _ in headers]]
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

            for g in grupos.values():
                elements.append(
                    Paragraph(
                        f"CLIENTE: {g['nombre']} - {g['dui']}", style_group
                    )
                )
                data = [headers]
                total_cli = 0
                total_com = 0
                ventas_ordenadas = sorted(
                    g["ventas"], key=lambda v: v.get("fecha_sort", ""), reverse=True
                )
                for v in ventas_ordenadas:
                    total_cli += v["total"]
                    total_com += v["comision"]
                    data.append(_row_from_summary(v))
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
        elements.append(Spacer(1, 8))

        ventas_todas = _fetch_ventas_rango(db, fecha_inicio, fecha_fin)
        ventas_restantes = [
            v for v in ventas_todas if v.get("id") not in included_ids
        ]
        dtes_huerfanos = _get_orphan_dtes(db, fecha_inicio, fecha_fin)
        if ventas_restantes or dtes_huerfanos:
            any_rows = True
            elements.append(
                Paragraph(
                    "SIN VENDEDOR",
                    style_header,
                )
            )
            grupos = {}
            for v in ventas_restantes:
                payload = _load_snapshot_payload(db, v.get("id"))
                key, nombre, doc_id = _cliente_group_info(db, v, payload)
                data = grupos.setdefault(
                    key,
                    {
                        "nombre": nombre,
                        "dui": doc_id,
                        "ventas": [],
                    },
                )
                detalles = db.get_detalles_venta(v["id"])
                data["ventas"].append(
                    _build_venta_summary(v, detalles, payload=payload)
                )
            for dte_row in dtes_huerfanos:
                payload = dte_row.get("payload") or {}
                rec = _dte_receptor_info(payload)
                nombre = rec.get("nombre") or "SIN CLIENTE"
                doc_id = rec.get("doc") or ""
                key = ("dte", doc_id or nombre)
                data = grupos.setdefault(
                    key,
                    {
                        "nombre": nombre,
                        "dui": doc_id,
                        "ventas": [],
                    },
                )
                data["ventas"].append(
                    _build_dte_summary(
                        payload,
                        numero_control=dte_row.get("numero_control"),
                        codigo=dte_row.get("codigo"),
                    )
                )

            if not grupos:
                data = [headers, ["" for _ in headers]]
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

            for g in grupos.values():
                elements.append(
                    Paragraph(
                        f"CLIENTE: {g['nombre']} - {g['dui']}", style_group
                    )
                )
                data = [headers]
                total_cli = 0
                total_com = 0
                ventas_ordenadas = sorted(
                    g["ventas"], key=lambda v: v.get("fecha_sort", ""), reverse=True
                )
                for v in ventas_ordenadas:
                    total_cli += v["total"]
                    total_com += v["comision"]
                    data.append(_row_from_summary(v))
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
            elements.append(Spacer(1, 8))

        if not any_rows:
            data = [headers, ["" for _ in headers]]
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
