from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QTableView, QLineEdit,
    QPushButton, QTabWidget, QMessageBox, QSplitter, QMenuBar, QAction, QFileDialog,
    QListWidget, QLabel, QComboBox, QTreeWidget, QTreeWidgetItem, QTableWidget, QTableWidgetItem, QDialog,
    QDateEdit, QCheckBox, QTextEdit, QAbstractItemView, QHeaderView, QSizePolicy,
    QInputDialog, QFormLayout, QDialogButtonBox, QSpinBox
)
from PyQt5.QtCore import Qt, QDate, QThread, pyqtSignal, QTimer
from PyQt5.QtGui import QColor
import os
import json
import sys
import subprocess
import unicodedata
from typing import Mapping
from inventory_manager import InventoryManager
from db import DB
from paths import (
    AUTO_BACKUP_DIR,
    DATOS_NEGOCIO_PATH,
    CONFIG_NEGOCIO_PATH,
    LAST_INVENTORY_PATH,
)
from dialogs import (
    RegisterSaleDialog,
    ProductDialog,
    RegisterPurchaseDialog,
    DistribuidorDialog,
    DistribuidorInfoDialog,
    ClienteDialog,
    EstadoCuentaDialog,
    UserConfigDialog,
    CompraDetalleDialog,
)

from sales_tab import SalesTab
from facturacion_tab import FacturacionTab
from datetime import datetime, date, timedelta

from num2words import num2words  # Instala las dependencias con: pip install -r requirements.txt

from factura_sv import generar_factura_electronica_pdf
from decimal import Decimal, ROUND_HALF_UP
from utils.fiscal_extra import build_fiscal_extra
from utils.resumen import sync_condicion_operacion_flags
from utils.monto import monto_a_texto_sv
from utils.jws import sign_json
from utils.firmador import iniciar_firmador, detener_firmador, firmador_activo
from mh_auth import invalidate_token_cache
from utils.party_resolver import normalize_identifier, resolve_party_names
from utils.facturacion_records import (
    TIPO_DTE_DESC,
    canonical_tipo_label,
    get_facturacion_rows,
)
import logging

logger = logging.getLogger(__name__)

def redondear(valor):
    return float(Decimal(str(valor)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def build_payment_condition_extra(data):
    condicion = data.get("condicion_operacion")
    if condicion not in {1, 2, 3}:
        return {}

    extra: dict = {}
    sync_condicion_operacion_flags(extra, condicion)
    if condicion == 2:
        plazo = data.get("pago_plazo")
        periodo = data.get("pago_periodo")
        if not plazo or not periodo:
            return extra
        pago = {
            "codigo": "01",
            "montoPago": float(data.get("total", 0) or 0),
            "plazo": plazo,
            "periodo": periodo,
        }
        referencia = (data.get("pago_referencia") or "").strip()
        if referencia:
            pago["referencia"] = referencia
        extra["pagos"] = [pago]
        extra["pago_plazo"] = plazo
        extra["pago_periodo"] = periodo
        if referencia:
            extra["pago_referencia"] = referencia
    return extra


class ExportThread(QThread):
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, filename, tab_order):
        super().__init__()
        self.filename = filename
        self.tab_order = tab_order

    def run(self):
        """Run the export in a background thread.

        A new ``InventoryManager`` instance is created so that this thread uses
        its own database connection, avoiding any cross-thread usage of the
        main application's connection.
        """
        try:
            manager = InventoryManager(DB(), enable_auto_backup=False)
            manager.exportar_inventario_json(
                self.filename, tab_order=self.tab_order
            )
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))


