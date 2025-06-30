from decimal import Decimal, getcontext, ROUND_HALF_UP
import json
import logging

logger = logging.getLogger(__name__)
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QSpinBox,
    QDoubleSpinBox, QPushButton, QListWidget, QListWidgetItem, QMessageBox, QCheckBox, QRadioButton, QComboBox,
    QDateEdit, QTableWidget, QTableWidgetItem, QGroupBox, QFormLayout, QButtonGroup,
    QAbstractItemView, QTextEdit, QStackedLayout, QWidget
)
from PyQt5.QtCore import Qt, QDate, QUrl
from PyQt5.QtGui import QColor, QDesktopServices
import os

getcontext().prec = 4

def get_field(obj, key, default=0):
    if isinstance(obj, dict):
        return obj.get(key, default)
    elif hasattr(obj, "keys"):
        return obj[key] if key in obj.keys() else default
    return default

def validar_nit(nit):
    import re
    return bool(re.match(r"^\d{4}-\d{6}-\d{3}-\d$", nit))

def validar_email(email):
    import re
    return bool(re.match(r"^[^@]+@[^@]+\.[^@]+$", email))

def cargar_departamentos_municipios():
    # Lista completa de departamentos y municipios de El Salvador
    return {
        "Ahuachapán": [
            "Ahuachapán", "Apaneca", "Atiquizaya", "Concepción de Ataco", "El Refugio", "Guaymango", "Jujutla",
            "San Francisco Menéndez", "San Lorenzo", "San Pedro Puxtla", "Tacuba", "Turín"
        ],
        "Cabañas": [
            "Cinquera", "Dolores", "Guacotecti", "Ilobasco", "Jutiapa", "San Isidro", "Sensuntepeque",
            "Tejutepeque", "Victoria"
        ],
        "Chalatenango": [
            "Agua Caliente", "Arcatao", "Azacualpa", "Citalá", "Comalapa", "Concepción Quezaltepeque",
            "Dulce Nombre de María", "El Carrizal", "El Paraíso", "La Laguna", "La Palma", "La Reina",
            "Las Vueltas", "Nombre de Jesús", "Nueva Concepción", "Nueva Trinidad", "Ojos de Agua", "Potonico",
            "San Antonio de la Cruz", "San Antonio Los Ranchos", "San Fernando", "San Francisco Lempa",
            "San Francisco Morazán", "San Ignacio", "San Isidro Labrador", "San Luis del Carmen",
            "San Miguel de Mercedes", "San Rafael", "Santa Rita", "Tejutla"
        ],
        "Cuscatlán": [
            "Candelaria", "Cojutepeque", "El Carmen", "El Rosario", "Monte San Juan", "Oratorio de Concepción",
            "San Bartolomé Perulapía", "San Cristóbal", "San José Guayabal", "San Pedro Perulapán",
            "San Rafael Cedros", "San Ramón", "Santa Cruz Analquito", "Santa Cruz Michapa", "Suchitoto",
            "Tenancingo"
        ],
        "La Libertad": [
            "Antiguo Cuscatlán", "Chiltiupán", "Ciudad Arce", "Colón", "Comasagua", "Huizúcar", "Jayaque",
            "Jicalapa", "La Libertad", "Nueva San Salvador (Santa Tecla)", "Nuevo Cuscatlán", "San Juan Opico",
            "Quezaltepeque", "Sacacoyo", "San José Villanueva", "San Matías", "San Pablo Tacachico", "Talnique",
            "Tamanique", "Teotepeque", "Tepecoyo", "Zaragoza"
        ],
        "La Paz": [
            "Cuyultitán", "El Rosario", "Jerusalén", "Mercedes La Ceiba", "Olocuilta", "Paraíso de Osorio",
            "San Antonio Masahuat", "San Emigdio", "San Francisco Chinameca", "San Juan Nonualco",
            "San Juan Talpa", "San Juan Tepezontes", "San Luis La Herradura", "San Luis Talpa",
            "San Miguel Tepezontes", "San Pedro Masahuat", "San Pedro Nonualco", "San Rafael Obrajuelo",
            "Santa María Ostuma", "Santiago Nonualco", "Tapalhuaca", "Zacatecoluca"
        ],
        "La Unión": [
            "Anamorós", "Bolívar", "Concepción de Oriente", "Conchagua", "El Carmen", "El Sauce", "Intipucá",
            "La Unión", "Lislique", "Meanguera del Golfo", "Nueva Esparta", "Pasaquina", "Polorós", "San Alejo",
            "San José", "Santa Rosa de Lima", "Yayantique", "Yucuaiquín"
        ],
        "Morazán": [
            "Arambala", "Cacaopera", "Chilanga", "Corinto", "Delicias de Concepción", "El Divisadero",
            "El Rosario", "Gualococti", "Guatajiagua", "Joateca", "Jocoaitique", "Jocoro", "Lolotiquillo",
            "Meanguera", "Osicala", "Perquín", "San Carlos", "San Fernando", "San Francisco Gotera",
            "San Isidro", "San Simón", "Sensembra", "Sociedad", "Torola", "Yamabal", "Yoloaiquín"
        ],
        "San Miguel": [
            "Carolina", "Chapeltique", "Chinameca", "Chirilagua", "Ciudad Barrios", "Comacarán", "El Tránsito",
            "Lolotique", "Moncagua", "Nueva Guadalupe", "Nuevo Edén de San Juan", "Quelepa", "San Antonio",
            "San Gerardo", "San Jorge", "San Luis de la Reina", "San Miguel", "San Rafael Oriente", "Sesori",
            "Uluazapa"
        ],
        "San Salvador": [
            "Aguilares", "Apopa", "Ayutuxtepeque", "Cuscatancingo", "Delgado", "El Paisnal", "Guazapa",
            "Ilopango", "Mejicanos", "Nejapa", "Panchimalco", "Rosario de Mora", "San Marcos", "San Martín",
            "San Salvador", "Santiago Texacuangos", "Santo Tomás", "Soyapango", "Tonacatepeque"
        ],
        "San Vicente": [
            "Apastepeque", "Guadalupe", "San Cayetano Istepeque", "San Esteban Catarina", "San Ildefonso",
            "San Lorenzo", "San Sebastián", "San Vicente", "Santa Clara", "Santo Domingo", "Tecoluca",
            "Tepetitán", "Verapaz"
        ],
        "Santa Ana": [
            "Candelaria de la Frontera", "Chalchuapa", "Coatepeque", "El Congo", "El Porvenir", "Masahuat",
            "Metapán", "San Antonio Pajonal", "San Sebastián Salitrillo", "Santa Ana", "Santa Rosa Guachipilín",
            "Santiago de la Frontera", "Texistepeque"
        ],
        "Sonsonate": [
            "Acajutla", "Armenia", "Caluco", "Cuisnahuat", "Izalco", "Juayúa", "Nahuizalco", "Nahulingo",
            "Salcoatitán", "San Antonio del Monte", "San Julián", "Santa Catarina Masahuat",
            "Santa Isabel Ishuatán", "Santo Domingo de Guzmán", "Sonsonate", "Sonzacate"
        ],
        "Usulután": [
            "Alegría", "Berlín", "California", "Concepción Batres", "El Triunfo", "Ereguayquín", "Estanzuelas",
            "Jiquilisco", "Jucuapa", "Jucuarán", "Mercedes Umaña", "Nueva Granada", "Ozatlán",
            "Puerto El Triunfo", "San Agustín", "San Buenaventura", "San Dionisio", "San Francisco Javier",
            "Santa Elena", "Santa María", "Santiago de María", "Tecapán", "Usulután"
        ]
    }

class ClienteSelectorDialog(QDialog):
    def __init__(self, clientes, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Seleccionar Cliente")
        layout = QVBoxLayout()
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Buscar cliente por nombre, NIT, NRC, etc.")
        layout.addWidget(self.search_bar)
        self.lista_clientes = QListWidget()
        self.clientes = sorted(clientes, key=lambda c: get_field(c, "codigo", "") or get_field(c, "nombre", ""))
        self.clientes_mostrados = self.clientes[:]  # <-- NUEVO: lista de los clientes actualmente mostrados
        self._mostrar_clientes(self.clientes)
        layout.addWidget(self.lista_clientes)
        self.btn_ok = QPushButton("Seleccionar")
        self.btn_ok.clicked.connect(self.accept)
        layout.addWidget(self.btn_ok)
        self.setLayout(layout)
        self.search_bar.textChanged.connect(self._filtrar_clientes)
        self.selected_cliente = None
        self.lista_clientes.itemClicked.connect(self._seleccionar_cliente)

    def _mostrar_clientes(self, clientes):
        self.lista_clientes.clear()
        self.clientes_mostrados = clientes[:]  # <-- Actualiza la lista de mostrados
        for cli in clientes:
            codigo = get_field(cli, "codigo", "")
            nombre = get_field(cli, "nombre", "")
            nit = get_field(cli, "nit", "")
            texto = f"{codigo} | {nombre} | NIT: {nit}"
            self.lista_clientes.addItem(texto)

    def _filtrar_clientes(self, texto):
        texto = texto.lower()
        filtrados = [
            cli for cli in self.clientes
            if texto in (get_field(cli, "codigo", "") or "").lower()
            or texto in (get_field(cli, "nombre", "") or "").lower()
            or texto in (get_field(cli, "nit", "") or "").lower()
            or texto in (get_field(cli, "nrc", "") or "").lower()
        ]
        self._mostrar_clientes(filtrados)

    def _seleccionar_cliente(self, item):
        idx = self.lista_clientes.currentRow()
        if idx >= 0:
            self.selected_cliente = self.clientes_mostrados[idx]  # <-- Usa la lista de mostrados

    def get_selected_cliente(self):
        return self.selected_cliente


class EstadoCuentaDialog(QDialog):
    """Ventana para configurar la generación de estados de cuenta."""

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("Generar estado de cuenta")

        layout = QVBoxLayout()

        # Modo de generación
        self.modo_combo = QComboBox()
        self.modo_combo.addItems(["Por cliente", "Por vendedor", "Todos los vendedores"])
        layout.addWidget(self.modo_combo)

        # --- Widgets dinámicos ---
        self.stack = QStackedLayout()

        # Por cliente
        cli_widget = QWidget()
        cli_layout = QVBoxLayout(cli_widget)
        self.cliente_search = QLineEdit()
        self.cliente_search.setPlaceholderText(
            "Buscar cliente por código o nombre..."
        )
        cli_layout.addWidget(self.cliente_search)
        self.cliente_table = QTableWidget(0, 2)
        self.cliente_table.setHorizontalHeaderLabels(["Código", "Nombre"])
        self.cliente_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.cliente_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.clientes = self.db.get_clientes()
        self.clientes_mostrados = list(self.clientes)
        self._mostrar_clientes(self.clientes)
        cli_layout.addWidget(self.cliente_table)
        self.solo_saldo_cliente = QCheckBox("Incluir solo saldos pendientes")
        cli_layout.addWidget(self.solo_saldo_cliente)
        self.stack.addWidget(cli_widget)

        # Por vendedor
        vend_widget = QWidget()
        vend_layout = QVBoxLayout(vend_widget)
        self.vendedor_search = QLineEdit()
        self.vendedor_search.setPlaceholderText(
            "Buscar vendedor por código o nombre..."
        )
        vend_layout.addWidget(self.vendedor_search)
        self.vendedor_table = QTableWidget(0, 2)
        self.vendedor_table.setHorizontalHeaderLabels(["Código", "Nombre"])
        self.vendedor_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.vendedor_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.vendedores = self.db.get_vendedores()
        self.vendedores_mostrados = list(self.vendedores)
        self._mostrar_vendedores(self.vendedores)
        vend_layout.addWidget(self.vendedor_table)
        self.solo_saldo_vend = QCheckBox("Incluir solo clientes con saldo")
        vend_layout.addWidget(self.solo_saldo_vend)
        self.stack.addWidget(vend_widget)

        # Todos los vendedores (tabla sin búsqueda)
        todos_widget = QWidget()
        todos_layout = QVBoxLayout(todos_widget)
        self.vendedor_table_all = QTableWidget(0, 2)
        self.vendedor_table_all.setHorizontalHeaderLabels(["Código", "Nombre"])
        self.vendedor_table_all.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.vendedor_table_all.setSelectionBehavior(QTableWidget.SelectRows)
        self._mostrar_vendedores_all(self.vendedores)
        todos_layout.addWidget(self.vendedor_table_all)
        self.stack.addWidget(todos_widget)

        layout.addLayout(self.stack)

        # Filtros comunes
        filtros = QHBoxLayout()
        self.anio_actual = QCheckBox("Año en curso")
        filtros.addWidget(self.anio_actual)
        filtros.addWidget(QLabel("Desde"))
        self.fecha_inicio = QDateEdit(QDate.currentDate())
        self.fecha_inicio.setCalendarPopup(True)
        filtros.addWidget(self.fecha_inicio)
        filtros.addWidget(QLabel("Hasta"))
        self.fecha_fin = QDateEdit(QDate.currentDate())
        self.fecha_fin.setCalendarPopup(True)
        filtros.addWidget(self.fecha_fin)
        layout.addLayout(filtros)

        self.incluir_pagos = QCheckBox("Incluir abonos/pagos realizados")
        self.agrupar_factura = QCheckBox("Agrupar por factura")
        self.incluir_detalles = QCheckBox("Incluir detalles de productos")
        layout.addWidget(self.incluir_pagos)
        layout.addWidget(self.agrupar_factura)
        layout.addWidget(self.incluir_detalles)

        # Botones
        btns = QHBoxLayout()
        self.btn_generar = QPushButton("Generar PDF")
        self.btn_imprimir = QPushButton("Generar e imprimir PDF")
        btns.addWidget(self.btn_generar)
        btns.addWidget(self.btn_imprimir)
        layout.addLayout(btns)

        self.setLayout(layout)

        self.modo_combo.currentIndexChanged.connect(self.stack.setCurrentIndex)
        self.anio_actual.toggled.connect(self._toggle_fechas)
        self.cliente_search.textChanged.connect(self._filtrar_clientes)
        self.vendedor_search.textChanged.connect(self._filtrar_vendedores)
        self.cliente_table.itemSelectionChanged.connect(self._seleccionar_cliente)
        self.vendedor_table.itemSelectionChanged.connect(self._seleccionar_vendedor)

        self.btn_generar.clicked.connect(self._generar_pdf)
        self.btn_imprimir.clicked.connect(self._generar_e_imprimir_pdf)

    def _toggle_fechas(self, checked):
        self.fecha_inicio.setEnabled(not checked)
        self.fecha_fin.setEnabled(not checked)
        if checked:
            self.fecha_inicio.setDate(QDate(QDate.currentDate().year(), 1, 1))
            self.fecha_fin.setDate(QDate.currentDate())

    def _mostrar_clientes(self, clientes):
        self.cliente_table.setRowCount(len(clientes))
        for row, c in enumerate(clientes):
            self.cliente_table.setItem(row, 0, QTableWidgetItem(c.get("codigo", "")))
            self.cliente_table.setItem(row, 1, QTableWidgetItem(c.get("nombre", "")))
        self.clientes_mostrados = list(clientes)

    def _filtrar_clientes(self, texto: str):
        texto = texto.lower()
        filtrados = [
            c
            for c in self.clientes
            if texto in (c.get("codigo", "") or "").lower()
            or texto in (c.get("nombre", "") or "").lower()
        ]
        self._mostrar_clientes(filtrados)

    def _seleccionar_cliente(self):
        idx = self.cliente_table.currentRow()
        if 0 <= idx < len(self.clientes_mostrados):
            self.selected_cliente = self.clientes_mostrados[idx]

    def _mostrar_vendedores(self, vendedores):
        self.vendedor_table.setRowCount(len(vendedores))
        for row, v in enumerate(vendedores):
            self.vendedor_table.setItem(row, 0, QTableWidgetItem(v.get("codigo", "")))
            self.vendedor_table.setItem(row, 1, QTableWidgetItem(v.get("nombre", "")))
        self.vendedores_mostrados = list(vendedores)

    def _mostrar_vendedores_all(self, vendedores):
        self.vendedor_table_all.setRowCount(len(vendedores))
        for row, v in enumerate(vendedores):
            self.vendedor_table_all.setItem(row, 0, QTableWidgetItem(v.get("codigo", "")))
            self.vendedor_table_all.setItem(row, 1, QTableWidgetItem(v.get("nombre", "")))

    def _filtrar_vendedores(self, texto: str):
        texto = texto.lower()
        filtrados = [
            v
            for v in self.vendedores
            if texto in (v.get("codigo", "") or "").lower()
            or texto in (v.get("nombre", "") or "").lower()
        ]
        self._mostrar_vendedores(filtrados)

    def _seleccionar_vendedor(self):
        idx = self.vendedor_table.currentRow()
        if 0 <= idx < len(self.vendedores_mostrados):
            self.selected_vendedor = self.vendedores_mostrados[idx]

    # ---- Generación de PDF -----
    def _collect_params(self):
        modo_idx = self.modo_combo.currentIndex()
        modo = "cliente" if modo_idx == 0 else "vendedor" if modo_idx == 1 else "todos"
        params = {
            "modo": modo,
            "fecha_inicio": self.fecha_inicio.date().toString("yyyy-MM-dd"),
            "fecha_fin": self.fecha_fin.date().toString("yyyy-MM-dd"),
            "incluir_pagos": self.incluir_pagos.isChecked(),
            "agrupar_factura": self.agrupar_factura.isChecked(),
            "incluir_detalles": self.incluir_detalles.isChecked(),
        }
        if modo == "cliente" and self.clientes_mostrados:
            idx = self.cliente_table.currentRow()
            if 0 <= idx < len(self.clientes_mostrados):
                params["cliente_id"] = self.clientes_mostrados[idx].get("id")
        if modo == "vendedor" and self.vendedores_mostrados:
            idx = self.vendedor_table.currentRow()
            if 0 <= idx < len(self.vendedores_mostrados):
                params["vendedor_id"] = self.vendedores_mostrados[idx].get("id")
        return params

    def _generar_pdf(self):
        params = self._collect_params()
        filename = "estado_cuenta.pdf"
        from estado_cuenta_pdf import generar_estado_cuenta_pdf
        try:
            generar_estado_cuenta_pdf(self.db, archivo=filename, **params)
            QMessageBox.information(self, "Estado de cuenta", f"Archivo generado en {filename}")
        except Exception as e:
            QMessageBox.warning(self, "Estado de cuenta", f"Error: {e}")

    def _generar_e_imprimir_pdf(self):
        self._generar_pdf()
        # Intentar abrir el PDF para imprimir/visualizar
        filename = "estado_cuenta.pdf"
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath(filename)))


