from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QTableView, QLineEdit,
    QPushButton, QTabWidget, QMessageBox, QSplitter, QMenuBar, QAction, QFileDialog,
    QListWidget, QInputDialog, QLabel, QComboBox, QTreeWidget, QTreeWidgetItem, QTableWidget, QTableWidgetItem, QDialog,
    QDateEdit, QCheckBox, QTextEdit
)
from PyQt5.QtCore import Qt, QDate
from PyQt5.QtGui import QColor
import os
import json
from inventory_manager import InventoryManager
from dialogs import RegisterSaleDialog, ClienteSelectorDialog, ProductDialog, RegisterPurchaseDialog, DistribuidorDialog, ClienteDialog
from sales_tab import SalesTab
from datetime import datetime

from num2words import num2words  # Instala las dependencias con: pip install -r requirements.txt

from factura_sv import generar_factura_electronica_pdf
from decimal import Decimal, ROUND_HALF_UP
from utils.monto import monto_a_texto_sv
import logging

logger = logging.getLogger(__name__)

def redondear(valor):
    return float(Decimal(str(valor)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Inventario Farmacia")
        self.resize(1200, 700)
        self.manager = InventoryManager()
        self.ultimo_archivo_json = None  # Guarda la ruta del último archivo .json usado
        self._setup_ui()
        self._apply_styles()
        self.estado_personas = []

    def generar_factura_pdf(self):
        """Función de generación de facturas no disponible."""
        QMessageBox.information(self, "Factura", "Función no disponible en esta versión.")

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

        # --- BOTONES LATERALES ---
        self.btn_add_product = QPushButton("Agregar Producto")
        self.btn_edit_product = QPushButton("Editar Producto")
        self.btn_register_sale = QPushButton("Registrar Venta")
        # Botón con salto de línea para que el texto quepa bien
        self.btn_register_credito_fiscal = QPushButton("Registrar Venta\nCrédito Fiscal")
        self.btn_register_purchase = QPushButton("Registrar Compra")
        self.btn_delete_product = QPushButton("Eliminar Producto")
        self.btn_guardar_rapido = QPushButton("Guardar\nRápido")
        self.btn_cargar_inventario = QPushButton("Cargar Inventario")

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
            btn.setStyleSheet("font-size:11px; padding:4px 0;")

        # Botones verdes más pequeños y debajo de los celestes pero encima del rojo
        self.btn_guardar_rapido.setStyleSheet(
            "background-color: #27ae60; color: #fff; font-weight: bold; font-size:11px; border-radius: 8px; min-width: 140px; min-height: 24px; max-width: 200px;")
        self.btn_cargar_inventario.setStyleSheet(
            "background-color: #27ae60; color: #fff; font-weight: bold; font-size:11px; border-radius: 8px; min-width: 140px; min-height: 24px; max-width: 200px;")

        self.btn_delete_product.setStyleSheet(
            "background-color: #b71c1c; color: #fff; font-weight: bold; font-size:11px; border-radius: 8px; min-width: 140px; min-height: 24px; max-width: 200px;")

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
        vend_dist_layout = QHBoxLayout()

        # Vendedores
        vend_layout = QVBoxLayout()
        vend_layout.addWidget(QLabel("Vendedores"))
        self.vendedores_tree = QTreeWidget()
        self.vendedores_tree.setHeaderHidden(True)
        vend_layout.addWidget(self.vendedores_tree)
        btn_add_vend = QPushButton("Añadir Vendedor")
        btn_add_vend.setMinimumHeight(24)
        btn_add_vend.setMaximumHeight(28)
        btn_add_vend.setStyleSheet("font-size:11px;")
        btn_add_vend.clicked.connect(self._agregar_vendedor)
        vend_layout.addWidget(btn_add_vend)

        btn_edit_vend = QPushButton("Editar Vendedor")
        btn_edit_vend.setMinimumHeight(24)
        btn_edit_vend.setMaximumHeight(28)
        btn_edit_vend.setStyleSheet("font-size:11px;")
        btn_edit_vend.clicked.connect(self._editar_vendedor)
        vend_layout.addWidget(btn_edit_vend)

        vend_dist_layout.addLayout(vend_layout)

        # Distribuidores -> Distribuidores
        dist_layout = QVBoxLayout()
        dist_layout.addWidget(QLabel("Distribuidores"))  # <--- Cambia aquí
        self.Distribuidores_tree = QTreeWidget()         # <--- Cambia el nombre de la variable también (opcional, pero recomendado)
        self.Distribuidores_tree.setHeaderHidden(True)
        dist_layout.addWidget(self.Distribuidores_tree)

        btns_h_layout = QHBoxLayout()
        btn_add_dist = QPushButton("Añadir Distribuidor")
        btn_add_dist.setMinimumHeight(24)
        btn_add_dist.setMaximumHeight(28)
        btn_add_dist.setStyleSheet("font-size:11px;")
        btn_add_dist.clicked.connect(self._agregar_Distribuidor)
        btns_h_layout.addWidget(btn_add_dist, alignment=Qt.AlignLeft)

        btn_info_dist = QPushButton("Info de Distribuidor")
        btn_info_dist.setFixedHeight(24)
        btn_info_dist.setFixedWidth(110)
        btn_info_dist.setStyleSheet(
            "background-color: #f1c40f; color: #222; font-size:10px; font-weight:bold; border-radius: 8px;"
        )
        btn_info_dist.clicked.connect(self._mostrar_info_Distribuidor)
        btns_h_layout.addWidget(btn_info_dist, alignment=Qt.AlignRight)

        dist_layout.addLayout(btns_h_layout)

        btn_edit_dist = QPushButton("Editar Distribuidor")
        btn_edit_dist.setMinimumHeight(24)
        btn_edit_dist.setMaximumHeight(28)
        btn_edit_dist.setStyleSheet("font-size:11px;")
        btn_edit_dist.clicked.connect(self._editar_Distribuidor)
        dist_layout.addWidget(btn_edit_dist)

        vend_dist_layout.addLayout(dist_layout)

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
        self.btn_edit_cliente = QPushButton("Editar Cliente")
        self.btn_delete_cliente = QPushButton("Eliminar Cliente")
        btns.addWidget(self.btn_add_cliente)
        btns.addWidget(self.btn_edit_cliente)
        btns.addWidget(self.btn_delete_cliente)
        clientes_layout.addLayout(btns)

        clientes_tab.setLayout(clientes_layout)

        # --- PESTAÑA DE VENTAS ---
        self.sales_tab = SalesTab(self.manager, self)

        # --- PESTAÑA DE COMPRAS ---
        from purchases_tab import PurchasesTab
        self.compras_tab = PurchasesTab(self.manager, self)

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
        self.tabs.addTab(self.sales_tab, "Ventas")
        self.tabs.addTab(self.compras_tab, "Compras")
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
        filtro_layout.addWidget(self.trabajadores_filtro_vendedor)
        filtro_layout.addWidget(self.trabajadores_filtro_area)
        trabajadores_layout.addLayout(filtro_layout)

        # Tabla
        self.trabajadores_table = QTableWidget(0, 10)
        self.trabajadores_table.setHorizontalHeaderLabels([
            "Código", "Nombre", "DUI", "NIT", "Nacimiento", "Cargo", "Área", "Teléfono", "Email", "¿Vendedor?"
        ])
        trabajadores_layout.addWidget(self.trabajadores_table)

        # Botones
        btns = QHBoxLayout()
        self.btn_add_trabajador = QPushButton("Agregar")
        self.btn_edit_trabajador = QPushButton("Editar")
        self.btn_delete_trabajador = QPushButton("Eliminar")
        btns.addWidget(self.btn_add_trabajador)
        btns.addWidget(self.btn_edit_trabajador)
        btns.addWidget(self.btn_delete_trabajador)
        trabajadores_layout.addLayout(btns)

        trabajadores_tab.setLayout(trabajadores_layout)
        self.tabs.addTab(trabajadores_tab, "Trabajadores")

        # --- PESTAÑA DE ESTADOS DE CUENTA ---
        estado_tab = QWidget()
        estado_layout = QVBoxLayout()

        controles = QHBoxLayout()
        self.estado_tipo_combo = QComboBox()
        self.estado_tipo_combo.addItems(["Cliente", "Vendedor"])
        self.estado_search_bar = QLineEdit()
        self.estado_search_bar.setPlaceholderText("Buscar por código o nombre...")
        self.estado_fecha_inicio = QDateEdit(QDate.currentDate())
        self.estado_fecha_inicio.setCalendarPopup(True)
        self.estado_fecha_fin = QDateEdit(QDate.currentDate())
        self.estado_fecha_fin.setCalendarPopup(True)
        self.estado_anio_actual = QCheckBox("Año en curso")
        self.btn_generar_estado = QPushButton("Generar")
        controles.addWidget(self.estado_tipo_combo)
        controles.addWidget(self.estado_search_bar)
        controles.addWidget(QLabel("Desde"))
        controles.addWidget(self.estado_fecha_inicio)
        controles.addWidget(QLabel("Hasta"))
        controles.addWidget(self.estado_fecha_fin)
        controles.addWidget(self.estado_anio_actual)
        controles.addWidget(self.btn_generar_estado)
        estado_layout.addLayout(controles)

        self.estado_table = QTableWidget(0, 2)
        self.estado_table.setHorizontalHeaderLabels(["Código", "Nombre"])
        estado_layout.addWidget(self.estado_table)

        estado_tab.setLayout(estado_layout)
        self.tabs.addTab(estado_tab, "Estados de cuenta")

        # Conexiones
        self.btn_add_trabajador.clicked.connect(self._agregar_trabajador)
        self.btn_edit_trabajador.clicked.connect(self._editar_trabajador)
        self.btn_delete_trabajador.clicked.connect(self._eliminar_trabajador)
        self.estado_tipo_combo.currentIndexChanged.connect(self._cargar_personas_estado)
        self.estado_search_bar.textChanged.connect(self._cargar_personas_estado)
        self.btn_generar_estado.clicked.connect(self._generar_estado_cuenta)
        self.estado_anio_actual.toggled.connect(self._toggle_estado_fechas)

        self._actualizar_tabla_trabajadores()
        self._cargar_personas_estado()

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
        self.actual_search_bar.textChanged.connect(self._actualizar_inventario_actual)
        self._actualizar_tabla_clientes()  # <-- SOLO AGREGA ESTA LÍNEA AL FINAL DE _setup_ui
        self._actualizar_inventario_actual()  # <-- AGREGA ESTA LÍNEA AL FINAL DE _setup_ui

        self.selected_row = None
        self._actualizar_inventario_actual()

    def _apply_styles(self):
        self.setStyleSheet("""
            QPushButton {
                background-color: #0097e6;
                color: #fff;
                border-radius: 8px;
                padding: 8px 0px;
                font-size: 12px;
                font-weight: bold;
                margin: 4px 0;
                min-width: 180px;
                min-height: 26px;
                max-width: 220px;
            }
            QPushButton:hover {
                background-color: #00a8ff;
            }
            QPushButton#btn_delete_product {
                background-color: #b71c1c;
                color: #fff;
            }
            QPushButton#btn_delete_product:hover {
                background-color: #d32f2f;
            }
            QLineEdit {
                border: 1px solid #dcdde1;
                border-radius: 6px;
                padding: 7px;
                font-size: 14px;
            }
            QTableView {
                background: #fff;
                border-radius: 8px;
                font-size: 13px;
            }
        """)
        # Si tienes el objectName para el botón de crédito fiscal, puedes agregarlo así:
        self.btn_register_credito_fiscal.setStyleSheet(
            "font-size:11px; min-width:200px; max-width:240px; min-height:26px; padding:6px 0;"
        )

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
                        None,
                        item.get("precio_con_iva", 0),
                        vendedor_id
                    )
                    if "lote_id" in item:
                        self.manager.db.disminuir_stock_lote(item["lote_id"], item["cantidad"])
                        self.manager.db.actualizar_stock_producto(item["producto_id"])
                self.manager.refresh_data()
                self.filter_products()
                self.sales_tab.load_sales()
                QMessageBox.information(self, "Venta", f"Venta registrada correctamente.\nTotal: ${total:.2f}")
                self._actualizar_historial()
                self._actualizar_inventario_actual()  # <-- AGREGA ESTA LÍNEA AQUÍ

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
                iva_retenido = data.get("iva_retenido", 0)
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
                    iva_retenido=iva_retenido,
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
                        item.get("precio_con_iva", 0),
                        vendedor_id
                    )
                   
                    if "lote_id" in item:
                        self.manager.db.disminuir_stock_lote(item["lote_id"], item["cantidad"])
                        self.manager.db.actualizar_stock_producto(item["producto_id"])
                self.manager.refresh_data()
                self.filter_products()
                self.sales_tab.load_sales()
                QMessageBox.information(self, "Venta a Crédito Fiscal", f"Venta registrada correctamente.\nTotal: ${venta_total:.2f}")
                self._actualizar_historial()
                self._actualizar_inventario_actual()

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
                self.compras_tab.refresh_filters()
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
                self.compras_tab.refresh_filters()
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
            self.compras_tab.refresh_filters()
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
            text = f"{vend.get('codigo', '')} - {vend['nombre']}"
            vend_item = QTreeWidgetItem([text])
            self.vendedores_tree.addTopLevelItem(vend_item)
            vend_item.setExpanded(False)

    def _actualizar_arbol_Distribuidores(self):
        self.Distribuidores_tree.clear()
        for dist in self.manager._Distribuidores:
            dist_item = QTreeWidgetItem([dist["nombre"]])
            vendedores = [v for v in self.manager._vendedores if v.get("Distribuidor_id") == dist["id"]]
            for vend in vendedores:
                text = f"{vend.get('codigo', '')} - {vend['nombre']}"
                vend_item = QTreeWidgetItem([text])
                dist_item.addChild(vend_item)
            self.Distribuidores_tree.addTopLevelItem(dist_item)
            dist_item.setExpanded(False)

    def _actualizar_lista_Distribuidores(self):
        self.Distribuidores_list.clear()
        for dist in self.manager.get_Distribuidor_names():
            self.Distribuidores_list.addItem(dist)

    def _agregar_vendedor(self):
        from dialogs import VendedorDialog
        codigo = self.manager.db.get_next_vendedor_codigo()
        dialog = VendedorDialog(self.manager._Distribuidores, self, codigo_sugerido=codigo)
        if dialog.exec_():
            data = dialog.get_data()
            self.manager.db.add_vendedor(
                data["nombre"],
                data["descripcion"],
                data["Distribuidor_id"],
                data["codigo"]
            )
            self.manager.refresh_data()
            self.compras_tab.refresh_filters()
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
                data["codigo"],
                data["nombre"],
                data["descripcion"],
                data["Distribuidor_id"]
            )
            self.manager.refresh_data()
            self.compras_tab.refresh_filters()
            self._actualizar_arbol_vendedores()
            QMessageBox.information(self, "Vendedor", "Vendedor editado correctamente.")

    def _agregar_Distribuidor(self):
        dialog = DistribuidorDialog(self)
        if dialog.exec_():
            data = dialog.get_data()
            self.manager.db.add_Distribuidor_detallado(data)
            self.manager.refresh_data()
            self.compras_tab.refresh_filters()
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
            self.compras_tab.refresh_filters()
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
        codigo = self.manager.db.get_next_cliente_codigo()
        dialog = ClienteDialog(self, codigo_sugerido=codigo)
        if dialog.exec_():
            data = dialog.get_data()
            self.manager.db.add_cliente(
                data["nombre"], data["nrc"], data["nit"], data["dui"], data["giro"],
                data["telefono"], data["email"], data["direccion"], data["departamento"], data["municipio"], data["codigo"]
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
                cli["id"], data["codigo"], data["nombre"], data["nrc"], data["nit"], data["dui"], data["giro"],
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
        """Actualización de historial (sin uso en la vista simplificada)."""
        pass
            

    def _limpiar_filtros_historial(self):
        """Método mantenido por compatibilidad."""
        pass

    def eventFilter(self, obj, event):
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
            self.inventario_actual_table.setItem(row, 2, QTableWidgetItem(str(d["cantidad"])))
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
        trabajadores = self.manager.db.get_trabajadores(solo_vendedores=solo_vendedores, area=area)
        self.trabajadores_table.setRowCount(len(trabajadores))
        for row, t in enumerate(trabajadores):
            self.trabajadores_table.setItem(row, 0, QTableWidgetItem(t.get("codigo", "")))
            self.trabajadores_table.setItem(row, 1, QTableWidgetItem(t.get("nombre", "")))
            self.trabajadores_table.setItem(row, 2, QTableWidgetItem(t.get("dui", "")))
            self.trabajadores_table.setItem(row, 3, QTableWidgetItem(t.get("nit", "")))
            self.trabajadores_table.setItem(row, 4, QTableWidgetItem(t.get("fecha_nacimiento", "")))
            self.trabajadores_table.setItem(row, 5, QTableWidgetItem(t.get("cargo", "")))
            self.trabajadores_table.setItem(row, 6, QTableWidgetItem(t.get("area", "")))
            self.trabajadores_table.setItem(row, 7, QTableWidgetItem(t.get("telefono", "")))
            self.trabajadores_table.setItem(row, 8, QTableWidgetItem(t.get("email", "")))
            self.trabajadores_table.setItem(row, 9, QTableWidgetItem("Sí" if t.get("es_vendedor") else "No"))

    def _get_selected_trabajador(self):
        row = self.trabajadores_table.currentRow()
        if row < 0:
            return None
        codigo = self.trabajadores_table.item(row, 0).text()
        trabajadores = self.manager.db.get_trabajadores()
        for t in trabajadores:
            if t.get("codigo", "") == codigo:
                return t
        return None

    def _agregar_trabajador(self):
        from dialogs import TrabajadorDialog
        codigo = self.manager.db.get_next_trabajador_codigo()
        dialog = TrabajadorDialog(parent=self)
        dialog.codigo.setText(codigo)
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

    def _cargar_personas_estado(self):
        search = self.estado_search_bar.text()
        if self.estado_tipo_combo.currentText() == "Cliente":
            personas = self.manager.db.get_clientes(search)
        else:
            personas = self.manager.db.get_trabajadores(
                solo_vendedores=True, search=search
            )
        self.estado_personas = personas
        self.estado_table.setColumnCount(2)
        self.estado_table.setHorizontalHeaderLabels(["Código", "Nombre"])
        self.estado_table.setRowCount(len(personas))
        for row, p in enumerate(personas):
            self.estado_table.setItem(row, 0, QTableWidgetItem(p.get("codigo", "")))
            self.estado_table.setItem(row, 1, QTableWidgetItem(p.get("nombre", "")))

    def _get_selected_estado_persona(self):
        row = self.estado_table.currentRow()
        if row < 0 or row >= len(getattr(self, "estado_personas", [])):
            return None
        return self.estado_personas[row]

    def _toggle_estado_fechas(self, checked: bool):
        """Habilita o deshabilita las fechas manuales."""
        self.estado_fecha_inicio.setEnabled(not checked)
        self.estado_fecha_fin.setEnabled(not checked)
        if checked:
            self.estado_fecha_inicio.setDate(QDate(QDate.currentDate().year(), 1, 1))
            self.estado_fecha_fin.setDate(QDate.currentDate())

    def _generar_estado_cuenta(self):
        persona = self._get_selected_estado_persona()
        if not persona:
            QMessageBox.warning(self, "Estado de cuenta", "Seleccione una persona")
            return
        persona_id = persona.get("id")
        tipo = "cliente" if self.estado_tipo_combo.currentText() == "Cliente" else "vendedor"
        if self.estado_anio_actual.isChecked():
            inicio = QDate(QDate.currentDate().year(), 1, 1)
            fin = QDate.currentDate()
        else:
            inicio = self.estado_fecha_inicio.date()
            fin = self.estado_fecha_fin.date()
        facturas = self.manager.db.get_estado_cuenta(
            persona_id,
            tipo,
            inicio.toString("yyyy-MM-dd"),
            fin.toString("yyyy-MM-dd"),
        )
        self.estado_table.setColumnCount(4)
        self.estado_table.setHorizontalHeaderLabels(["Fecha", "Factura", "Monto", "Saldo"])
        self.estado_table.setRowCount(len(facturas))
        for row, f in enumerate(facturas):
            self.estado_table.setItem(row, 0, QTableWidgetItem(f.get("fecha", "")))
            self.estado_table.setItem(row, 1, QTableWidgetItem(str(f.get("id"))))
            self.estado_table.setItem(row, 2, QTableWidgetItem(f"${float(f.get('total', 0)):.2f}"))
            self.estado_table.setItem(row, 3, QTableWidgetItem(f"${float(f.get('saldo', 0)):.2f}"))