class EditarLoteDialog(QDialog):
    """Diálogo para editar los datos de un lote."""

    def __init__(
        self,
        parent=None,
        *,
        producto: str = "",
        codigo: str = "",
        cantidad: int = 0,
        codigo_lote: str = "",
        registro_sanitario: str = "",
        fecha_vencimiento: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Editar lote")

        layout = QVBoxLayout(self)
        descripcion = QLabel(f"Producto: {producto} ({codigo})")
        descripcion.setWordWrap(True)
        layout.addWidget(descripcion)

        form = QFormLayout()

        self.cantidad_spin = QSpinBox()
        self.cantidad_spin.setMinimum(0)
        self.cantidad_spin.setMaximum(1_000_000_000)
        self.cantidad_spin.setValue(max(0, cantidad))
        form.addRow("Cantidad:", self.cantidad_spin)

        self.codigo_lote_edit = QLineEdit(codigo_lote)
        self.codigo_lote_edit.setPlaceholderText("Código de lote")
        form.addRow("Código de lote:", self.codigo_lote_edit)

        self.registro_sanitario_edit = QLineEdit(registro_sanitario)
        self.registro_sanitario_edit.setPlaceholderText("Registro sanitario")
        form.addRow("Registro sanitario:", self.registro_sanitario_edit)

        self.fecha_vencimiento_edit = QDateEdit()
        self.fecha_vencimiento_edit.setCalendarPopup(True)
        self.fecha_vencimiento_edit.setDisplayFormat("yyyy-MM-dd")
        self.fecha_vencimiento_edit.setMinimumDate(QDate(1900, 1, 1))
        self.fecha_vencimiento_edit.setMaximumDate(QDate(7999, 12, 31))
        fecha_actual = QDate.currentDate()
        self.fecha_vencimiento_edit.setDate(fecha_actual)

        self.sin_fecha_checkbox = QCheckBox("Sin fecha de vencimiento")
        self.sin_fecha_checkbox.toggled.connect(
            lambda checked: self.fecha_vencimiento_edit.setEnabled(not checked)
        )

        if fecha_vencimiento:
            fecha_qt = QDate.fromString(fecha_vencimiento, "yyyy-MM-dd")
            if fecha_qt.isValid():
                self.fecha_vencimiento_edit.setDate(fecha_qt)
                self.sin_fecha_checkbox.setChecked(False)
            else:
                self.sin_fecha_checkbox.setChecked(True)
                self.fecha_vencimiento_edit.setEnabled(False)
        else:
            self.sin_fecha_checkbox.setChecked(True)
            self.fecha_vencimiento_edit.setEnabled(False)

        form.addRow("Fecha de vencimiento:", self.fecha_vencimiento_edit)
        layout.addLayout(form)
        layout.addWidget(self.sin_fecha_checkbox)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_values(self) -> tuple[int, str, str, str]:
        cantidad = self.cantidad_spin.value()
        codigo_lote = self.codigo_lote_edit.text().strip()
        registro_sanitario = self.registro_sanitario_edit.text().strip()
        fecha_vencimiento = ""
        if not self.sin_fecha_checkbox.isChecked():
            fecha_vencimiento = self.fecha_vencimiento_edit.date().toString("yyyy-MM-dd")
        return cantidad, codigo_lote, registro_sanitario, fecha_vencimiento


class MainWindow(QMainWindow):
    # Generic signal emitted whenever sales or payment data changes. Tabs
    # that need to stay in sync can listen for this signal to refresh
    # immediately instead of waiting for the periodic timers.
    data_changed = pyqtSignal()

    def __init__(self, user=None):
        super().__init__()
        self.user = user or {"username": "admin", "role": "admin"}
        self.setWindowTitle("Inventario Farmacia")
        self.resize(1200, 700)
        self.db = DB()
        self.manager = InventoryManager(self.db, enable_auto_backup=True)
        self.ultimo_archivo_json = None  # Guarda la ruta del último archivo .json usado
        self._load_last_inventory_path()
        self.firmador_proc = None
        # Contador de cambios en la base de datos para detectar si hay datos sin guardar
        self._mark_saved()
        self._setup_ui()
        self._apply_styles()
        QTimer.singleShot(0, self._verificar_firmador)

        # Timer to periodically refresh the "Estados de cuenta" table so it
        # stays synchronized with new sales or payments made from any tab.
        self._historial_timer = QTimer(self)
        self._historial_timer.setInterval(10000)  # 10 seconds
        self._historial_timer.timeout.connect(self._mostrar_historial_general)
        self._historial_timer.start()

        # When data changes elsewhere emit a signal so the tabs refresh
        # immediately instead of waiting for the timer interval.
        self.data_changed.connect(self.facturacion_tab.refresh_and_reload)
        self.data_changed.connect(self._mostrar_historial_general)

    def iniciar_firmador(self):
        """Lanza el servicio externo de firmado de documentos."""
        if self.firmador_proc and self.firmador_proc.poll() is None:
            QMessageBox.information(
                self,
                "Firmador",
                "El firmador ya está corriendo, no es necesario volver a ejecutarlo.",
            )
            return
        if firmador_activo():
            QMessageBox.information(
                self,
                "Firmador",
                "El firmador ya está corriendo, no es necesario volver a ejecutarlo.",
            )
            return
        try:
            self.firmador_proc = iniciar_firmador()
            QMessageBox.information(
                self, "Firmador", "El firmador está corriendo."
            )
        except FileNotFoundError as exc:
            QMessageBox.critical(self, "Error", f"No se encontró el firmador:\n{exc}")
        except RuntimeError:
            QMessageBox.information(
                self,
                "Firmador",
                "El firmador ya está corriendo, no es necesario volver a ejecutarlo.",
            )
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"No se pudo iniciar el firmador:\n{exc}")

    def _verificar_firmador(self):
        if firmador_activo():
            QMessageBox.information(
                self,
                "Firmador",
                "El firmador ya está corriendo, no es necesario volver a ejecutarlo.",
            )
        else:
            resp = QMessageBox.question(
                self,
                "Firmador",
                "El firmador no está corriendo y es necesario para generar facturas. ¿Desea iniciarlo?",
            )
            if resp == QMessageBox.Yes:
                self.iniciar_firmador()

    @staticmethod
    def _parse_invoice_datetime(value):
        if isinstance(value, datetime):
            return value
        if not value:
            return None
        if isinstance(value, str):
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
                try:
                    return datetime.strptime(value, fmt)
                except ValueError:
                    continue
        return None

    @staticmethod
    def _normalize_envio_text(value: str) -> str:
        lowered = str(value or "").strip().lower()
        if not lowered:
            return ""
        normalized = unicodedata.normalize("NFKD", lowered)
        return "".join(ch for ch in normalized if not unicodedata.combining(ch))

    def _get_latest_invoice_row(self):
        manager = getattr(self, "manager", None)
        if manager is None:
            return None
        try:
            rows = get_facturacion_rows(manager.db)
        except Exception:
            logger.exception(
                "Error al obtener registros de facturación para validar la última factura"
            )
            return None

        latest_row = None
        latest_key = None
        allowed_tipo_labels = {"Consumidor final", "Crédito fiscal", "Ticket"}
        for row in rows:
            try:
                tipo_label = canonical_tipo_label(row.get("tipo"))
                if not tipo_label:
                    code_value = row.get("codigo")
                    code_str = str(code_value).zfill(2) if code_value is not None else ""
                    if code_str:
                        tipo_label = TIPO_DTE_DESC.get(code_str)
                if tipo_label not in allowed_tipo_labels:
                    continue
                row_type = str(row.get("row_type") or "").strip().lower()
                if row_type and row_type not in {"venta", "ticket"}:
                    continue
                timestamp = row.get("_parsed_fecha")
                if isinstance(timestamp, datetime) and timestamp.tzinfo is not None:
                    timestamp = timestamp.replace(tzinfo=None)
                if not isinstance(timestamp, datetime):
                    timestamp = self._parse_invoice_datetime(row.get("fecha"))
                if timestamp is None:
                    timestamp = datetime.min
                venta_id = row.get("venta_id")
                try:
                    venta_key = int(venta_id)
                except (TypeError, ValueError):
                    venta_key = 0
                rec_id = row.get("id")
                try:
                    rec_key = int(rec_id)
                except (TypeError, ValueError):
                    rec_key = 0
                key = (timestamp, venta_key, rec_key)
            except Exception:
                logger.exception(
                    "Error al procesar un registro de facturación durante la validación"
                )
                continue

            if latest_key is None or key > latest_key:
                latest_key = key
                latest_row = row

        return latest_row

    def _ensure_last_invoice_sent(self) -> bool:
        try:
            latest_row = self._get_latest_invoice_row()
        except Exception:
            logger.exception(
                "Error inesperado al validar la última factura antes de registrar una venta"
            )
            return True

        if not latest_row:
            return True

        envio_state = str(latest_row.get("envio") or "").strip()
        normalized = self._normalize_envio_text(envio_state)
        if not normalized:
            normalized = "pendiente de envio"

        if normalized.startswith("pendiente") or "no enviado" in normalized or "no enviada" in normalized:
            QMessageBox.warning(
                self,
                "Documento pendiente",
                "El último ticket o factura no ha sido enviado. Envía o elimina el último documento.",
            )
            return False

        return True

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
        cargar_respaldo_action = QAction("Cargar copia de seguridad...", self)
        cargar_respaldo_action.triggered.connect(self.cargar_copia_seguridad)
        firmar_dte_action = QAction("Firmar DTE...", self)
        firmar_dte_action.triggered.connect(self.firmar_dte_manual)
        archivo_menu.addAction(nuevo_inventario_action)
        archivo_menu.addAction(guardar_como_action)
        archivo_menu.addAction(cargar_inventario_action)
        archivo_menu.addAction(cargar_respaldo_action)

        # --- CONFIGURACIÓN ---
        config_menu = menubar.addMenu("Configuración")
        datos_negocio_action = QAction("Datos del negocio", self)
        datos_negocio_action.triggered.connect(self._abrir_datos_negocio)
        config_menu.addAction(datos_negocio_action)
        correo_action = QAction("Configuración de correo", self)
        correo_action.triggered.connect(self._abrir_config_correo)
        config_menu.addAction(correo_action)
        dte_action = QAction("Facturación electrónica", self)
        dte_action.triggered.connect(self._abrir_config_facturacion)
        config_menu.addAction(dte_action)
        if self.user["role"] == "admin":
            user_action = QAction("Configuración de usuarios", self)
            user_action.triggered.connect(self._abrir_config_usuarios)
            config_menu.addAction(user_action)
        else:
            config_menu.menuAction().setVisible(False)
        abrir_firmador_action = QAction("Iniciar firmador", self)
        abrir_firmador_action.triggered.connect(self.iniciar_firmador)
        config_menu.addAction(abrir_firmador_action)
        config_menu.addAction(firmar_dte_action)

        # DEBUG: Acción temporal para depurar Venta vs DTE
        debug_venta_dte_action = QAction("Debug Venta vs DTE", self)
        debug_venta_dte_action.triggered.connect(self._debug_venta_vs_dte)
        config_menu.addAction(debug_venta_dte_action)

        logout_action = QAction("Cerrar sesión", self)
        logout_action.triggered.connect(self.cerrar_sesion)
        menubar.addAction(logout_action)

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

        if self.user["role"] == "guest":
            for btn in [
                self.btn_add_product,
                self.btn_edit_product,
                self.btn_register_sale,
                self.btn_register_credito_fiscal,
                self.btn_register_purchase,
                self.btn_delete_product,
                self.btn_guardar_rapido,
                self.btn_cargar_inventario,
            ]:
                btn.setEnabled(False)

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
        self.vendedor_combo_filtro.addItem("Todos", None)
        for v in self.manager.get_vendedores_compra():
            self.vendedor_combo_filtro.addItem(v["nombre"], v["id"])

        self.vendedor_combo_filtro.currentIndexChanged.connect(self.filter_products)
        filtros_layout.addWidget(QLabel("Vendedor:"))
        filtros_layout.addWidget(self.vendedor_combo_filtro)

        self.distribuidor_combo_filtro = QComboBox()
        self.distribuidor_combo_filtro.addItem("Todos", None)
        for d in self.manager._Distribuidores:
            self.distribuidor_combo_filtro.addItem(d["nombre"], d["id"])

        self.distribuidor_combo_filtro.currentIndexChanged.connect(self.filter_products)
        filtros_layout.addWidget(QLabel("Distribuidor:"))
        filtros_layout.addWidget(self.distribuidor_combo_filtro)

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
        self.product_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.product_table.clicked.connect(self._on_table_clicked)
        self.product_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.product_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
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

        btn_delete_vend = QPushButton("Eliminar Vendedor")
        btn_delete_vend.setMinimumHeight(24)
        btn_delete_vend.setMaximumHeight(28)
        btn_delete_vend.setStyleSheet("font-size:11px;")
        btn_delete_vend.clicked.connect(self._eliminar_vendedor)
        vend_layout.addWidget(btn_delete_vend)

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

        btn_delete_dist = QPushButton("Eliminar Distribuidor")
        btn_delete_dist.setMinimumHeight(24)
        btn_delete_dist.setMaximumHeight(28)
        btn_delete_dist.setStyleSheet("font-size:11px;")
        btn_delete_dist.clicked.connect(self._eliminar_Distribuidor)
        dist_layout.addWidget(btn_delete_dist)

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
        self.clientes_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.clientes_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.clientes_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.clientes_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
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
        self.inventario_actual_table = QTableWidget(0, 9)
        self.inventario_actual_table.setHorizontalHeaderLabels([
            "Producto",
            "Código",
            "Cantidad",
            "Precio compra",
            "Código lote",
            "Registro sanitario",
            "Fecha compra",
            "Fecha vencimiento",
            "Distribuidor",  # <--- Cambia aquí
        ])
        self.inventario_actual_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.inventario_actual_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.inventario_actual_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.inventario_actual_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        inventario_actual_layout.addWidget(self.inventario_actual_table)

        inventario_actual_buttons = QHBoxLayout()
        inventario_actual_buttons.addStretch()
        self.btn_refresh_inventario = QPushButton("Actualizar")
        self.btn_view_lote = QPushButton("Ver información")
        self.btn_edit_lote = QPushButton("Editar lote")
        self.btn_delete_lote = QPushButton("Eliminar lote")
        inventario_actual_buttons.addWidget(self.btn_refresh_inventario)
        inventario_actual_buttons.addWidget(self.btn_view_lote)
        inventario_actual_buttons.addWidget(self.btn_edit_lote)
        inventario_actual_buttons.addWidget(self.btn_delete_lote)
        inventario_actual_layout.addLayout(inventario_actual_buttons)

        inventario_actual_tab.setLayout(inventario_actual_layout)

        # --- AGREGA LAS CUATRO PESTAÑAS AL QTabWidget ---
        self.tabs = QTabWidget()
        self.tabs.setMovable(True)
        tab_widget.setObjectName("Inventario")
        vend_dist_tab.setObjectName("Vendedores y Distribuidores")
        clientes_tab.setObjectName("Clientes")
        self.sales_tab.setObjectName("Ventas")
        self.compras_tab.setObjectName("Compras")
        inventario_actual_tab.setObjectName("Inventario actual")
        self.facturacion_tab = FacturacionTab(self.manager, self)
        self.facturacion_tab.setObjectName("Facturacion")

        self.tabs.addTab(tab_widget, "Inventario")
        self.tabs.addTab(vend_dist_tab, "Vendedores y Distribuidores")
        self.tabs.addTab(clientes_tab, "Clientes")
        self.tabs.addTab(self.sales_tab, "Ventas")
        self.tabs.addTab(self.compras_tab, "Compras")
        self.tabs.addTab(inventario_actual_tab, "Inventario actual")
        self.tabs.addTab(self.facturacion_tab, "Facturacion")
        self.setCentralWidget(self.tabs)

        # --- PESTAÑA DE TRABAJADORES ---
        trabajadores_tab = QWidget()
        trabajadores_tab.setObjectName("Trabajadores")
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
        self.trabajadores_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.trabajadores_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.trabajadores_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.trabajadores_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
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
        estado_tab.setObjectName("Estados de cuenta")
        estado_layout = QVBoxLayout()

        controles = QHBoxLayout()
        self.estado_tipo_combo = QComboBox()
        self.estado_tipo_combo.addItems(["Cliente", "Vendedor"])
        # Mostrar por defecto los vendedores al abrir la pestaña
        self.estado_tipo_combo.setCurrentIndex(1)
        self.estado_search_bar = QLineEdit()
        self.estado_search_bar.setPlaceholderText("Buscar por código o nombre...")
        self.estado_filtrar_fechas = QCheckBox("Filtrar por fechas")
        self.estado_quick_range = QComboBox()
        self.estado_quick_range.addItems(
            ["Personalizado", "Hoy", "Esta semana", "Este mes", "Este año"]
        )
        self.estado_fecha_inicio = QDateEdit(QDate.currentDate())
        self.estado_fecha_inicio.setCalendarPopup(True)
        self.estado_fecha_fin = QDateEdit(QDate.currentDate())
        self.estado_fecha_fin.setCalendarPopup(True)
        self.btn_generar_estado = QPushButton("Generar")
        controles.addWidget(self.estado_tipo_combo)
        controles.addWidget(self.estado_search_bar)
        controles.addWidget(self.estado_filtrar_fechas)
        controles.addWidget(self.estado_quick_range)
        controles.addWidget(QLabel("Desde"))
        controles.addWidget(self.estado_fecha_inicio)
        controles.addWidget(QLabel("Hasta"))
        controles.addWidget(self.estado_fecha_fin)
        controles.addWidget(self.btn_generar_estado)
        estado_layout.addLayout(controles)

        self.estado_table = QTableWidget(0, 6)
        self.estado_table.setHorizontalHeaderLabels([
            "Fecha",
            "Factura",
            "Tipo",
            "Cliente",
            "Vendedor",
            "Monto",
        ])
        self.estado_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.estado_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.estado_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.estado_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)


        estado_layout.addWidget(self.estado_table)

        estado_tab.setLayout(estado_layout)
        self.tabs.addTab(estado_tab, "Estados de cuenta")

        # Conexiones
        self.btn_add_trabajador.clicked.connect(self._agregar_trabajador)
        self.btn_edit_trabajador.clicked.connect(self._editar_trabajador)
        self.btn_delete_trabajador.clicked.connect(self._eliminar_trabajador)
        self.estado_tipo_combo.currentIndexChanged.connect(self._mostrar_historial_general)
        self.estado_search_bar.textChanged.connect(self._mostrar_historial_general)
        self.btn_generar_estado.clicked.connect(self._abrir_generar_estado_dialog)
        self.estado_filtrar_fechas.toggled.connect(self._toggle_estado_filtro_fechas)
        self.estado_filtrar_fechas.toggled.connect(self._mostrar_historial_general)
        self.estado_quick_range.currentIndexChanged.connect(
            self._apply_estado_quick_range
        )
        self.estado_quick_range.currentIndexChanged.connect(
            self._mostrar_historial_general
        )
        self.estado_fecha_inicio.dateChanged.connect(self._mostrar_historial_general)
        self.estado_fecha_fin.dateChanged.connect(self._mostrar_historial_general)

        self._actualizar_tabla_trabajadores()
        self._toggle_estado_filtro_fechas(False)
        self._mostrar_historial_general()

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
        self.btn_refresh_inventario.clicked.connect(self._actualizar_inventario_actual)
        self.btn_view_lote.clicked.connect(self._ver_informacion_lote)
        self.btn_edit_lote.clicked.connect(self._editar_lote_inventario_actual)
        self.btn_delete_lote.clicked.connect(self._eliminar_lote_inventario_actual)
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
        vendedor_id = self.vendedor_combo_filtro.currentData()

        Distribuidor_id = None
        if hasattr(self, "distribuidor_combo_filtro"):
            Distribuidor_id = self.distribuidor_combo_filtro.currentData()


        # Orden por stock
        stock_sort = None
        if hasattr(self, "stock_sort_combo"):
            stock_sort = self.stock_sort_combo.currentIndex()

        self.manager.filter_products(
            vendedor_id=vendedor_id,
            Distribuidor_id=Distribuidor_id,
            search=search,
        )
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
                data["nombre"], data["codigo"], data["sku"], None, None,
                data["precio_compra"], data["precio_venta_minorista"], data["precio_venta_mayorista"], 0
            )
            self._actualizar_arbol_vendedores()
            self._actualizar_arbol_Distribuidores()
            if hasattr(self, "vendedor_combo_filtro"):
                self.vendedor_combo_filtro.blockSignals(True)
                self.vendedor_combo_filtro.setCurrentIndex(0)
                self.vendedor_combo_filtro.blockSignals(False)

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
                data["nombre"], data["codigo"], data["sku"],
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
            self._actualizar_arbol_vendedores()
            self._actualizar_arbol_Distribuidores()
            self.filter_products()
            QMessageBox.information(self, "Producto eliminado", f"El producto '{prod['nombre']}' ha sido eliminado.")
        self.selected_row = None

    def registrar_venta(self):
        if not self._ensure_last_invoice_sent():
            return
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
                        "codigo_lote": d.get("codigo_lote", ""),
                        "registro_sanitario": d.get("registro_sanitario", ""),
                        "stock": d.get("cantidad", 0),
                        "precio_unitario": d.get("precio_unitario", 0),
                        "vendedor_id": prod.get("vendedor_id"),
                        "Distribuidor_id": compra.get("Distribuidor_id"),
                        "fecha_vencimiento": d.get("fecha_vencimiento", ""),
                        "precio_venta_minorista": prod.get("precio_venta_minorista", 0),
                        "precio_venta_mayorista": prod.get("precio_venta_mayorista", 0),
                    })
        Distribuidores = [v["nombre"] for v in self.manager._Distribuidores]
        vendedores_trabajadores = self.manager.db.get_trabajadores(solo_vendedores=True)
        dialog = RegisterSaleDialog(productos_lote, Distribuidores, vendedores_trabajadores, self)
        try:
            if dialog.exec_():
                data = dialog.get_data()
                items = data.get("items", [])
                if not items:
                    raise ValueError("Debe agregar al menos un producto a la venta.")
                total = data.get("total", 0)  # <-- Usa el total calculado por el diálogo
                fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                cliente_id = data["cliente"]["id"] if data.get("cliente") and "id" in data["cliente"] else None
                Distribuidor_nombre = dialog.Distribuidor_combo.currentText()
                Distribuidor = next((v for v in self.manager._Distribuidores if v["nombre"] == Distribuidor_nombre), None)
                Distribuidor_id = Distribuidor["id"] if Distribuidor else None
                vendedor_id = data.get("vendedor_id")
                estado = data.get("estado", "Pagada")
                extra = build_fiscal_extra(data)
                payment_extra = build_payment_condition_extra(data)
                if payment_extra:
                    extra.update(payment_extra)

                if data.get("venta_a_cuenta_de") or data.get("documento_venta_a_cuenta"):
                    extra["venta_a_cuenta_de"] = data.get("venta_a_cuenta_de", "")
                    extra["documento_venta_a_cuenta"] = data.get("documento_venta_a_cuenta", "")

                venta_id = self.manager.db.add_venta(
                    fecha,
                    total,
                    cliente_id=cliente_id,
                    Distribuidor_id=Distribuidor_id,
                    vendedor_id=vendedor_id,
                    extra=extra or None,
                    estado=estado,
                )
                # Agrega todos los productos de la venta
                for item in items:
                    prod = next((p for p in self.manager._products if p["id"] == item["producto_id"]), None)
                    if not prod:
                        continue
                    if prod["stock"] < item["cantidad"]:
                        raise ValueError(f"No hay suficiente stock para el producto {prod['nombre']}.")
                    extra_data = item.get("extra") or (
                        {"lote_id": item.get("lote_id"), "producto_id": item.get("producto_id"), "cantidad": item.get("cantidad")}
                        if item.get("lote_id") is not None
                        else None
                    )
                    self.manager.db.add_detalle_venta(
                        venta_id,
                        prod["id"],
                        item["cantidad"],
                        item["precio"],
                        item.get("descuento", 0),
                        item.get("descuento_tipo", ""),
                        item.get("iva", 0),
                        item.get("comision_monto", 0),
                        item.get("iva_tipo", ""),
                        item.get("tipo_fiscal", "Gravada"),
                        extra_data,
                        item.get("precio_con_iva", 0),
                        item.get("vendedor_id", vendedor_id)
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
                # Notify other tabs that the underlying data changed so they
                # can refresh immediately.
                self.data_changed.emit()

        except Exception as e:
            QMessageBox.critical(self, "Error al registrar venta", str(e))
            self._actualizar_historial()

    def registrar_compra(self):
        productos = [dict(p) for p in self.manager._products]
        Distribuidores = [dict(v) for v in self.manager._Distribuidores]
        proveedores = [dict(v) for v in self.manager.get_vendedores_compra()]
        dialog = RegisterPurchaseDialog(
            productos,
            Distribuidores,
            proveedores,
            self
        )
        try:
            result = dialog.exec_()
            if result == QDialog.Accepted:
                QMessageBox.information(self, "Compra", "Compra registrada correctamente.")
                self.manager.refresh_data()
                self.compras_tab.refresh_filters()
                self.compras_tab.load_purchases()
                self.sales_tab.load_sales()
                self.filter_products()
                self._actualizar_historial()
                self._actualizar_inventario_actual()
        except Exception as e:
            QMessageBox.critical(self, "Error al registrar compra", str(e))

    def registrar_venta_credito_fiscal(self):
        if not self._ensure_last_invoice_sent():
            return
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
                            "codigo_lote": d.get("codigo_lote", ""),
                            "registro_sanitario": d.get("registro_sanitario", ""),
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
            dialog = RegisterCreditoFiscalDialog(productos_lote, Distribuidores, vendedores_trabajadores, self)
            dialog.set_productos_data(productos_lote)
            if dialog.exec_():
                
                data = dialog.get_data()
                logger.debug("IVA calculado en get_data: %s", data.get("iva"))
                items = data.get("items", [])

                if not items:
                    raise ValueError("Debe agregar al menos un producto a la venta.")
                
                # --- CÁLCULOS FISCALES ---
                sumas = data.get("sumas", 0)
                descuentos = data.get("descuentos", 0)
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

                extra = build_fiscal_extra(data)
                payment_extra = build_payment_condition_extra(data)
                if payment_extra:
                    extra.update(payment_extra)

                if data.get("venta_a_cuenta_de") or data.get("documento_venta_a_cuenta"):
                    extra["venta_a_cuenta_de"] = data.get("venta_a_cuenta_de", "")
                    extra["documento_venta_a_cuenta"] = data.get("documento_venta_a_cuenta", "")

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
                    documento_venta_a_cuenta=data.get("documento_venta_a_cuenta", ""),
                    fecha_remision_anterior=data.get("fecha_remision_anterior", ""),
                    fecha_remision=data.get("fecha_remision", ""),
                    sumas=sumas,
                    descuentos=descuentos,
                    iva=iva,
                    subtotal=subtotal,
                    ventas_exentas=data.get("ventas_exentas", 0),
                    ventas_no_sujetas=data.get("ventas_no_sujetas", 0),
                    total_letras=total_letras,
                    extra=extra or None,
                )
                if not venta_id:
                    raise ValueError(
                        "No se pudo registrar la venta a cr\xE9dito fiscal."
                    )
                logger.debug("IVA guardado en la venta: %s", iva)

                for item in items:
                    prod = next((p for p in self.manager._products if p["id"] == item["producto_id"]), None)
                    if not prod:
                        continue
                    if prod["stock"] < item["cantidad"]:
                        raise ValueError(f"No hay suficiente stock para el producto {prod['nombre']}.")
                    extra_data = item.get("extra") or (
                        {"lote_id": item.get("lote_id"), "producto_id": item.get("producto_id"), "cantidad": item.get("cantidad")}
                        if item.get("lote_id") is not None
                        else None
                    )
                    self.manager.db.add_detalle_venta(
                        venta_id,
                        prod["id"],
                        item["cantidad"],
                        item["precio"],
                        item.get("descuento", 0),
                        item.get("descuento_tipo", ""),
                        item.get("iva", 0),
                        item.get("comision_monto", 0),
                        item.get("iva_tipo", ""),
                        item.get("tipo_fiscal", "Gravada"),
                        extra_data,
                        item.get("precio_con_iva", 0),
                        item.get("vendedor_id", vendedor_id)
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
                # Trigger refresh in other tabs immediately
                self.data_changed.emit()

        except Exception as e:
            QMessageBox.critical(self, "Error al registrar venta a crédito fiscal", str(e))

    def _post_guardado_exitoso(self, filename):
        self.ultimo_archivo_json = filename
        with open(LAST_INVENTORY_PATH, "w", encoding="utf-8") as f:
            json.dump({"ultimo": filename}, f)
        self._mark_saved()

    def _exportar_inventario(
        self,
        filename,
        *,
        titulo_dialogo,
        mensaje_exito,
        asincrono=True,
        mostrar_mensajes=True,
    ):
        tab_order = self.get_tab_order()
        if asincrono:
            thread = ExportThread(filename, tab_order)

            def on_finished():
                self._post_guardado_exitoso(filename)
                if mostrar_mensajes:
                    QMessageBox.information(
                        self,
                        titulo_dialogo,
                        mensaje_exito,
                    )

            def on_error(error):
                if mostrar_mensajes:
                    QMessageBox.critical(
                        self,
                        "Error",
                        f"No se pudo guardar el inventario:\n{error}",
                    )

            thread.finished.connect(on_finished)
            thread.error.connect(on_error)
            thread.start()
            self.export_thread = thread
            return thread

        try:
            manager = InventoryManager(DB(), enable_auto_backup=False)
            manager.exportar_inventario_json(filename, tab_order=tab_order)
        except Exception as exc:
            if mostrar_mensajes:
                QMessageBox.critical(
                    self,
                    "Error",
                    f"No se pudo guardar el inventario:\n{exc}",
                )
            return False

        self._post_guardado_exitoso(filename)
        if mostrar_mensajes:
            QMessageBox.information(
                self,
                titulo_dialogo,
                mensaje_exito,
            )
        return True

    def _cargar_inventario_desde_archivo(
        self,
        filename: str,
        *,
        titulo_dialogo: str,
        mensaje_exito: str,
    ) -> bool:
        try:
            data = self.manager.importar_inventario_json(filename)
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"No se pudo cargar el inventario:\n{exc}")
            self._actualizar_historial()
            return False

        if isinstance(data, dict) and data.get("tab_order"):
            self.set_tab_order(data["tab_order"])
        self.ultimo_archivo_json = filename
        try:
            with open(LAST_INVENTORY_PATH, "w", encoding="utf-8") as fh:
                json.dump({"ultimo": filename}, fh)
        except OSError as exc:
            logger.exception("No se pudo actualizar la ruta del último inventario: %s", exc)
        self.compras_tab.refresh_filters()
        self.filter_products()
        self.compras_tab.refresh_filters()
        self.compras_tab.load_purchases()
        self.sales_tab.load_sales()
        self._actualizar_tabla_clientes()
        self._mostrar_historial_general()
        self._actualizar_arbol_vendedores()
        self._actualizar_arbol_Distribuidores()
        self._actualizar_tabla_trabajadores()
        self._actualizar_inventario_actual()
        self._actualizar_historial()
        self._cargar_personas_estado()
        self._mark_saved()
        QMessageBox.information(self, titulo_dialogo, mensaje_exito)
        return True

    def guardar_como(self):
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Guardar inventario como",
            "",
            "Archivos JSON (*.json);;Todos los archivos (*)",
        )
        if not filename:
            return False

        self._exportar_inventario(
            filename,
            titulo_dialogo="Guardar como",
            mensaje_exito="Inventario guardado correctamente.",
        )
        return True

    def cargar_inventario(self):
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Cargar inventario",
            "",
            "Archivos JSON (*.json);;Todos los archivos (*)",
        )
        if filename:
            self._cargar_inventario_desde_archivo(
                filename,
                titulo_dialogo="Cargar inventario",
                mensaje_exito="Inventario cargado correctamente.",
            )

    def cargar_copia_seguridad(self):
        initial_dir = AUTO_BACKUP_DIR if os.path.isdir(AUTO_BACKUP_DIR) else ""
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Cargar copia de seguridad",
            initial_dir,
            "Archivos JSON (*.json);;Todos los archivos (*)",
        )
        if filename:
            self._cargar_inventario_desde_archivo(
                filename,
                titulo_dialogo="Cargar copia de seguridad",
                mensaje_exito="Copia de seguridad cargada correctamente.",
            )

    def firmar_dte_manual(self):
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar DTE",
            "",
            "Archivos JSON (*.json);;Todos los archivos (*)",
        )
        if not filename:
            return
        try:
            with open(filename, "r", encoding="utf-8") as fh:
                contenido = fh.read()
            token = sign_json(contenido)
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"No se pudo firmar el DTE:\n{exc}")
            return
        default_jws = os.path.splitext(filename)[0] + ".jws"
        save_path, _ = QFileDialog.getSaveFileName(
            self,
            "Guardar JWS",
            default_jws,
            "Archivos JWS (*.jws);;Todos los archivos (*)",
        )
        if not save_path:
            return
        try:
            with open(save_path, "w", encoding="utf-8") as fh:
                fh.write(token)
            QMessageBox.information(
                self,
                "Firmado",
                f"DTE firmado guardado en:\n{save_path}",
            )
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"No se pudo guardar el archivo:\n{exc}")

    def guardar_rapido(self, *, asincrono=True, mostrar_mensajes=True):
        filename = self.ultimo_archivo_json
        if not filename:
            filename, _ = QFileDialog.getSaveFileName(
                self,
                "Guardar inventario",
                "",
                "Archivos JSON (*.json);;Todos los archivos (*)",
            )
            if not filename:
                if mostrar_mensajes:
                    QMessageBox.warning(
                        self,
                        "Guardar rápido",
                        "Primero debes guardar o cargar un inventario manualmente.",
                    )
                return False

        resultado = self._exportar_inventario(
            filename,
            titulo_dialogo="Guardar rápido",
            mensaje_exito=f"Inventario guardado en:\n{filename}",
            asincrono=asincrono,
            mostrar_mensajes=mostrar_mensajes,
        )

        if asincrono:
            return resultado is not None
        return bool(resultado)

    def cargar_rapido(self):
        import os
        if self.ultimo_archivo_json and os.path.exists(self.ultimo_archivo_json):
            try:
                data = self.manager.importar_inventario_json(self.ultimo_archivo_json)
                if isinstance(data, dict) and data.get("tab_order"):
                    self.set_tab_order(data["tab_order"])
                self.compras_tab.refresh_filters()

                self.compras_tab.load_purchases()
                self.sales_tab.load_sales()

                self.filter_products()
                self._actualizar_tabla_clientes()  # <-- SOLO AGREGA ESTA LÍNEA
                self._mostrar_historial_general()
                self._mark_saved()
                QMessageBox.information(self, "Cargar rápido", f"Inventario cargado de:\n{self.ultimo_archivo_json}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"No se pudo cargar el inventario:\n{e}")
        else:
            QMessageBox.warning(self, "Cargar rápido", "No hay un inventario guardado previamente para cargar.")

    def cerrar_sesion(self):
        reply = QMessageBox.question(
            self,
            "Cerrar sesión",
            "¿Desea cerrar la sesión actual?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        # Al confirmar, mostrar nuevamente el diálogo de selección de usuario
        from PyQt5.QtWidgets import QApplication, QLineEdit
        from user_picker_dialog import UserPickerDialog
        from db import DB

        app = QApplication.instance()

        # Cerrar la ventana actual antes de abrir el selector de usuarios
        self.close()

        db = DB()
        users = [
            {"id": u["id"], "name": u["username"], "subtitle": u.get("role", "")}
            for u in db.get_users()
        ]
        dlg = UserPickerDialog(users, multi_select=False, parent=None)
        if dlg.exec_() != QDialog.Accepted:
            app.quit()
            return

        selected = dlg.selected_user_ids()
        if not selected:
            app.quit()
            return

        user_id = selected if not isinstance(selected, list) else selected[0]
        user = db.get_user(user_id)
        if not user:
            app.quit()
            return

        if user["username"] != "invitado":
            while True:
                password, ok = QInputDialog.getText(
                    None,
                    "Contraseña",
                    f"Ingrese la contraseña para {user['username']}",
                    QLineEdit.Password,
                )
                if not ok:
                    app.quit()
                    return
                if db.authenticate(user["username"], password):
                    break
                QMessageBox.warning(None, "Error", "Contraseña incorrecta")

        # Abrir una nueva ventana principal para el usuario seleccionado
        nueva_ventana = MainWindow(user)
        nueva_ventana.show()
        # Mantener referencia para evitar que se recolecte
        self._next_window = nueva_ventana

    def nuevo_inventario(self):
        reply = QMessageBox.question(
            self,
            "Nuevo inventario",
            "¿Estás seguro de que quieres borrar todo el inventario actual? Esta acción no se puede deshacer.",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            try:
                self.manager.db.limpiar_inventario()
            except Exception as exc:
                QMessageBox.warning(
                    self,
                    "Nuevo inventario",
                    f"No se pudo limpiar la base de datos: {exc}",
                )
                return
            self.manager.db.limpiar_productos()
            self.manager.db.limpiar_vendedores()
            self.manager.db.limpiar_Distribuidores()
            # Reset last loaded inventory so old data is not reimported
            self.ultimo_archivo_json = None
            try:
                if os.path.exists(LAST_INVENTORY_PATH):
                    os.remove(LAST_INVENTORY_PATH)
            except OSError:
                pass
            self.manager.refresh_data()
            self.compras_tab.refresh_filters()

            self.compras_tab.load_purchases()

            self.sales_tab.load_sales()  # <-- AGREGA ESTA LÍNEA

            self._actualizar_tabla_trabajadores()  # <-- AGREGA ESTA LÍNEA
            self.filter_products()
            self._actualizar_arbol_vendedores()
            self._actualizar_arbol_Distribuidores()
            self._actualizar_tabla_clientes()
            self._mostrar_historial_general()
            self._actualizar_historial()
            self._cargar_personas_estado()
            if hasattr(self, "vendedor_combo_filtro"):
                self.vendedor_combo_filtro.setCurrentIndex(0)
            if hasattr(self, "distribuidor_combo_filtro"):
                self.distribuidor_combo_filtro.setCurrentIndex(0)
            self._actualizar_inventario_actual()
            QMessageBox.information(self, "Nuevo inventario", "Inventario limpio y listo para usar.")

    def _actualizar_arbol_vendedores(self):
        self.vendedores_tree.clear()
        for vend in self.manager.get_vendedores_compra():
            text = f"{vend.get('codigo', '')} - {vend['nombre']}"
            vend_item = QTreeWidgetItem([text])
            vend_item.setData(0, Qt.UserRole, vend.get("id"))
            self.vendedores_tree.addTopLevelItem(vend_item)
            vend_item.setExpanded(False)

    def _actualizar_arbol_Distribuidores(self):
        self.Distribuidores_tree.clear()
        for dist in self.manager._Distribuidores:
            dist_item = QTreeWidgetItem([dist["nombre"]])
            dist_item.setData(0, Qt.UserRole, dist.get("id"))
            vendedores = [
                v
                for v in self.manager.get_vendedores_compra()
                if v.get("Distribuidor_id") == dist["id"]
            ]
            for vend in vendedores:
                text = f"{vend.get('codigo', '')} - {vend['nombre']}"
                vend_item = QTreeWidgetItem([text])
                vend_item.setData(0, Qt.UserRole, vend.get("id"))
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
                descripcion=data["descripcion"],
                Distribuidor_id=data["Distribuidor_id"],
                codigo=data["codigo"],
                dui=data["dui"],

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
        item = selected_items[0]
        vendedor_id = item.data(0, Qt.UserRole)
        vendedor = next(
            (
                c
                for c in self.manager.get_vendedores_compra()
                if c["id"] == vendedor_id
            ),
            None,
        )
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
                data["Distribuidor_id"],
                dui=data["dui"],

            )
            self.manager.refresh_data()
            self.compras_tab.refresh_filters()
            self._actualizar_arbol_vendedores()
            QMessageBox.information(self, "Vendedor", "Vendedor editado correctamente.")

    def _eliminar_vendedor(self):
        selected_items = self.vendedores_tree.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "Eliminar vendedor", "Seleccione un vendedor para eliminar.")
            return
        item = selected_items[0]
        vendedor_id = item.data(0, Qt.UserRole)
        confirm = QMessageBox.question(
            self,
            "Eliminar",
            f"¿Eliminar vendedor '{item.text(0)}'?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm == QMessageBox.Yes:
            try:
                self.manager.db.delete_vendedor(vendedor_id)
            except ValueError:
                QMessageBox.warning(
                    self,
                    "Eliminar vendedor",
                    "El vendedor tiene registros asociados y no puede eliminarse.",
                )
                return
            self.manager.refresh_data()
            self.compras_tab.refresh_filters()
            self._actualizar_arbol_vendedores()
            self._actualizar_arbol_Distribuidores()
            QMessageBox.information(
                self,
                "Vendedor eliminado",
                f"El vendedor '{item.text(0)}' ha sido eliminado.",
            )

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
        item = selected_items[0]
        # Asegurarse de que sea un Distribuidor (no un vendedor hijo)
        if item.parent() is not None:
            QMessageBox.warning(self, "Editar Distribuidor", "Seleccione un Distribuidor para editar.")
            return
        dist_id = item.data(0, Qt.UserRole)
        # Busca el Distribuidor en la base de datos
        Distribuidor = next((v for v in self.manager._Distribuidores if v["id"] == dist_id), None)
        if not Distribuidor:
            QMessageBox.warning(self, "Editar Distribuidor", "No se encontró el Distribuidor seleccionado.")
            return
        dialog = DistribuidorDialog(self, Distribuidor=Distribuidor)
        if dialog.exec_():
            data = dialog.get_data()
            # Actualiza el Distribuidor en la base de datos
            self.manager.db.cursor.execute("""
                UPDATE Distribuidores SET
                    codigo=?, nombre=?, telefono=?, email=?, cargo=?, sucursal=?,
                    fecha_inicio=?, direccion=?, departamento=?, municipio=?,
                    tipo_contrato=?, comisiones_especificas=?, metodo_pago=?, nit=?, nrc=?,
                    cuenta_bancaria=?, notas=?
                WHERE id=?
            """, (
                data.get("codigo", ""),
                data.get("nombre", ""),
                data.get("telefono", ""),
                data.get("email", ""),
                data.get("cargo", ""),
                data.get("sucursal", ""),
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
        item = selected_items[0]
        if item.parent() is not None:
            QMessageBox.information(self, "Información de Distribuidor", "Seleccione un Distribuidor para ver su información.")
            return
        dist_id = item.data(0, Qt.UserRole)
        Distribuidor = next((v for v in self.manager._Distribuidores if v["id"] == dist_id), None)
        if not Distribuidor:
            QMessageBox.warning(self, "Información de Distribuidor", "No se encontró el Distribuidor seleccionado.")
            return

        dialog = DistribuidorInfoDialog(Distribuidor, self)
        dialog.exec_()

    def _eliminar_Distribuidor(self):
        selected_items = self.Distribuidores_tree.selectedItems()
        if not selected_items:
            QMessageBox.warning(
                self, "Eliminar Distribuidor", "Seleccione un Distribuidor para eliminar."
            )
            return
        item = selected_items[0]
        if item.parent() is not None:
            QMessageBox.warning(
                self, "Eliminar Distribuidor", "Seleccione un Distribuidor para eliminar."
            )
            return
        dist_id = item.data(0, Qt.UserRole)
        confirm = QMessageBox.question(
            self,
            "Eliminar Distribuidor",
            f"¿Eliminar Distribuidor '{item.text(0)}'?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            self.manager.db.delete_Distribuidor(dist_id)
        except ValueError:
            QMessageBox.warning(
                self,
                "Eliminar Distribuidor",
                "No se puede eliminar el Distribuidor porque tiene registros asociados.",
            )
            return
        self.manager.refresh_data()
        self.compras_tab.refresh_filters()
        self._actualizar_arbol_Distribuidores()
        self._actualizar_arbol_vendedores()
        QMessageBox.information(
            self, "Distribuidor", "Distribuidor eliminado correctamente."
        )

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
            try:
                self.manager.add_cliente(
                    data["nombre"],
                    data["nrc"],
                    data["nit"],
                    data["dui"],
                    data["giro"],
                    data["codActividad"],
                    data["telefono"],
                    data["email"],
                    data["direccion"],
                    data["departamento"],
                    data["municipio"],
                    data["codigo"],
                    nombreComercial=data["nombreComercial"],
                    tipoContribuyente=data["tipoContribuyente"],
                    razonSocial=data["razonSocial"],
                )
            except ValueError as e:
                QMessageBox.warning(dialog, "Cliente", str(e))
                return
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
            try:
                self.manager.update_cliente(
                    cli["id"],
                    data["codigo"],
                    data["nombre"],
                    data["nrc"],
                    data["nit"],
                    data["dui"],
                    data["giro"],
                    data["telefono"],
                    data["email"],
                    data["direccion"],
                    data["departamento"],
                    data["municipio"],
                    codActividad=data["codActividad"],
                    nombreComercial=data["nombreComercial"],
                    tipoContribuyente=data["tipoContribuyente"],
                    razonSocial=data["razonSocial"],
                )
            except ValueError as e:
                QMessageBox.warning(dialog, "Cliente", str(e))
                return
            self._actualizar_tabla_clientes()
            QMessageBox.information(self, "Cliente", "Cliente editado correctamente.")

    def _eliminar_cliente(self):
        cli = self._get_selected_cliente()
        if not cli:
            QMessageBox.warning(self, "Eliminar cliente", "Seleccione un cliente para eliminar.")
            return
        confirm = QMessageBox.question(self, "Eliminar", f"¿Eliminar cliente '{cli['nombre']}'?", QMessageBox.Yes | QMessageBox.No)
        if confirm == QMessageBox.Yes:
            self.manager.delete_cliente(cli["id"])
            self._actualizar_tabla_clientes()
            QMessageBox.information(self, "Cliente eliminado", f"El cliente '{cli['nombre']}' ha sido eliminado.")

    def _actualizar_historial(self):
        """Recarga la tabla de historial."""
        self._mostrar_historial_general()
            

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
        catalogs = getattr(self.manager, "catalogs", None)
        compras = self.manager.db.get_compras()
        if catalogs and catalogs.products:
            productos_dict = catalogs.products
        else:
            productos_dict = {p["id"]: p for p in self.manager.db.get_productos()}
        for compra in compras:
            compra_id = compra["id"]
            detalles_compra = self.manager.db.get_detalles_compra(compra_id)
            _, distribuidor_nombre = resolve_party_names(compra, catalogs)
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
                    "codigo_lote": d.get("codigo_lote") or "",
                    "registro_sanitario": d.get("registro_sanitario") or "",
                    "fecha_compra": compra.get("fecha", ""),
                    "fecha_vencimiento": fecha_vencimiento,
                    "Distribuidor": distribuidor_nombre,
                    "detalle_id": d.get("id"),
                    "producto_id": d.get("producto_id"),
                    "compra_id": compra_id,
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
            item_producto = QTableWidgetItem(d["producto"])
            item_producto.setData(Qt.UserRole, d)
            self.inventario_actual_table.setItem(row, 0, item_producto)
            self.inventario_actual_table.setItem(row, 1, QTableWidgetItem(d["codigo"]))
            item_cantidad = QTableWidgetItem(str(d["cantidad"]))
            stock = d.get("cantidad", 0)
            if stock < 5:
                item_cantidad.setBackground(QColor("red"))
            elif stock < 10:
                item_cantidad.setBackground(QColor("orange"))
            elif stock < 25:
                item_cantidad.setBackground(QColor("yellow"))
            else:
                item_cantidad.setBackground(QColor("lightgreen"))
            self.inventario_actual_table.setItem(row, 2, item_cantidad)
            self.inventario_actual_table.setItem(row, 3, QTableWidgetItem(f"${d['precio_compra']:.2f}"))
            self.inventario_actual_table.setItem(row, 4, QTableWidgetItem(d["codigo_lote"]))
            self.inventario_actual_table.setItem(row, 5, QTableWidgetItem(d["registro_sanitario"]))
            self.inventario_actual_table.setItem(row, 6, QTableWidgetItem(d["fecha_compra"]))
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
                        item_venc.setBackground(QColor("lightgreen"))
                        item_venc.setForeground(QColor("black"))
                except Exception:
                    pass
            self.inventario_actual_table.setItem(row, 7, item_venc)
            self.inventario_actual_table.setItem(row, 8, QTableWidgetItem(d["Distribuidor"]))

    def _confirm_inventory_conflict(self, target: str) -> bool:
        message = (
            f"Editar o eliminar {target} puede causar conflictos en el inventario, "
            "proceda solo si está seguro de que no causará conflictos con sus cambios."
        )
        result = QMessageBox.warning(
            self,
            "Advertencia",
            message,
            QMessageBox.Ok | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        return result == QMessageBox.Ok

    def _editar_lote_inventario_actual(self):
        row = self.inventario_actual_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Editar lote", "Seleccione un lote para editar.")
            return

        item_producto = self.inventario_actual_table.item(row, 0)
        if not item_producto:
            QMessageBox.warning(self, "Editar lote", "No se pudo obtener la información del lote seleccionado.")
            return

        data = item_producto.data(Qt.UserRole) or {}
        detalle_id = data.get("detalle_id")

        if not detalle_id:
            QMessageBox.warning(self, "Editar lote", "No se encontró el identificador del lote seleccionado.")
            return

        cantidad_actual = int(data.get("cantidad", 0) or 0)
        producto = data.get("producto", "")
        codigo = data.get("codigo", "")

        if not self._confirm_inventory_conflict("este lote"):
            return

        dialog = EditarLoteDialog(
            self,
            producto=producto,
            codigo=codigo,
            cantidad=cantidad_actual,
            codigo_lote=data.get("codigo_lote") or "",
            registro_sanitario=data.get("registro_sanitario") or "",
            fecha_vencimiento=data.get("fecha_vencimiento") or "",
        )

        if dialog.exec_() != QDialog.Accepted:
            return

        (
            nueva_cantidad,
            nuevo_codigo_lote,
            nuevo_registro_sanitario,
            nueva_fecha_vencimiento,
        ) = dialog.get_values()

        cambios: dict[str, object] = {}
        if nueva_cantidad != cantidad_actual:
            cambios["cantidad"] = nueva_cantidad

        codigo_lote_actual = data.get("codigo_lote") or ""
        if nuevo_codigo_lote != codigo_lote_actual:
            cambios["codigo_lote"] = nuevo_codigo_lote

        registro_sanitario_actual = data.get("registro_sanitario") or ""
        if nuevo_registro_sanitario != registro_sanitario_actual:
            cambios["registro_sanitario"] = nuevo_registro_sanitario

        fecha_actual = data.get("fecha_vencimiento") or ""
        if nueva_fecha_vencimiento != fecha_actual:
            cambios["fecha_vencimiento"] = nueva_fecha_vencimiento

        if not cambios:
            return

        try:
            self.manager.update_detalle_compra(detalle_id, **cambios)
        except ValueError as exc:
            QMessageBox.warning(self, "Editar lote", str(exc))
            return
        except Exception as exc:  # pragma: no cover - logging unexpected errors
            logger.exception("Error al actualizar el lote: %s", exc)
            QMessageBox.critical(
                self,
                "Editar lote",
                "Ocurrió un error al actualizar el lote.",
            )
            return

        QMessageBox.information(
            self,
            "Editar lote",
            "El lote se actualizó correctamente.",
        )

        self._actualizar_inventario_actual()
        self.filter_products()
        self.data_changed.emit()

    def _ver_informacion_lote(self):
        row = self.inventario_actual_table.currentRow()
        logger.info(
            "Inventario actual: solicitando detalle de lote en fila %s", row
        )
        if row < 0:
            QMessageBox.warning(
                self,
                "Ver información",
                "Seleccione un lote para consultar su información.",
            )
            return

        item_producto = self.inventario_actual_table.item(row, 0)
        if not item_producto:
            logger.warning(
                "Inventario actual: la fila %s no tiene item asociado", row
            )
            QMessageBox.warning(
                self,
                "Ver información",
                "No se pudo obtener la información del lote seleccionado.",
            )
            return

        data = item_producto.data(Qt.UserRole) or {}
        compra_id = data.get("compra_id")
        logger.info(
            "Inventario actual: lote con datos %s -> compra asociada %s",
            {k: data.get(k) for k in ("producto", "codigo", "detalle_id")},
            compra_id,
        )
        if not compra_id:
            QMessageBox.warning(
                self,
                "Ver información",
                "El lote seleccionado no tiene una compra asociada.",
            )
            return

        compra = self.manager.db.get_compra(compra_id)
        if compra:
            logger.info(
                "Inventario actual: compra %s recuperada desde base de datos",
                compra_id,
            )
        else:
            logger.warning(
                "Inventario actual: no se pudo recuperar la compra %s", compra_id
            )
        if not compra:
            QMessageBox.warning(
                self,
                "Ver información",
                "No fue posible cargar la compra asociada al lote seleccionado.",
            )
            return

        detalles = self.manager.db.get_detalles_compra(compra_id)
        logger.info(
            "Inventario actual: compra %s tiene %s partidas", compra_id, len(detalles)
        )
        catalogs = getattr(self.manager, "catalogs", None)
        dialog = CompraDetalleDialog(compra, detalles, self, catalogs=catalogs)
        dialog.exec_()

    def _eliminar_lote_inventario_actual(self):
        row = self.inventario_actual_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Eliminar lote", "Seleccione un lote para eliminar.")
            return

        item_producto = self.inventario_actual_table.item(row, 0)
        if not item_producto:
            QMessageBox.warning(
                self,
                "Eliminar lote",
                "No se pudo obtener la información del lote seleccionado.",
            )
            return

        data = item_producto.data(Qt.UserRole) or {}
        detalle_id = data.get("detalle_id")
        if not detalle_id:
            QMessageBox.warning(
                self,
                "Eliminar lote",
                "No se encontró el identificador del lote seleccionado.",
            )
            return

        producto = data.get("producto", "")
        codigo = data.get("codigo", "")
        cantidad = data.get("cantidad", 0)

        if not self._confirm_inventory_conflict("este lote"):
            return

        confirm = QMessageBox.question(
            self,
            "Eliminar lote",
            f"¿Eliminar el lote de {producto} (código {codigo}) con {cantidad} unidades?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        try:
            self.manager.delete_detalle_compra(detalle_id)
        except ValueError as exc:
            QMessageBox.warning(self, "Eliminar lote", str(exc))
            return
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.exception("Error al eliminar el lote %s", detalle_id)
            QMessageBox.critical(
                self,
                "Eliminar lote",
                "Ocurrió un error al eliminar el lote seleccionado.",
            )
            return

        QMessageBox.information(
            self,
            "Eliminar lote",
            "El lote se eliminó correctamente del inventario.",
        )

        self._actualizar_inventario_actual()
        if hasattr(self, "compras_tab") and hasattr(self.compras_tab, "load_purchases"):
            try:
                self.compras_tab.load_purchases()
            except Exception:  # pragma: no cover - keep UI responsive
                logger.exception("No se pudo refrescar la pestaña de compras tras eliminar el lote")
        self.filter_products()
        self.data_changed.emit()

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
        datos_path = DATOS_NEGOCIO_PATH
        datos = {}
        if os.path.exists(datos_path):
            try:
                with open(datos_path, "r", encoding="utf-8") as f:
                    datos = json.load(f)
                    dir_info = datos.get("direccion") or {}
                    dir_info.setdefault("departamento", "")
                    dir_info.setdefault("municipio", "")
                    datos["direccion"] = dir_info
            except Exception:
                datos = {}
        from dialogs import DatosNegocioDialog
        dlg = DatosNegocioDialog(datos, self)
        if dlg.exec_():
            datos_nuevos = dlg.get_data()
            datos.update(datos_nuevos)
            dir_info = datos.get("direccion") or {}
            dir_info.setdefault("departamento", "")
            dir_info.setdefault("municipio", "")
            datos["direccion"] = dir_info
            with open(datos_path, "w", encoding="utf-8") as f:
                json.dump(datos, f, ensure_ascii=False, indent=2)
            QMessageBox.information(self, "Datos del negocio", "Datos guardados correctamente.")

    def _abrir_config_correo(self):
        import os, json
        datos_path = DATOS_NEGOCIO_PATH
        datos = {}
        if os.path.exists(datos_path):
            try:
                with open(datos_path, "r", encoding="utf-8") as f:
                    datos = json.load(f)
            except Exception:
                datos = {}
        from dialogs import EmailConfigDialog
        dlg = EmailConfigDialog(datos, self)
        if dlg.exec_():
            datos.update(dlg.get_data())
            with open(datos_path, "w", encoding="utf-8") as f:
                json.dump(datos, f, ensure_ascii=False, indent=2)
            QMessageBox.information(self, "Configuración de correo", "Datos guardados correctamente.")

    def _abrir_config_facturacion(self):
        import os, json
        datos_path = DATOS_NEGOCIO_PATH
        config_path = CONFIG_NEGOCIO_PATH
        datos = {}
        config = {}
        if os.path.exists(datos_path):
            try:
                with open(datos_path, "r", encoding="utf-8") as f:
                    datos = json.load(f)
            except Exception:
                datos = {}
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
            except Exception:
                config = {}
        from dialogs import DTEConfigDialog
        dte_api = datos.get("dte_api", {})
        ambiente = config.get("ambiente", "pruebas")
        env_conf = config.get(ambiente, {})
        fe_config = env_conf.get("firma_electronica", {})

        dialog_kwargs = {}
        try:
            import inspect

            params = inspect.signature(DTEConfigDialog.__init__).parameters
            if "db" in params:
                dialog_kwargs["db"] = self.manager.db
        except (AttributeError, ValueError, TypeError):  # pragma: no cover - defensive
            pass

        dlg = DTEConfigDialog(
            dte_api,
            fe_config,
            env_conf,
            self,
            datos_negocio=datos,
            **dialog_kwargs,
        )
        if dlg.exec_():
            new_dte_api, new_fe, new_urls = dlg.get_data()
            negocio_updates = getattr(dlg, "get_negocio_updates", lambda: {})()
            if isinstance(negocio_updates, Mapping):
                datos.update(negocio_updates)
            ambiente = new_dte_api["ambiente"]
            datos["dte_api"] = new_dte_api
            config["ambiente"] = ambiente
            config.setdefault(ambiente, {})
            config[ambiente]["firma_electronica"] = new_fe
            config[ambiente]["auth_url"] = new_urls.get("auth_url", "")
            config[ambiente]["recepcion_url"] = new_urls.get("recepcion_url", "")
            if "auth" in new_urls:
                config[ambiente]["auth"] = new_urls["auth"]
            with open(datos_path, "w", encoding="utf-8") as f:
                json.dump(datos, f, ensure_ascii=False, indent=2)
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            invalidate_token_cache()
            QMessageBox.information(self, "Facturación electrónica", "Datos guardados correctamente.")

    def _abrir_config_usuarios(self):
        dlg = UserConfigDialog(self.manager.db, self)
        dlg.exec_()

    def _actualizar_tabla_trabajadores(self):
        solo_vendedores = self.trabajadores_filtro_vendedor.isChecked()
        area = self.trabajadores_filtro_area.text()
        trabajadores = self.manager.db.get_trabajadores(
            solo_vendedores=solo_vendedores, area=area
        )
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
        confirm = QMessageBox.question(
            self,
            "Eliminar",
            f"¿Eliminar trabajador '{t['nombre']}'?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm == QMessageBox.Yes:
            count = self.manager.db.cursor.execute(
                "SELECT COUNT(*) FROM ventas WHERE vendedor_id=?",
                (t["id"],),
            ).fetchone()[0]
            if count > 0:
                QMessageBox.warning(
                    self,
                    "Eliminar trabajador",
                    "El trabajador tiene ventas asociadas y no puede eliminarse.",
                )
                return
            try:
                self.manager.db.delete_trabajador(t["id"])
            except ValueError:
                QMessageBox.warning(
                    self,
                    "Eliminar trabajador",
                    "El trabajador tiene ventas asociadas y no puede eliminarse.",
                )
                return
            self._actualizar_tabla_trabajadores()
            QMessageBox.information(
                self,
                "Trabajador eliminado",
                f"El trabajador '{t['nombre']}' ha sido eliminado.",
            )


    def _toggle_estado_filtro_fechas(self, checked: bool):
        self.estado_quick_range.setEnabled(checked)
        custom = self.estado_quick_range.currentIndex() == 0
        self.estado_fecha_inicio.setEnabled(checked and custom)
        self.estado_fecha_fin.setEnabled(checked and custom)
        if checked:
            self._apply_estado_quick_range()

    def _apply_estado_quick_range(self):
        if not self.estado_filtrar_fechas.isChecked():
            return
        option = self.estado_quick_range.currentText()
        today = date.today()
        if option == "Hoy":
            self.estado_fecha_inicio.setDate(QDate(today))
            self.estado_fecha_fin.setDate(QDate(today))
            self.estado_fecha_inicio.setEnabled(False)
            self.estado_fecha_fin.setEnabled(False)
        elif option == "Esta semana":
            start = today - timedelta(days=today.weekday())
            end = start + timedelta(days=6)
            self.estado_fecha_inicio.setDate(QDate(start))
            self.estado_fecha_fin.setDate(QDate(end))
            self.estado_fecha_inicio.setEnabled(False)
            self.estado_fecha_fin.setEnabled(False)
        elif option == "Este mes":
            start = today.replace(day=1)
            if today.month == 12:
                end = date(today.year, 12, 31)
            else:
                end = date(today.year, today.month + 1, 1) - timedelta(days=1)
            self.estado_fecha_inicio.setDate(QDate(start))
            self.estado_fecha_fin.setDate(QDate(end))
            self.estado_fecha_inicio.setEnabled(False)
            self.estado_fecha_fin.setEnabled(False)
        elif option == "Este año":
            start = date(today.year, 1, 1)
            end = date(today.year, 12, 31)
            self.estado_fecha_inicio.setDate(QDate(start))
            self.estado_fecha_fin.setDate(QDate(end))
            self.estado_fecha_inicio.setEnabled(False)
            self.estado_fecha_fin.setEnabled(False)
        else:
            self.estado_fecha_inicio.setEnabled(True)
            self.estado_fecha_fin.setEnabled(True)

    def _abrir_generar_estado_dialog(self):
        """Abre la ventana de generación de estados de cuenta."""
        dialog = EstadoCuentaDialog(self.manager.db, self)
        tipo_idx = 0 if self.estado_tipo_combo.currentText() == "Cliente" else 1
        dialog.modo_combo.setCurrentIndex(tipo_idx)
        dialog.stack.setCurrentIndex(tipo_idx)
        if self.estado_filtrar_fechas.isChecked():
            dialog.filtrar_fechas_chk.setChecked(True)
            range_text = self.estado_quick_range.currentText()
            idx = dialog.quick_range.findText(range_text)
            if idx >= 0:
                dialog.quick_range.setCurrentIndex(idx)
            if idx == 0:
                dialog.fecha_inicio.setDate(self.estado_fecha_inicio.date())
                dialog.fecha_fin.setDate(self.estado_fecha_fin.date())
        else:
            dialog.filtrar_fechas_chk.setChecked(False)
        dialog.exec_()

    def _imprimir_estado_cuenta(self):
        dialog = EstadoCuentaDialog(self.manager.db, self)
        dialog.modo_combo.setCurrentIndex(1)
        dialog.stack.setCurrentIndex(1)
        if self.estado_filtrar_fechas.isChecked():
            dialog.filtrar_fechas_chk.setChecked(True)
            range_text = self.estado_quick_range.currentText()
            idx = dialog.quick_range.findText(range_text)
            if idx >= 0:
                dialog.quick_range.setCurrentIndex(idx)
            if idx == 0:
                dialog.fecha_inicio.setDate(self.estado_fecha_inicio.date())
                dialog.fecha_fin.setDate(self.estado_fecha_fin.date())
        else:
            dialog.filtrar_fechas_chk.setChecked(False)
        dialog.exec_()


    def _mostrar_historial_general(self):
        """Muestra el historial completo filtrando por cliente o vendedor."""
        tipo = "cliente" if self.estado_tipo_combo.currentText() == "Cliente" else "vendedor"

        if self.estado_filtrar_fechas.isChecked():
            inicio = self.estado_fecha_inicio.date().toPyDate()
            fin = self.estado_fecha_fin.date().toPyDate()
        else:
            inicio = None
            fin = None

        filtro = self.estado_search_bar.text().lower()
        ventas = self.manager.db.get_ventas()
        rows = []
        for v in ventas:
            fecha_str = v.get("fecha", "")
            try:
                fdate = datetime.strptime(fecha_str, "%Y-%m-%d %H:%M:%S").date()
            except ValueError:
                try:
                    fdate = datetime.strptime(fecha_str, "%Y-%m-%d").date()
                except ValueError:
                    fdate = None
            if inicio and fdate and fdate < inicio:
                continue
            if fin and fdate and fdate > fin:
                continue

            if tipo == "cliente" and not v.get("cliente_id"):
                continue
            if tipo == "vendedor" and not v.get("vendedor_id"):
                continue

            cli_nombre = ""
            vend_nombre = ""
            codigo = ""
            if v.get("cliente_id"):
                cli = self.manager.db.get_cliente(v["cliente_id"])
                if cli:
                    cli_nombre = cli.get("nombre", "")
                    codigo = cli.get("codigo", "")
            if v.get("vendedor_id"):
                trab = self.manager.db.get_trabajador(v["vendedor_id"])
                if trab:
                    vend_nombre = trab.get("nombre", "")
                    if tipo == "vendedor":
                        codigo = trab.get("codigo", "")

            if filtro and filtro not in cli_nombre.lower() and filtro not in vend_nombre.lower() and filtro not in codigo.lower():
                continue

            tipo_factura = "Crédito fiscal" if self.manager.db.get_venta_credito_fiscal(v.get("id")) else "Consumidor final"
            rows.append((fecha_str, v.get("id"), tipo_factura, cli_nombre, vend_nombre, v.get("total", 0)))

        self.estado_table.setColumnCount(6)
        self.estado_table.setHorizontalHeaderLabels([
            "Fecha",
            "Factura",
            "Tipo",
            "Cliente",
            "Vendedor",
            "Monto",
        ])
        self.estado_table.setRowCount(len(rows))
        for row, (fecha, fid, tipo, cli, vend, monto) in enumerate(rows):
            self.estado_table.setItem(row, 0, QTableWidgetItem(fecha))
            self.estado_table.setItem(row, 1, QTableWidgetItem(str(fid)))
            self.estado_table.setItem(row, 2, QTableWidgetItem(tipo))
            self.estado_table.setItem(row, 3, QTableWidgetItem(cli))
            self.estado_table.setItem(row, 4, QTableWidgetItem(vend))
            self.estado_table.setItem(row, 5, QTableWidgetItem(f"${float(monto):.2f}"))

    def _cargar_personas_estado(self):
        """Carga datos para la pestaña de estados de cuenta."""
        self._clientes_estado = self.manager.db.get_clientes()
        self._vendedores_estado = self.manager.db.get_trabajadores(solo_vendedores=True)
        self.estado_search_bar.clear()
        self._mostrar_historial_general()

    def get_tab_order(self):
        return [self.tabs.tabText(i) for i in range(self.tabs.count())]

    def set_tab_order(self, order):
        for desired_index, title in enumerate(order):
            index = self._find_tab_index(title)
            if index != -1 and index != desired_index:
                self.tabs.tabBar().moveTab(index, desired_index)

    def _find_tab_index(self, title):
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i) == title:
                return i
        return -1

    # DEBUG: Método temporal para pruebas de Venta vs DTE
    def _debug_venta_vs_dte(self):  # pragma: no cover - debug helper
        """Compara cálculos de una venta con su DTE correspondiente."""
        row = self.sales_tab.sales_table.currentRow()
        venta_id = None
        if row >= 0:
            item = self.sales_tab.sales_table.item(row, 0)
            if item is not None:
                try:
                    venta_id = int(item.text())
                except ValueError:
                    venta_id = None
        else:
            text = self.sales_tab.search_bar.text().strip()
            if text.isdigit():
                venta_id = int(text)

        if venta_id is None:
            QMessageBox.warning(
                self,
                "Debug Venta vs DTE",
                "Seleccione una venta o ingrese un ID válido en el campo de búsqueda.",
            )
            return

        try:
            from utils.doc_generation import log_venta_vs_dte

            log_venta_vs_dte(self.manager, venta_id)

            db_path = self.manager.db.conn.execute("PRAGMA database_list").fetchone()[2]
            script = os.path.join(
                os.path.dirname(__file__), "tools", "venta_vs_dte_debug.py"
            )
            popen_kwargs = {}
            creationflag = getattr(subprocess, "CREATE_NEW_CONSOLE", None)
            if creationflag is not None:
                popen_kwargs["creationflags"] = creationflag
            else:
                popen_kwargs["start_new_session"] = True
            subprocess.Popen(
                [sys.executable, script, str(venta_id), "--db", db_path],
                **popen_kwargs,
            )
        except Exception as exc:  # pragma: no cover - debug helper
            QMessageBox.critical(self, "Error", str(exc))

    def _mark_saved(self):
        """Registra el estado actual de la base de datos como guardado.

        Se almacena el número total de cambios realizados en la conexión de
        SQLite para poder detectar posteriormente si el inventario ha sido
        modificado sin guardar.
        """
        self._db_change_counter = self.manager.db.conn.total_changes

    def _load_last_inventory_path(self):
        """Carga la última ruta usada para guardar el inventario.

        Permite que la opción "Guardar rápido" funcione al iniciar la
        aplicación reutilizando el mismo archivo utilizado previamente.
        """
        if not os.path.exists(LAST_INVENTORY_PATH):
            return
        try:
            with open(LAST_INVENTORY_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            logger.warning(
                "No se pudo leer %s para restaurar el último inventario",
                LAST_INVENTORY_PATH,
            )
            return

        ultimo = data.get("ultimo") if isinstance(data, dict) else None
        if ultimo:
            self.ultimo_archivo_json = ultimo

    def closeEvent(self, event):
        if self.manager.db.conn.total_changes == self._db_change_counter:
            detener_firmador()
            event.accept()
            return
        reply = QMessageBox.question(
            self,
            "Salir",
            "¿Desea guardar el inventario antes de salir?",
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
            QMessageBox.Yes,
        )
        if reply == QMessageBox.Yes:
            guardado = self.guardar_rapido(asincrono=False)
            if guardado:
                detener_firmador()
                event.accept()
            else:
                event.ignore()
        elif reply == QMessageBox.No:
            detener_firmador()
            event.accept()
        else:
            event.ignore()