class ProductDialogBase:
    """Mixin with shared helper methods for product selection dialogs."""

    def _mostrar_productos(self, productos):
        self.product_list.clear()
        for p in productos:
            texto = (
                f"{p['nombre']} | Código: {p['codigo']} | Stock: {p['stock']} | "
                f"Vence: {p.get('fecha_vencimiento', '')}"
            )
            item = QListWidgetItem(texto)
            stock = p.get("stock", 0)
            if stock < 5:
                item.setBackground(QColor("red"))
            elif stock < 10:
                item.setBackground(QColor("orange"))
            elif stock < 25:
                item.setBackground(QColor("yellow"))
            else:
                item.setBackground(QColor("green"))
            self.product_list.addItem(item)
        self.productos = productos

    def _filtrar_productos(self, texto):
        texto = texto.lower()
        filtrados = [
            p for p in self._productos_original
            if texto in p.get("nombre", "").lower()
            or texto in p.get("codigo", "").lower()
            or texto in (
                f"{p['nombre']} | Código: {p['codigo']} | Stock: {p['stock']} | "
                f"Vence: {p.get('fecha_vencimiento', '')}"
            ).lower()
        ]
        self._mostrar_productos(filtrados)

    def _toggle_iva_radios(self, state):
        checked = self.iva_checkbox.isChecked()
        self.iva_agregado_radio.setEnabled(checked)
        self.iva_desglosado_radio.setEnabled(checked)
        if not checked:
            self.iva_agregado_radio.setAutoExclusive(False)
            self.iva_desglosado_radio.setAutoExclusive(False)
            self.iva_agregado_radio.setChecked(False)
            self.iva_desglosado_radio.setChecked(False)
            self.iva_agregado_radio.setAutoExclusive(True)
            self.iva_desglosado_radio.setAutoExclusive(True)
        else:
            if not self.iva_agregado_radio.isChecked() and not self.iva_desglosado_radio.isChecked():
                self.iva_agregado_radio.setChecked(True)
        if hasattr(self, "_recalcular_totales"):
            self._recalcular_totales()

    def _actualizar_Distribuidor_por_producto(self):
        idx = self.product_list.currentRow()
        if idx < 0 or idx >= len(self.productos):
            return
        lote = self.productos[idx]
        distribuidor_id = lote.get("Distribuidor_id")
        Distribuidores = getattr(self, "Distribuidores", None)
        if Distribuidores is None and hasattr(self, "parent") and self.parent() and hasattr(self.parent(), "manager"):
            Distribuidores = getattr(self.parent().manager, "_Distribuidores", None)
        if Distribuidores:
            for i, dist in enumerate(Distribuidores):
                if dist.get("id") == distribuidor_id:
                    self.Distribuidor_combo.setCurrentIndex(i)
                    break

    def _abrir_selector_cliente(self):
        selector = ClienteSelectorDialog(self.clientes, self)
        if selector.exec_():
            cli = selector.get_selected_cliente()
            if cli:
                nombre = get_field(cli, "codigo", "") or get_field(cli, "nombre", "")
                nit = get_field(cli, "nit", "")
                self.selected_cliente = cli
                self.cliente_label.setText(f"{nombre} | NIT: {nit}")
                for attr, key in [
                    ("nrc_edit", "nrc"),
                    ("nit_edit", "nit"),
                    ("giro_edit", "giro"),
                    ("email_edit", "email"),
                ]:
                    widget = getattr(self, attr, None)
                    if widget is not None:
                        widget.setText(get_field(cli, key, ""))


