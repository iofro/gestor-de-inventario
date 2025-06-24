from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QTableView, QLineEdit,
    QPushButton, QTabWidget, QMessageBox, QSplitter, QMenuBar, QAction, QFileDialog,
    QListWidget, QInputDialog, QLabel, QComboBox, QTreeWidget, QTreeWidgetItem, QTableWidget, QTableWidgetItem, QDialog,
    QDateEdit, QCheckBox, QHeaderView
)
from PyQt5.QtCore import Qt, QDate
from PyQt5.QtGui import QColor

STOCK_THRESHOLD = 5
import os
import json
from inventory_manager import InventoryManager
from dialogs import RegisterSaleDialog, ClienteSelectorDialog, ProductDialog, RegisterPurchaseDialog, DistribuidorDialog, ClienteDialog
from datetime import datetime
from num2words import num2words  # Instala con: pip install num2words
from factura_sv import generar_factura_electronica_pdf
from decimal import Decimal, ROUND_HALF_UP
import logging

logger = logging.getLogger(__name__)

def redondear(valor):
    return float(Decimal(str(valor)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

def monto_a_texto_sv(monto):
    """
    Convierte un monto a texto en formato fiscal salvadoreño:
    174.50 -> "CIENTO SETENTA Y CUATRO 50/100 DÓLARES"
    """
    entero = int(monto)
    centavos = int(round((monto - entero) * 100))
    palabras = num2words(entero, lang='es').upper()
    return f"{palabras} {centavos:02d}/100 DÓLARES"

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Inventario Farmacia")
        self.resize(1200, 700)
        self.manager = InventoryManager()
        self.ultimo_archivo_json = None  # Guarda la ruta del último archivo .json usado
        # Configuración de la aplicación
        self.config_path = "config.json"
        self.theme = "light"
        self._load_config()
        self._setup_ui()
        self._update_tema_action_text()
        self._apply_styles()

    def _load_config(self):
        """Carga las preferencias de la aplicación desde config.json"""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.theme = data.get("theme", "light")
            except Exception:
                self.theme = "light"

    def _save_config(self):
        """Guarda las preferencias de la aplicación"""
        data = {"theme": self.theme}
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _update_tema_action_text(self):
        if hasattr(self, "toggle_tema_action"):
            if self.theme == "light":
                self.toggle_tema_action.setText("Tema oscuro")
            else:
                self.toggle_tema_action.setText("Tema claro")

    def generar_factura_pdf(self):
        row = self.historial_ventas_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Factura", "Seleccione una venta del historial.")
            return

        venta_id_item = self.historial_ventas_table.item(row, 5)
        if not venta_id_item:
            QMessageBox.warning(self, "Factura", "No se encontró el ID de la venta seleccionada.")
            return
        venta_id = int(venta_id_item.text())

        ventas = self.manager.db.get_ventas()
        venta = next((v for v in ventas if v.get("id") == venta_id), None)
        if not venta:
            QMessageBox.warning(self, "Factura", "No se encontró la venta seleccionada.")
            return

        self.manager.db.cursor.execute("SELECT * FROM ventas_credito_fiscal WHERE venta_id=?", (venta_id,))
        vcf = self.manager.db.cursor.fetchone()
        if vcf:
            for key in vcf.keys():
                venta[key] = vcf[key]

        vendedor_nombre = ""
        if venta.get("vendedor_id"):
            vendedor = next((v for v in self.manager.db.get_trabajadores() if v["id"] == venta.get("vendedor_id")), None)
            if vendedor:
                vendedor_nombre = vendedor.get("nombre", "")
        venta["vendedor_nombre"] = vendedor_nombre

        detalles = self.manager.db.get_detalles_venta(venta["id"])
        if not detalles:
            detalles = self.manager.db.get_detalles_venta(venta_id)

        productos_dict = {int(p["id"]): p for p in self.manager.db.get_productos()}
        detalles_pdf = []
        
        for d in detalles:
            producto_id = int(d.get("producto_id", 0))
            prod = productos_dict.get(producto_id)
            tipo_fiscal = (d.get("tipo_fiscal") or "gravada").strip().lower()
            cantidad = d.get("cantidad", 0)
            precio_unitario = d.get("precio_unitario", 0)
            iva_tipo = d.get("iva_tipo", "desglosado").lower()
            precio_con_iva = d.get("precio_con_iva", 0)

            if iva_tipo == "desglosado" and tipo_fiscal in ["venta gravada", "gravada"]:
                # --- CAMBIO: Usa SIEMPRE el precio_con_iva guardado, sin recalcular ---
                iva_unitario = round(precio_con_iva - precio_unitario, 2)
                ventas_gravadas = round(precio_unitario * cantidad, 2)
                iva_total = round(iva_unitario * cantidad, 2)
            else:
                iva_unitario = d.get("iva", 0)
                ventas_gravadas = round(precio_unitario * cantidad, 2) if tipo_fiscal in ["venta gravada", "gravada"] else 0
                iva_total = round(iva_unitario * cantidad, 2) if tipo_fiscal in ["venta gravada", "gravada"] else 0

            ventas_exentas = round(precio_unitario * cantidad, 2) if tipo_fiscal in ["venta exenta", "exenta"] else 0
            ventas_no_sujetas = round(precio_unitario * cantidad, 2) if tipo_fiscal in ["venta no sujeta", "no sujeta"] else 0

            detalles_pdf.append({
                "descripcion": prod.get("nombre", f"ID {producto_id}") if prod else f"ID {producto_id}",
                "codigo": prod.get("codigo", "") if prod else "",
                "cantidad": cantidad,
                "precio_unitario": precio_unitario,
                "ventas_gravadas": ventas_gravadas,
                "ventas_exentas": ventas_exentas,
                "ventas_no_sujetas": ventas_no_sujetas,
                "tipo_fiscal": tipo_fiscal,
                "iva": iva_total,
                "iva_tipo": iva_tipo
            })
            
        cliente = next((c for c in self.manager._clientes if c["id"] == venta.get("cliente_id")), {})
        distribuidor = next((d for d in self.manager._Distribuidores if d["id"] == venta.get("Distribuidor_id")), {})

        if not venta.get("nit"):
            venta["nit"] = cliente.get("nit", "")
        if not venta.get("venta_a_cuenta_de"):
            venta["venta_a_cuenta_de"] = cliente.get("nombre", "")

        sumas = round(sum(d["ventas_gravadas"] for d in detalles_pdf), 2)
        ventas_exentas = round(sum(d["ventas_exentas"] for d in detalles_pdf), 2)
        ventas_no_sujetas = round(sum(d["ventas_no_sujetas"] for d in detalles_pdf), 2)
        iva = round(sum(d.get("iva", 0) for d in detalles_pdf), 2)
        subtotal = round(sumas + ventas_exentas + ventas_no_sujetas, 2)

        total = round(sumas + iva + ventas_exentas + ventas_no_sujetas, 2)

        venta["sumas"] = sumas
        venta["ventas_exentas"] = ventas_exentas
        venta["ventas_no_sujetas"] = ventas_no_sujetas
        venta["iva"] = iva
        venta["subtotal"] = subtotal
        venta["total"] = total
        venta["total_operacion"] = total  # Para el PDF
        venta["descuentos_globales"] = 0  # Si tienes descuentos globales, cámbialo aquí
        venta["total_letras"] = monto_a_texto_sv(total)

        # --- Diálogo con botones personalizados ---
        msg = QMessageBox(self)
        msg.setWindowTitle("Tipo de factura")
        msg.setText("¿Qué tipo de factura desea generar?")
        btn_consumidor = msg.addButton("Consumidor Final", QMessageBox.YesRole)
        btn_fiscal = msg.addButton("Crédito Fiscal", QMessageBox.NoRole)
        msg.setDefaultButton(btn_consumidor)
        msg.exec_()
        if msg.clickedButton() == btn_consumidor:
            ruta, _ = QFileDialog.getSaveFileName(self, "Guardar factura PDF", f"factura_{venta['id']}_consumidor_final.pdf", "PDF Files (*.pdf)")
            if not ruta:
                return
            from factura_sv import imprimir_factura_consumidor_final
            imprimir_factura_consumidor_final(venta, detalles_pdf, cliente, distribuidor, archivo=ruta)
            QMessageBox.information(self, "Factura", f"Factura PDF de consumidor final generada en:\n{ruta}")
        else:
            ruta, _ = QFileDialog.getSaveFileName(self, "Guardar factura PDF", f"factura_{venta['id']}_credito_fiscal.pdf", "PDF Files (*.pdf)")
            if not ruta:
                return
            
            from factura_sv import generar_factura_electronica_pdf

            factura = {
                "encabezado": {
                    "tipo_documento": "Factura",
                    "numero_documento": f"F-{venta.get('id', '')}",
                    "modelo_facturacion": "Electrónico"
                },
                "emisor": {
                    "nombre": distribuidor.get("nombre", ""),
                    "direccion": distribuidor.get("direccion", ""),
                    "nit": distribuidor.get("nit", ""),
                    "nrc": distribuidor.get("nrc", ""),
                    "correo": distribuidor.get("email", ""),
                    "telefono": distribuidor.get("telefono", ""),
                    "actividad_economica": distribuidor.get("giro", "")
                },
                "receptor": {
                    "nombre": cliente.get("nombre", ""),
                    "direccion": cliente.get("direccion", ""),
                    "telefono": cliente.get("telefono", ""),
                    "correo": cliente.get("email", ""),
                    "nrc": cliente.get("nrc", "")
                },
                "control_fiscal": {
                    "codigo_generacion": venta.get("codigo_generacion", ""),
                    "numero_control": venta.get("numero_control", ""),
                    "sello_recepcion": venta.get("sello_recepcion", ""),
                    "fecha_hora_emision": venta.get("fecha", "")
                },
                "detalle_productos": [
                    {
                        "no": i+1,
                        "cantidad": d["cantidad"],
                        "descripcion": d["descripcion"],
                        "precio_unitario": d["precio_unitario"],
                        "ventas_gravadas": d["ventas_gravadas"],
                        "exentas": d["ventas_exentas"],
                        "no_sujetas": d["ventas_no_sujetas"],
                        "otros_montos": 0
                    }
                    for i, d in enumerate(detalles_pdf)
                ],
                "totales": {
                    "sumas": venta.get("sumas", 0),
                    "subtotal": venta.get("subtotal", 0),
                    "total_operacion": venta.get("total", 0),
                    "total_a_pagar": venta.get("total", 0),
                    "valor_letras": venta.get("total_letras", "")
                },
                "otros": {
                    "condicion_pago": venta.get("condicion_pago", ""),
                    "codigo_guia": "",
                    "codigo_transaccion": ""
                },
                "pie_pagina": {
                    "numero_pagina": 1,
                    "notas": "Documento válido para efectos fiscales según la ley."
                }
            }
            

            from factura_sv import generar_factura_electronica_pdf
            generar_factura_electronica_pdf(venta, detalles_pdf, cliente, distribuidor, archivo=ruta)
            QMessageBox.information(self, "Factura", f"Factura PDF de crédito fiscal generada en:\n{ruta}")


    def _generar_texto_factura_matricial(self, venta, detalles, cliente, distribuidor):
        """Genera el texto plano de la factura para impresoras matriciales."""

        def coordenada_a_texto_raw(x_cm, y_cm, texto, ancho_char_cm=0.25, alto_linea_cm=0.40):
            espacios = int(x_cm / ancho_char_cm)
            saltos = int(y_cm / alto_linea_cm)
            return ("\n" * saltos) + (" " * espacios) + str(texto) + "\n"

        factura_raw = ""

        # Encabezado
        factura_raw += coordenada_a_texto_raw(4.45, 4.80, cliente.get("nombre", ""))
        factura_raw += coordenada_a_texto_raw(4.45, 5.40, cliente.get("direccion", ""))
        factura_raw += coordenada_a_texto_raw(3.81, 6.40, venta.get("fecha_remision", ""))
        factura_raw += coordenada_a_texto_raw(3.81, 6.90, venta.get("giro", ""))
        factura_raw += coordenada_a_texto_raw(3.81, 7.50, venta.get("fecha_remision_anterior", ""))
        factura_raw += coordenada_a_texto_raw(4.45, 8.00, venta.get("condicion_pago", ""))
        factura_raw += coordenada_a_texto_raw(4.45, 8.50, venta.get("vendedor_nombre", ""))
        factura_raw += coordenada_a_texto_raw(7.62, 6.40, venta.get("nrc", ""))
        factura_raw += coordenada_a_texto_raw(7.62, 7.50, venta.get("no_remision", ""))
        factura_raw += coordenada_a_texto_raw(11.43, 6.40, venta.get("nit", ""))
        factura_raw += coordenada_a_texto_raw(12.07, 7.50, venta.get("orden_no", ""))
        factura_raw += coordenada_a_texto_raw(11.43, 8.00, venta.get("venta_a_cuenta_de", ""))
        factura_raw += coordenada_a_texto_raw(11.75, 8.50, venta.get("fecha", ""))

        # Detalle de productos
        y_base = 10.10
        row_height = 0.6
        for i, d in enumerate(detalles):
            y = y_base + i * row_height
            factura_raw += coordenada_a_texto_raw(2.22, y, str(d.get("cantidad", "")))
            factura_raw += coordenada_a_texto_raw(3.90, y, d.get("descripcion", ""))
            factura_raw += coordenada_a_texto_raw(9.21, y, f"{d.get('precio_unitario', 0):.2f}")
            factura_raw += coordenada_a_texto_raw(11.11, y, f"{d.get('ventas_exentas', 0):.2f}")
            factura_raw += coordenada_a_texto_raw(12.70, y, f"{d.get('ventas_no_sujetas', 0):.2f}")
            factura_raw += coordenada_a_texto_raw(14.10, y, f"{d.get('ventas_gravadas', 0):.2f}")

        # Totales y resumen fiscal
        factura_raw += coordenada_a_texto_raw(2.22, 22.23, venta.get("total_letras", ""))
        factura_raw += coordenada_a_texto_raw(14.10, 21.59, f"{venta.get('sumas', 0):.2f}")
        factura_raw += coordenada_a_texto_raw(14.10, 22.23, f"{venta.get('iva', 0):.2f}")
        factura_raw += coordenada_a_texto_raw(14.10, 22.86, f"{venta.get('subtotal', 0):.2f}")
        factura_raw += coordenada_a_texto_raw(14.10, 23.45, f"{venta.get('descuentos_globales', 0):.2f}")
        factura_raw += coordenada_a_texto_raw(14.10, 24.00, f"{venta.get('ventas_exentas', 0):.2f}")
        factura_raw += coordenada_a_texto_raw(14.10, 24.60, f"{venta.get('ventas_no_sujetas', 0):.2f}")
        factura_raw += coordenada_a_texto_raw(14.10, 25.08, f"{venta.get('total', 0):.2f}")

        return factura_raw

    def imprimir_factura_prueba(self):
        """Imprime una factura de crédito fiscal con datos de prueba."""
        venta = {
            "fecha": "23/06/2025",
            "giro": "Venta de productos farmacéuticos",
            "fecha_remision": "21/06/2025",
            "condicion_pago": "Crédito 30 días",
            "vendedor_nombre": "Luis Ramírez",
            "nrc": "123456-7",
            "no_remision": "004587",
            "nit": "0614-260991-101-0",
            "orden_no": "000324",
            "venta_a_cuenta_de": "Distribuidora Centroamericana",
            "fecha_remision_anterior": "15/06/2025",
            "sumas": 34.00,
            "iva": 4.42,
            "subtotal": 38.42,
            "ventas_no_sujetas": 0.00,
            "ventas_exentas": 0.00,
            "total": 38.42,
            "descuentos_globales": 0.00,
            "total_letras": "Treinta y cuatro dólares con cero centavos",
        }

        cliente = {
            "nombre": "Comercial La Nueva Era S.A.",
            "direccion": "Calle El Progreso #123, San Salvador",
        }

        detalles = [
            {
                "cantidad": 10,
                "descripcion": "Acetaminofén 500mg caja x100",
                "precio_unitario": 2.50,
                "ventas_gravadas": 25.00,
                "ventas_no_sujetas": 0.00,
                "ventas_exentas": 0.00,
            },
            {
                "cantidad": 5,
                "descripcion": "Alcohol gel 500ml",
                "precio_unitario": 1.80,
                "ventas_gravadas": 9.00,
                "ventas_no_sujetas": 0.00,
                "ventas_exentas": 0.00,
            },
        ]

        texto = self._generar_texto_factura_matricial(venta, detalles, cliente, {})

        import win32print
        from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel, QComboBox, QPushButton, QMessageBox

        class PrinterDialog(QDialog):
            def __init__(self, parent=None):
                super().__init__(parent)
                self.setWindowTitle("Seleccionar impresora")
                layout = QVBoxLayout()
                layout.addWidget(QLabel("Seleccione una impresora:"))
                self.printer_combo = QComboBox()
                printers = win32print.EnumPrinters(
                    win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
                )
                self.printer_combo.addItems([p[2] for p in printers])
                layout.addWidget(self.printer_combo)
                btn_ok = QPushButton("Imprimir")
                btn_ok.clicked.connect(self.accept)
                layout.addWidget(btn_ok)
                self.setLayout(layout)

            def get_selected_printer(self):
                return self.printer_combo.currentText()

        dlg = PrinterDialog(self)
        if not dlg.exec_():
            return
        printer_name = dlg.get_selected_printer()
        if not printer_name:
            return
        try:
            SLIP_MODE = b"\x1B\x69"
            hprinter = win32print.OpenPrinter(printer_name)
            win32print.StartDocPrinter(hprinter, 1, ("Factura RAW", None, "RAW"))
            win32print.StartPagePrinter(hprinter)
            win32print.WritePrinter(hprinter, SLIP_MODE + texto.encode("utf-8"))
            win32print.EndPagePrinter(hprinter)
            win32print.EndDocPrinter(hprinter)
            win32print.ClosePrinter(hprinter)
            QMessageBox.information(self, "Impresión", "Factura de prueba enviada a la impresora.")
        except Exception as e:
            QMessageBox.critical(self, "Error de impresión", str(e))

    def _setup_ui(self):
        # --- BARRA SUPERIOR HORIZONTAL ---
        menubar = QMenuBar(self)
        self.setMenuBar(menubar)

        # Menú Archivo
        archivo_menu = menubar.addMenu("Archivo")
        nuevo_inventario_action = QAction("Nuevo inventario", self)
        nuevo_inventario_action.triggered.connect(self.nuevo_inventario)
        guardar_como_action = QAction("Guardar como...", self)
        guardar_como_action.triggered.connect(self.guardar_como)
        cargar_inventario_action = QAction("Cargar inventario...", self)
        cargar_inventario_action.triggered.connect(self.cargar_inventario)
        archivo_menu.addAction(nuevo_inventario_action)
        archivo_menu.addAction(guardar_como_action)
        archivo_menu.addAction(cargar_inventario_action)

        # --- NUEVO MENÚ CONFIGURACIÓN ---
        configuracion_menu = menubar.addMenu("Configuración")
        datos_negocio_action = QAction("Datos del negocio", self)
        datos_negocio_action.triggered.connect(self._abrir_datos_negocio)
        configuracion_menu.addAction(datos_negocio_action)
        # Opción para alternar tema claro/oscuro
        self.toggle_tema_action = QAction("", self)
        self.toggle_tema_action.triggered.connect(self._toggle_tema)
        configuracion_menu.addAction(self.toggle_tema_action)

        # --- BOTONES LATERALES ---
        self.btn_add_product = QPushButton("Agregar Producto")
        self.btn_add_product.setObjectName("btn_add_product")
        self.btn_add_product.setToolTip("Agregar un nuevo producto al inventario")
        self.btn_edit_product = QPushButton("Editar Producto")
        self.btn_edit_product.setObjectName("btn_edit_product")
        self.btn_edit_product.setToolTip("Editar el producto seleccionado")
        self.btn_register_sale = QPushButton("Registrar Venta")
        self.btn_register_sale.setObjectName("btn_register_sale")
        self.btn_register_sale.setToolTip("Registrar una venta")
        # Botón con salto de línea para que el texto quepa bien
        self.btn_register_credito_fiscal = QPushButton("Registrar Venta\nCrédito Fiscal")
        self.btn_register_credito_fiscal.setObjectName("btn_register_credito_fiscal")
        self.btn_register_credito_fiscal.setToolTip("Registrar una venta a crédito fiscal")
        self.btn_register_purchase = QPushButton("Registrar Compra")
        self.btn_register_purchase.setObjectName("btn_register_purchase")
        self.btn_register_purchase.setToolTip("Registrar una compra")
        self.btn_delete_product = QPushButton("Eliminar Producto")
        self.btn_delete_product.setObjectName("btn_delete_product")
        self.btn_delete_product.setToolTip("Eliminar el producto seleccionado")
        self.btn_guardar_rapido = QPushButton("Guardar\nRápido")
        self.btn_guardar_rapido.setObjectName("btn_guardar_rapido")
        self.btn_guardar_rapido.setToolTip("Guardar inventario rápidamente")
        self.btn_cargar_inventario = QPushButton("Cargar Inventario")
        self.btn_cargar_inventario.setObjectName("btn_cargar_inventario")
        self.btn_cargar_inventario.setToolTip("Cargar inventario desde un archivo")

        # Botones más pequeños
        for btn in [
            self.btn_add_product, self.btn_edit_product, self.btn_register_sale,
            self.btn_register_credito_fiscal, self.btn_register_purchase,
            self.btn_guardar_rapido, self.btn_cargar_inventario, self.btn_delete_product
        ]:
            btn.setMinimumHeight(24)
            btn.setMaximumHeight(28)
            btn.setMinimumWidth(140)
            btn.setMaximumWidth(200)
            # estilos definidos en style.qss


        btn_layout = QVBoxLayout()
        btn_layout.addWidget(self.btn_add_product)
        btn_layout.addWidget(self.btn_edit_product)
        btn_layout.addWidget(self.btn_register_sale)
        btn_layout.addWidget(self.btn_register_credito_fiscal)
        btn_layout.addWidget(self.btn_register_purchase)
        # Botones verdes debajo de los celestes pero encima del rojo
        btn_layout.addWidget(self.btn_guardar_rapido)
        btn_layout.addWidget(self.btn_cargar_inventario)
        btn_layout.addStretch(1)
        btn_layout.addWidget(self.btn_delete_product)

        btn_widget = QWidget()
        btn_widget.setLayout(btn_layout)
        btn_widget.setMaximumWidth(220)  # Puedes ajustar el ancho máximo si lo deseas

        # --- Splitter y pestaña de inventario ---
        main_layout = QVBoxLayout()
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Buscar por nombre o código...")
        self.search_bar.textChanged.connect(self.filter_products)
        main_layout.addWidget(self.search_bar)

        # --- Filtros en una sola fila ---
        filtros_layout = QHBoxLayout()
        self.vendedor_combo_filtro = QComboBox()
        self.vendedor_combo_filtro.addItem("Todos")
        self.vendedor_combo_filtro.addItems(self.manager.get_vendedor_names())
        self.vendedor_combo_filtro.currentIndexChanged.connect(self.filter_products)
        filtros_layout.addWidget(QLabel("Vendedor:"))
        filtros_layout.addWidget(self.vendedor_combo_filtro)

        self.stock_sort_combo = QComboBox()
        self.stock_sort_combo.addItems(["Ordenar por stock", "Más stock a menos", "Menos stock a más"])
        self.stock_sort_combo.currentIndexChanged.connect(self.filter_products)
        filtros_layout.addWidget(QLabel("Stock:"))
        filtros_layout.addWidget(self.stock_sort_combo)

        filtros_layout.addStretch(1)
        main_layout.addLayout(filtros_layout)

        self.product_table = QTableView()
        self.product_table.setAlternatingRowColors(True)
        header = self.product_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)
        self.product_table.setModel(self.manager.get_products_model())
        self.product_table.setSelectionBehavior(QTableView.SelectRows)
        self.product_table.setSelectionMode(QTableView.SingleSelection)
        self.product_table.clicked.connect(self._on_table_clicked)
        self.selected_row = None
        main_layout.addWidget(self.product_table)

        main_widget = QWidget()
        main_widget.setLayout(main_layout)
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(btn_widget)
        splitter.addWidget(main_widget)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 4)
        splitter.setChildrenCollapsible(False)
        tab_widget = QWidget()
        tab_layout = QVBoxLayout()
        tab_layout.addWidget(splitter)
        tab_widget.setLayout(tab_layout)

        # --- PESTAÑA DE vendEGORÍAS Y DistribuidorES ---
        vend_dist_tab = QWidget()
        vend_dist_layout = QVBoxLayout()

        # Barra de búsqueda para vendedores y distribuidores
        self.vend_dist_search = QLineEdit()
        self.vend_dist_search.setPlaceholderText("Buscar...")
        self.vend_dist_search.textChanged.connect(self._filtrar_vend_dist)
        vend_dist_layout.addWidget(self.vend_dist_search)

        vend_dist_content = QHBoxLayout()

        # Vendedores
        vend_layout = QVBoxLayout()
        vend_layout.addWidget(QLabel("Vendedores"))
        self.vendedores_tree = QTreeWidget()
        self.vendedores_tree.setHeaderHidden(True)
        vend_layout.addWidget(self.vendedores_tree)
        btn_add_vend = QPushButton("Añadir Vendedor")
        btn_add_vend.setObjectName("btn_add_vend")
        btn_add_vend.setToolTip("Añadir un nuevo vendedor")
        btn_add_vend.setMinimumHeight(24)
        btn_add_vend.setMaximumHeight(28)
        btn_add_vend.clicked.connect(self._agregar_vendedor)
        vend_layout.addWidget(btn_add_vend)

        btn_edit_vend = QPushButton("Editar Vendedor")
        btn_edit_vend.setObjectName("btn_edit_vend")
        btn_edit_vend.setToolTip("Editar el vendedor seleccionado")
        btn_edit_vend.setMinimumHeight(24)
        btn_edit_vend.setMaximumHeight(28)
        btn_edit_vend.clicked.connect(self._editar_vendedor)
        vend_layout.addWidget(btn_edit_vend)

        vend_dist_content.addLayout(vend_layout)

        # Distribuidores -> Distribuidores
        dist_layout = QVBoxLayout()
        dist_layout.addWidget(QLabel("Distribuidores"))  # <--- Cambia aquí
        self.Distribuidores_tree = QTreeWidget()         # <--- Cambia el nombre de la variable también (opcional, pero recomendado)
        self.Distribuidores_tree.setHeaderHidden(True)
        dist_layout.addWidget(self.Distribuidores_tree)

        btns_h_layout = QHBoxLayout()
        btn_add_dist = QPushButton("Añadir Distribuidor")
        btn_add_dist.setObjectName("btn_add_dist")
        btn_add_dist.setToolTip("Añadir un nuevo distribuidor")
        btn_add_dist.setMinimumHeight(24)
        btn_add_dist.setMaximumHeight(28)
        btn_add_dist.clicked.connect(self._agregar_Distribuidor)
        btns_h_layout.addWidget(btn_add_dist, alignment=Qt.AlignLeft)

        btn_info_dist = QPushButton("Info de Distribuidor")
        btn_info_dist.setObjectName("btn_info_dist")
        btn_info_dist.setToolTip("Mostrar información del distribuidor")
        btn_info_dist.setFixedHeight(24)
        btn_info_dist.setFixedWidth(110)
        btn_info_dist.clicked.connect(self._mostrar_info_Distribuidor)
        btns_h_layout.addWidget(btn_info_dist, alignment=Qt.AlignRight)

        dist_layout.addLayout(btns_h_layout)

        btn_edit_dist = QPushButton("Editar Distribuidor")
        btn_edit_dist.setObjectName("btn_edit_dist")
        btn_edit_dist.setToolTip("Editar el distribuidor seleccionado")
        btn_edit_dist.setMinimumHeight(24)
        btn_edit_dist.setMaximumHeight(28)
        btn_edit_dist.clicked.connect(self._editar_Distribuidor)
        dist_layout.addWidget(btn_edit_dist)

        vend_dist_content.addLayout(dist_layout)

        vend_dist_layout.addLayout(vend_dist_content)
        vend_dist_tab.setLayout(vend_dist_layout)

        # --- PESTAÑA DE CLIENTES ---
        clientes_tab = QWidget()
        clientes_layout = QVBoxLayout()

        # Barra de búsqueda
        self.cliente_search = QLineEdit()
        self.cliente_search.setPlaceholderText("Buscar cliente por nombre, código, NIT, etc.")
        clientes_layout.addWidget(self.cliente_search)

        # Tabla de clientes
        self.clientes_table = QTableWidget(0, 10)
        self.clientes_table.setHorizontalHeaderLabels([
            "Código", "Nombre", "NRC", "NIT", "DUI", "Giro", "Teléfono", "Correo", "Departamento", "Municipio"
        ])
        clientes_layout.addWidget(self.clientes_table)

        # Botones
        btns = QHBoxLayout()
        self.btn_add_cliente = QPushButton("Agregar Cliente")
        self.btn_add_cliente.setToolTip("Agregar un nuevo cliente")
        self.btn_edit_cliente = QPushButton("Editar Cliente")
        self.btn_edit_cliente.setToolTip("Editar el cliente seleccionado")
        self.btn_delete_cliente = QPushButton("Eliminar Cliente")
        self.btn_delete_cliente.setToolTip("Eliminar el cliente seleccionado")
        btns.addWidget(self.btn_add_cliente)
        btns.addWidget(self.btn_edit_cliente)
        btns.addWidget(self.btn_delete_cliente)
        clientes_layout.addLayout(btns)

        clientes_tab.setLayout(clientes_layout)

        # --- PESTAÑA DE HISTORIAL ---
        historial_tab = QWidget()
        historial_layout = QVBoxLayout()

        # Filtros por mes y año
        filtros_historial_layout = QHBoxLayout()
        
        self.ventas_mes_filtro = QDateEdit(QDate.currentDate())
        self.ventas_mes_filtro.setDisplayFormat("MMMM yyyy")
        self.ventas_mes_filtro.setCalendarPopup(True)
        self.ventas_mes_filtro.setMinimumWidth(140)
        self.ventas_mes_filtro.setMaximumWidth(180)
        self.ventas_mes_filtro.setDate(QDate.currentDate())
        self.ventas_mes_filtro.setSpecialValueText("Todas")
        self.ventas_mes_filtro.setDate(QDate(2000, 1, 1))  # Valor especial para "Todas"
        self.ventas_mes_filtro.setMinimumDate(QDate(2000, 1, 1))
        filtros_historial_layout.addWidget(QLabel("Ver ventas de:"))
        filtros_historial_layout.addWidget(self.ventas_mes_filtro)

        self.compras_mes_filtro = QDateEdit(QDate.currentDate())
        self.compras_mes_filtro.setDisplayFormat("MMMM yyyy")
        self.compras_mes_filtro.setCalendarPopup(True)
        self.compras_mes_filtro.setMinimumWidth(140)
        self.compras_mes_filtro.setMaximumWidth(180)
        self.compras_mes_filtro.setDate(QDate.currentDate())
        self.compras_mes_filtro.setSpecialValueText("Todas")
        self.compras_mes_filtro.setDate(QDate(2000, 1, 1))  # Valor especial para "Todas"
        self.compras_mes_filtro.setMinimumDate(QDate(2000, 1, 1))
        filtros_historial_layout.addWidget(QLabel("Ver compras de:"))
        filtros_historial_layout.addWidget(self.compras_mes_filtro)

        # Barra de búsqueda para historial
        self.historial_search = QLineEdit()
        self.historial_search.setPlaceholderText("Buscar en historial...")
        self.historial_search.textChanged.connect(self._actualizar_historial)
        filtros_historial_layout.addWidget(self.historial_search)

        # --- AGREGA EL BOTÓN "Ver todo" ---
        self.btn_ver_todo_historial = QPushButton("Ver todo")
        self.btn_ver_todo_historial.setToolTip("Mostrar todo el historial")
        self.btn_ver_todo_historial.setMinimumWidth(100)
        filtros_historial_layout.addWidget(self.btn_ver_todo_historial)

        historial_layout.addLayout(filtros_historial_layout)

        # Layout horizontal para tablas y totales
        tablas_totales_layout = QHBoxLayout()

        # Tabla de historial de ventas
        ventas_layout = QVBoxLayout()
        self.historial_ventas_table = QTableWidget(0, 6)
        self.historial_ventas_table.setAlternatingRowColors(True)
        header = self.historial_ventas_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)
        self.historial_ventas_table.setHorizontalHeaderLabels([
            "Fecha", "Cliente", "Total", "Productos", "Distribuidor", "ID"
        ])
        self.historial_ventas_table.setColumnHidden(5, True)

        ventas_layout.addWidget(QLabel("Historial de Ventas"))
        ventas_layout.addWidget(self.historial_ventas_table)
        self.total_ingresos_label = QLabel("Total ingresos: $0.00")
        ventas_layout.addWidget(self.total_ingresos_label, alignment=Qt.AlignRight)
        self.btn_generar_factura = QPushButton("Generar factura PDF")
        self.btn_generar_factura.setToolTip("Generar la factura en formato PDF")
        self.btn_generar_factura.clicked.connect(self.generar_factura_pdf)
        ventas_layout.addWidget(self.btn_generar_factura)
        self.btn_prueba_impresion = QPushButton("🖨️ Prueba de impresión")
        self.btn_prueba_impresion.setToolTip("Imprimir una prueba de factura")
        self.btn_prueba_impresion.clicked.connect(self.imprimir_factura_prueba)
        ventas_layout.addWidget(self.btn_prueba_impresion)
        tablas_totales_layout.addLayout(ventas_layout)

        # Tabla de historial de compras
        self.historial_compras_table = QTableWidget(0, 7)
        self.historial_compras_table.setAlternatingRowColors(True)
        header = self.historial_compras_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)
        self.historial_compras_table.setHorizontalHeaderLabels([
            "Fecha", "Distribuidor", "Vendedor", "Total", "Comisión", "Productos", "ID"
        ])
        self.historial_compras_table.setColumnHidden(6, True)  # Oculta la columna ID

        compras_layout = QVBoxLayout()
        compras_layout.addWidget(QLabel("Historial de Compras"))
        compras_layout.addWidget(self.historial_compras_table)
        self.total_gastos_label = QLabel("Total gastos: $0.00")
        compras_layout.addWidget(self.total_gastos_label, alignment=Qt.AlignRight)
        tablas_totales_layout.addLayout(compras_layout)

        # ...dentro de _setup_ui, después de crear la tabla de historial de compras...
        self.historial_compras_table.itemDoubleClicked.connect(self.mostrar_detalle_compra)

        historial_layout.addLayout(tablas_totales_layout)
        historial_tab.setLayout(historial_layout)

        # --- PESTAÑA DE INVENTARIO ACTUAL ---
        inventario_actual_tab = QWidget()
        inventario_actual_layout = QVBoxLayout()

        # Filtros (opcional, puedes agregar por vendedor, categoría, Distribuidor, búsqueda, etc.)
        filtros_actual_layout = QHBoxLayout()
        self.actual_search_bar = QLineEdit()
        self.actual_search_bar.setPlaceholderText("Buscar por nombre o código...")
        filtros_actual_layout.addWidget(self.actual_search_bar)
        inventario_actual_layout.addLayout(filtros_actual_layout)

        # Tabla de inventario actual (por lote)
        self.inventario_actual_table = QTableWidget(0, 7)
        self.inventario_actual_table.setAlternatingRowColors(True)
        header = self.inventario_actual_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)
        self.inventario_actual_table.setHorizontalHeaderLabels([
            "Producto", "Código", "Cantidad", "Precio compra", "Fecha compra", "Fecha vencimiento", "Distribuidor"  # <--- Cambia aquí
        ])
        inventario_actual_layout.addWidget(self.inventario_actual_table)

        inventario_actual_tab.setLayout(inventario_actual_layout)

        # --- AGREGA LAS CUATRO PESTAÑAS AL QTabWidget ---
        self.tabs = QTabWidget()
        self.tabs.addTab(tab_widget, "Inventario")
        self.tabs.addTab(vend_dist_tab, "Vendedores y Distribuidores")  # <-- Esta línea es clave
        self.tabs.addTab(clientes_tab, "Clientes")
        self.tabs.addTab(historial_tab, "Historial")
        self.tabs.addTab(inventario_actual_tab, "Inventario actual")
        self.setCentralWidget(self.tabs)

        # --- PESTAÑA DE TRABAJADORES ---
        trabajadores_tab = QWidget()
        trabajadores_layout = QVBoxLayout()

        # Filtros
        filtro_layout = QHBoxLayout()
        self.trabajadores_filtro_vendedor = QCheckBox("Solo vendedores")
        self.trabajadores_filtro_vendedor.stateChanged.connect(self._actualizar_tabla_trabajadores)
        self.trabajadores_filtro_area = QLineEdit()
        self.trabajadores_filtro_area.setPlaceholderText("Filtrar por área/departamento")
        self.trabajadores_filtro_area.textChanged.connect(self._actualizar_tabla_trabajadores)
        self.trabajadores_search = QLineEdit()
        self.trabajadores_search.setPlaceholderText("Buscar trabajador...")
        self.trabajadores_search.textChanged.connect(self._actualizar_tabla_trabajadores)
        filtro_layout.addWidget(self.trabajadores_filtro_vendedor)
        filtro_layout.addWidget(self.trabajadores_filtro_area)
        filtro_layout.addWidget(self.trabajadores_search)
        trabajadores_layout.addLayout(filtro_layout)

        # Tabla
        self.trabajadores_table = QTableWidget(0, 9)
        self.trabajadores_table.setHorizontalHeaderLabels([
            "Nombre", "DUI", "NIT", "Nacimiento", "Cargo", "Área", "Teléfono", "Email", "¿Vendedor?"
        ])
        trabajadores_layout.addWidget(self.trabajadores_table)

        # Botones
        btns = QHBoxLayout()
        self.btn_add_trabajador = QPushButton("Agregar")
        self.btn_add_trabajador.setToolTip("Agregar un nuevo trabajador")
        self.btn_edit_trabajador = QPushButton("Editar")
        self.btn_edit_trabajador.setToolTip("Editar el trabajador seleccionado")
        self.btn_delete_trabajador = QPushButton("Eliminar")
        self.btn_delete_trabajador.setToolTip("Eliminar el trabajador seleccionado")
        btns.addWidget(self.btn_add_trabajador)
        btns.addWidget(self.btn_edit_trabajador)
        btns.addWidget(self.btn_delete_trabajador)
        trabajadores_layout.addLayout(btns)

        trabajadores_tab.setLayout(trabajadores_layout)
        self.tabs.addTab(trabajadores_tab, "Trabajadores")

        # Conexiones
        self.btn_add_trabajador.clicked.connect(self._agregar_trabajador)
        self.btn_edit_trabajador.clicked.connect(self._editar_trabajador)
        self.btn_delete_trabajador.clicked.connect(self._eliminar_trabajador)

        self._actualizar_tabla_trabajadores()

        # Conexiones
        self.btn_guardar_rapido.clicked.connect(self.guardar_rapido)
        self.btn_cargar_inventario.clicked.connect(self.cargar_inventario)
        self.btn_add_product.clicked.connect(self.agregar_producto)
        self.btn_edit_product.clicked.connect(self.editar_producto)
        self.btn_register_sale.clicked.connect(self.registrar_venta)
        self.btn_register_credito_fiscal.clicked.connect(self.registrar_venta_credito_fiscal)
        self.btn_register_purchase.clicked.connect(self.registrar_compra)
        self.btn_delete_product.clicked.connect(self.eliminar_producto)
        self.btn_add_cliente.clicked.connect(self._agregar_cliente)
        self.btn_edit_cliente.clicked.connect(self._editar_cliente)
        self.btn_delete_cliente.clicked.connect(self._eliminar_cliente)
        self.cliente_search.textChanged.connect(self._actualizar_tabla_clientes)
        self.ventas_mes_filtro.dateChanged.connect(self._actualizar_historial)
        self.compras_mes_filtro.dateChanged.connect(self._actualizar_historial)
        self.btn_ver_todo_historial.clicked.connect(self._limpiar_filtros_historial)
        self.actual_search_bar.textChanged.connect(self._actualizar_inventario_actual)
        self._actualizar_tabla_clientes()  # <-- SOLO AGREGA ESTA LÍNEA AL FINAL DE _setup_ui
        self._actualizar_inventario_actual()  # <-- AGREGA ESTA LÍNEA AL FINAL DE _setup_ui

        self.selected_row = None
        self._actualizar_inventario_actual()

    def _apply_styles(self):
        qss_file = "style_light.qss" if self.theme == "light" else "style_dark.qss"
        if os.path.exists(qss_file):
            try:
                with open(qss_file, "r", encoding="utf-8") as f:
                    self.setStyleSheet(f.read())
            except Exception:
                pass
        else:
            self.setStyleSheet("")
        # Si tienes el objectName para el botón de crédito fiscal, puedes agregarlo así:
        self.btn_register_credito_fiscal.setStyleSheet(
            "font-size:11px; min-width:200px; max-width:240px; min-height:26px; padding:6px 0;"
        )

    def _toggle_tema(self):
        """Alterna entre tema claro y oscuro"""
        self.theme = "dark" if self.theme == "light" else "light"
        self._update_tema_action_text()
        self._apply_styles()
        self._save_config()

    def filter_products(self):
        search = self.search_bar.text()
        vendedor_nombre = None
        vendedor_combo_index = self.vendedor_combo_filtro.currentIndex()
        if vendedor_combo_index > 0:  # Si no es "Todos"
            vendedor_nombre = self.vendedor_combo_filtro.itemText(vendedor_combo_index)

        # Orden por stock
        stock_sort = None
        if hasattr(self, "stock_sort_combo"):
            stock_sort = self.stock_sort_combo.currentIndex()

        self.manager.filter_products(vendedor_nombre=vendedor_nombre, search=search)
        productos = self.manager._products

        if stock_sort == 1:  # Más stock a menos
            productos = sorted(productos, key=lambda x: x.get("stock", 0), reverse=True)
        elif stock_sort == 2:  # Menos stock a más
            productos = sorted(productos, key=lambda x: x.get("stock", 0))

        self.manager._model.update_data(productos)
        self.product_table.setModel(self.manager.get_products_model())

    def agregar_producto(self):
        dialog = ProductDialog(self.manager._vendedores, self.manager._Distribuidores, self)
        if dialog.exec_():
            data = dialog.get_data()
            self.manager.add_producto(
                data["nombre"], data["codigo"], None, None,
                data["precio_compra"], data["precio_venta_minorista"], data["precio_venta_mayorista"], 0
            )
            self.manager.refresh_data()
            self._actualizar_arbol_vendedores()
            self._actualizar_arbol_Distribuidores()
            if hasattr(self, "vendedor_combo_filtro"):
                self.vendedor_combo_filtro.setCurrentIndex(0)
            self.filter_products()
            QMessageBox.information(self, "Producto", "Producto agregado correctamente.")

    def editar_producto(self):
        prod = self._get_selected_product()
        if not prod:
            QMessageBox.warning(self, "Editar producto", "Seleccione un producto para editar.")
            return
        dialog = ProductDialog(self.manager._vendedores, self.manager._Distribuidores, self, producto=prod)
        if dialog.exec_():
            data = dialog.get_data()
            self.manager.edit_producto(
                prod["id"],
                data["nombre"], data["codigo"],
                prod.get("vendedor_id"),  # Mantén el vendedor original
                prod.get("Distribuidor_id"),  # Mantén el Distribuidor original
                data["precio_compra"], data["precio_venta_minorista"], data["precio_venta_mayorista"], data.get("stock", prod.get("stock", 0)),
            )
            self.filter_products()
            QMessageBox.information(self, "Producto", "Producto editado correctamente.")
        self.selected_row = None

    def eliminar_producto(self):
        prod = self._get_selected_product()
        if not prod:
            QMessageBox.warning(self, "Eliminar producto", "Seleccione un producto para eliminar.")
            return
        confirm = QMessageBox.question(self, "Eliminar", f"¿Eliminar producto '{prod['nombre']}'?", QMessageBox.Yes | QMessageBox.No)
        if confirm == QMessageBox.Yes:
            self.manager.delete_producto(prod["id"])
            self.manager.refresh_data()
            self._actualizar_arbol_vendedores()
            self._actualizar_arbol_Distribuidores()
            self.filter_products()
            QMessageBox.information(self, "Producto eliminado", f"El producto '{prod['nombre']}' ha sido eliminado.")
        self.selected_row = None

    def registrar_venta(self):
        # Obtén los lotes con stock > 0 del inventario actual
        productos_lote = []
        compras = self.manager.db.get_compras()
        productos_dict = {p["id"]: p for p in self.manager._products}
        for compra in compras:
            detalles = self.manager.db.get_detalles_compra(compra["id"])
            for d in detalles:
                prod = productos_dict.get(d["producto_id"])
                if not prod:
                    continue
                if d.get("cantidad", 0) > 0:
                    # Incluye info de lote, producto, distribuidor y precios de venta
                    productos_lote.append({
                        "lote_id": d["id"],
                        "producto_id": d["producto_id"],
                        "nombre": prod.get("nombre", ""),
                        "codigo": prod.get("codigo", ""),
                        "stock": d.get("cantidad", 0),
                        "precio_unitario": d.get("precio_unitario", 0),
                        "Distribuidor_id": compra.get("Distribuidor_id"),
                        "fecha_vencimiento": d.get("fecha_vencimiento", ""),
                        "precio_venta_minorista": prod.get("precio_venta_minorista", 0),
                        "precio_venta_mayorista": prod.get("precio_venta_mayorista", 0),
                    })
        clientes = [dict(c) for c in self.manager._clientes]
        Distribuidores = [v["nombre"] for v in self.manager._Distribuidores]
        vendedores_trabajadores = self.manager.db.get_trabajadores(solo_vendedores=True)
        dialog = RegisterSaleDialog(productos_lote, clientes, Distribuidores, vendedores_trabajadores, self)
        try:
            if dialog.exec_():
                data = dialog.get_data()
                items = data.get("items", [])
                if not items:
                    raise ValueError("Debe agregar al menos un producto a la venta.")
                total = data.get("total", 0)  # <-- Usa el total calculado por el diálogo (ya descuenta IVA retenido)
                fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                cliente_id = data["cliente"]["id"] if data.get("cliente") and "id" in data["cliente"] else None
                Distribuidor_nombre = dialog.Distribuidor_combo.currentText()
                Distribuidor = next((v for v in self.manager._Distribuidores if v["nombre"] == Distribuidor_nombre), None)
                Distribuidor_id = Distribuidor["id"] if Distribuidor else None
                vendedor_id = data.get("vendedor_id")
                venta_id = self.manager.db.add_venta(
                    fecha, total, cliente_id=cliente_id, Distribuidor_id=Distribuidor_id, vendedor_id=vendedor_id
                )
                # Agrega todos los productos de la venta
                for item in items:
                    prod = next((p for p in self.manager._products if p["id"] == item["producto_id"]), None)
                    if not prod:
                        continue
                    if prod["stock"] < item["cantidad"]:
                        raise ValueError(f"No hay suficiente stock para el producto {prod['nombre']}.")
                    self.manager.db.add_detalle_venta(
                        venta_id,
                        prod["id"],
                        item["cantidad"],
                        item["precio"],
                        item.get("descuento_monto", 0),
                        item.get("descuento_tipo", ""),
                        item.get("iva", 0),
                        item.get("comision_monto", 0),
                        item.get("iva_tipo", ""),
                        item.get("tipo_fiscal", "Gravada"),
                        None
                    )
                    if "lote_id" in item:
                        self.manager.db.disminuir_stock_lote(item["lote_id"], item["cantidad"])
                        self.manager.db.actualizar_stock_producto(item["producto_id"])
                self.manager.refresh_data()
                self.filter_products()
                QMessageBox.information(self, "Venta", f"Venta registrada correctamente.\nTotal: ${total:.2f}")
                self._actualizar_historial()
                self._actualizar_inventario_actual()  # <-- AGREGA ESTA LÍNEA AQUÍ

                # --- PREGUNTA SI DESEA IMPRIMIR LA FACTURA ---
                respuesta = QMessageBox.question(
                    self,
                    "Imprimir factura",
                    "¿Desea imprimir la factura en impresora matricial?",
                    QMessageBox.Yes | QMessageBox.No
                )
                if respuesta == QMessageBox.Yes:
                    # Mostrar diálogo para seleccionar impresora
                    import win32print
                    import win32ui
                    from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel, QComboBox, QPushButton

                    class PrinterDialog(QDialog):
                        def __init__(self, parent=None):
                            super().__init__(parent)
                            self.setWindowTitle("Seleccionar impresora")
                            layout = QVBoxLayout()
                            layout.addWidget(QLabel("Seleccione una impresora:"))
                            self.printer_combo = QComboBox()
                            printers = win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS)
                            self.printer_combo.addItems([printer[2] for printer in printers])
                            layout.addWidget(self.printer_combo)
                            btn_ok = QPushButton("Imprimir")
                            btn_ok.clicked.connect(self.accept)
                            layout.addWidget(btn_ok)
                            self.setLayout(layout)

                        def get_selected_printer(self):
                            return self.printer_combo.currentText()

                    dlg = PrinterDialog(self)
                    if dlg.exec_():
                        printer_name = dlg.get_selected_printer()
                        if printer_name:
                            try:
                                import prueba_impresion
                                prueba_impresion.imprimir_factura_raw(printer_name)
                                QMessageBox.information(self, "Impresión", "Factura enviada a la impresora.")
                            except Exception as e:
                                QMessageBox.critical(self, "Error de impresión", str(e))
        except Exception as e:
            QMessageBox.critical(self, "Error al registrar venta", str(e))
            self._actualizar_historial()

    def registrar_compra(self):
        productos = [dict(p) for p in self.manager._products]
        Distribuidores = [dict(v) for v in self.manager._Distribuidores]
        dialog = RegisterPurchaseDialog(
            productos,
            Distribuidores,
            self.manager._vendedores,
            self
        )
        try:
            result = dialog.exec_()
            if result == QDialog.Accepted:
                QMessageBox.information(self, "Compra", "Compra registrada correctamente.")
                self.filter_products()
                self._actualizar_historial()
                self._actualizar_inventario_actual()
        except Exception as e:
            QMessageBox.critical(self, "Error al registrar compra", str(e))

    def registrar_venta_credito_fiscal(self):
        try:
            # Arma la lista de productos disponibles para la venta (con stock > 0)
            productos_lote = []
            compras = self.manager.db.get_compras()
            productos_dict = {p["id"]: p for p in self.manager._products}
            for compra in compras:
                detalles = self.manager.db.get_detalles_compra(compra["id"])
                for d in detalles:
                    prod = productos_dict.get(d["producto_id"])
                    if not prod:
                        continue
                    if d.get("cantidad", 0) > 0:
                        productos_lote.append({
                            "lote_id": d["id"],
                            "producto_id": d["producto_id"],
                            "nombre": prod.get("nombre", ""),
                            "codigo": prod.get("codigo", ""),
                            "stock": d.get("cantidad", 0),
                            "precio_unitario": d.get("precio_unitario", 0),
                            "Distribuidor_id": compra.get("Distribuidor_id"),
                            "fecha_vencimiento": d.get("fecha_vencimiento", ""),
                            "precio_venta_minorista": prod.get("precio_venta_minorista", 0),
                            "precio_venta_mayorista": prod.get("precio_venta_mayorista", 0),
                        })

            if not productos_lote:
                QMessageBox.warning(self, "Venta a Crédito Fiscal", "No hay productos con stock disponible para vender.")
                return

            clientes = self.manager.db.get_clientes()
            if not clientes:
                raise ValueError("No hay clientes registrados.")
            from dialogs import RegisterCreditoFiscalDialog
            Distribuidores = [dict(v) for v in self.manager._Distribuidores]
            vendedores_trabajadores = self.manager.db.get_trabajadores(solo_vendedores=True)
            dialog = RegisterCreditoFiscalDialog(productos_lote, clientes, Distribuidores, vendedores_trabajadores, self)
            dialog.set_productos_data(productos_lote)
            if dialog.exec_():
                
                data = dialog.get_data()
                logger.debug("IVA calculado en get_data: %s", data.get("iva"))
                items = data.get("items", [])

                if not items:
                    raise ValueError("Debe agregar al menos un producto a la venta.")
                
                # --- CÁLCULOS FISCALES ---
                sumas = data.get("sumas", 0)
                iva = data.get("iva", 0)
                subtotal = data.get("subtotal", 0)
                venta_total = data.get("total", 0)
                total_letras = monto_a_texto_sv(venta_total)
                # ---------------------------------------------------

                fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                Distribuidor_nombre = dialog.Distribuidor_combo.currentText()
                Distribuidor = next((v for v in self.manager._Distribuidores if v["nombre"] == Distribuidor_nombre), None)
                Distribuidor_id = Distribuidor["id"] if Distribuidor else None
                vendedor_id = data.get("vendedor_id")
                venta_id = self.manager.db.add_venta_credito_fiscal(
                    cliente_id=data["cliente"]["id"],
                    fecha=fecha,
                    total=venta_total,
                    nrc=data.get("nrc", ""),
                    nit=data.get("nit", ""),
                    giro=data.get("giro", ""),
                    Distribuidor_id=Distribuidor_id,
                    vendedor_id=vendedor_id,
                    no_remision=data.get("no_remision", ""),
                    orden_no=data.get("orden_no", ""),
                    condicion_pago=data.get("condicion_pago", ""),
                    venta_a_cuenta_de=data.get("venta_a_cuenta_de", ""),
                    fecha_remision_anterior=data.get("fecha_remision_anterior", ""),
                    fecha_remision=data.get("fecha_remision", ""),
                    sumas=sumas,
                    iva=iva,
                    subtotal=subtotal,
                    ventas_exentas=data.get("ventas_exentas", 0),
                    ventas_no_sujetas=data.get("ventas_no_sujetas", 0),
                    total_letras=total_letras
                )
                logger.debug("IVA guardado en la venta: %s", iva)

                for item in items:
                    prod = next((p for p in self.manager._products if p["id"] == item["producto_id"]), None)
                    if not prod:
                        continue
                    if prod["stock"] < item["cantidad"]:
                        raise ValueError(f"No hay suficiente stock para el producto {prod['nombre']}.")
                    self.manager.db.add_detalle_venta(
                        venta_id,
                        prod["id"],
                        item["cantidad"],
                        item["precio"],
                        item.get("descuento_monto", 0),
                        item.get("descuento_tipo", ""),
                        item.get("iva", 0),
                        item.get("comision_monto", 0),
                        item.get("iva_tipo", ""),
                        item.get("tipo_fiscal", "Gravada"),
                        item.get("extra", None), 
                        item.get("precio_con_iva", 0)  
                    )
                   
                    if "lote_id" in item:
                        self.manager.db.disminuir_stock_lote(item["lote_id"], item["cantidad"])
                        self.manager.db.actualizar_stock_producto(item["producto_id"])
                self.manager.refresh_data()
                self.filter_products()
                QMessageBox.information(self, "Venta a Crédito Fiscal", f"Venta registrada correctamente.\nTotal: ${venta_total:.2f}")
                self._actualizar_historial()
                self._actualizar_inventario_actual()

                # --- PREGUNTA SI DESEA IMPRIMIR LA FACTURA ---
                respuesta = QMessageBox.question(
                    self,
                    "Imprimir factura",
                    "¿Desea imprimir la factura en impresora matricial?",
                    QMessageBox.Yes | QMessageBox.No
                )
                if respuesta == QMessageBox.Yes:
                    import win32print
                    import win32ui
                    from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel, QComboBox, QPushButton

                    class PrinterDialog(QDialog):
                        def __init__(self, parent=None):
                            super().__init__(parent)
                            self.setWindowTitle("Seleccionar impresora")
                            layout = QVBoxLayout()
                            layout.addWidget(QLabel("Seleccione una impresora:"))
                            self.printer_combo = QComboBox()
                            printers = win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS)
                            self.printer_combo.addItems([printer[2] for printer in printers])
                            layout.addWidget(self.printer_combo)
                            btn_ok = QPushButton("Imprimir")
                            btn_ok.clicked.connect(self.accept)
                            layout.addWidget(btn_ok)
                            self.setLayout(layout)

                        def get_selected_printer(self):
                            return self.printer_combo.currentText()

                    dlg = PrinterDialog(self)
                    if dlg.exec_():
                        printer_name = dlg.get_selected_printer()
                        if printer_name:
                            try:
                                import prueba_impresion
                                prueba_impresion.imprimir_factura_raw(printer_name)
                                QMessageBox.information(self, "Impresión", "Factura enviada a la impresora.")
                            except Exception as e:
                                QMessageBox.critical(self, "Error de impresión", str(e))
        except Exception as e:
            QMessageBox.critical(self, "Error al registrar venta a crédito fiscal", str(e))

    def guardar_como(self):
        filename, _ = QFileDialog.getSaveFileName(self, "Guardar inventario como", "", "Archivos JSON (*.json);;Todos los archivos (*)")
        if filename:
            try:
                self.manager.exportar_inventario_json(filename)
                self.ultimo_archivo_json = filename
                with open("ultimo_inventario.json", "w", encoding="utf-8") as f:
                    json.dump({"ultimo": filename}, f)
                QMessageBox.information(self, "Guardar como", "Inventario guardado correctamente.")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"No se pudo guardar el inventario:\n{e}")
                self._actualizar_historial()

    def cargar_inventario(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Cargar inventario", "", "Archivos JSON (*.json);;Todos los archivos (*)")
        if filename:
            try:
                self.manager.importar_inventario_json(filename)
                self.ultimo_archivo_json = filename
                with open("ultimo_inventario.json", "w", encoding="utf-8") as f:
                    json.dump({"ultimo": filename}, f)
                self.filter_products()
                self._actualizar_tabla_clientes()
                self._actualizar_arbol_vendedores()     
                self._actualizar_arbol_Distribuidores()  
                self._actualizar_tabla_trabajadores()
                self._actualizar_inventario_actual() 
                self._actualizar_historial() 
                QMessageBox.information(self, "Cargar inventario", "Inventario cargado correctamente.")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"No se pudo cargar el inventario:\n{e}")
                self._actualizar_historial()

    def guardar_rapido(self):
        if self.ultimo_archivo_json:
            try:
                self.manager.exportar_inventario_json(self.ultimo_archivo_json)
                QMessageBox.information(self, "Guardar rápido", f"Inventario guardado en:\n{self.ultimo_archivo_json}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"No se pudo guardar el inventario:\n{e}")
        else:
            QMessageBox.warning(self, "Guardar rápido", "Primero debes guardar o cargar un inventario manualmente.")
            self._actualizar_historial()

    def cargar_rapido(self):
        import os
        if self.ultimo_archivo_json and os.path.exists(self.ultimo_archivo_json):
            try:
                self.manager.importar_inventario_json(self.ultimo_archivo_json)
                self.filter_products()
                self._actualizar_tabla_clientes()  # <-- SOLO AGREGA ESTA LÍNEA
                QMessageBox.information(self, "Cargar rápido", f"Inventario cargado de:\n{self.ultimo_archivo_json}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"No se pudo cargar el inventario:\n{e}")
        else:
            QMessageBox.warning(self, "Cargar rápido", "No hay un inventario guardado previamente para cargar.")

    def nuevo_inventario(self):
        reply = QMessageBox.question(
            self,
            "Nuevo inventario",
            "¿Estás seguro de que quieres borrar todo el inventario actual? Esta acción no se puede deshacer.",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.manager.db.limpiar_productos()
            self.manager.db.limpiar_vendedores()
            self.manager.db.limpiar_Distribuidores()
            try:
                self.manager.db.cursor.execute("DELETE FROM trabajadores")
                self.manager.db.cursor.execute("DELETE FROM clientes")
                self.manager.db.cursor.execute("DELETE FROM ventas")
                self.manager.db.cursor.execute("DELETE FROM detalles_venta")
                self.manager.db.cursor.execute("DELETE FROM compras")
                self.manager.db.cursor.execute("DELETE FROM detalles_compra")
                self.manager.db.cursor.execute("DELETE FROM movimientos")
                self.manager.db.conn.commit()
            except Exception:
                pass
            self.manager.refresh_data()
            self._actualizar_tabla_trabajadores()  # <-- AGREGA ESTA LÍNEA
            self.filter_products()
            self._actualizar_arbol_vendedores()
            self._actualizar_arbol_Distribuidores()
            self._actualizar_tabla_clientes()
            self._actualizar_historial()
            if hasattr(self, "vendedor_combo_filtro"):
                self.vendedor_combo_filtro.setCurrentIndex(0)
            QMessageBox.information(self, "Nuevo inventario", "Inventario limpio y listo para usar.")

    def _actualizar_arbol_vendedores(self):
        self.vendedores_tree.clear()
        for vend in self.manager._vendedores:
            vend_item = QTreeWidgetItem([vend["nombre"]])
            self.vendedores_tree.addTopLevelItem(vend_item)
            vend_item.setExpanded(False)

    def _actualizar_arbol_Distribuidores(self):
        self.Distribuidores_tree.clear()
        for dist in self.manager._Distribuidores:
            dist_item = QTreeWidgetItem([dist["nombre"]])
            vendedores = [v for v in self.manager._vendedores if v.get("Distribuidor_id") == dist["id"]]
            for vend in vendedores:
                vend_item = QTreeWidgetItem([vend["nombre"]])
                dist_item.addChild(vend_item)
            self.Distribuidores_tree.addTopLevelItem(dist_item)
            dist_item.setExpanded(False)

    def _actualizar_lista_Distribuidores(self):
        self.Distribuidores_list.clear()
        for dist in self.manager.get_Distribuidor_names():
            self.Distribuidores_list.addItem(dist)

    def _filtrar_vend_dist(self):
        search = self.vend_dist_search.text().lower()
        # Filtrar vendedores
        for i in range(self.vendedores_tree.topLevelItemCount()):
            item = self.vendedores_tree.topLevelItem(i)
            visible = search in item.text(0).lower()
            item.setHidden(not visible)
        # Filtrar Distribuidores y sus vendedores
        for i in range(self.Distribuidores_tree.topLevelItemCount()):
            dist_item = self.Distribuidores_tree.topLevelItem(i)
            dist_match = search in dist_item.text(0).lower()
            child_match = False
            for j in range(dist_item.childCount()):
                child = dist_item.child(j)
                match = search in child.text(0).lower()
                child.setHidden(not match)
                child_match = child_match or match
            dist_item.setHidden(not (dist_match or child_match))

    def _agregar_vendedor(self):
        from dialogs import VendedorDialog
        dialog = VendedorDialog(self.manager._Distribuidores, self)
        if dialog.exec_():
            data = dialog.get_data()
            self.manager.db.add_vendedor(
                data["nombre"],
                data["descripcion"],
                data["Distribuidor_id"]
            )
            self.manager.refresh_data()
            self._actualizar_arbol_vendedores()
            QMessageBox.information(self, "Vendedor", "Vendedor agregado correctamente.")

    def _editar_vendedor(self):
        from dialogs import VendedorDialog
        selected_items = self.vendedores_tree.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "Editar vendedor", "Seleccione una vendedor para editar.")
            return
        nombre_actual = selected_items[0].text(0)
        vendedor = next((c for c in self.manager._vendedores if c["nombre"] == nombre_actual), None)
        if not vendedor:
            QMessageBox.warning(self, "Editar vendedor", "No se encontró la vendedor seleccionada.")
            return
        dialog = VendedorDialog(self.manager._Distribuidores, self, vendedor=vendedor)
        if dialog.exec_():
            data = dialog.get_data()
            self.manager.db.update_vendedor(
                vendedor["id"],
                data["nombre"],
                data["descripcion"],
                data["Distribuidor_id"]
            )
            self.manager.refresh_data()
            self._actualizar_arbol_vendedores()
            QMessageBox.information(self, "Vendedor", "Vendedor editado correctamente.")

    def _agregar_Distribuidor(self):
        dialog = DistribuidorDialog(self)
        if dialog.exec_():
            data = dialog.get_data()
            self.manager.db.add_Distribuidor_detallado(data)
            self.manager.refresh_data()
            self._actualizar_arbol_Distribuidores()
            QMessageBox.information(self, "Distribuidor", "Distribuidor agregado correctamente.")

    def _editar_Distribuidor(self):
        selected_items = self.Distribuidores_tree.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "Editar Distribuidor", "Seleccione un Distribuidor para editar.")
            return
        nombre_actual = selected_items[0].text(0)
        # Busca el Distribuidor en la base de datos
        Distribuidor = next((v for v in self.manager._Distribuidores if v["nombre"] == nombre_actual), None)
        if not Distribuidor:
            QMessageBox.warning(self, "Editar Distribuidor", "No se encontró el Distribuidor seleccionado.")
            return
        dialog = DistribuidorDialog(self, Distribuidor=Distribuidor)
        if dialog.exec_():
            data = dialog.get_data()
            # Actualiza el Distribuidor en la base de datos
            self.manager.db.cursor.execute("""
                UPDATE Distribuidores SET
                    codigo=?, nombre=?, dui=?, telefono=?, email=?, cargo=?, sucursal=?,
                    comision_base=?, fecha_inicio=?, direccion=?, departamento=?, municipio=?,
                    tipo_contrato=?, comisiones_especificas=?, metodo_pago=?, nit=?, nrc=?,
                    cuenta_bancaria=?, notas=?
                WHERE id=?
            """, (
                data.get("codigo", ""),
                data.get("nombre", ""),
                data.get("dui", ""),
                data.get("telefono", ""),
                data.get("email", ""),
                data.get("cargo", ""),
                data.get("sucursal", ""),
                data.get("comision_base", 0),
                data.get("fecha_inicio", ""),
                data.get("direccion", ""),
                data.get("departamento", ""),
                data.get("municipio", ""),
                data.get("tipo_contrato", ""),
                data.get("comisiones_especificas", ""),
                data.get("metodo_pago", ""),
                data.get("nit", ""),
                data.get("nrc", ""),
                data.get("cuenta_bancaria", ""),
                data.get("notas", ""),
                Distribuidor["id"]
            ))
            self.manager.db.conn.commit()
            self.manager.refresh_data()
            self._actualizar_arbol_Distribuidores()
            QMessageBox.information(self, "Distribuidor", "Distribuidor editado correctamente.")
        self.selected_row = None

    def _mostrar_info_Distribuidor(self):
        selected_items = self.Distribuidores_tree.selectedItems()
        if not selected_items:
            QMessageBox.information(self, "Información de Distribuidor", "Seleccione un Distribuidor para ver su información.")
            return
        nombre_actual = selected_items[0].text()
        Distribuidor = next((v for v in self.manager._Distribuidores if v["nombre"] == nombre_actual), None)
        if not Distribuidor:
            QMessageBox.warning(self, "Información de Distribuidor", "No se encontró el Distribuidor seleccionado.")
            return

        # Construye el texto con toda la información relevante
        info = (
            f"<b>Código:</b> {Distribuidor['codigo'] if 'codigo' in Distribuidor.keys() else ''}<br>"
            f"<b>Nombre:</b> {Distribuidor['nombre'] if 'nombre' in Distribuidor.keys() else ''}<br>"
            f"<b>DUI:</b> {Distribuidor['dui'] if 'dui' in Distribuidor.keys() else ''}<br>"
            f"<b>Teléfono:</b> {Distribuidor['telefono'] if 'telefono' in Distribuidor.keys() else ''}<br>"
            f"<b>Email:</b> {Distribuidor['email'] if 'email' in Distribuidor.keys() else ''}<br>"
            f"<b>Cargo:</b> {Distribuidor['cargo'] if 'cargo' in Distribuidor.keys() else ''}<br>"
            f"<b>Sucursal/Laboratorio:</b> {Distribuidor['sucursal'] if 'sucursal' in Distribuidor.keys() else ''}<br>"
            f"<b>Comisión base:</b> {Distribuidor['comision_base'] if 'comision_base' in Distribuidor.keys() else ''}<br>"
            f"<b>Fecha de inicio:</b> {Distribuidor['fecha_inicio'] if 'fecha_inicio' in Distribuidor.keys() else ''}<br>"
            f"<b>Dirección:</b> {Distribuidor['direccion'] if 'direccion' in Distribuidor.keys() else ''}<br>"
            f"<b>Departamento:</b> {Distribuidor['departamento'] if 'departamento' in Distribuidor.keys() else ''}<br>"
            f"<b>Municipio:</b> {Distribuidor['municipio'] if 'municipio' in Distribuidor.keys() else ''}<br>"
            f"<b>Tipo de contrato:</b> {Distribuidor['tipo_contrato'] if 'tipo_contrato' in Distribuidor.keys() else ''}<br>"
            f"<b>Comisiones específicas:</b> {Distribuidor['comisiones_especificas'] if 'comisiones_especificas' in Distribuidor.keys() else ''}<br>"
            f"<b>Método/periodicidad pago:</b> {Distribuidor['metodo_pago'] if 'metodo_pago' in Distribuidor.keys() else ''}<br>"
            f"<b>NIT:</b> {Distribuidor['nit'] if 'nit' in Distribuidor.keys() else ''}<br>"
            f"<b>NRC:</b> {Distribuidor['nrc'] if 'nrc' in Distribuidor.keys() else ''}<br>"
            f"<b>Cuenta bancaria:</b> {Distribuidor['cuenta_bancaria'] if 'cuenta_bancaria' in Distribuidor.keys() else ''}<br>"
            f"<b>Notas:</b> {Distribuidor['notas'] if 'notas' in Distribuidor.keys() else ''}"
        )
        QMessageBox.information(self, "Información de Distribuidor", info)

    def _actualizar_tabla_clientes(self):
        search = self.cliente_search.text()
        clientes = self.manager.db.get_clientes(search)
        self.clientes_table.setRowCount(len(clientes))
        for row, cli in enumerate(clientes):
            self.clientes_table.setItem(row, 0, QTableWidgetItem(cli.get("codigo", "")))
            self.clientes_table.setItem(row, 1, QTableWidgetItem(cli.get("nombre", "")))
            self.clientes_table.setItem(row, 2, QTableWidgetItem(cli.get("nrc", "")))
            self.clientes_table.setItem(row, 3, QTableWidgetItem(cli.get("nit", "")))
            self.clientes_table.setItem(row, 4, QTableWidgetItem(cli.get("dui", "")))
            self.clientes_table.setItem(row, 5, QTableWidgetItem(cli.get("giro", "")))
            self.clientes_table.setItem(row, 6, QTableWidgetItem(cli.get("telefono", "")))
            self.clientes_table.setItem(row, 7, QTableWidgetItem(cli.get("email", "")))
            self.clientes_table.setItem(row, 8, QTableWidgetItem(cli.get("departamento", "")))
            self.clientes_table.setItem(row, 9, QTableWidgetItem(cli.get("municipio", "")))

    def _get_selected_cliente(self):
        row = self.clientes_table.currentRow()
        if row < 0:
            return None
        codigo = self.clientes_table.item(row, 0).text()
        clientes = self.manager.db.get_clientes()
        for cli in clientes:
            if cli.get("codigo", "") == codigo:
                return cli
        return None

    def _agregar_cliente(self):
        dialog = ClienteDialog(self)
        if dialog.exec_():
            data = dialog.get_data()
            self.manager.db.add_cliente(
                data["nombre"], data["nrc"], data["nit"], data["dui"], data["giro"],
                data["telefono"], data["email"], data["direccion"], data["departamento"], data["municipio"]
            )
            self._actualizar_tabla_clientes()
            QMessageBox.information(self, "Cliente", "Cliente agregado correctamente.")

    def _editar_cliente(self):
        cli = self._get_selected_cliente()
        if not cli:
            QMessageBox.warning(self, "Editar cliente", "Seleccione un cliente para editar.")
            return
        dialog = ClienteDialog(self, cliente=cli)
        if dialog.exec_():
            data = dialog.get_data()
            self.manager.db.update_cliente(
                cli["id"], data["nombre"], data["nrc"], data["nit"], data["dui"], data["giro"],
                data["telefono"], data["email"], data["direccion"], data["departamento"], data["municipio"]
            )
            self._actualizar_tabla_clientes()
            QMessageBox.information(self, "Cliente", "Cliente editado correctamente.")

    def _eliminar_cliente(self):
        cli = self._get_selected_cliente()
        if not cli:
            QMessageBox.warning(self, "Eliminar cliente", "Seleccione un cliente para eliminar.")
            return
        confirm = QMessageBox.question(self, "Eliminar", f"¿Eliminar cliente '{cli['nombre']}'?", QMessageBox.Yes | QMessageBox.No)
        if confirm == QMessageBox.Yes:
            self.manager.db.delete_cliente(cli["id"])
            self._actualizar_tabla_clientes()
            QMessageBox.information(self, "Cliente eliminado", f"El cliente '{cli['nombre']}' ha sido eliminado.")

    def _actualizar_historial(self):
        # Ventas
        ventas = self.manager.db.get_ventas()
        # Si el filtro no está en "Todas", filtra por mes/año
        if self.ventas_mes_filtro.date() != QDate(2000, 1, 1):
            mes_ventas = self.ventas_mes_filtro.date().month()
            anio_ventas = self.ventas_mes_filtro.date().year()
            ventas = [
                v for v in ventas
                if v.get("fecha") and
                   int(v["fecha"][5:7]) == mes_ventas and
                   int(v["fecha"][:4]) == anio_ventas
            ]
        clientes = {c["id"]: c["nombre"] for c in self.manager.db.get_clientes()}
        productos_dict = {p["id"]: p for p in self.manager.db.get_productos()}
        Distribuidores_dict = {v["id"]: v["nombre"] for v in self.manager.db.get_Distribuidores()}
        detalles_venta = {v["id"]: self.manager.db.get_detalles_venta(v["id"]) for v in ventas}
        for row, v in enumerate(ventas):
            logger.debug(
                "detalles_venta para venta %s: %s",
                v['id'],
                detalles_venta.get(v["id"], [])
            )
        search = self.historial_search.text().lower()
        ventas_filtradas = []
        total_ingresos = 0
        for v in ventas:
            productos_strs = []
            for d in detalles_venta.get(v["id"], []):
                producto_nombre = productos_dict.get(d["producto_id"], "Desconocido")
                cantidad = d["cantidad"]
                # Busca el detalle de compra más reciente para este producto
                self.manager.db.cursor.execute(
                    "SELECT c.Distribuidor_id FROM detalles_compra dc "
                    "JOIN compras c ON dc.compra_id = c.id "
                    "WHERE dc.producto_id=? ORDER BY c.fecha DESC, c.id DESC LIMIT 1",
                    (d["producto_id"],)
                )
                row_dist = self.manager.db.cursor.fetchone()
                if row_dist and row_dist["Distribuidor_id"]:
                    dist_nombre = Distribuidores_dict.get(row_dist["Distribuidor_id"], "Desconocido")
                else:
                    dist_nombre = "Desconocido"
                productos_strs.append(f"{producto_nombre} x{cantidad} ({dist_nombre})")
            productos = ", ".join(productos_strs)
            cliente_nombre = clientes.get(v.get("cliente_id"), "")
            total = v.get('total', 0)
            texto_busqueda = f"{cliente_nombre} {productos} {dist_nombre} {v.get('id','')}".lower()
            if search and search not in texto_busqueda:
                continue
            total_ingresos += float(total)
            Distribuidor_id = v.get("Distribuidor_id", None)
            if Distribuidor_id is not None and Distribuidor_id in Distribuidores_dict:
                Distribuidor_nombre = Distribuidores_dict[Distribuidor_id]
            else:
                Distribuidor_nombre = "Desconocido"
            ventas_filtradas.append((v, productos, cliente_nombre, Distribuidor_nombre))

        self.historial_ventas_table.setRowCount(len(ventas_filtradas))
        for row, (v, productos, cliente_nombre, Distribuidor_nombre) in enumerate(ventas_filtradas):
            total = v.get('total', 0)
            self.historial_ventas_table.setItem(row, 0, QTableWidgetItem(v.get("fecha", "")))
            self.historial_ventas_table.setItem(row, 1, QTableWidgetItem(cliente_nombre))
            self.historial_ventas_table.setItem(row, 2, QTableWidgetItem(f"${float(total):.2f}"))
            self.historial_ventas_table.setItem(row, 3, QTableWidgetItem(productos))
            self.historial_ventas_table.setItem(row, 4, QTableWidgetItem(Distribuidor_nombre))
            self.historial_ventas_table.setItem(row, 5, QTableWidgetItem(str(v["id"])))
        self.total_ingresos_label.setText(f"Total ingresos: ${total_ingresos:.2f}")

        # Filtro por mes y año para compras
        mes_compras = self.compras_mes_filtro.date().month()
        anio_compras = self.compras_mes_filtro.date().year()
        compras = self.manager.db.get_compras()
        # Si el filtro no está en "Todas", filtra por mes/año
        if self.compras_mes_filtro.date() != QDate(2000, 1, 1):
            mes_compras = self.compras_mes_filtro.date().month()
            anio_compras = self.compras_mes_filtro.date().year()
            compras = [
                c for c in compras
                if c.get("fecha") and
                   int(c["fecha"][5:7]) == mes_compras and
                   int(c["fecha"][:4]) == anio_compras
            ]
        productos_dict = {p["id"]: p for p in self.manager.db.get_productos()}
        Distribuidores_dict = {v["id"]: v["nombre"] for v in self.manager.db.get_Distribuidores()}
        detalles_compra = {c["id"]: self.manager.db.get_detalles_compra(c["id"]) for c in compras}
        search_lower = self.historial_search.text().lower()
        compras_filtradas = []
        total_gastos = 0
        vendedores_dict = {v["id"]: v["nombre"] for v in self.manager.db.get_vendedores()}
        for c in compras:
            productos = ", ".join(
                f'{productos_dict.get(d["producto_id"], "Desconocido")} x{d["cantidad"]}'
                for d in detalles_compra.get(c["id"], [])
            )
            Distribuidor_id = c.get("Distribuidor_id", None)
            Distribuidor_nombre = ""
            if Distribuidor_id is not None and Distribuidor_id in Distribuidores_dict:
                Distribuidor_nombre = Distribuidores_dict[Distribuidor_id]
            vendedor_nombre = vendedores_dict.get(c.get("vendedor_id"), "")
            total = c.get('total', 0)
            comision_monto = c.get('comision_monto', 0)
            texto_busqueda = f"{Distribuidor_nombre} {vendedor_nombre} {productos} {c.get('id','')}".lower()
            if search_lower and search_lower not in texto_busqueda:
                continue
            total_gastos += float(total)
            compras_filtradas.append((c, productos, Distribuidor_nombre, vendedor_nombre, total, comision_monto))

        self.historial_compras_table.setRowCount(len(compras_filtradas))
        for row, (c, productos, Distribuidor_nombre, vendedor_nombre, total, comision_monto) in enumerate(compras_filtradas):
            self.historial_compras_table.setItem(row, 0, QTableWidgetItem(c["fecha"]))  # Fecha
            self.historial_compras_table.setItem(row, 1, QTableWidgetItem(Distribuidor_nombre))  # Distribuidor
            self.historial_compras_table.setItem(row, 2, QTableWidgetItem(vendedor_nombre))  # Vendedor
            self.historial_compras_table.setItem(row, 3, QTableWidgetItem(f"${float(total):.2f}"))  # Total
            self.historial_compras_table.setItem(row, 4, QTableWidgetItem(f"${float(comision_monto):.2f}"))  # Comisión
            self.historial_compras_table.setItem(row, 5, QTableWidgetItem(productos))  # Productos
            self.historial_compras_table.setItem(row, 6, QTableWidgetItem(str(c["id"])))  # ID oculto
            
    def _actualizar_historial_compras(self):
        self.historial_compras_table.setRowCount(0)
        compras = self.manager.db.get_compras()
        productos_dict = {p["id"]: p for p in self.manager.db.get_productos()}
        Distribuidores_dict = {d["id"]: d["nombre"] for d in self.manager.db.get_Distribuidores()}
        vendedores_dict = {v["id"]: v["nombre"] for v in self.manager.db.get_vendedores()}

        for compra in compras:
            detalles = self.manager.db.get_detalles_compra(compra["id"])
            # Junta los nombres de los productos de los detalles
            productos = ", ".join([productos_dict.get(d["producto_id"], {}).get("nombre", "") for d in detalles])
            # Suma la comisión de todos los detalles de la compra
            comision_total = sum(float(d.get("comision_monto", 0)) for d in detalles)
            row = self.historial_compras_table.rowCount()
            self.historial_compras_table.insertRow(row)
            self.historial_compras_table.setItem(row, 0, QTableWidgetItem(compra["fecha"]))  # Fecha
            self.historial_compras_table.setItem(row, 1, QTableWidgetItem(Distribuidores_dict.get(compra["Distribuidor_id"], "")))  # Distribuidor
            self.historial_compras_table.setItem(row, 2, QTableWidgetItem(vendedores_dict.get(compra["vendedor_id"], "")))  # Vendedor
            self.historial_compras_table.setItem(row, 3, QTableWidgetItem(f"${compra['total']:.2f}"))  # Total
            self.historial_compras_table.setItem(row, 4, QTableWidgetItem(f"${comision_total:.2f}"))  # Comisión
            self.historial_compras_table.setItem(row, 5, QTableWidgetItem(productos))  # Productos
            self.historial_compras_table.setItem(row, 6, QTableWidgetItem(str(compra["id"])))  # ID oculto

    def mostrar_detalle_compra(self, item):
        row = item.row()
        compra_id_item = self.historial_compras_table.item(row, 6)
        logger.debug(
            "ID de compra seleccionado: %s",
            compra_id_item.text() if compra_id_item else "NO ITEM"
        )
        if not compra_id_item:
            QMessageBox.warning(self, "Detalle de compra", "No se encontró el ID de la compra seleccionada.")
            return
        compra_id = int(compra_id_item.text())
        compras = self.manager.db.get_compras()
        compra = next((c for c in compras if c["id"] == compra_id), None)
        if not compra:
            QMessageBox.warning(self, "Detalle de compra", "No se encontró la compra seleccionada.")
            return
        detalles = self.manager.db.get_detalles_compra(compra_id)
        try:
            from dialogs import CompraDetalleDialog
            dlg = CompraDetalleDialog(compra, detalles, self)
            dlg.exec_()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo mostrar el detalle:\n{e}")

    def _limpiar_filtros_historial(self):
        """Limpia los filtros de mes y año en la pestaña de historial."""
        self.ventas_mes_filtro.setDate(QDate(2000, 1, 1))
        self.compras_mes_filtro.setDate(QDate(2000, 1, 1))
        self._actualizar_historial()

    def eventFilter(self, obj, event):
        if event.type() == event.FocusIn:
            if obj == self.ventas_mes_filtro and obj.date() == QDate(2000, 1, 1):
                obj.setDate(QDate.currentDate())
            if obj == self.compras_mes_filtro and obj.date() == QDate(2000, 1, 1):
                obj.setDate(QDate.currentDate())
        return super().eventFilter(obj, event)

    def _actualizar_inventario_actual(self):
        search = self.actual_search_bar.text()
        # Aquí puedes aplicar el filtro por búsqueda en la tabla de inventario actual
        for row in range(self.inventario_actual_table.rowCount()):
            item = self.inventario_actual_table.item(row, 0)  # Suponiendo que el nombre del producto está en la columna 0
            if item and search.lower() in item.text().lower():
                self.inventario_actual_table.showRow(row)
            else:
                self.inventario_actual_table.hideRow(row)
        # Obtén todos los detalles de compra (lotes)
        detalles = []
        compras = self.manager.db.get_compras()
        productos_dict = {p["id"]: p for p in self.manager.db.get_productos()}
        Distribuidores_dict = {v["id"]: v["nombre"] for v in self.manager.db.get_Distribuidores()}
        for compra in compras:
            compra_id = compra["id"]
            detalles_compra = self.manager.db.get_detalles_compra(compra_id)
            for d in detalles_compra:
                prod = productos_dict.get(d["producto_id"])
                if not prod:
                    continue
                # Busca la fecha de vencimiento en el detalle si la tienes (ajusta si la guardas en la tabla)
                fecha_vencimiento = d.get("fecha_vencimiento", "")
                detalles.append({
                    "producto": prod.get("nombre", ""),
                    "codigo": prod.get("codigo", ""),
                    "cantidad": d.get("cantidad", 0),
                    "precio_compra": d.get("precio_unitario", 0),
                    "fecha_compra": compra.get("fecha", ""),
                    "fecha_vencimiento": fecha_vencimiento,
                    "Distribuidor": Distribuidores_dict.get(compra.get("Distribuidor_id"), "")
                })

        # Filtra solo los lotes con stock > 0
        detalles = [d for d in detalles if d["cantidad"] > 0]

        # Aplica búsqueda
        search = self.actual_search_bar.text().lower()
        if search:
            detalles = [
                d for d in detalles
                if search in d["producto"].lower() or search in d["codigo"].lower()
            ]

        self.inventario_actual_table.setRowCount(len(detalles))
        for row, d in enumerate(detalles):
            self.inventario_actual_table.setItem(row, 0, QTableWidgetItem(d["producto"]))
            self.inventario_actual_table.setItem(row, 1, QTableWidgetItem(d["codigo"]))
            item_cantidad = QTableWidgetItem(str(d["cantidad"]))
            cantidad_val = int(d.get("cantidad", 0))
            if cantidad_val < STOCK_THRESHOLD:
                color = QColor("red") if cantidad_val == 0 else QColor("yellow")
                item_cantidad.setBackground(color)
            self.inventario_actual_table.setItem(row, 2, item_cantidad)
            self.inventario_actual_table.setItem(row, 3, QTableWidgetItem(f"${d['precio_compra']:.2f}"))
            self.inventario_actual_table.setItem(row, 4, QTableWidgetItem(d["fecha_compra"]))
            # --- FECHA DE VENCIMIENTO CON COLOR ---
            item_venc = QTableWidgetItem(d["fecha_vencimiento"])
            fecha_str = d["fecha_vencimiento"]
            if fecha_str:
                try:
                    from datetime import datetime
                    fecha_venc = datetime.strptime(fecha_str, "%Y-%m-%d")
                    hoy = datetime.today()
                    meses = (fecha_venc.year - hoy.year) * 12 + (fecha_venc.month - hoy.month)
                    if fecha_venc < hoy:
                        item_venc.setBackground(QColor("black"))
                        item_venc.setForeground(QColor("white"))
                    elif meses <= 3:
                        item_venc.setBackground(QColor("red"))
                        item_venc.setForeground(QColor("white"))
                    elif meses <= 6:
                        item_venc.setBackground(QColor("orange"))
                        item_venc.setForeground(QColor("black"))
                    elif meses > 6:
                        item_venc.setBackground(QColor("green"))
                        item_venc.setForeground(QColor("black"))
                except Exception:
                    pass
            self.inventario_actual_table.setItem(row, 5, item_venc)
            self.inventario_actual_table.setItem(row, 6, QTableWidgetItem(d["Distribuidor"]))

    def _on_table_clicked(self, index):
        self.selected_row = index.row()

    def _get_selected_product(self):
        index = self.product_table.currentIndex()
        if not index.isValid():
            return None
        row = index.row()
        if row < 0 or row >= len(self.manager._products):
            return None
        return self.manager._products[row]
    
    def _abrir_datos_negocio(self):
        # Puedes guardar/cargar los datos en un archivo JSON local, por ejemplo:
        import os, json
        datos_path = "datos_negocio.json"
        datos = {}
        if os.path.exists(datos_path):
            try:
                with open(datos_path, "r", encoding="utf-8") as f:
                    datos = json.load(f)
            except Exception:
                datos = {}
        from dialogs import DatosNegocioDialog
        dlg = DatosNegocioDialog(datos, self)
        if dlg.exec_():
            datos_nuevos = dlg.get_data()
            with open(datos_path, "w", encoding="utf-8") as f:
                json.dump(datos_nuevos, f, ensure_ascii=False, indent=2)
            QMessageBox.information(self, "Datos del negocio", "Datos guardados correctamente.")

    def _actualizar_tabla_trabajadores(self):
        solo_vendedores = self.trabajadores_filtro_vendedor.isChecked()
        area = self.trabajadores_filtro_area.text().strip() or None
        search = self.trabajadores_search.text().lower()
        trabajadores = self.manager.db.get_trabajadores(solo_vendedores=solo_vendedores, area=area)
        if search:
            trabajadores = [t for t in trabajadores if search in t.get("nombre", "").lower() or search in t.get("dui", "").lower() or search in t.get("nit", "").lower()]
        self.trabajadores_table.setRowCount(len(trabajadores))
        for row, t in enumerate(trabajadores):
            self.trabajadores_table.setItem(row, 0, QTableWidgetItem(t.get("nombre", "")))
            self.trabajadores_table.setItem(row, 1, QTableWidgetItem(t.get("dui", "")))
            self.trabajadores_table.setItem(row, 2, QTableWidgetItem(t.get("nit", "")))
            self.trabajadores_table.setItem(row, 3, QTableWidgetItem(t.get("fecha_nacimiento", "")))
            self.trabajadores_table.setItem(row, 4, QTableWidgetItem(t.get("cargo", "")))
            self.trabajadores_table.setItem(row, 5, QTableWidgetItem(t.get("area", "")))
            self.trabajadores_table.setItem(row, 6, QTableWidgetItem(t.get("telefono", "")))
            self.trabajadores_table.setItem(row, 7, QTableWidgetItem(t.get("email", "")))
            self.trabajadores_table.setItem(row, 8, QTableWidgetItem("Sí" if t.get("es_vendedor") else "No"))

    def _get_selected_trabajador(self):
        row = self.trabajadores_table.currentRow()
        if row < 0:
            return None
        nombre = self.trabajadores_table.item(row, 0).text()
        trabajadores = self.manager.db.get_trabajadores()
        for t in trabajadores:
            if t.get("nombre", "") == nombre:
                return t
        return None

    def _agregar_trabajador(self):
        from dialogs import TrabajadorDialog
        dialog = TrabajadorDialog(parent=self)
        if dialog.exec_():
            data = dialog.get_data()
            self.manager.db.add_trabajador(data)
            self._actualizar_tabla_trabajadores()
            QMessageBox.information(self, "Trabajador", "Trabajador agregado correctamente.")

    def _editar_trabajador(self):
        t = self._get_selected_trabajador()
        if not t:
            QMessageBox.warning(self, "Editar trabajador", "Seleccione un trabajador para editar.")
            return
        from dialogs import TrabajadorDialog
        dialog = TrabajadorDialog(trabajador=t, parent=self)
        if dialog.exec_():
            data = dialog.get_data()
            self.manager.db.update_trabajador(t["id"], data)
            self._actualizar_tabla_trabajadores()
            QMessageBox.information(self, "Trabajador", "Trabajador editado correctamente.")

    def _eliminar_trabajador(self):
        t = self._get_selected_trabajador()
        if not t:
            QMessageBox.warning(self, "Eliminar trabajador", "Seleccione un trabajador para eliminar.")
            return
        confirm = QMessageBox.question(self, "Eliminar", f"¿Eliminar trabajador '{t['nombre']}'?", QMessageBox.Yes | QMessageBox.No)
        if confirm == QMessageBox.Yes:
            self.manager.db.delete_trabajador(t["id"])
            self._actualizar_tabla_trabajadores()
            QMessageBox.information(self, "Trabajador eliminado", f"El trabajador '{t['nombre']}' ha sido eliminado.")