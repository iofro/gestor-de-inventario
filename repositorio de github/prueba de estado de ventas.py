import sys
import datetime
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QPushButton, QMessageBox
from reportlab.lib.pagesizes import landscape, A4, LETTER
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics
import json
import os
from paths import DATOS_NEGOCIO_PATH

# Puedes registrar Arial si tienes el archivo, si no, Helvetica es suficiente
# pdfmetrics.registerFont(TTFont('Arial', 'arial.ttf'))

def calcular_total(cantidad, p_unitario):
    return round(cantidad * p_unitario, 2)

def calcular_comision(total, porc):
    try:
        porc_val = float(porc.replace('%', '').replace(',', '.'))
    except:
        porc_val = 0
    return round(total * (porc_val / 100), 2)

def generar_estado_ventas_pdf(filename, datos_negocio=None):
    # Datos de ejemplo (exactamente como en la foto, con cálculos corregidos)
    fecha_reporte = "20/06/2025"
    fecha_inicio = "01/01/2025"
    fecha_fin = "31/12/2025"
    vendedor = {"nombre": "JAVIER PORTILLO", "codigo": "005"}

    if datos_negocio is None:
        datos_negocio = {}
        if os.path.exists(DATOS_NEGOCIO_PATH):
            try:
                with open(DATOS_NEGOCIO_PATH, "r", encoding="utf-8") as f:
                    datos_negocio = json.load(f)
            except Exception:
                datos_negocio = {}

    clientes = [
        {
            "nombre": "MARIA DE JESUS REYES DE BENITES",
            "dui": "00126111-4",
            "ventas": [
                {
                    "comprobante": "FA-000770",
                    "valor_fact": 95.00,
                    "facturo": "11/06/2025",
                    "item": "AMOXICILINA 500 MG X 100 CAPSULAS BALAXI",
                    "cantidad": 5.00,
                    "p_unitario": 6.497500,
                    "porc_comision": "8.00%"
                },
                {
                    "comprobante": "FA-000770",
                    "valor_fact": 95.00,
                    "facturo": "11/06/2025",
                    "item": "OMEPRAZOL 20 MG CAPSULAS X 100 BALAXI",
                    "cantidad": 5.00,
                    "p_unitario": 6.215000,
                    "porc_comision": "8.00%"
                },
                {
                    "comprobante": "FA-000770",
                    "valor_fact": 95.00,
                    "facturo": "11/06/2025",
                    "item": "SELECTAVIT B-COMPLEX FORTE X 12 SACHETS",
                    "cantidad": 4.00,
                    "p_unitario": 10.283000,
                    "porc_comision": "8.00%"
                },
                {
                    "comprobante": "FA-000770",
                    "valor_fact": 95.00,
                    "facturo": "11/06/2025",
                    "item": "ENVIO C807 EXPRESS",
                    "cantidad": 1.00,
                    "p_unitario": 2.655500,
                    "porc_comision": "0.00%"
                }
            ]
        },
        {
            "nombre": "MARIO MISAEL MARTINEZ PANAMEÑO",
            "dui": "00631366-5",
            "ventas": [
                {
                    "comprobante": "FA-000735",
                    "valor_fact": 202.91,
                    "facturo": "28/05/2025",
                    "item": "CLORFENIRAMINA MALEATO 8MG 100TAB. GAMMA",
                    "cantidad": 1.00,
                    "p_unitario": 40.680000,
                    "porc_comision": "8.00%"
                },
                {
                    "comprobante": "FA-000735",
                    "valor_fact": 202.91,
                    "facturo": "28/05/2025",
                    "item": "NEUROMENTAL B12 X 21 SACHETS DE 15ML",
                    "cantidad": 1.00,
                    "p_unitario": 4.820500,
                    "porc_comision": "8.00%"
                },
                {
                    "comprobante": "FA-000735",
                    "valor_fact": 202.91,
                    "facturo": "28/05/2025",
                    "item": "MULTIVITAMINAS CON MINERALES 50S ROX",
                    "cantidad": 1.00,
                    "p_unitario": 40.680000,
                    "porc_comision": "8.00%"
                },
                {
                    "comprobante": "FA-000735",
                    "valor_fact": 202.91,
                    "facturo": "28/05/2025",
                    "item": "ALCOODO ALCOHOL ETILICO 90° X 1 GAL",
                    "cantidad": 12.00,
                    "p_unitario": 0.429000,
                    "porc_comision": "8.00%"
                },
                {
                    "comprobante": "FA-000735",
                    "valor_fact": 202.91,
                    "facturo": "28/05/2025",
                    "item": "AMOXICILINA 500 MG X 100 CAPSULAS BALAXI",
                    "cantidad": 5.00,
                    "p_unitario": 6.497500,
                    "porc_comision": "8.00%"
                },
                {
                    "comprobante": "FA-000735",
                    "valor_fact": 202.91,
                    "facturo": "28/05/2025",
                    "item": "CREMA COMBINADA 20G FUNIVER",
                    "cantidad": 6.00,
                    "p_unitario": 8.959833,
                    "porc_comision": "8.00%"
                },
                {
                    "comprobante": "FA-000735",
                    "valor_fact": 202.91,
                    "facturo": "28/05/2025",
                    "item": "FORXEX SILDENAFIL 50MG X 100 TAB ROWALT",
                    "cantidad": 1.00,
                    "p_unitario": 31.680000,
                    "porc_comision": "8.00%"
                },
                {
                    "comprobante": "FA-000735",
                    "valor_fact": 202.91,
                    "facturo": "28/05/2025",
                    "item": "ENVIO C807 EXPRESS",
                    "cantidad": 1.00,
                    "p_unitario": 2.655500,
                    "porc_comision": "0.00%"
                }
            ]
        },
        {
            "nombre": "NOEMY PORTILLO DE GRANADOS",
            "dui": "01132129-9",
            "ventas": [
                {
                    "comprobante": "FA-000727",
                    "valor_fact": 57.95,
                    "facturo": "28/05/2025",
                    "item": "PARACETAMOL (ACETAMINOFEN) ANH 500MG X 100 TAB",
                    "cantidad": 1.00,
                    "p_unitario": 4.633000,
                    "porc_comision": "0.00%"
                },
                {
                    "comprobante": "FA-000727",
                    "valor_fact": 57.95,
                    "facturo": "28/05/2025",
                    "item": "LORATEL LORATADINA 10 MG C/100 TAB",
                    "cantidad": 1.00,
                    "p_unitario": 7.000000,
                    "porc_comision": "8.00%"
                },
                {
                    "comprobante": "FA-000727",
                    "valor_fact": 57.95,
                    "facturo": "28/05/2025",
                    "item": "NOVOMIT",
                    "cantidad": 1.00,
                    "p_unitario": 23.160000,
                    "porc_comision": "8.00%"
                },
                {
                    "comprobante": "FA-000727",
                    "valor_fact": 57.95,
                    "facturo": "28/05/2025",
                    "item": "ALEFRIN CLORFENIRAMINA MALEATO 4 MG 1 DE 100 TAB",
                    "cantidad": 1.00,
                    "p_unitario": 28.042000,
                    "porc_comision": "8.00%"
                },
                {
                    "comprobante": "FA-000727",
                    "valor_fact": 57.95,
                    "facturo": "28/05/2025",
                    "item": "ENVIO C807 EXPRESS",
                    "cantidad": 1.00,
                    "p_unitario": 2.655500,
                    "porc_comision": "0.00%"
                }
            ]
        },
        {
            "nombre": "ROBERTO ELIDUK FLORES REYES",
            "dui": "01139004-4",
            "ventas": []
        }
    ]

    # Configuración del PDF
    doc = SimpleDocTemplate(
        filename,
        pagesize=landscape(LETTER),
        leftMargin=36,  # 0.5 inch ~ 1.27 cm
        rightMargin=36,
        topMargin=28,   # 1 cm
        bottomMargin=28
    )
    elements = []
    styles = getSampleStyleSheet()
    style_title = ParagraphStyle('title', parent=styles['Heading1'], alignment=TA_CENTER, fontSize=14, fontName='Helvetica-Bold', spaceAfter=2)
    style_subtitle = ParagraphStyle('subtitle', parent=styles['Normal'], alignment=TA_CENTER, fontSize=10, fontName='Helvetica', spaceAfter=8)
    style_vendedor = ParagraphStyle('vendedor', parent=styles['Normal'], alignment=TA_LEFT, fontSize=10, fontName='Helvetica-Bold', spaceAfter=10)
    style_cliente = ParagraphStyle('cliente', parent=styles['Normal'], alignment=TA_LEFT, fontSize=9, fontName='Helvetica-Bold', spaceAfter=4)
    style_normal = ParagraphStyle('normal', parent=styles['Normal'], fontSize=8, fontName='Helvetica')

    # Encabezado
    elements.append(Paragraph(datos_negocio.get("nombre_comercial", ""), style_title))
    elements.append(Paragraph(f"Reporte de VENTAS por VENDEDOR desde: {fecha_inicio} al {fecha_fin}", style_subtitle))
    elements.append(Spacer(1, 2))
    elements.append(Paragraph(f"{vendedor['nombre']} — {vendedor['codigo']}", style_vendedor))
    elements.append(Spacer(1, 6))

    # Tabla de ventas por cliente
    col_widths = [65, 55, 55, 170, 45, 60, 55, 55, 55]
    headers = ["Comprobante", "Valor Fact", "Facturó", "ITEM", "Cantidad", "P.Unitario", "Total", "% Comisión", "Comisión"]

    for cliente in clientes:
        elements.append(Paragraph(f"CLIENTE: {cliente['nombre']} - {cliente['dui']}", style_cliente))
        data = [headers]
        total_cliente = 0
        total_comision = 0
        for venta in cliente['ventas']:
            total = calcular_total(venta['cantidad'], venta['p_unitario'])
            comision = calcular_comision(total, venta['porc_comision'])
            total_cliente += total
            total_comision += comision
            data.append([
                venta['comprobante'],
                f"{venta['valor_fact']:.2f}",
                venta['facturo'],
                venta['item'],
                f"{venta['cantidad']:.2f}",
                f"{venta['p_unitario']:.6f}",
                f"{total:.2f}",
                venta['porc_comision'],
                f"{comision:.2f}"
            ])
        # Si no hay ventas, deja solo el encabezado
        if len(cliente['ventas']) == 0:
            data.append([""] * len(headers))
        # Tabla de ventas
        t = Table(data, colWidths=col_widths, repeatRows=1)
        t.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#f5f5f5")),
            ('TEXTCOLOR', (0,0), (-1,0), colors.HexColor("#222")),
            ('ALIGN', (0,0), (3,-1), 'LEFT'),
            ('ALIGN', (4,1), (-1,-1), 'RIGHT'),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTSIZE', (0,0), (-1,0), 9),
            ('FONTSIZE', (0,1), (-1,-1), 8),
            ('BOTTOMPADDING', (0,0), (-1,0), 5),
            ('TOPPADDING', (0,0), (-1,0), 3),
            ('GRID', (0,0), (-1,-1), 0.4, colors.grey),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ]))
        elements.append(t)
        # Totales del cliente
        if len(cliente['ventas']) > 0:
            total_tabla = Table([
                ["", "", "", "", "", "TOTAL:", f"{total_cliente:.2f}", "", f"{total_comision:.2f}"]
            ], colWidths=col_widths)
            total_tabla.setStyle(TableStyle([
                ('SPAN', (0,0), (5,0)),
                ('ALIGN', (6,0), (6,0), 'RIGHT'),
                ('ALIGN', (8,0), (8,0), 'RIGHT'),
                ('FONTNAME', (5,0), (8,0), 'Helvetica-Bold'),
                ('FONTSIZE', (5,0), (8,0), 9),
                ('TEXTCOLOR', (5,0), (8,0), colors.HexColor("#1a237e")),
                ('TOPPADDING', (0,0), (-1,0), 2),
                ('BOTTOMPADDING', (0,0), (-1,0), 2),
            ]))
            elements.append(total_tabla)
        elements.append(Spacer(1, 10))

    # Pie de página personalizado
    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont('Helvetica', 8)
        # Fecha en esquina inferior derecha
        canvas.drawRightString(doc.pagesize[0] - doc.rightMargin, 18, f"{fecha_reporte} Página {doc.page}")
        canvas.restoreState()

    doc.build(elements, onFirstPage=footer, onLaterPages=footer)

class VentanaDemo(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Demo Estado de Ventas PDF")
        layout = QVBoxLayout()
        btn = QPushButton("Generar PDF de ejemplo")
        btn.clicked.connect(self.generar_pdf_ejemplo)
        layout.addWidget(btn)
        self.setLayout(layout)
        self.resize(350, 100)

    def generar_pdf_ejemplo(self):
        filename = "estado_ventas_demo.pdf"
        try:
            generar_estado_ventas_pdf(filename)
            QMessageBox.information(self, "PDF generado", f"El PDF se generó correctamente:\n{filename}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error al generar PDF:\n{e}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    ventana = VentanaDemo()
    ventana.show()
    sys.exit(app.exec_())