class RegisterSaleDialog(QDialog, ProductDialogBase):
    def __init__(self, productos, clientes, Distribuidores, vendedores_trabajadores, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Registrar Venta")


        main_layout = QHBoxLayout()

        self.productos = productos
        self.clientes = clientes
        self.vendedores_trabajadores = vendedores_trabajadores
        self.venta_items = []


        left_layout = QVBoxLayout()

        # Barra de búsqueda de productos
        self.product_search = QLineEdit()
        self.product_search.setPlaceholderText("Buscar producto por nombre o código...")
        left_layout.addWidget(self.product_search)

        # Lista de productos
        self.product_list = QListWidget()
        self._productos_original = list(productos)
        self._mostrar_productos(productos)
        left_layout.addWidget(self.product_list)

        # Tipo de venta
        left_layout.addWidget(QLabel("Tipo de venta:"))
        self.tipo_minorista = QRadioButton("Minorista")
        self.tipo_mayorista_unit = QRadioButton("Mayorista (unitario)")
        self.tipo_mayorista_total = QRadioButton("Mayorista (total personalizado)")
        self.tipo_minorista.setChecked(True)
        tipo_layout = QHBoxLayout()
        tipo_layout.addWidget(self.tipo_minorista)
        tipo_layout.addWidget(self.tipo_mayorista_unit)
        tipo_layout.addWidget(self.tipo_mayorista_total)
        left_layout.addLayout(tipo_layout)

        # Cantidad
        left_layout.addWidget(QLabel("Cantidad:"))
        self.cantidad_spin = QSpinBox()
        self.cantidad_spin.setMinimum(1)
        self.cantidad_spin.setMaximum(100000)
        left_layout.addWidget(self.cantidad_spin)

        # Precio unitario y total
        precio_layout = QHBoxLayout()
        self.precio_spin = QDoubleSpinBox()
        self.precio_spin.setMinimum(0)
        self.precio_spin.setMaximum(1000000)
        self.precio_spin.setDecimals(2)
        self.precio_spin.setPrefix("$")
        precio_layout.addWidget(QLabel("Precio unitario:"))
        precio_layout.addWidget(self.precio_spin)
        self.precio_total_spin = QDoubleSpinBox()
        self.precio_total_spin.setMinimum(0)
        self.precio_total_spin.setMaximum(100000000)
        self.precio_total_spin.setDecimals(2)
        self.precio_total_spin.setPrefix("$")
        precio_layout.addWidget(QLabel("Precio total:"))
        precio_layout.addWidget(self.precio_total_spin)
        left_layout.addLayout(precio_layout)

        # Descuento
        descuento_layout = QHBoxLayout()
        descuento_layout.addWidget(QLabel("Descuento:"))
        self.descuento_spin = QDoubleSpinBox()
        self.descuento_spin.setMinimum(0)
        self.descuento_spin.setMaximum(1000000)
        self.descuento_spin.setDecimals(2)
        self.descuento_spin.setValue(0)
        descuento_layout.addWidget(self.descuento_spin)
        self.descuento_tipo_combo = QComboBox()
        self.descuento_tipo_combo.addItems(["%", "$"])
        descuento_layout.addWidget(self.descuento_tipo_combo)
        left_layout.addLayout(descuento_layout)

        self.descuento_spin.valueChanged.connect(self._recalcular_totales)
        self.descuento_tipo_combo.currentIndexChanged.connect(self._recalcular_totales)

        # IVA con checkbox y radios
        iva_layout = QHBoxLayout()
        self.iva_checkbox = QCheckBox("Aplicar IVA")
        self.iva_checkbox.setChecked(False)
        iva_layout.addWidget(self.iva_checkbox)
        self.iva_agregado_radio = QRadioButton("IVA agregado (sumar 13%)")
        self.iva_desglosado_radio = QRadioButton("IVA desglosado (precio incluye IVA)")
        self.iva_agregado_radio.setChecked(False)
        self.iva_desglosado_radio.setChecked(False)
        self.iva_agregado_radio.setEnabled(False)
        self.iva_desglosado_radio.setEnabled(False)
        iva_layout.addWidget(self.iva_agregado_radio)
        iva_layout.addWidget(self.iva_desglosado_radio)
        left_layout.addLayout(iva_layout)


        # --- Clasificación fiscal individual por producto ---
        fiscal_layout = QHBoxLayout()
        fiscal_layout.addWidget(QLabel("Tipo fiscal:"))
        self.tipo_fiscal_combo = QComboBox()
        self.tipo_fiscal_combo.addItems(["Venta gravada", "Venta exenta", "Venta no sujeta"])
        fiscal_layout.addWidget(self.tipo_fiscal_combo)
        left_layout.addLayout(fiscal_layout)

        # Botón agregar a venta
        self.btn_agregar = QPushButton("Agregar a venta")
        left_layout.addWidget(self.btn_agregar)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([
            "Producto", "Cantidad", "Precio U.", "Descuento", "Tipo fiscal", "Eliminar"
        ])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        left_layout.addWidget(self.table)
        self.btn_agregar.clicked.connect(self._agregar_a_venta)
        self.table.cellClicked.connect(self._eliminar_fila)

        right_layout = QVBoxLayout()
        
        # Combo de vendedor trabajador
        right_layout.addWidget(QLabel("Vendedor (trabajador):"))
        self.vendedor_combo = QComboBox()
        self.vendedor_combo.addItem("Sin vendedor")
        for v in vendedores_trabajadores:
            self.vendedor_combo.addItem(v["nombre"])
        right_layout.addWidget(self.vendedor_combo)

        # Cliente selector
        right_layout.addWidget(QLabel("Cliente:"))
        self.cliente_btn = QPushButton("Seleccionar Cliente")
        self.cliente_label = QLabel("(Ningún cliente seleccionado)")
        right_layout.addWidget(self.cliente_btn)
        right_layout.addWidget(self.cliente_label)
        self.selected_cliente = None

        # Campo "Venta a cuenta de"
        right_layout.addWidget(QLabel("Venta a cuenta de:"))
        self.venta_a_cuenta_de_edit = QLineEdit()
        self.venta_a_cuenta_de_edit.setPlaceholderText("Venta a cuenta de")
        right_layout.addWidget(self.venta_a_cuenta_de_edit)

        # Distribuidor
        right_layout.addWidget(QLabel("Distribuidor:"))
        self.Distribuidor_combo = QComboBox()
        self.Distribuidor_combo.addItems(Distribuidores)
        right_layout.addWidget(self.Distribuidor_combo)

        # Resumen
        self.sumas_label = QLabel("Sumas: $0.00")
        self.iva_label = QLabel("IVA: $0.00")
        self.subtotal_label = QLabel("Subtotal: $0.00")
        self.total_label = QLabel("Venta total: $0.00")
        right_layout.addWidget(self.sumas_label)
        right_layout.addWidget(self.iva_label)
        right_layout.addWidget(self.subtotal_label)
        right_layout.addWidget(self.total_label)

        # Botón para registrar la venta
        self.btn_ok = QPushButton("Registrar")
        right_layout.addWidget(self.btn_ok)
        self.btn_ok.clicked.connect(self._validar_y_accept)  

        # --- AGREGA LOS DOS LAYOUTS AL PRINCIPAL ---
        main_layout.addLayout(left_layout, 2)
        main_layout.addLayout(right_layout, 1)
        self.setLayout(main_layout)

        # Creamos un diccionario que mapea nombre de producto a nombre de Distribuidor
        self._producto_Distribuidor_map = {}
        # Construimos un diccionario id->nombre para Distribuidores
        Distribuidores_dict = {}
        if parent and hasattr(parent, "manager") and hasattr(parent.manager, "_Distribuidores"):
            for v in parent.manager._Distribuidores:
                Distribuidores_dict[v["id"]] = v["nombre"]
        # Llena el mapa producto->Distribuidor
        for p in productos:
            nombre_prod = get_field(p, "nombre", "")
            Distribuidor_nombre = ""
            Distribuidor_id = None
            # Acceso seguro a Distribuidor_id
            if isinstance(p, dict):
                Distribuidor_id = p.get("Distribuidor_id")
            elif hasattr(p, "keys") and "Distribuidor_id" in p.keys():
                Distribuidor_id = p["Distribuidor_id"]
            if Distribuidor_id and Distribuidor_id in Distribuidores_dict:
                Distribuidor_nombre = Distribuidores_dict[Distribuidor_id]
            self._producto_Distribuidor_map[nombre_prod] = Distribuidor_nombre

        # Agrupa tipo de venta en su propio grupo
        self.tipo_venta_group = QButtonGroup(self)
        self.tipo_venta_group.setExclusive(True)
        self.tipo_venta_group.addButton(self.tipo_minorista)
        self.tipo_venta_group.addButton(self.tipo_mayorista_unit)
        self.tipo_venta_group.addButton(self.tipo_mayorista_total)

        # Agrupa los radios en un grupo exclusivo para que solo uno pueda estar seleccionado
        self.iva_group = QButtonGroup(self)
        self.iva_group.setExclusive(True)
        self.iva_group.addButton(self.iva_agregado_radio)
        self.iva_group.addButton(self.iva_desglosado_radio)

        # --- CONEXIONES PARA IVA ---
        # Al cambiar la checkbox, habilita/deshabilita los radios y selecciona uno por defecto si se activa
        self.iva_checkbox.stateChanged.connect(self._toggle_iva_radios)
        # Al cambiar cualquiera de los radios, recalcula el total en tiempo real
        self.iva_agregado_radio.toggled.connect(self._recalcular_totales)      # <--- CORRIGE AQUÍ
        self.iva_desglosado_radio.toggled.connect(self._recalcular_totales)    # <--- Y AQUÍ

        # Estado
        self.productos_data = productos

        # Conexiones
        self.cliente_btn.clicked.connect(self._abrir_selector_cliente)
        self.product_list.currentRowChanged.connect(self._actualizar_precio_defecto)
        self.tipo_minorista.toggled.connect(self._actualizar_precio_defecto)
        self.tipo_mayorista_unit.toggled.connect(self._actualizar_precio_defecto)
        self.tipo_mayorista_total.toggled.connect(self._actualizar_precio_defecto)
        self.cantidad_spin.valueChanged.connect(self._recalcular_totales)
        self.precio_spin.valueChanged.connect(self._recalcular_totales)
        self.precio_total_spin.valueChanged.connect(self._recalcular_totales)
        self.iva_agregado_radio.toggled.connect(self._recalcular_totales)
        self.iva_desglosado_radio.toggled.connect(self._recalcular_totales)
        self.product_search.textChanged.connect(self._filtrar_productos)       

        # Permitir edición según tipo de venta
        self.tipo_minorista.toggled.connect(self._toggle_precio_edicion)
        self.tipo_mayorista_unit.toggled.connect(self._toggle_precio_edicion)
        self.tipo_mayorista_total.toggled.connect(self._toggle_precio_edicion)

        # --- INICIO BLOQUE NUEVO: Actualizar combo de Distribuidor en tiempo real según producto seleccionado ---
        self.product_list.currentRowChanged.connect(self._actualizar_Distribuidor_por_producto)
        # --- FIN BLOQUE NUEVO ---

    def set_productos_data(self, productos_data):
        self.productos_data = productos_data

    def _actualizar_precio_defecto(self):
        idx = self.product_list.currentRow()
        if idx < 0:
            self.precio_spin.setValue(0)
            self.precio_total_spin.setValue(0)
            self._recalcular_totales()
            return
        nombre = self.product_list.currentItem().text()
        prod = None
        if 0 <= idx < len(self.productos):
            prod = self.productos[idx]
        elif self.productos_data:
            for p in self.productos_data:
                nombre_prod = get_field(p, "nombre", "")
                if nombre.startswith(nombre_prod):
                    prod = p
                    break
        precio = 0
        if prod:
            if self.tipo_minorista.isChecked():
                precio = get_field(prod, "precio_venta_minorista", 0)
            elif self.tipo_mayorista_unit.isChecked() or self.tipo_mayorista_total.isChecked():
                precio = get_field(prod, "precio_venta_mayorista", 0)
        self.precio_spin.blockSignals(True)
        self.precio_total_spin.blockSignals(True)
        self.precio_spin.setValue(float(precio))
        self.precio_total_spin.setValue(float(precio) * self.cantidad_spin.value())
        self.precio_spin.blockSignals(False)
        self.precio_total_spin.blockSignals(False)
        self._toggle_precio_edicion()
        self._recalcular_totales()

    def _toggle_precio_edicion(self):
        # Permitir editar el campo correspondiente según el tipo de venta
        if self.tipo_minorista.isChecked():
            self.precio_spin.setEnabled(True)
            self.precio_total_spin.setEnabled(False)
        elif self.tipo_mayorista_unit.isChecked():
            self.precio_spin.setEnabled(True)
            self.precio_total_spin.setEnabled(False)
        elif self.tipo_mayorista_total.isChecked():
            self.precio_spin.setEnabled(False)
            self.precio_total_spin.setEnabled(True)
        self._recalcular_totales()


    def _recalcular_totales(self):
        cantidad = self.cantidad_spin.value()

        # --- Sincroniza precio unitario y total en modo mayorista total ---
        if self.tipo_mayorista_total.isChecked():
            precio_total = self.precio_total_spin.value()
            precio_unitario = round(precio_total / cantidad, 6) if cantidad > 0 else 0
            self.precio_spin.blockSignals(True)
            self.precio_spin.setValue(precio_unitario)
            self.precio_spin.blockSignals(False)
        else:
            precio_unitario = self.precio_spin.value()
            precio_total = precio_unitario * cantidad
            self.precio_total_spin.blockSignals(True)
            self.precio_total_spin.setValue(precio_total)
            self.precio_total_spin.blockSignals(False)

        descuento_valor = self.descuento_spin.value()
        descuento_tipo = self.descuento_tipo_combo.currentText()
        subtotal = precio_total

        # Cálculo del descuento
        if descuento_tipo == "%":
            descuento_monto = subtotal * (descuento_valor / 100)
        else:
            descuento_monto = descuento_valor

        subtotal_con_descuento = max(subtotal - descuento_monto, 0)

        # IVA (si aplica)
        iva = 0
        if hasattr(self, "iva_checkbox") and self.iva_checkbox.isChecked():
            if self.iva_agregado_radio.isChecked():
                iva = subtotal_con_descuento * 0.13
                total = subtotal_con_descuento + iva
            elif self.iva_desglosado_radio.isChecked():
                iva = subtotal_con_descuento * 13 / 113
                total = subtotal_con_descuento
            else:
                total = subtotal_con_descuento
        else:
            total = subtotal_con_descuento

        self.subtotal_label.setText(f"Subtotal: ${subtotal:.2f}")
        self.iva_label.setText(f"IVA: ${iva:.2f}")
        self.total_label.setText(f"TOTAL: ${total:.2f}")


    def get_data(self):
        vendedor_idx = self.vendedor_combo.currentIndex()
        vendedor_id = None
        if vendedor_idx > 0:
            vendedor_id = self.vendedores_trabajadores[vendedor_idx - 1]["id"]

        sumas = 0
        ventas_exentas = 0
        ventas_no_sujetas = 0
        total = 0
        iva = 0

        for item in self.venta_items:
            tipo_fiscal = item.get("tipo_fiscal", "").lower()
            if tipo_fiscal == "venta gravada":
                sumas += item["subtotal_con_descuento"]
                iva += item.get("iva", 0)  # <-- Suma el IVA real de cada producto gravado
            elif tipo_fiscal == "venta exenta":
                ventas_exentas += item["subtotal_con_descuento"]
            elif tipo_fiscal == "venta no sujeta":
                ventas_no_sujetas += item["subtotal_con_descuento"]
            total += item.get("total", 0) 

        return {
        "cliente": self.selected_cliente if self.selected_cliente else {},
            "items": self.venta_items,
            "tipo_venta": (
                "Minorista" if self.tipo_minorista.isChecked()
                else "Mayorista (unitario)" if self.tipo_mayorista_unit.isChecked()
                else "Mayorista (total personalizado)"
            ),
            "precio_total_manual": float(self.precio_total_spin.value()),
            "iva_agregado": self.iva_agregado_radio.isChecked(),
            "venta_a_cuenta_de": self.venta_a_cuenta_de_edit.text(),
            "sumas": sumas,
            "iva": iva,
            "ventas_exentas": ventas_exentas,
            "ventas_no_sujetas": ventas_no_sujetas,
            "subtotal": sumas + ventas_exentas + ventas_no_sujetas,
            "total": sumas + ventas_exentas + ventas_no_sujetas + iva,
            "fecha": QDate.currentDate().toString("yyyy-MM-dd"),
            "Distribuidor_id": (
                self.Distribuidor_combo.currentIndex()
                if self.Distribuidor_combo.currentIndex() >= 0 else None
            ),
            "vendedor_id": vendedor_id
        }
    
    def _agregar_a_venta(self):
        idx = self.product_list.currentRow()
        if idx < 0:
            QMessageBox.warning(self, "Validación", "Seleccione un producto del inventario actual.")
            return
        lote = self.productos[idx]
        cantidad = self.cantidad_spin.value()

        # --- Cálculo de precio unitario según tipo de venta ---
        if self.tipo_mayorista_total.isChecked():
            precio_total = self.precio_total_spin.value()
            precio = round(precio_total / cantidad, 6) if cantidad > 0 else 0
        else:
            precio = self.precio_spin.value()
            precio_total = precio * cantidad

        descuento_valor = self.descuento_spin.value()
        descuento_tipo = self.descuento_tipo_combo.currentText()
        subtotal = precio_total

        if descuento_tipo == "%":
            descuento_monto = subtotal * (descuento_valor / 100)
        else:
            descuento_monto = descuento_valor

        subtotal_con_descuento = max(subtotal - descuento_monto, 0)

        iva = 0
        iva_tipo = "ninguno"
        precio_sin_iva = precio  # Por defecto, el precio es el ingresado
        if hasattr(self, "iva_checkbox") and self.iva_checkbox.isChecked():
            if self.iva_agregado_radio.isChecked():
                iva = round(subtotal_con_descuento * 0.13, 2)
                iva_tipo = "agregado"
                total = subtotal_con_descuento + iva
            elif self.iva_desglosado_radio.isChecked():
                iva = round(subtotal_con_descuento * 13 / 113, 2)
                iva_tipo = "desglosado"
                precio_sin_iva_total = subtotal_con_descuento - iva
                precio = round(precio_sin_iva_total / cantidad, 6) if cantidad > 0 else 0
                subtotal = precio_sin_iva_total
                total = subtotal_con_descuento
            else:
                total = subtotal_con_descuento
                iva_tipo = "ninguno"
        else:
            total = subtotal_con_descuento
            iva_tipo = "ninguno"

        comision_monto = 0
        tipo_fiscal = self.tipo_fiscal_combo.currentText()

        self.venta_items.append({
            "lote_id": lote["lote_id"],
            "producto_id": lote["producto_id"],
            "producto": lote["nombre"],
            "cantidad": cantidad,
            "precio": precio,  # Siempre el precio unitario sin IVA si es desglosado
            "descuento": descuento_valor,
            "descuento_tipo": descuento_tipo,
            "descuento_monto": descuento_monto,
            "subtotal": subtotal,
            "subtotal_con_descuento": subtotal_con_descuento,
            "iva": iva,
            "iva_tipo": iva_tipo,
            "comision_monto": comision_monto,
            "total": total,
            "tipo_fiscal": tipo_fiscal,
            "Distribuidor_id": lote["Distribuidor_id"],
            "fecha_vencimiento": lote.get("fecha_vencimiento", "")
        })
        self._actualizar_tabla()
        self._recalcular_totales()

    def _actualizar_tabla(self):
        self.table.setRowCount(len(self.venta_items))
        for i, item in enumerate(self.venta_items):
            self.table.setItem(i, 0, QTableWidgetItem(item["producto"]))
            self.table.setItem(i, 1, QTableWidgetItem(str(item["cantidad"])))
            self.table.setItem(i, 2, QTableWidgetItem(f"${item['precio']:.2f}"))
            self.table.setItem(i, 3, QTableWidgetItem(f"{item['descuento']}{item['descuento_tipo']}"))
            self.table.setItem(i, 4, QTableWidgetItem(item.get("tipo_fiscal", "")))
            btn = QPushButton("Eliminar")
            btn.setStyleSheet(
                "background-color: #b71c1c; color: #fff; border-radius: 6px; font-size:9px;"
                "min-width:70px; max-width:100px; min-height:10px; max-height:15px;"
            )

            btn.clicked.connect(lambda _, row=i: self._eliminar_item(row))
            self.table.setCellWidget(i, 5, btn)

    def _eliminar_fila(self, row, col):
        if col == 5:
            self._eliminar_item(row)

    def _eliminar_item(self, row):
        if 0 <= row < len(self.venta_items):
            del self.venta_items[row]
            self._actualizar_tabla()
            self._recalcular_totales()

    def _validar_y_accept(self):
        if not self.product_list.currentItem():
            QMessageBox.warning(self, "Validación", "Seleccione un producto.")
            return
        if self.cantidad_spin.value() <= 0:
            QMessageBox.warning(self, "Validación", "La cantidad debe ser mayor que cero.")
            return
        if self.precio_spin.value() <= 0:
            QMessageBox.warning(self, "Validación", "El precio debe ser mayor que cero.")
            return
        self.accept()

class ProductDialog(QDialog):
    def __init__(self, vendedores, Distribuidores, parent=None, producto=None):
        super().__init__(parent)
        self.setWindowTitle("Producto")
        layout = QVBoxLayout()
        self.codigo_edit = QLineEdit()
        self.codigo_edit = QLineEdit()
        self.nombre_edit = QLineEdit()
        self.codigo_edit = QLineEdit()
        self.precio_compra_spin = QDoubleSpinBox()
        self.precio_compra_spin.setMaximum(1000000)
        self.precio_compra_spin.setDecimals(2)
        self.precio_venta_minorista_spin = QDoubleSpinBox()
        self.precio_venta_minorista_spin.setMaximum(1000000)
        self.precio_venta_minorista_spin.setDecimals(2)
        self.precio_venta_mayorista_spin = QDoubleSpinBox()
        self.precio_venta_mayorista_spin.setMaximum(1000000)
        self.precio_venta_mayorista_spin.setDecimals(2)

        layout.addWidget(QLabel("Código:"))
        layout.addWidget(self.codigo_edit)
        layout.addWidget(QLabel("Código:"))
        layout.addWidget(self.codigo_edit)
        layout.addWidget(QLabel("Nombre:"))
        layout.addWidget(self.nombre_edit)
        layout.addWidget(QLabel("Código:"))
        layout.addWidget(self.codigo_edit)
        layout.addWidget(QLabel("Precio de compra:"))
        layout.addWidget(self.precio_compra_spin)
        layout.addWidget(QLabel("Precio venta minorista:"))
        layout.addWidget(self.precio_venta_minorista_spin)
        layout.addWidget(QLabel("Precio venta mayorista:"))
        layout.addWidget(self.precio_venta_mayorista_spin)

        btns = QHBoxLayout()
        self.btn_ok = QPushButton("Guardar")
        self.btn_cancel = QPushButton("Cancelar")
        btns.addWidget(self.btn_ok)
        btns.addWidget(self.btn_cancel)
        layout.addLayout(btns)
        self.setLayout(layout)

        self.btn_ok.clicked.connect(self.accept)
        self.btn_cancel.clicked.connect(self.reject)

        if producto:
            self.nombre_edit.setText(producto.get("nombre", ""))
            self.codigo_edit.setText(producto.get("codigo", ""))
            self.precio_compra_spin.setValue(producto.get("precio_compra", 0))
            self.precio_venta_minorista_spin.setValue(producto.get("precio_venta_minorista", 0))
            self.precio_venta_mayorista_spin.setValue(producto.get("precio_venta_mayorista", 0))

    def get_data(self):
        return {
            "nombre": self.nombre_edit.text(),
            "codigo": self.codigo_edit.text(),
            "precio_compra": self.precio_compra_spin.value(),
            "precio_venta_minorista": self.precio_venta_minorista_spin.value(),
            "precio_venta_mayorista": self.precio_venta_mayorista_spin.value()
        }

class RegisterPurchaseDialog(QDialog):
    
    def __init__(self, productos, Distribuidores, Vendedores, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Registrar Compra")
        self.productos = productos
        self.Distribuidores = Distribuidores
        self.Vendedores = Vendedores
        self.compra_items = []

        layout = QVBoxLayout()

        # Mapeo producto -> vendedor y vendedor -> Distribuidor
        self._producto_vendedor_map = {}
        self._vendedor_Distribuidor_map = {}
        for v in self.Vendedores:
            self._vendedor_Distribuidor_map[v["id"]] = v.get("Distribuidor_id")
        for p in self.productos:
            self._producto_vendedor_map[p["nombre"]] = p.get("vendedor_id")

        # Vendedor
        vendedor_layout = QHBoxLayout()
        vendedor_layout.addWidget(QLabel("Vendedor:"))
        self.vendedor_combo = QComboBox()
        self.vendedor_combo.addItems([v["nombre"] for v in self.Vendedores])
        vendedor_layout.addWidget(self.vendedor_combo)
        layout.addLayout(vendedor_layout)

        # Distribuidor (no editable)
        Distribuidor_layout = QHBoxLayout()
        Distribuidor_layout.addWidget(QLabel("Distribuidor:"))
        self.Distribuidor_combo = QComboBox()
        self.Distribuidor_combo.setEnabled(False)
        Distribuidor_layout.addWidget(self.Distribuidor_combo)
        layout.addLayout(Distribuidor_layout)

        # Producto
        producto_layout = QHBoxLayout()
        producto_layout.addWidget(QLabel("Producto:"))
        self.product_list = QListWidget()
        self.product_list.addItems([p["nombre"] for p in productos])
        producto_layout.addWidget(self.product_list)
        layout.addLayout(producto_layout)

        # ...dentro de __init__ de RegisterPurchaseDialog, antes de self.btn_agregar...
        self.subtotal_label = QLabel("Subtotal: $0.00")
        self.iva_label = QLabel("IVA: $0.00")
        self.comision_label_resumen = QLabel("Comisión: $0.00")
        self.total_label = QLabel("TOTAL: $0.00")
        layout.addWidget(self.subtotal_label)
        layout.addWidget(self.iva_label)
        layout.addWidget(self.comision_label_resumen)
        layout.addWidget(self.total_label)

        # Cantidad, precio unitario y precio total
        cantidad_layout = QHBoxLayout()
        cantidad_layout.addWidget(QLabel("Cantidad:"))
        self.cantidad_spin = QSpinBox()
        self.cantidad_spin.setMinimum(1)
        self.cantidad_spin.setMaximum(100000)
        cantidad_layout.addWidget(self.cantidad_spin)
        cantidad_layout.addWidget(QLabel("Precio unitario:"))
        self.precio_unitario_spin = QDoubleSpinBox()
        self.precio_unitario_spin.setMinimum(0)
        self.precio_unitario_spin.setMaximum(1000000)
        self.precio_unitario_spin.setDecimals(2)
        cantidad_layout.addWidget(self.precio_unitario_spin)
        cantidad_layout.addWidget(QLabel("Precio total:"))
        self.precio_total_spin = QDoubleSpinBox()
        self.precio_total_spin.setMinimum(0)
        self.precio_total_spin.setMaximum(100000000)
        self.precio_total_spin.setDecimals(2)
        cantidad_layout.addWidget(self.precio_total_spin)
        cantidad_layout.addWidget(QLabel("Fecha vencimiento:"))
        self.fecha_vencimiento_edit = QDateEdit(QDate.currentDate())
        self.fecha_vencimiento_edit.setCalendarPopup(True)
        cantidad_layout.addWidget(self.fecha_vencimiento_edit)
        layout.addLayout(cantidad_layout)
        descuento_layout = QHBoxLayout()
        descuento_layout.addWidget(QLabel("Descuento:"))
        self.descuento_spin = QDoubleSpinBox()
        self.descuento_spin.setMinimum(0)
        self.descuento_spin.setMaximum(1000000)
        self.descuento_spin.setDecimals(2)
        self.descuento_spin.setValue(0)
        descuento_layout.addWidget(self.descuento_spin)

        self.descuento_tipo_combo = QComboBox()
        self.descuento_tipo_combo.addItems(["%", "$"])
        descuento_layout.addWidget(self.descuento_tipo_combo)

        layout.addLayout(descuento_layout)

        # IVA con checkbox y radios
        iva_layout = QHBoxLayout()
        self.iva_checkbox = QCheckBox("Aplicar IVA")
        self.iva_checkbox.setChecked(False)
        iva_layout.addWidget(self.iva_checkbox)
        self.iva_desglosado_radio = QRadioButton("IVA desglosado (restar del precio)")
        self.iva_desglosado_radio.setChecked(False)
        self.iva_desglosado_radio.setEnabled(False)
        iva_layout.addWidget(self.iva_desglosado_radio)
        self.iva_añadido_radio = QRadioButton("IVA añadido (sumar al precio)")
        self.iva_añadido_radio.setChecked(False)
        self.iva_añadido_radio.setEnabled(False)
        iva_layout.addWidget(self.iva_añadido_radio)
        layout.addLayout(iva_layout)

        # Agrupa IVA en su propio grupo
        self.iva_group = QButtonGroup(self)
        self.iva_group.setExclusive(True)
        self.iva_group.addButton(self.iva_desglosado_radio)
        self.iva_group.addButton(self.iva_añadido_radio)

        # Resumen
        self.subtotal_label = QLabel("Subtotal: $0.00")
        self.iva_label = QLabel("IVA: $0.00")
        self.total_label = QLabel("TOTAL: $0.00")
        layout.addWidget(self.subtotal_label)
        layout.addWidget(self.iva_label)
        layout.addWidget(self.total_label)

        # Conexiones para IVA
        self.iva_checkbox.stateChanged.connect(self._toggle_iva_radios)
        self.iva_desglosado_radio.toggled.connect(self._actualizar_total_general)

        # Comisión (ahora del vendedor)
        comision_layout = QHBoxLayout()
        comision_layout.addWidget(QLabel("Comisión (%):"))
        self.comision_pct_spin = QDoubleSpinBox()
        self.comision_pct_spin.setRange(0, 100)
        self.comision_pct_spin.setDecimals(2)
        self.comision_pct_spin.setValue(0)
        comision_layout.addWidget(self.comision_pct_spin)

        comision_layout.addWidget(QLabel("Tipo:"))
        self.comision_tipo_combo = QComboBox()
        self.comision_tipo_combo.addItems(["Añadida al total", "Desglosada (incluida en el precio)"])
        comision_layout.addWidget(self.comision_tipo_combo)

        layout.addLayout(comision_layout)

        # Botón agregar a compra
        self.btn_agregar = QPushButton("Agregar a compra")
        layout.addWidget(self.btn_agregar)

        # En el __init__ de RegisterPurchaseDialog, donde creas la tabla:
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels([
            "Producto", "Cantidad", "Precio U.", "Subtotal", "IVA", "Comisión", "Total", "Vencimiento", "Eliminar"
        ])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        layout.addWidget(self.table)

        # Total general de la compra
        total_general_layout = QHBoxLayout()
        self.total_general_label = QLabel("Total compra: $0.00")
        total_general_layout.addWidget(self.total_general_label)
        layout.addLayout(total_general_layout)

        # Botón registrar compra
        self.btn_registrar = QPushButton("Registrar Compra")
        self.btn_cancelar = QPushButton("Cancelar")
        botones_layout = QHBoxLayout()
        botones_layout.addStretch(1)
        botones_layout.addWidget(self.btn_registrar)
        botones_layout.addWidget(self.btn_cancelar)
        layout.addLayout(botones_layout)

        self.setLayout(layout)

        # --- CONEXIONES ---
        self.btn_cancelar.clicked.connect(self.reject)
        self.btn_registrar.clicked.connect(self._registrar_compra)
        self.btn_agregar.clicked.connect(self._agregar_a_compra)
        self.table.cellClicked.connect(self._eliminar_fila)
        self.product_list.currentRowChanged.connect(self._actualizar_vendedor_y_Distribuidor)
        self.vendedor_combo.currentIndexChanged.connect(self._actualizar_Distribuidor)
        self.comision_pct_spin.valueChanged.connect(self._actualizar_total_general)
        self.product_list.currentRowChanged.connect(self._actualizar_precio_unitario_por_producto)
        self._actualizar_precio_unitario_por_producto()

        # Inicializa combos
        if productos:
            self.product_list.setCurrentRow(0)
            self._actualizar_vendedor_y_Distribuidor()
        self._actualizar_total_general()
        
        # Conexiones para cálculo en tiempo real
        self.cantidad_spin.valueChanged.connect(self._calcular_preview_item)
        self.precio_unitario_spin.valueChanged.connect(self._calcular_preview_item)
        self.precio_total_spin.valueChanged.connect(self._calcular_preview_item)
        self.comision_pct_spin.valueChanged.connect(self._calcular_preview_item)
        self.iva_checkbox.stateChanged.connect(self._toggle_iva_radios)
        self.iva_desglosado_radio.toggled.connect(self._calcular_preview_item)
        self.iva_añadido_radio.toggled.connect(self._calcular_preview_item)
        self.product_list.currentRowChanged.connect(self._calcular_preview_item)
        self._calcular_preview_item()

        self._calcular_preview_item()

    # --- NUEVO MÉTODO ---
    def _actualizar_precio_unitario_por_producto(self):
        idx = self.product_list.currentRow()
        if idx < 0 or idx >= len(self.productos):
            self.precio_unitario_spin.setValue(0)
            return
        prod = self.productos[idx]
        precio = prod.get("precio_compra", 0)
        self.precio_unitario_spin.blockSignals(True)
        self.precio_unitario_spin.setValue(float(precio))
        self.precio_unitario_spin.blockSignals(False)
        self._calcular_preview_item()

    def _calcular_preview_item(self):
        cantidad = self.cantidad_spin.value()

        precio_unit = self.precio_unitario_spin.value()
        precio_total = self.precio_total_spin.value()

        # Si el total es editable y el usuario lo modificó, ajusta el precio unitario
        if self.precio_total_spin.isEnabled() and self.precio_total_spin.hasFocus():
            precio_unit = round(precio_total / cantidad, 6) if cantidad > 0 else 0
            self.precio_unitario_spin.blockSignals(True)
            self.precio_unitario_spin.setValue(precio_unit)
            self.precio_unitario_spin.blockSignals(False)
        else:
            precio_total = cantidad * precio_unit
            self.precio_total_spin.blockSignals(True)
            self.precio_total_spin.setValue(precio_total)
            self.precio_total_spin.blockSignals(False)

        subtotal = cantidad * precio_unit

        # Descuento
        descuento_valor = self.descuento_spin.value()
        descuento_tipo = self.descuento_tipo_combo.currentText()
        if descuento_tipo == "%":
            descuento_monto = subtotal * (descuento_valor / 100)
        else:
            descuento_monto = descuento_valor
        subtotal_con_descuento = max(subtotal - descuento_monto, 0)

        # Comisión (se calcula antes del IVA para determinar la base)
        comision_pct = self.comision_pct_spin.value()
        comision_tipo = self.comision_tipo_combo.currentText()
        if comision_tipo == "Añadida al total":
            comision_monto = subtotal_con_descuento * (comision_pct / 100)
        elif comision_tipo == "Desglosada (incluida en el precio)":
            # La comisión ya está incluida en el precio, se calcula cuánto representa
            comision_monto = subtotal_con_descuento * (comision_pct / (100 + comision_pct)) if comision_pct > 0 else 0
        else:
            comision_monto = 0

        # Base para calcular IVA
        base_iva = subtotal_con_descuento
        if comision_tipo == "Desglosada (incluida en el precio)":
            base_iva = subtotal_con_descuento - comision_monto

        # IVA
        iva = 0
        total = subtotal_con_descuento
        if self.iva_checkbox.isChecked():
            if self.iva_desglosado_radio.isChecked():
                iva = base_iva * 13 / 113
                total = subtotal_con_descuento
            elif self.iva_añadido_radio.isChecked():
                iva = base_iva * 0.13
                total = subtotal_con_descuento + iva

        # Total final considerando comisión
        if comision_tipo == "Añadida al total":
            total_final = total + comision_monto
        else:
            total_final = total  # Comisión ya incluida o inexistente

        self.subtotal_label.setText(f"Subtotal: ${subtotal:.2f}")
        self.iva_label.setText(f"IVA: ${iva:.2f}")
        self.comision_label_resumen.setText(f"Comisión: ${comision_monto:.2f}")
        self.total_label.setText(f"TOTAL: ${total_final:.2f}")
        
    def _toggle_iva_radios(self, state):
        checked = self.iva_checkbox.isChecked()
        self.iva_desglosado_radio.setEnabled(checked)
        self.iva_añadido_radio.setEnabled(checked)
        if checked and not (self.iva_desglosado_radio.isChecked() or self.iva_añadido_radio.isChecked()):
            self.iva_desglosado_radio.setChecked(True)
        if not checked:
            self.iva_group.setExclusive(False)
            self.iva_desglosado_radio.setChecked(False)
            self.iva_añadido_radio.setChecked(False)
            self.iva_group.setExclusive(True)
        self._calcular_preview_item()

    def _actualizar_total_general(self):
        total_general = 0
        subtotal_general = 0
        iva_general = 0
        for item in self.compra_items:
            subtotal = item["cantidad"] * item["precio"]
            subtotal_general += subtotal
            if hasattr(self, "iva_checkbox") and self.iva_checkbox.isChecked() and self.iva_desglosado_radio.isChecked():
                iva = subtotal - (subtotal / 1.13)
            else:
                iva = 0
            iva_general += iva
            total_general += subtotal
        self.subtotal_label.setText(f"Subtotal: ${subtotal_general:.2f}")
        self.iva_label.setText(f"IVA: ${iva_general:.2f}")
        self.total_label.setText(f"TOTAL: ${total_general:.2f}")
        self.total_general_label.setText(f"Total compra: ${total_general:.2f}")

    def _actualizar_vendedor_y_Distribuidor(self):
        idx = self.product_list.currentRow()
        if idx < 0:
            return
        producto = self.productos[idx]
        vendedor_id = producto.get("vendedor_id")
        # Selecciona el vendedor correspondiente
        for i, v in enumerate(self.Vendedores):
            if v["id"] == vendedor_id:
                self.vendedor_combo.setCurrentIndex(i)
                break
        self._actualizar_Distribuidor()

    def _actualizar_Distribuidor(self):
        idx = self.vendedor_combo.currentIndex()
        if idx < 0:
            self.Distribuidor_combo.clear()
            return
        vendedor = self.Vendedores[idx]
        Distribuidor_id = vendedor.get("Distribuidor_id")
        self.Distribuidor_combo.clear()
        for d in self.Distribuidores:
            if d["id"] == Distribuidor_id:
                self.Distribuidor_combo.addItem(d["nombre"])
                break
        # Actualiza comisión base del vendedor
        comision = vendedor.get("comision_base", 0)
        try:
            comision_val = float(comision) if comision is not None else 0.0
        except Exception:
            comision_val = 0.0
        self.comision_label_resumen.setText(f"Comisión vendedor: {comision_val}%")
        self.comision_pct_spin.setValue(comision_val)

    def _agregar_a_compra(self):
        producto = self.product_list.currentItem().text() if self.product_list.currentItem() else ""
        cantidad = self.cantidad_spin.value()
        precio = self.precio_unitario_spin.value()
        if not producto or cantidad <= 0 or precio <= 0:
            QMessageBox.warning(self, "Validación", "Seleccione producto, cantidad y precio válidos.")
            return

        # --- CÁLCULO DE SUBTOTAL Y DESCUENTO ---
        subtotal = cantidad * precio
        descuento_pct = self.descuento_spin.value()
        descuento_monto = subtotal * (descuento_pct / 100)
        subtotal_con_descuento = subtotal - descuento_monto

        # --- CÁLCULO DE COMISIÓN SEGÚN TIPO (antes del IVA) ---
        comision_pct = self.comision_pct_spin.value()
        comision_tipo = self.comision_tipo_combo.currentText()
        if comision_tipo == "Añadida al total":
            comision_monto = subtotal_con_descuento * (comision_pct / 100)
        elif comision_tipo == "Desglosada (incluida en el precio)":
            comision_monto = subtotal_con_descuento * (comision_pct / (100 + comision_pct)) if comision_pct > 0 else 0
        else:
            comision_monto = 0

        base_iva = subtotal_con_descuento
        if comision_tipo == "Desglosada (incluida en el precio)":
            base_iva = subtotal_con_descuento - comision_monto

        # --- CÁLCULO DE IVA ---
        iva = 0
        iva_tipo = "ninguno"
        if self.iva_checkbox.isChecked():
            if self.iva_desglosado_radio.isChecked():
                iva = base_iva * 13 / 113
                iva_tipo = "desglosado"
                total = subtotal_con_descuento
            elif self.iva_añadido_radio.isChecked():
                iva = base_iva * 0.13
                iva_tipo = "añadido"
                total = subtotal_con_descuento + iva
            else:
                total = subtotal_con_descuento
                iva = 0
                iva_tipo = "ninguno"
        else:
            total = subtotal_con_descuento
            iva = 0
            iva_tipo = "ninguno"

        # --- TOTAL FINAL CON COMISIÓN ---
        if comision_tipo == "Añadida al total":
            total_con_comision = total + comision_monto
        else:
            total_con_comision = total  # El total ya incluye la comisión o no hay

        fecha_vencimiento = self.fecha_vencimiento_edit.date().toString("yyyy-MM-dd")

        self.compra_items.append({
            "producto": producto,
            "cantidad": cantidad,
            "precio": precio,
            "subtotal": subtotal,
            "descuento_pct": descuento_pct,
            "descuento_monto": descuento_monto,
            "descuento": descuento_monto,  # para compatibilidad con lo que ya tienes
            "descuento_tipo": "%",  # <--- agrega este campo (ajusta si tienes lógica de descuento)
            "iva": iva,
            "iva_tipo": iva_tipo,
            "comision_pct": comision_pct,
            "comision_monto": comision_monto,
            "comision_tipo": "",
            "total": total_con_comision,
            "fecha_vencimiento": fecha_vencimiento
        })
        self._actualizar_tabla()
        self._actualizar_total_general()

    def _actualizar_tabla(self):
        self.table.setRowCount(len(self.compra_items))
        for i, item in enumerate(self.compra_items):
            self.table.setItem(i, 0, QTableWidgetItem(item["producto"]))
            self.table.setItem(i, 1, QTableWidgetItem(str(item["cantidad"])))
            self.table.setItem(i, 2, QTableWidgetItem(f"${item['precio']:.2f}"))
            self.table.setItem(i, 3, QTableWidgetItem(f"${item['subtotal']:.2f}"))
            self.table.setItem(i, 4, QTableWidgetItem(f"${item['iva']:.2f}"))
            # Comisión (monto y porcentaje)
            comision_text = f"${item.get('comision_monto', 0):.2f} ({item.get('comision_pct', 0)}%)"
            self.table.setItem(i, 5, QTableWidgetItem(comision_text))
            self.table.setItem(i, 6, QTableWidgetItem(f"${item['total']:.2f}"))
            self.table.setItem(i, 7, QTableWidgetItem(item.get("fecha_vencimiento", "")))
            btn = QPushButton("Eliminar")
            btn.setStyleSheet(
                "background-color: #b71c1c; color: #fff; border-radius: 6px; font-size:9px;"
                "min-width:70px; max-width:100px; min-height:10px; max-height:15px;"
            )
            btn.clicked.connect(lambda _, row=i: self._eliminar_item(row))
            self.table.setCellWidget(i, 8, btn)

    def _eliminar_fila(self, row, col):
        if col == 8:
            self._eliminar_item(row)

    def _eliminar_item(self, row):
        if 0 <= row < len(self.compra_items):
            del self.compra_items[row]
            self._actualizar_tabla()
            self._actualizar_total_general()

    def _actualizar_total_general(self):
        total_general = sum(item["total"] for item in self.compra_items)
        self.total_general_label.setText(f"Total compra: ${total_general:.2f}")

    def _registrar_compra(self):
        if not self.compra_items:
            QMessageBox.warning(self, "Validación", "Debe agregar al menos un producto a la compra.")
            return

        # Obtén los datos DIRECTAMENTE de los combos y la lista de items
        fecha = QDate.currentDate().toString("yyyy-MM-dd")
        total_general = sum(item["total"] for item in self.compra_items)
        vendedor_idx = self.vendedor_combo.currentIndex()
        vendedor_id = self.Vendedores[vendedor_idx]["id"] if vendedor_idx >= 0 else None
        Distribuidor_id = None
        if self.Distribuidor_combo.count() > 0:
            dist_name = self.Distribuidor_combo.currentText()
            for d in self.Distribuidores:
                if d["nombre"] == dist_name:
                    Distribuidor_id = d["id"]
                    break

        if vendedor_id is None or Distribuidor_id is None:
            respuesta = QMessageBox.question(
                self,
                "Confirmaci\u00f3n",
                "esta a punto de agregar una compra sin vendedor, esto puede causar errores en el sistema, esta seguro de continuar?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if respuesta != QMessageBox.Yes:
                return

        comision_total = sum(item.get("comision_monto", 0) for item in self.compra_items)
        compra_id = self.parent().manager.db.add_compra_detallada({
            "fecha": fecha,
            "producto_id": None,
            "cantidad": 0,
            "precio_unitario": 0,
            "total": total_general,
            "Distribuidor_id": Distribuidor_id,
            "comision_pct": 0,
            "comision_monto": comision_total,  # <-- Aquí la suma real
            "vendedor_id": vendedor_id
        })

        # Guarda cada detalle de compra con todos los campos
        productos_dict = {p["nombre"]: p["id"] for p in self.productos}
        for item in self.compra_items:
            producto_id = productos_dict.get(item["producto"])
            self.parent().manager.db.add_detalle_compra(
                compra_id,
                producto_id,
                item["cantidad"],
                item["precio"],
                item.get("fecha_vencimiento", ""),
                item.get("descuento_monto", 0),      # <--- monto de descuento
                item.get("descuento_tipo", "%"),      # <--- tipo de descuento
                item.get("iva", 0),
                item.get("iva_tipo", ""),
                item.get("comision_pct", 0),
                item.get("comision_monto", 0),
                item.get("comision_tipo", "")
            )
            # Aumenta el stock del producto
            self.parent().manager.aumentar_stock(producto_id, item["cantidad"])

        self.accept()

    def get_data(self):
        total_general = sum(item["total"] for item in self.compra_items)
        vendedor_idx = self.vendedor_combo.currentIndex()
        vendedor_id = self.Vendedores[vendedor_idx]["id"] if vendedor_idx >= 0 else None
        Distribuidor_id = None
        if self.Distribuidor_combo.count() > 0:
            dist_name = self.Distribuidor_combo.currentText()
            for d in self.Distribuidores:
                if d["nombre"] == dist_name:
                    Distribuidor_id = d["id"]
                    break
        return {
            "fecha": QDate.currentDate().toString("yyyy-MM-dd"),
            "vendedor_id": vendedor_id,
            "Distribuidor_id": Distribuidor_id,
            "items": self.compra_items,
            "total": total_general,
            "comision_pct": self.comision_pct_spin.value(),
            "comision_tipo": self.comision_tipo_combo.currentText()
        }
    
class RegisterCreditoFiscalDialog(QDialog, ProductDialogBase):
    def __init__(self, productos, clientes, Distribuidores, vendedores_trabajadores, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Registrar Venta a Crédito Fiscal")
        main_layout = QHBoxLayout()

        # --- LADO IZQUIERDO ---
        left_layout = QVBoxLayout()
        self.productos = productos
        self.venta_items = []
        self.clientes = clientes
        self.Distribuidores = Distribuidores

        # Distribuidor
        left_layout.addWidget(QLabel("Distribuidor:"))
        self.Distribuidor_combo = QComboBox()
        if isinstance(Distribuidores[0], dict):
            self.Distribuidor_combo.addItems([d["nombre"] for d in Distribuidores])
        else:
            self.Distribuidor_combo.addItems(Distribuidores)
        left_layout.addWidget(self.Distribuidor_combo)

        # Barra de búsqueda de productos
        self.product_search = QLineEdit()
        self.product_search.setPlaceholderText("Buscar producto por nombre o código...")
        left_layout.addWidget(self.product_search)

        # Lista de productos
        self.product_list = QListWidget()
        self._productos_original = list(productos)
        self._mostrar_productos(productos)
        left_layout.addWidget(self.product_list)

        # Tipo de venta
        left_layout.addWidget(QLabel("Tipo de venta:"))
        self.tipo_minorista = QRadioButton("Minorista")
        self.tipo_mayorista_unit = QRadioButton("Mayorista (unitario)")
        self.tipo_mayorista_total = QRadioButton("Mayorista (total personalizado)")
        self.tipo_minorista.setChecked(True)
        tipo_layout = QHBoxLayout()
        tipo_layout.addWidget(self.tipo_minorista)
        tipo_layout.addWidget(self.tipo_mayorista_unit)
        tipo_layout.addWidget(self.tipo_mayorista_total)
        left_layout.addLayout(tipo_layout)
        self.tipo_venta_group = QButtonGroup(self)
        self.tipo_venta_group.setExclusive(True)
        self.tipo_venta_group.addButton(self.tipo_minorista)
        self.tipo_venta_group.addButton(self.tipo_mayorista_unit)
        self.tipo_venta_group.addButton(self.tipo_mayorista_total)

        # Cantidad
        left_layout.addWidget(QLabel("Cantidad:"))
        self.cantidad_spin = QSpinBox()
        self.cantidad_spin.setMinimum(1)
        self.cantidad_spin.setMaximum(100000)
        left_layout.addWidget(self.cantidad_spin)


        # Precio unitario y total
        precio_layout = QHBoxLayout()
        self.precio_spin = QDoubleSpinBox()
        self.precio_spin.setMinimum(0)
        self.precio_spin.setMaximum(1000000)
        self.precio_spin.setDecimals(2)
        self.precio_spin.setPrefix("$")
        precio_layout.addWidget(QLabel("Precio unitario:"))
        precio_layout.addWidget(self.precio_spin)
        self.precio_total_spin = QDoubleSpinBox()
        self.precio_total_spin.setMinimum(0)
        self.precio_total_spin.setMaximum(100000000)
        self.precio_total_spin.setDecimals(2)
        self.precio_total_spin.setPrefix("$")
        precio_layout.addWidget(QLabel("Precio total:"))
        precio_layout.addWidget(self.precio_total_spin)
        left_layout.addLayout(precio_layout)

        # Descuento
        descuento_layout = QHBoxLayout()
        descuento_layout.addWidget(QLabel("Descuento:"))
        self.descuento_spin = QDoubleSpinBox()
        self.descuento_spin.setMinimum(0)
        self.descuento_spin.setMaximum(1000000)
        self.descuento_spin.setDecimals(2)
        self.descuento_spin.setValue(0)
        descuento_layout.addWidget(self.descuento_spin)
        self.descuento_tipo_combo = QComboBox()
        self.descuento_tipo_combo.addItems(["%", "$"])
        descuento_layout.addWidget(self.descuento_tipo_combo)
        left_layout.addLayout(descuento_layout)
        self.descuento_spin.valueChanged.connect(self._recalcular_totales)
        self.descuento_tipo_combo.currentIndexChanged.connect(self._recalcular_totales)

        # IVA con checkbox y radios
        iva_layout = QHBoxLayout()
        self.iva_checkbox = QCheckBox("Aplicar IVA")
        self.iva_checkbox.setChecked(False)
        iva_layout.addWidget(self.iva_checkbox)
        self.iva_agregado_radio = QRadioButton("IVA agregado (sumar 13%)")
        self.iva_desglosado_radio = QRadioButton("IVA desglosado (precio incluye IVA)")
        self.iva_agregado_radio.setChecked(False)
        self.iva_desglosado_radio.setChecked(False)
        self.iva_agregado_radio.setEnabled(False)
        self.iva_desglosado_radio.setEnabled(False)
        iva_layout.addWidget(self.iva_agregado_radio)
        iva_layout.addWidget(self.iva_desglosado_radio)
        left_layout.addLayout(iva_layout)
        self.iva_group = QButtonGroup(self)
        self.iva_group.setExclusive(True)
        self.iva_group.addButton(self.iva_agregado_radio)
        self.iva_group.addButton(self.iva_desglosado_radio)
        self.iva_checkbox.stateChanged.connect(self._toggle_iva_radios)
        self.iva_agregado_radio.toggled.connect(self._recalcular_totales)
        self.iva_desglosado_radio.toggled.connect(self._recalcular_totales)

        # Selector de tipo fiscal
        tipo_fiscal_layout = QHBoxLayout()
        tipo_fiscal_layout.addWidget(QLabel("Tipo fiscal:"))
        self.tipo_fiscal_combo = QComboBox()
        self.tipo_fiscal_combo.addItems(["Venta gravada", "Venta exenta", "Venta no sujeta"])
        tipo_fiscal_layout.addWidget(self.tipo_fiscal_combo)
        left_layout.addLayout(tipo_fiscal_layout)

        self.subtotal_label = QLabel("Subtotal: $0.00")
        self.iva_label = QLabel("IVA: $0.00")
        left_layout.addWidget(self.subtotal_label)
        left_layout.addWidget(self.iva_label)



        self.total_label = QLabel("TOTAL: $0.00")
        left_layout.addWidget(self.total_label)

        # Botón agregar a venta
        self.btn_agregar = QPushButton("Agregar a venta")
        left_layout.addWidget(self.btn_agregar)
        self.btn_agregar.clicked.connect(self._agregar_a_venta)

        # Tabla de productos agregados
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels([
            "Producto", "Cantidad", "Precio U.", "Descuento", "IVA", "Tipo fiscal", "Eliminar"
        ])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        left_layout.addWidget(self.table)
        self.table.cellClicked.connect(self._eliminar_fila)

        # Botón para registrar la venta
        self.btn_ok = QPushButton("Registrar")
        self.btn_ok.clicked.connect(self._validar_y_accept)
        left_layout.addWidget(self.btn_ok)

        # --- LADO DERECHO: datos del cliente ---
        right_layout = QVBoxLayout()

        right_layout.addWidget(QLabel("Vendedor (trabajador):"))
        self.vendedor_combo = QComboBox()
        self.vendedor_combo.addItem("Sin vendedor")
        for v in vendedores_trabajadores:
            self.vendedor_combo.addItem(v["nombre"])
        self.vendedores_trabajadores = vendedores_trabajadores
        right_layout.addWidget(self.vendedor_combo)

        right_layout.addWidget(QLabel("Cliente:"))
        self.cliente_btn = QPushButton("Seleccionar Cliente")
        self.cliente_label = QLabel("(Ningún cliente seleccionado)")
        right_layout.addWidget(self.cliente_btn)
        right_layout.addWidget(self.cliente_label)
        self.selected_cliente = None

        right_layout.addWidget(QLabel("NRC:"))
        self.nrc_edit = QLineEdit()
        self.nrc_edit.setPlaceholderText("NRC del cliente")
        right_layout.addWidget(self.nrc_edit)

        right_layout.addWidget(QLabel("NIT:"))
        self.nit_edit = QLineEdit()
        self.nit_edit.setPlaceholderText("NIT del cliente")
        right_layout.addWidget(self.nit_edit)

        right_layout.addWidget(QLabel("Giro:"))
        self.giro_edit = QLineEdit()
        self.giro_edit.setPlaceholderText("Giro del cliente")
        right_layout.addWidget(self.giro_edit)

        right_layout.addWidget(QLabel("Correo electrónico:"))
        self.email_edit = QLineEdit()
        self.email_edit.setPlaceholderText("Correo electrónico")
        right_layout.addWidget(self.email_edit)
        right_layout.addStretch(1)

        right_layout.addWidget(QLabel("No. Remisión:"))
        self.no_remision_edit = QLineEdit()
        self.no_remision_edit.setPlaceholderText("Número de remisión")
        right_layout.addWidget(self.no_remision_edit)

        right_layout.addWidget(QLabel("Orden No.:"))
        self.orden_no_edit = QLineEdit()
        self.orden_no_edit.setPlaceholderText("Número de orden")
        right_layout.addWidget(self.orden_no_edit)

        right_layout.addWidget(QLabel("Condición de pago:"))
        self.condicion_pago_combo = QComboBox()
        self.condicion_pago_combo.setEditable(True)  
        self.condicion_pago_combo.addItems(["Contado", "Crédito", "Otro..."])
        right_layout.addWidget(self.condicion_pago_combo)

        right_layout.addWidget(QLabel("Venta a cuenta de:"))
        self.venta_a_cuenta_de_edit = QLineEdit()
        self.venta_a_cuenta_de_edit.setPlaceholderText("Venta a cuenta de")
        right_layout.addWidget(self.venta_a_cuenta_de_edit)

        right_layout.addWidget(QLabel("Fecha nota de remisión anterior:"))
        self.fecha_remision_anterior = QDateEdit(QDate.currentDate())
        self.fecha_remision_anterior.setCalendarPopup(True)
        right_layout.addWidget(self.fecha_remision_anterior)

        right_layout.addWidget(QLabel("Fecha de remisión:"))
        self.fecha_remision = QDateEdit(QDate.currentDate())
        self.fecha_remision.setCalendarPopup(True)
        right_layout.addWidget(self.fecha_remision)

        # --- Agrega ambos layouts al principal ---
        main_layout.addLayout(left_layout, 2)
        main_layout.addLayout(right_layout, 1)
        self.setLayout(main_layout)

        # Estado
        self.productos_data = productos

        # Conexiones adicionales
        self.cliente_btn.clicked.connect(self._abrir_selector_cliente)
        self.product_list.currentRowChanged.connect(self._actualizar_precio_defecto)
        self.tipo_minorista.toggled.connect(self._actualizar_precio_defecto)
        self.tipo_mayorista_unit.toggled.connect(self._actualizar_precio_defecto)
        self.tipo_mayorista_total.toggled.connect(self._actualizar_precio_defecto)
        self.cantidad_spin.valueChanged.connect(self._recalcular_totales)
        self.precio_spin.valueChanged.connect(self._recalcular_totales)
        self.precio_total_spin.valueChanged.connect(self._recalcular_totales)
        self.product_search.textChanged.connect(self._filtrar_productos)
        self.tipo_minorista.toggled.connect(self._toggle_precio_edicion)
        self.tipo_mayorista_unit.toggled.connect(self._toggle_precio_edicion)
        self.tipo_mayorista_total.toggled.connect(self._toggle_precio_edicion)
        self.product_list.currentRowChanged.connect(self._actualizar_Distribuidor_por_producto)

        if productos:
            self.product_list.setCurrentRow(0)
            self._actualizar_precio_defecto()

    def set_productos_data(self, productos_data):
        self.productos_data = productos_data

    def _actualizar_precio_defecto(self):
        idx = self.product_list.currentRow()
        if idx < 0:
            self.precio_spin.setValue(0)
            self.precio_total_spin.setValue(0)
            self._recalcular_totales()
            return
        nombre = self.product_list.currentItem().text()
        prod = None
        if 0 <= idx < len(self.productos):
            prod = self.productos[idx]
        elif self.productos_data:
            for p in self.productos_data:
                nombre_prod = get_field(p, "nombre", "")
                if nombre.startswith(nombre_prod):
                    prod = p
                    break
        precio = 0
        if prod:
            if self.tipo_minorista.isChecked():
                precio = get_field(prod, "precio_venta_minorista", 0)
            elif self.tipo_mayorista_unit.isChecked():
                precio = get_field(prod, "precio_venta_mayorista", 0)
            else:
                precio = get_field(prod, "precio_venta_mayorista", 0)
        self.precio_spin.blockSignals(True)
        self.precio_total_spin.blockSignals(True)
        self.precio_spin.setValue(float(precio))
        self.precio_total_spin.setValue(float(precio) * self.cantidad_spin.value())
        self.precio_spin.blockSignals(False)
        self.precio_total_spin.blockSignals(False)
        self._toggle_precio_edicion()
        self._recalcular_totales()

    def _toggle_precio_edicion(self):
        if self.tipo_minorista.isChecked():
            self.precio_spin.setEnabled(True)
            self.precio_total_spin.setEnabled(False)
        elif self.tipo_mayorista_unit.isChecked():
            self.precio_spin.setEnabled(True)
            self.precio_total_spin.setEnabled(False)
        elif self.tipo_mayorista_total.isChecked():
            self.precio_spin.setEnabled(False)
            self.precio_total_spin.setEnabled(True)
        self._recalcular_totales()

    def _recalcular_totales(self):
        cantidad = self.cantidad_spin.value()

        # --- Sincroniza precio unitario y total en modo mayorista total ---
        if self.tipo_mayorista_total.isChecked():
            precio_total = self.precio_total_spin.value()
            precio_unitario = round(precio_total / cantidad, 6) if cantidad > 0 else 0
            self.precio_spin.blockSignals(True)
            self.precio_spin.setValue(precio_unitario)
            self.precio_spin.blockSignals(False)
        else:
            precio_unitario = self.precio_spin.value()
            precio_total = precio_unitario * cantidad
            self.precio_total_spin.blockSignals(True)
            self.precio_total_spin.setValue(precio_total)
            self.precio_total_spin.blockSignals(False)

        descuento_valor = self.descuento_spin.value()
        descuento_tipo = self.descuento_tipo_combo.currentText()
        subtotal = precio_total

        # Cálculo del descuento
        if descuento_tipo == "%":
            descuento_monto = subtotal * (descuento_valor / 100)
        else:
            descuento_monto = descuento_valor

        subtotal_con_descuento = max(subtotal - descuento_monto, 0)

        # IVA (si aplica)
        iva = 0
        total = subtotal_con_descuento
        if hasattr(self, "iva_checkbox") and self.iva_checkbox.isChecked():
            if self.iva_agregado_radio.isChecked():
                iva = subtotal_con_descuento * 0.13
                total = subtotal_con_descuento + iva
            elif self.iva_desglosado_radio.isChecked():
                iva = subtotal_con_descuento * 13 / 113
                total = subtotal_con_descuento
                subtotal = subtotal_con_descuento - iva
            else:
                total = subtotal_con_descuento
        else:
            total = subtotal_con_descuento

        self.subtotal_label.setText(f"Subtotal: ${subtotal:.2f}")
        self.iva_label.setText(f"IVA: ${iva:.2f}")
        self.total_label.setText(f"TOTAL: ${total:.2f}")

    def _agregar_a_venta(self):
        idx = self.product_list.currentRow()
        if idx < 0:
            QMessageBox.warning(self, "Validación", "Seleccione un producto del inventario actual.")
            return
        lote = self.productos[idx]
        cantidad = self.cantidad_spin.value()

        # --- Cálculo de precio unitario según tipo de venta ---
        if self.tipo_mayorista_total.isChecked():
            precio_total = self.precio_total_spin.value()
            precio = round(precio_total / cantidad, 6) if cantidad > 0 else 0
        else:
            precio = self.precio_spin.value()
            precio_total = precio * cantidad

        descuento_valor = self.descuento_spin.value()
        descuento_tipo = self.descuento_tipo_combo.currentText()
        subtotal = precio_total

        if descuento_tipo == "%":
            descuento_monto = subtotal * (descuento_valor / 100)
        else:
            descuento_monto = descuento_valor

        subtotal_con_descuento = max(subtotal - descuento_monto, 0)


        iva = 0
        iva_tipo = "ninguno"
        precio_sin_iva = precio  # Por defecto, el precio es el ingresado
        precio_con_iva = precio  # Por defecto, igual

        if hasattr(self, "iva_checkbox") and self.iva_checkbox.isChecked():
            if self.iva_agregado_radio.isChecked():
                iva = round(subtotal_con_descuento * 0.13, 2)
                iva_tipo = "agregado"
                iva_unitario = iva / cantidad if cantidad > 0 else 0
                precio_con_iva = round(precio + iva_unitario, 2)
                total = subtotal_con_descuento + iva
            elif self.iva_desglosado_radio.isChecked():
                iva = round(subtotal_con_descuento * 13 / 113, 2)
                iva_tipo = "desglosado"
                precio_sin_iva_total = subtotal_con_descuento - iva
                precio = round(precio_sin_iva_total / cantidad, 6) if cantidad > 0 else 0
                iva_unitario = iva / cantidad if cantidad > 0 else 0
                precio_con_iva = round(precio + iva_unitario, 2)
                subtotal = precio_sin_iva_total
                total = subtotal_con_descuento
            else:
                total = subtotal_con_descuento
                iva_tipo = "ninguno"
        else:
            total = subtotal_con_descuento
            iva_tipo = "ninguno"
            
        comision_monto = 0
        tipo_fiscal = self.tipo_fiscal_combo.currentText()

        self.venta_items.append({
            "lote_id": lote["lote_id"],
            "producto_id": lote["producto_id"],
            "producto": lote["nombre"],
            "cantidad": cantidad,
            "precio": precio,  # sin IVA si es desglosado
            "precio_con_iva": precio_con_iva,  # <--- NUEVO
            "descuento": descuento_valor,
            "descuento_tipo": descuento_tipo,
            "descuento_monto": descuento_monto,
            "subtotal": subtotal,
            "subtotal_con_descuento": subtotal_con_descuento,
            "iva": iva,
            "iva_tipo": iva_tipo,
            "comision_monto": comision_monto,
            "total": total,
            "tipo_fiscal": tipo_fiscal,
            "Distribuidor_id": lote["Distribuidor_id"],
            "fecha_vencimiento": lote.get("fecha_vencimiento", "")
        })

        self._actualizar_tabla()
        self._recalcular_totales()


    def _actualizar_tabla(self):
        self.table.setRowCount(len(self.venta_items))
        for i, item in enumerate(self.venta_items):
            self.table.setItem(i, 0, QTableWidgetItem(item["producto"]))
            self.table.setItem(i, 1, QTableWidgetItem(str(item["cantidad"])))
            self.table.setItem(i, 2, QTableWidgetItem(f"${item['precio']:.2f}"))
            self.table.setItem(i, 3, QTableWidgetItem(f"{item['descuento']}{item['descuento_tipo']}"))
            self.table.setItem(i, 4, QTableWidgetItem(str(item.get("iva", ""))))
            self.table.setItem(i, 5, QTableWidgetItem(item.get("tipo_fiscal", "")))
            btn = QPushButton("Eliminar")
            btn.setStyleSheet(
                "background-color: #b71c1c; color: #fff; border-radius: 6px; font-size:9px;"
                "min-width:70px; max-width:100px; min-height:10px; max-height:15px;"
            )
            btn.clicked.connect(lambda _, row=i: self._eliminar_item(row))
            self.table.setCellWidget(i, 6, btn)

    def _eliminar_fila(self, row, col):
        if col == 6:
            self._eliminar_item(row)

    def _eliminar_item(self, row):
        if 0 <= row < len(self.venta_items):
            del self.venta_items[row]
            self._actualizar_tabla()
            self._recalcular_totales()

    def _validar_y_accept(self):
        if not self.selected_cliente or "id" not in self.selected_cliente:
            QMessageBox.warning(self, "Validación", "Debe seleccionar un cliente válido.")
            return
        if not self.venta_items:
            QMessageBox.warning(self, "Validación", "Debe agregar al menos un producto a la venta.")
            return
        self.accept()

    def get_data(self):
        vendedor_idx = self.vendedor_combo.currentIndex()
        vendedor_id = None
        if vendedor_idx > 0:
            vendedor_id = self.vendedores_trabajadores[vendedor_idx - 1]["id"]

        sumas = 0
        ventas_exentas = 0
        ventas_no_sujetas = 0
        total = 0
        iva = 0

        for item in self.venta_items:
            tipo_fiscal = item.get("tipo_fiscal", "").lower()
            base = item["subtotal_con_descuento"]
            if item.get("iva_tipo") == "desglosado":
                base = item.get("subtotal", base)

            if tipo_fiscal == "venta gravada":
                sumas += base
                iva += item.get("iva", 0)
            elif tipo_fiscal == "venta exenta":
                ventas_exentas += base
            elif tipo_fiscal == "venta no sujeta":
                ventas_no_sujetas += base
            total += item.get("total", 0)

        return {
            "cliente": self.selected_cliente if self.selected_cliente else {},
            "items": self.venta_items,
            "tipo_venta": (
                "Minorista" if self.tipo_minorista.isChecked()
                else "Mayorista (unitario)" if self.tipo_mayorista_unit.isChecked()
                else "Mayorista (total personalizado)"
            ),
            "precio_total_manual": float(self.precio_total_spin.value()),
            "iva_agregado": self.iva_agregado_radio.isChecked(),
            "nrc": self.nrc_edit.text(),
            "nit": self.nit_edit.text(),
            "giro": self.giro_edit.text(),
            "email": self.email_edit.text(),
            "no_remision": self.no_remision_edit.text(),
            "orden_no": self.orden_no_edit.text(),
            "condicion_pago": self.condicion_pago_combo.currentText(),
            "venta_a_cuenta_de": self.venta_a_cuenta_de_edit.text(),
            "fecha_remision_anterior": self.fecha_remision_anterior.date().toString("yyyy-MM-dd"),
            "fecha_remision": self.fecha_remision.date().toString("yyyy-MM-dd"),
            "sumas": sumas,
            "iva": iva,
            "subtotal": sumas + ventas_exentas + ventas_no_sujetas,
            "ventas_exentas": ventas_exentas,
            "ventas_no_sujetas": ventas_no_sujetas,
            "total": sumas + ventas_exentas + ventas_no_sujetas + iva,
            "fecha": QDate.currentDate().toString("yyyy-MM-dd"),
            "Distribuidor_id": (
                self.Distribuidor_combo.currentIndex()
                if self.Distribuidor_combo.currentIndex() >= 0 else None
            ),
            "vendedor_id": vendedor_id
        }

class DistribuidorDialog(QDialog):
    def __init__(self, parent=None, Distribuidor=None):
        super().__init__(parent)
        self.setWindowTitle("Registrar/Editar Distribuidor")
        self.setMinimumWidth(900)
        main_layout = QVBoxLayout()

        # --- Datos principales ---
        datos_principales = QGroupBox("Datos principales")
        form1 = QFormLayout()
        self.codigo_edit = QLineEdit()
        self.nombre_edit = QLineEdit()
        self.dui_edit = QLineEdit()
        self.telefono_edit = QLineEdit()
        self.email_edit = QLineEdit()
        self.cargo_edit = QLineEdit()
        self.sucursal_edit = QLineEdit()
        self.fecha_inicio_edit = QDateEdit(QDate.currentDate())
        self.fecha_inicio_edit.setCalendarPopup(True)

        form1.addRow("Código:", self.codigo_edit)
        form1.addRow("Nombre completo:", self.nombre_edit)
        form1.addRow("DUI:", self.dui_edit)
        form1.addRow("Teléfono:", self.telefono_edit)
        form1.addRow("Email:", self.email_edit)
        form1.addRow("Cargo:", self.cargo_edit)
        form1.addRow("Sucursal/Laboratorio:", self.sucursal_edit)
        form1.addRow("Fecha de inicio:", self.fecha_inicio_edit)
        datos_principales.setLayout(form1)

        # --- Detalles adicionales (opcional) ---
        detalles = QGroupBox("Detalles adicionales (opcional)")
        form2 = QFormLayout()
        self.direccion_edit = QLineEdit()
        self.departamento_edit = QLineEdit()
        self.municipio_edit = QLineEdit()
        self.tipo_contrato_edit = QLineEdit()
        self.comisiones_especificas_edit = QLineEdit()
        self.metodo_pago_edit = QLineEdit()
        self.nit_edit = QLineEdit()
        self.nrc_edit = QLineEdit()
        self.cuenta_bancaria_edit = QLineEdit()
        self.notas_edit = QLineEdit()

        form2.addRow("Dirección:", self.direccion_edit)
        form2.addRow("Departamento:", self.departamento_edit)
        form2.addRow("Municipio:", self.municipio_edit)
        form2.addRow("Tipo de contrato:", self.tipo_contrato_edit)
        form2.addRow("Comisiones específicas:", self.comisiones_especificas_edit)
        form2.addRow("Método/periodicidad pago:", self.metodo_pago_edit)
        form2.addRow("NIT:", self.nit_edit)
        form2.addRow("NRC:", self.nrc_edit)
        form2.addRow("Cuenta bancaria:", self.cuenta_bancaria_edit)
        form2.addRow("Notas:", self.notas_edit)
        detalles.setLayout(form2)

        # --- Agrupa horizontalmente las secciones ---
        h_layout = QHBoxLayout()
        h_layout.addWidget(datos_principales)
        h_layout.addWidget(detalles)
        main_layout.addLayout(h_layout)

        # --- Botones ---
        btns = QHBoxLayout()
        self.btn_ok = QPushButton("Guardar")
        self.btn_cancel = QPushButton("Cancelar")
        btns.addWidget(self.btn_ok)
        btns.addWidget(self.btn_cancel)
        main_layout.addLayout(btns)
        self.setLayout(main_layout)

        self.btn_ok.clicked.connect(self.accept)
        self.btn_cancel.clicked.connect(self.reject)

        # Si es edición, carga los datos existentes
        if Distribuidor:
            self.codigo_edit.setText(Distribuidor["codigo"] if "codigo" in Distribuidor.keys() else "")
            self.nombre_edit.setText(Distribuidor["nombre"] if "nombre" in Distribuidor.keys() else "")
            self.dui_edit.setText(Distribuidor["dui"] if "dui" in Distribuidor.keys() else "")
            self.telefono_edit.setText(Distribuidor["telefono"] if "telefono" in Distribuidor.keys() else "")
            self.email_edit.setText(Distribuidor["email"] if "email" in Distribuidor.keys() else "")
            self.cargo_edit.setText(Distribuidor["cargo"] if "cargo" in Distribuidor.keys() else "")
            self.sucursal_edit.setText(Distribuidor["sucursal"] if "sucursal" in Distribuidor.keys() else "")
            if "fecha_inicio" in Distribuidor.keys() and Distribuidor["fecha_inicio"]:
                self.fecha_inicio_edit.setDate(QDate.fromString(Distribuidor["fecha_inicio"], "yyyy-MM-dd"))
            self.direccion_edit.setText(Distribuidor["direccion"] if "direccion" in Distribuidor.keys() else "")
            self.departamento_edit.setText(Distribuidor["departamento"] if "departamento" in Distribuidor.keys() else "")
            self.municipio_edit.setText(Distribuidor["municipio"] if "municipio" in Distribuidor.keys() else "")
            self.tipo_contrato_edit.setText(Distribuidor["tipo_contrato"] if "tipo_contrato" in Distribuidor.keys() else "")
            self.comisiones_especificas_edit.setText(Distribuidor["comisiones_especificas"] if "comisiones_especificas" in Distribuidor.keys() else "")
            self.metodo_pago_edit.setText(Distribuidor["metodo_pago"] if "metodo_pago" in Distribuidor.keys() else "")
            self.nit_edit.setText(Distribuidor["nit"] if "nit" in Distribuidor.keys() else "")
            self.nrc_edit.setText(Distribuidor["nrc"] if "nrc" in Distribuidor.keys() else "")
            self.cuenta_bancaria_edit.setText(Distribuidor["cuenta_bancaria"] if "cuenta_bancaria" in Distribuidor.keys() else "")
            self.notas_edit.setText(Distribuidor["notas"] if "notas" in Distribuidor.keys() else "")

    def get_data(self):
        return {
            "codigo": self.codigo_edit.text(),
            "nombre": self.nombre_edit.text(),
            "dui": self.dui_edit.text(),
            "telefono": self.telefono_edit.text(),
            "email": self.email_edit.text(),
            "cargo": self.cargo_edit.text(),
            "sucursal": self.sucursal_edit.text(),
            "fecha_inicio": self.fecha_inicio_edit.date().toString("yyyy-MM-dd"),
            "direccion": self.direccion_edit.text(),
            "departamento": self.departamento_edit.text(),
            "municipio": self.municipio_edit.text(),
            "tipo_contrato": self.tipo_contrato_edit.text(),
            "comisiones_especificas": self.comisiones_especificas_edit.text(),
            "metodo_pago": self.metodo_pago_edit.text(),
            "nit": self.nit_edit.text(),
            "nrc": self.nrc_edit.text(),
            "cuenta_bancaria": self.cuenta_bancaria_edit.text(),
            "notas": self.notas_edit.text()
        }

class ClienteDialog(QDialog):
    def __init__(self, parent=None, cliente=None, codigo_sugerido=None):
        super().__init__(parent)
        self.setWindowTitle("Agregar/Editar Cliente")
        self.departamentos_data = cargar_departamentos_municipios()
        layout = QVBoxLayout()

        self.codigo_edit = QLineEdit()
        self.nombre_edit = QLineEdit()
        self.nrc_edit = QLineEdit()
        self.nit_edit = QLineEdit()
        self.dui_edit = QLineEdit()
        self.giro_edit = QLineEdit()
        self.telefono_edit = QLineEdit()
        self.email_edit = QLineEdit()
        self.direccion_edit = QLineEdit()
        self.departamento_combo = QComboBox()
        self.departamento_combo.addItems([""] + list(self.departamentos_data.keys()))
        self.municipio_combo = QComboBox()

        form = [
            ("Código:", self.codigo_edit),
            ("Nombre completo:", self.nombre_edit),
            ("NRC:", self.nrc_edit),
            ("NIT:", self.nit_edit),
            ("DUI:", self.dui_edit),
            ("Giro:", self.giro_edit),
            ("Teléfono:", self.telefono_edit),
            ("Correo electrónico:", self.email_edit),
            ("Dirección:", self.direccion_edit),
            ("Departamento:", self.departamento_combo),
            ("Municipio:", self.municipio_combo),
        ]
        for label, widget in form:
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
            row.addWidget(widget)
            layout.addLayout(row)

        btns = QHBoxLayout()
        self.btn_ok = QPushButton("Guardar")
        self.btn_cancel = QPushButton("Cancelar")
        btns.addWidget(self.btn_ok)
        btns.addWidget(self.btn_cancel)
        layout.addLayout(btns)
        self.setLayout(layout)

        self.departamento_combo.currentTextChanged.connect(self._actualizar_municipios)
        self.btn_ok.clicked.connect(self._validar_y_accept)
        self.btn_cancel.clicked.connect(self.reject)

        if codigo_sugerido and not cliente:
            self.codigo_edit.setText(codigo_sugerido)

        if cliente:
            self.codigo_edit.setText(cliente.get("codigo", ""))
            self.nombre_edit.setText(cliente.get("nombre", ""))
            self.nrc_edit.setText(cliente.get("nrc", ""))
            self.nit_edit.setText(cliente.get("nit", ""))
            self.dui_edit.setText(cliente.get("dui", ""))
            self.giro_edit.setText(cliente.get("giro", ""))
            self.telefono_edit.setText(cliente.get("telefono", ""))
            self.email_edit.setText(cliente.get("email", ""))
            self.direccion_edit.setText(cliente.get("direccion", ""))
            idx_depto = self.departamento_combo.findText(cliente.get("departamento", ""), Qt.MatchFixedString)
            if idx_depto >= 0:
                self.departamento_combo.setCurrentIndex(idx_depto)
            self._actualizar_municipios()
            idx_muni = self.municipio_combo.findText(cliente.get("municipio", ""), Qt.MatchFixedString)
            if idx_muni >= 0:
                self.municipio_combo.setCurrentIndex(idx_muni)

    def _actualizar_municipios(self):
        depto = self.departamento_combo.currentText()
        self.municipio_combo.clear()
        if depto and depto in self.departamentos_data:
            self.municipio_combo.addItems(self.departamentos_data[depto])

    def _validar_y_accept(self):
        if not self.nombre_edit.text().strip():
            QMessageBox.warning(self, "Validación", "El nombre es obligatorio.")
            return
        email = self.email_edit.text().strip()
        if not email:
            QMessageBox.warning(
                self,
                "Validación",
                "El correo electrónico es obligatorio."
            )
            return
        if not validar_email(email):
            QMessageBox.warning(
                self,
                "Validación",
                "Ingrese un correo electrónico válido."
            )
            return
        self.accept()

    def get_data(self):
        return {
            "codigo": self.codigo_edit.text().strip(),
            "nombre": self.nombre_edit.text().strip(),
            "nrc": self.nrc_edit.text().strip(),
            "nit": self.nit_edit.text().strip(),
            "dui": self.dui_edit.text().strip(),
            "giro": self.giro_edit.text().strip(),
            "telefono": self.telefono_edit.text().strip(),
            "email": self.email_edit.text().strip(),
            "direccion": self.direccion_edit.text().strip(),
            "departamento": self.departamento_combo.currentText(),
            "municipio": self.municipio_combo.currentText(),
        }

class VendedorDialog(QDialog):
    def __init__(self, Distribuidores, parent=None, vendedor=None, codigo_sugerido=None):
        super().__init__(parent)
        self.setWindowTitle("Agregar/Editar Vendedor")
        layout = QVBoxLayout()

        self.codigo_edit = QLineEdit()
        self.nombre_edit = QLineEdit()
        self.descripcion_edit = QLineEdit()
        self.Distribuidor_combo = QComboBox()
        self.Distribuidores = Distribuidores
        self.Distribuidor_combo.addItem("Sin Distribuidor")
        self.Distribuidor_combo.addItems([d["nombre"] for d in self.Distribuidores])

        layout.addWidget(QLabel("Código:"))
        layout.addWidget(self.codigo_edit)
        layout.addWidget(QLabel("Nombre:"))
        layout.addWidget(self.nombre_edit)
        layout.addWidget(QLabel("Descripción:"))
        layout.addWidget(self.descripcion_edit)
        layout.addWidget(QLabel("Distribuidor:"))
        layout.addWidget(self.Distribuidor_combo)

        btns = QHBoxLayout()
        self.btn_ok = QPushButton("Guardar")
        self.btn_cancel = QPushButton("Cancelar")
        btns.addWidget(self.btn_ok)
        btns.addWidget(self.btn_cancel)
        layout.addLayout(btns)
        self.setLayout(layout)

        self.btn_ok.clicked.connect(self.accept)
        self.btn_cancel.clicked.connect(self.reject)

        if codigo_sugerido and not vendedor:
            self.codigo_edit.setText(codigo_sugerido)

        if vendedor:
            self.codigo_edit.setText(vendedor.get("codigo", ""))
            self.nombre_edit.setText(vendedor.get("nombre", ""))
            self.descripcion_edit.setText(vendedor.get("descripcion", ""))
            Distribuidor_id = vendedor.get("Distribuidor_id")
            if Distribuidor_id:
                for i, d in enumerate(self.Distribuidores):
                    if d["id"] == Distribuidor_id:
                        self.Distribuidor_combo.setCurrentIndex(i + 1)  # +1 por "Sin Distribuidor"
                        break

    def get_data(self):
        idx = self.Distribuidor_combo.currentIndex()
        Distribuidor_id = None
        if idx > 0:
            Distribuidor_id = self.Distribuidores[idx - 1]["id"]
        return {
            "codigo": self.codigo_edit.text(),
            "nombre": self.nombre_edit.text(),
            "descripcion": self.descripcion_edit.text(),
            "Distribuidor_id": Distribuidor_id,
        }
class CompraDetalleDialog(QDialog):
    def __init__(self, compra, detalles, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Detalle de Compra")
        layout = QVBoxLayout()

        # Depuración: registra los detalles que llegan
        logger.debug("DETALLES DE COMPRA: %s", detalles)

        # --- Obtén los nombres de vendedor y Distribuidor ---
        vendedores = []
        Distribuidores = []
        productos = []
        if parent and hasattr(parent, "manager"):
            vendedores = getattr(parent.manager, "_vendedores", [])
            Distribuidores = getattr(parent.manager, "_Distribuidores", [])
            productos = getattr(parent.manager, "_products", [])
        vendedores_dict = {v["id"]: v["nombre"] for v in vendedores}
        Distribuidores_dict = {d["id"]: d["nombre"] for d in Distribuidores}
        productos_dict = {p["id"]: p["nombre"] for p in productos}

        vendedor_nombre = vendedores_dict.get(compra.get("vendedor_id"), "Desconocido")
        Distribuidor_nombre = Distribuidores_dict.get(compra.get("Distribuidor_id"), "Desconocido")

        layout.addWidget(QLabel(f"Fecha: {compra.get('fecha', '')}"))
        layout.addWidget(QLabel(f"Vendedor: {vendedor_nombre}"))
        layout.addWidget(QLabel(f"Distribuidor: {Distribuidor_nombre}"))
        layout.addWidget(QLabel(f"Total general: ${compra.get('total', 0):.2f}"))

        # --- Tabla de detalles ---
        table = QTableWidget(len(detalles), 8)
        table.setHorizontalHeaderLabels([
            "Producto", "Cantidad", "Precio U.", "Subtotal", "Descuento",
            "IVA", "Comisión", "Vencimiento"
        ])
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        for i, d in enumerate(detalles):
            nombre_producto = productos_dict.get(d.get("producto_id"), "Desconocido")
            precio_unitario = d.get("precio_unitario", d.get("precio", 0))
            subtotal = d.get("cantidad", 0) * precio_unitario
            table.setItem(i, 0, QTableWidgetItem(nombre_producto))
            table.setItem(i, 1, QTableWidgetItem(str(d.get("cantidad", ""))))
            table.setItem(i, 2, QTableWidgetItem(f"${precio_unitario:.2f}"))
            table.setItem(i, 3, QTableWidgetItem(f"${subtotal:.2f}"))
            table.setItem(i, 4, QTableWidgetItem(f"${d.get('descuento', 0):.2f}"))
            table.setItem(i, 5, QTableWidgetItem(f"${d.get('iva', 0):.2f}"))
            # Mostrar el monto de la comisión:
            table.setItem(i, 6, QTableWidgetItem(f"${d.get('comision_monto', 0):.2f}"))
            table.setItem(i, 7, QTableWidgetItem(str(d.get("fecha_vencimiento", ""))))
        table.resizeColumnsToContents()
        layout.addWidget(table)
        self.setLayout(layout)

class DatosNegocioDialog(QDialog):
    def __init__(self, datos=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Datos del negocio")
        self.setMinimumWidth(900)
        main_layout = QVBoxLayout()

        # --- Agrupación horizontal ---
        h_layout = QHBoxLayout()

        # --- Grupo 1: Identificación comercial y Ubicación ---
        grupo1 = QGroupBox("🧾 Identificación comercial y 🗺️ Ubicación")
        form1 = QFormLayout()
        self.nombre_comercial = QLineEdit()
        self.razon_social = QLineEdit()
        self.giro = QLineEdit()
        self.slogan = QLineEdit()
        self.direccion = QLineEdit()
        self.municipio = QLineEdit()
        self.departamento = QLineEdit()
        self.codigo_postal = QLineEdit()
        self.pais = QLineEdit()
        form1.addRow("Nombre comercial:", self.nombre_comercial)
        form1.addRow("Razón social:", self.razon_social)
        form1.addRow("Giro o actividad económica:", self.giro)
        form1.addRow("Slogan o lema empresarial:", self.slogan)
        form1.addRow("Dirección exacta:", self.direccion)
        form1.addRow("Municipio:", self.municipio)
        form1.addRow("Departamento:", self.departamento)
        form1.addRow("Código postal:", self.codigo_postal)
        form1.addRow("País:", self.pais)
        grupo1.setLayout(form1)
        h_layout.addWidget(grupo1)

        # --- Grupo 2: Contacto y Representante Legal ---
        grupo2 = QGroupBox("📞 Contacto y 🧑‍💼 Representante Legal")
        form2 = QFormLayout()
        self.telefono_fijo = QLineEdit()
        self.telefono_movil = QLineEdit()
        self.email = QLineEdit()
        self.sitio_web = QLineEdit()
        self.representante_nombre = QLineEdit()
        self.representante_cargo = QLineEdit()
        self.representante_dui_nit = QLineEdit()
        self.representante_email = QLineEdit()
        self.representante_telefono = QLineEdit()
        form2.addRow("Teléfono fijo:", self.telefono_fijo)
        form2.addRow("Teléfono móvil:", self.telefono_movil)
        form2.addRow("Correo electrónico oficial:", self.email)
        form2.addRow("Sitio web:", self.sitio_web)
        form2.addRow("Nombre representante:", self.representante_nombre)
        form2.addRow("Cargo:", self.representante_cargo)
        form2.addRow("DUI/NIT representante:", self.representante_dui_nit)
        form2.addRow("Correo representante:", self.representante_email)
        form2.addRow("Teléfono representante:", self.representante_telefono)
        grupo2.setLayout(form2)
        h_layout.addWidget(grupo2)

        # --- Grupo 3: Datos Fiscales ---
        grupo3 = QGroupBox("💼 Datos Fiscales")
        form3 = QFormLayout()
        self.nit = QLineEdit()
        self.nrc = QLineEdit()
        self.regimen = QLineEdit()
        self.ciiu = QLineEdit()
        self.contador_nombre = QLineEdit()
        self.contador_nit = QLineEdit()
        form3.addRow("NIT:", self.nit)
        form3.addRow("NRC:", self.nrc)
        form3.addRow("Régimen tributario:", self.regimen)
        form3.addRow("Código CIIU:", self.ciiu)
        form3.addRow("Nombre contador:", self.contador_nombre)
        form3.addRow("NIT contador:", self.contador_nit)
        grupo3.setLayout(form3)
        h_layout.addWidget(grupo3)

        # --- Grupo 4: Configuración de correo ---
        grupo4 = QGroupBox("\ud83d\udce7 Configuraci\u00f3n de correo")
        form4 = QFormLayout()

        # Proveedor de correo y configuraci\u00f3n SMTP predefinida
        self.combo_email_provider = QComboBox()
        self.combo_email_provider.addItems([
            "Gmail",
            "Outlook",
            "Yahoo",
            "Zoho",
            "iCloud",
        ])

        self.smtp_server = QLineEdit()
        self.smtp_port = QLineEdit()
        self.email_usuario = QLineEdit()
        self.email_contrasena = QLineEdit()
        self.email_contrasena.setEchoMode(QLineEdit.Password)

        form4.addRow("Proveedor:", self.combo_email_provider)
        form4.addRow("Servidor SMTP:", self.smtp_server)
        form4.addRow("Puerto SMTP:", self.smtp_port)
        form4.addRow("Usuario:", self.email_usuario)
        form4.addRow("Contrase\u00f1a:", self.email_contrasena)
        grupo4.setLayout(form4)

        self.combo_email_provider.currentTextChanged.connect(
            self._update_smtp_fields
        )
        self.email.textChanged.connect(self._update_user_field)
        self._update_smtp_fields()

        main_layout.addLayout(h_layout)
        main_layout.addWidget(grupo4)

        # --- Botones ---
        btns = QHBoxLayout()
        self.btn_guardar = QPushButton("Guardar")
        self.btn_cancelar = QPushButton("Cancelar")
        btns.addWidget(self.btn_guardar)
        btns.addWidget(self.btn_cancelar)
        main_layout.addLayout(btns)
        self.setLayout(main_layout)

        self.btn_guardar.clicked.connect(self.accept)
        self.btn_cancelar.clicked.connect(self.reject)

        # Si hay datos previos, cárgalos
        if datos:
            self.set_data(datos)

    def get_data(self):
        return {
            "nombre_comercial": self.nombre_comercial.text(),
            "razon_social": self.razon_social.text(),
            "giro": self.giro.text(),
            "slogan": self.slogan.text(),
            "direccion": self.direccion.text(),
            "municipio": self.municipio.text(),
            "departamento": self.departamento.text(),
            "codigo_postal": self.codigo_postal.text(),
            "pais": self.pais.text(),
            "telefono_fijo": self.telefono_fijo.text(),
            "telefono_movil": self.telefono_movil.text(),
            "email": self.email.text(),
            "sitio_web": self.sitio_web.text(),
            "representante_nombre": self.representante_nombre.text(),
            "representante_cargo": self.representante_cargo.text(),
            "representante_dui_nit": self.representante_dui_nit.text(),
            "representante_email": self.representante_email.text(),
            "representante_telefono": self.representante_telefono.text(),
            "nit": self.nit.text(),
            "nrc": self.nrc.text(),
            "regimen": self.regimen.text(),
            "ciiu": self.ciiu.text(),
            "contador_nombre": self.contador_nombre.text(),
            "contador_nit": self.contador_nit.text(),
            "email_provider": self.combo_email_provider.currentText(),
            "smtp_server": self.smtp_server.text(),
            "smtp_port": self.smtp_port.text(),
            "email_usuario": self.email_usuario.text(),
            "email_contrasena": self.email_contrasena.text(),
        }

    def set_data(self, datos):
        self.nombre_comercial.setText(datos.get("nombre_comercial", ""))
        self.razon_social.setText(datos.get("razon_social", ""))
        self.giro.setText(datos.get("giro", ""))
        self.slogan.setText(datos.get("slogan", ""))
        self.direccion.setText(datos.get("direccion", ""))
        self.municipio.setText(datos.get("municipio", ""))
        self.departamento.setText(datos.get("departamento", ""))
        self.codigo_postal.setText(datos.get("codigo_postal", ""))
        self.pais.setText(datos.get("pais", ""))
        self.telefono_fijo.setText(datos.get("telefono_fijo", ""))
        self.telefono_movil.setText(datos.get("telefono_movil", ""))
        self.email.setText(datos.get("email", ""))
        self.sitio_web.setText(datos.get("sitio_web", ""))
        self.representante_nombre.setText(datos.get("representante_nombre", ""))
        self.representante_cargo.setText(datos.get("representante_cargo", ""))
        self.representante_dui_nit.setText(datos.get("representante_dui_nit", ""))
        self.representante_email.setText(datos.get("representante_email", ""))
        self.representante_telefono.setText(datos.get("representante_telefono", ""))
        self.nit.setText(datos.get("nit", ""))
        self.nrc.setText(datos.get("nrc", ""))
        self.regimen.setText(datos.get("regimen", ""))
        self.ciiu.setText(datos.get("ciiu", ""))
        self.contador_nombre.setText(datos.get("contador_nombre", ""))
        self.contador_nit.setText(datos.get("contador_nit", ""))
        provider = datos.get("email_provider", "Gmail")
        idx = self.combo_email_provider.findText(provider)
        if idx >= 0:
            self.combo_email_provider.setCurrentIndex(idx)
        else:
            self.combo_email_provider.setCurrentIndex(0)
        self.smtp_server.setText(datos.get("smtp_server", ""))
        self.smtp_port.setText(str(datos.get("smtp_port", "")))
        self.email_usuario.setText(datos.get("email_usuario", self.email.text()))
        self.email_contrasena.setText(datos.get("email_contrasena", ""))
        self._update_smtp_fields()

    def _update_user_field(self):
        """Autocompletar el usuario con el correo oficial."""
        self.email_usuario.setText(self.email.text())

    def _update_smtp_fields(self):
        """Actualizar datos SMTP al cambiar de proveedor."""
        provider = self.combo_email_provider.currentText()
        defaults = {
            "Gmail": ("smtp.gmail.com", 587),
            "Outlook": ("smtp.office365.com", 587),
            "Yahoo": ("smtp.mail.yahoo.com", 587),
            "Zoho": ("smtp.zoho.com", 587),
            "iCloud": ("smtp.mail.me.com", 587),
        }
        server, port = defaults.get(provider, ("", ""))
        self.smtp_server.setText(server)
        self.smtp_port.setText(str(port))
        self.smtp_server.setReadOnly(True)
        self.smtp_port.setReadOnly(True)
        self.email_usuario.setText(self.email.text())
        self.email_usuario.setReadOnly(True)
class TrabajadorDialog(QDialog):
    def __init__(self, trabajador=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Trabajador")
        layout = QVBoxLayout()
        form = QFormLayout()
        self.codigo = QLineEdit()
        self.nombre = QLineEdit()
        self.dui = QLineEdit()
        self.nit = QLineEdit()
        self.fecha_nacimiento = QDateEdit(QDate.currentDate())
        self.fecha_nacimiento.setCalendarPopup(True)
        self.cargo = QLineEdit()
        self.area = QLineEdit()
        self.fecha_contratacion = QDateEdit(QDate.currentDate())
        self.fecha_contratacion.setCalendarPopup(True)
        self.telefono = QLineEdit()
        self.email = QLineEdit()
        self.direccion = QLineEdit()
        self.salario_base = QDoubleSpinBox()
        self.salario_base.setMaximum(1000000)
        self.salario_base.setDecimals(2)
        self.comentarios = QLineEdit()
        self.es_vendedor = QCheckBox("¿Es vendedor?")

        form.addRow("Código:", self.codigo)
        form.addRow("Nombre completo:", self.nombre)
        form.addRow("DUI:", self.dui)
        form.addRow("NIT:", self.nit)
        form.addRow("Fecha de nacimiento:", self.fecha_nacimiento)
        form.addRow("Cargo o puesto:", self.cargo)
        form.addRow("Área / Departamento:", self.area)
        form.addRow("Fecha de contratación:", self.fecha_contratacion)
        form.addRow("Teléfono:", self.telefono)
        form.addRow("Correo electrónico:", self.email)
        form.addRow("Dirección:", self.direccion)
        form.addRow("Salario base:", self.salario_base)
        form.addRow("Comentarios:", self.comentarios)
        form.addRow(self.es_vendedor)
        layout.addLayout(form)

        btns = QHBoxLayout()
        self.btn_ok = QPushButton("Guardar")
        self.btn_cancel = QPushButton("Cancelar")
        btns.addWidget(self.btn_ok)
        btns.addWidget(self.btn_cancel)
        layout.addLayout(btns)
        self.setLayout(layout)

        self.btn_ok.clicked.connect(self._validar_y_accept)
        self.btn_cancel.clicked.connect(self.reject)

        if trabajador:
            self.codigo.setText(trabajador.get("codigo", ""))
            self.nombre.setText(trabajador.get("nombre", ""))
            self.dui.setText(trabajador.get("dui", ""))
            self.nit.setText(trabajador.get("nit", ""))
            if trabajador.get("fecha_nacimiento"):
                self.fecha_nacimiento.setDate(QDate.fromString(trabajador["fecha_nacimiento"], "yyyy-MM-dd"))
            self.cargo.setText(trabajador.get("cargo", ""))
            self.area.setText(trabajador.get("area", ""))
            if trabajador.get("fecha_contratacion"):
                self.fecha_contratacion.setDate(QDate.fromString(trabajador["fecha_contratacion"], "yyyy-MM-dd"))
            self.telefono.setText(trabajador.get("telefono", ""))
            self.email.setText(trabajador.get("email", ""))
            self.direccion.setText(trabajador.get("direccion", ""))
            self.salario_base.setValue(trabajador.get("salario_base", 0) or 0)
            self.comentarios.setText(trabajador.get("comentarios", ""))
            self.es_vendedor.setChecked(trabajador.get("es_vendedor", 0) == 1)

    def _validar_y_accept(self):
        self.accept()

    def get_data(self):
        return {
            "codigo": self.codigo.text().strip(),
            "nombre": self.nombre.text().strip(),
            "dui": self.dui.text().strip(),
            "nit": self.nit.text().strip(),
            "fecha_nacimiento": self.fecha_nacimiento.date().toString("yyyy-MM-dd"),
            "cargo": self.cargo.text().strip(),
            "area": self.area.text().strip(),
            "fecha_contratacion": self.fecha_contratacion.date().toString("yyyy-MM-dd"),
            "telefono": self.telefono.text().strip(),
            "email": self.email.text().strip(),
            "direccion": self.direccion.text().strip(),
            "salario_base": self.salario_base.value(),
            "comentarios": self.comentarios.text().strip(),
            "es_vendedor": self.es_vendedor.isChecked()
        }


class ManualInvoiceDialog(QDialog):
    """Dialogo para generar manualmente una factura en PDF."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Generar factura manual")

        main_layout = QVBoxLayout(self)

        type_layout = QHBoxLayout()
        type_layout.addWidget(QLabel("Tipo de factura:"))
        self.type_combo = QComboBox()
        self.type_combo.addItems(["Consumidor final", "Crédito fiscal"])
        type_layout.addWidget(self.type_combo)
        main_layout.addLayout(type_layout)

        self.stack = QStackedLayout()

        # --- Consumidor final ---
        cf_widget = QWidget()
        cf_form = QFormLayout(cf_widget)
        self.cf_nombre = QLineEdit()
        self.cf_direccion = QLineEdit()
        self.cf_fecha = QDateEdit(QDate.currentDate())
        self.cf_fecha.setCalendarPopup(True)
        self.cf_observaciones = QTextEdit()
        cf_form.addRow("Nombre:", self.cf_nombre)
        cf_form.addRow("Dirección:", self.cf_direccion)
        cf_form.addRow("Fecha:", self.cf_fecha)
        cf_form.addRow("Observaciones:", self.cf_observaciones)
        self.stack.addWidget(cf_widget)

        # --- Crédito fiscal ---
        cr_widget = QWidget()
        cr_form = QFormLayout(cr_widget)
        self.cr_codigo_generacion = QLineEdit()
        self.cr_numero_control = QLineEdit()
        self.cr_sello = QLineEdit()
        self.cr_condicion_pago = QLineEdit()
        self.cr_no_remision = QLineEdit()
        self.cr_orden_no = QLineEdit()
        self.cr_vendedor = QLineEdit()
        self.cr_venta_cuenta = QLineEdit()
        self.cr_fecha = QDateEdit(QDate.currentDate())
        self.cr_fecha.setCalendarPopup(True)
        self.cr_cliente_nombre = QLineEdit()
        self.cr_cliente_direccion = QLineEdit()
        self.cr_cliente_nit = QLineEdit()
        self.cr_cliente_nrc = QLineEdit()
        self.cr_cliente_giro = QLineEdit()
        self.cr_total_letras = QLineEdit()
        self.cr_observaciones = QTextEdit()

        credit_fields = [
            ("Código generación:", self.cr_codigo_generacion),
            ("Número control:", self.cr_numero_control),
            ("Sello recepción:", self.cr_sello),
            ("Condición de pago:", self.cr_condicion_pago),
            ("No remisión:", self.cr_no_remision),
            ("Orden No:", self.cr_orden_no),
            ("Vendedor:", self.cr_vendedor),
            ("Venta a cuenta de:", self.cr_venta_cuenta),
            ("Fecha:", self.cr_fecha),
            ("Cliente:", self.cr_cliente_nombre),
            ("Dirección:", self.cr_cliente_direccion),
            ("NIT:", self.cr_cliente_nit),
            ("NRC:", self.cr_cliente_nrc),
            ("Giro:", self.cr_cliente_giro),
            ("Total en letras:", self.cr_total_letras),
            ("Observaciones:", self.cr_observaciones),
        ]

        for lbl, w in credit_fields:
            cr_form.addRow(lbl, w)

        self.stack.addWidget(cr_widget)

        main_layout.addLayout(self.stack)

        btns = QHBoxLayout()
        self.btn_ok = QPushButton("Generar PDF")
        self.btn_cancel = QPushButton("Cancelar")
        btns.addWidget(self.btn_ok)
        btns.addWidget(self.btn_cancel)
        main_layout.addLayout(btns)

        self.type_combo.currentIndexChanged.connect(self.stack.setCurrentIndex)
        self.btn_ok.clicked.connect(self.accept)
        self.btn_cancel.clicked.connect(self.reject)

    def get_data(self):
        if self.type_combo.currentIndex() == 0:
            return {
                "tipo": "consumidor",
                "fecha": self.cf_fecha.date().toString("yyyy-MM-dd"),
                "cliente": {
                    "nombre": self.cf_nombre.text(),
                    "direccion": self.cf_direccion.text(),
                },
                "observaciones": self.cf_observaciones.toPlainText(),
                "detalles": [],
            }
        else:
            return {
                "tipo": "credito",
                "codigo_generacion": self.cr_codigo_generacion.text(),
                "numero_control": self.cr_numero_control.text(),
                "sello_recepcion": self.cr_sello.text(),
                "condicion_pago": self.cr_condicion_pago.text(),
                "no_remision": self.cr_no_remision.text(),
                "orden_no": self.cr_orden_no.text(),
                "vendedor_nombre": self.cr_vendedor.text(),
                "venta_a_cuenta_de": self.cr_venta_cuenta.text(),
                "fecha": self.cr_fecha.date().toString("yyyy-MM-dd"),
                "total_letras": self.cr_total_letras.text(),
                "observaciones": self.cr_observaciones.toPlainText(),
                "cliente": {
                    "nombre": self.cr_cliente_nombre.text(),
                    "direccion": self.cr_cliente_direccion.text(),
                    "nit": self.cr_cliente_nit.text(),
                    "nrc": self.cr_cliente_nrc.text(),
                    "giro": self.cr_cliente_giro.text(),
                },
                "detalles": [],
            }
