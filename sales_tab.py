from typing import Optional

from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QPushButton,
    QLabel,
    QSplitter,
    QDateEdit,
    QTextEdit,
    QMessageBox,
    QFileDialog,
    QAbstractItemView,
    QFrame,
    QHeaderView,
    QSizePolicy,
    QScrollArea,
    QStackedWidget,
    QDialog,
    QCheckBox,
    QComboBox,
    QTabWidget,
    QGridLayout,
    QStyledItemDelegate,
)
from PyQt5.QtCore import Qt, QDate, QSize, QSignalBlocker, QRectF
from PyQt5.QtGui import QPixmap, QColor, QPainter, QPainterPath, QPen
from dialogs import RegisterCreditoFiscalDialog, RegisterSaleDialog
from datetime import datetime, date, timedelta
import importlib.util
import dte
from utils.jws import sign_json

_MATPLOTLIB_AVAILABLE = importlib.util.find_spec("matplotlib") is not None

if _MATPLOTLIB_AVAILABLE:
    from matplotlib import dates as mdates, ticker as mticker
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
    from matplotlib.figure import Figure
else:
    mdates = None
    mticker = None
    FigureCanvas = None
Figure = None
from utils.email_sender import EmailSender
from utils.email_builder import build_email
from utils.doc_generation import generate_invoice_pdf, generate_ticket_pdf
from utils.printing import open_pdf as open_pdf_file
from utils.loading import create_loading_dialog, loading_dialog
import tempfile
import subprocess
import shutil
import os
import json
import warnings
from paths import (
    DATOS_NEGOCIO_PATH,
    FACTURAS_CONSUMIDOR_FINAL_DIR,
    FACTURAS_CREDITO_FISCAL_DIR,
    TICKETS_OUTPUT_DIR,
    resolve_user_visible_path,
)
import logging

CF_DIR = FACTURAS_CONSUMIDOR_FINAL_DIR
CREDITO_DIR = FACTURAS_CREDITO_FISCAL_DIR
TICKETS_DIR = TICKETS_OUTPUT_DIR

logger = logging.getLogger(__name__)


def _adjust_font(font, *, delta=0, bold=False, min_size=8):
    point = font.pointSize()
    if point <= 0:
        point = 12
    point = max(point + delta, min_size)
    font.setPointSize(point)
    if bold:
        font.setBold(True)
    return font


class StatusDelegate(QStyledItemDelegate):
    """Delegate para resaltar estados de venta en la tabla."""

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        text = str(index.data() or "").strip().lower()
        bg_color = QColor("#E5F6ED")
        fg_color = QColor("#047857")
        if "anul" in text:
            bg_color = QColor("#FEE2E2")
            fg_color = QColor("#B91C1C")
        rect = QRectF(option.rect.adjusted(6, 10, -6, -10))
        path = QPainterPath()
        path.addRoundedRect(rect, 8, 8)
        painter.setPen(Qt.NoPen)
        painter.setBrush(bg_color)
        painter.drawPath(path)
        painter.setPen(fg_color)
        font = painter.font()
        font = _adjust_font(font, delta=1, bold=True)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignCenter, index.data())
        painter.restore()

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), 50)


class DteStatusDelegate(QStyledItemDelegate):
    """Delegate para mostrar estado DTE con pildoras de color."""

    COLORS = {
        "falta": ("#FEE2E2", "#B91C1C"),     # rojo suave
        "guardado": ("#DBEAFE", "#1D4ED8"),  # azul suave
        "enviado": ("#DCFCE7", "#15803D"),   # verde suave
    }

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        text = str(index.data() or "").strip()
        key = text.lower()
        bg_hex, fg_hex = self.COLORS.get(key, ("#E5E7EB", "#374151"))
        rect = QRectF(option.rect.adjusted(6, 12, -6, -12))
        path = QPainterPath()
        path.addRoundedRect(rect, 10, 10)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(bg_hex))
        painter.drawPath(path)
        painter.setPen(QColor(fg_hex))
        font = painter.font()
        font = _adjust_font(font, delta=0, bold=True)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignCenter, text)
        painter.restore()

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), 44)


class _StatsKpiCard(QFrame):
    """Small helper widget to display prominent KPI values."""

    def __init__(self, title: str, tooltip: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("StatsKpiCard")
        self.setFrameShape(QFrame.StyledPanel)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        title_label = QLabel(title)
        title_label.setWordWrap(True)
        title_font = title_label.font()
        title_font.setBold(True)
        title_label.setFont(title_font)
        if tooltip:
            title_label.setToolTip(tooltip)
        layout.addWidget(title_label)

        self.value_label = QLabel("—")
        self.value_label.setFont(_adjust_font(self.value_label.font(), delta=6, bold=True))
        self.value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(self.value_label)

        self.detail_label = QLabel("")
        self.detail_label.setFont(_adjust_font(self.detail_label.font(), delta=-1))
        self.detail_label.setStyleSheet("color: #5f6b7a;")
        self.detail_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(self.detail_label)

        layout.addStretch(1)

    def set_value(self, value: str, detail: str = "") -> None:
        self.value_label.setText(value)
        self.detail_label.setText(detail)


class _StatsSectionFrame(QFrame):
    """Card-style frame with padded content and title area."""

    def __init__(self, title: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("StatsSection")
        self.setFrameShape(QFrame.StyledPanel)
        wrapper = QVBoxLayout(self)
        wrapper.setContentsMargins(16, 16, 16, 16)
        wrapper.setSpacing(16)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)

        title_label = QLabel(title)
        title_label.setFont(_adjust_font(title_label.font(), delta=1, bold=True))
        header.addWidget(title_label)
        header.addStretch(1)

        self.header_layout = header
        wrapper.addLayout(header)

        self.body_layout = QVBoxLayout()
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(12)
        wrapper.addLayout(self.body_layout)

    def add_header_widget(self, widget: QWidget) -> None:
        insert_pos = self.header_layout.count() - 1
        self.header_layout.insertWidget(insert_pos, widget)


class _StatsChartWidget(QWidget):
    """Simple wrapper around a Matplotlib canvas with loading/empty states."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        if FigureCanvas is not None and Figure is not None:
            figure = Figure(figsize=(7, 3), constrained_layout=True)
            figure.set_constrained_layout(True)
            self.canvas = FigureCanvas(figure)
            self.canvas.setMinimumHeight(260)
            self.canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            layout.addWidget(self.canvas)
            self.canvas.hide()
        else:
            self.canvas = None

        self.empty_label = QLabel("No hay datos para mostrar")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setObjectName("StatsEmptyLabel")
        layout.addWidget(self.empty_label)

        if self.canvas is not None:
            self.empty_label.hide()

    def show_empty(self, message: str) -> None:
        self.empty_label.setText(message)
        self.empty_label.show()
        if self.canvas is not None:
            self.canvas.hide()

    def show_canvas(self) -> None:
        if self.canvas is not None:
            self.empty_label.hide()
            self.canvas.show()

    @property
    def has_canvas(self) -> bool:
        return self.canvas is not None

class SalesTab(QWidget):
    """Simple tab to list sales and preview invoices."""

    def __init__(self, manager, parent=None, check_smtp=True):
        super().__init__(parent)
        self.manager = manager
        self.main_window = parent
        self.current_credito_fiscal = None
        self.preview_pdf_file = None
        self.preview_image_file = None
        self.email_subject = ""
        self.email_body = ""
        self.email_thread = None
        self._email_loading_dialog = None
        self._stats_dirty = True
        self._setup_ui()
        self._load_email_config()
        if check_smtp:
            self._check_smtp_credentials()

    def _setup_ui(self):
        container_layout = QVBoxLayout(self)
        container_layout.setContentsMargins(0, 0, 0, 0)

        self.sales_tabs = QTabWidget()
        container_layout.addWidget(self.sales_tabs)

        main_tab = QWidget()
        main_layout = QHBoxLayout(main_tab)
        main_layout.setContentsMargins(24, 24, 24, 24)
        main_layout.setSpacing(20)

        # Panel izquierdo: Historial
        left_card = QFrame()
        left_card.setObjectName("ModernCard")
        left_layout = QVBoxLayout(left_card)
        left_layout.setContentsMargins(16, 16, 16, 16)
        left_layout.setSpacing(12)

        title_left = QLabel("Historial de Ventas")
        title_left.setFont(_adjust_font(title_left.font(), delta=3, bold=True))
        left_layout.addWidget(title_left)

        filters_layout = QVBoxLayout()
        filters_layout.setSpacing(8)

        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Buscar número o cliente")
        self.search_bar.setMinimumHeight(38)
        self.search_bar.textChanged.connect(self.load_sales)
        filters_layout.addWidget(self.search_bar)

        date_row = QHBoxLayout()
        date_row.setSpacing(8)
        self.date_filter_cb = QCheckBox("Filtrar por fecha")
        self.quick_range = QComboBox()
        self.quick_range.addItems(["Personalizado", "Esta semana", "Este mes", "Este año"])
        self.date_from = QDateEdit(QDate.currentDate().addYears(-2))
        self.date_from.setCalendarPopup(True)
        self.date_to = QDateEdit(QDate.currentDate())
        self.date_to.setCalendarPopup(True)
        self.quick_range.setEnabled(False)
        self.date_from.setEnabled(False)
        self.date_to.setEnabled(False)
        self.date_filter_cb.toggled.connect(self._toggle_date_filter)
        self.quick_range.currentIndexChanged.connect(self._apply_quick_range)
        self.date_from.dateChanged.connect(self.load_sales)
        self.date_to.dateChanged.connect(self.load_sales)
        for w in [self.date_filter_cb, self.quick_range, QLabel("Desde"), self.date_from, QLabel("Hasta"), self.date_to]:
            date_row.addWidget(w)
        filters_layout.addLayout(date_row)

        self.client_filter = QLineEdit()
        self.client_filter.setPlaceholderText("Cliente")
        self.client_filter.setMinimumHeight(36)
        self.client_filter.textChanged.connect(self.load_sales)
        filters_layout.addWidget(self.client_filter)

        left_layout.addLayout(filters_layout)

        self.sales_table = QTableWidget(0, 5)
        self.sales_table.setHorizontalHeaderLabels([
            "DTE",
            "Cliente",
            "Fecha",
            "Total",
            "Estado",
        ])
        self.sales_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.sales_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.sales_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.sales_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.sales_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.sales_table.setFrameShape(QFrame.NoFrame)
        self.sales_table.setShowGrid(False)
        self.sales_table.setAlternatingRowColors(False)
        self.sales_table.verticalHeader().hide()
        self.sales_table.verticalHeader().setDefaultSectionSize(50)
        header = self.sales_table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header.setFixedHeight(44)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.sales_table.setColumnWidth(2, 90)
        self.sales_table.setColumnWidth(3, 90)
        self.dte_delegate = DteStatusDelegate(self.sales_table)
        self.status_delegate = StatusDelegate(self.sales_table)
        self.sales_table.setItemDelegateForColumn(0, self.dte_delegate)
        self.sales_table.setItemDelegateForColumn(4, self.status_delegate)
        self.sales_table.itemSelectionChanged.connect(self.show_sale)
        left_layout.addWidget(self.sales_table)

        actions_row = QHBoxLayout()
        actions_row.addStretch(1)
        self.btn_guardar_dte_manual = QPushButton("Guardar DTE manualmente")
        self.btn_guardar_dte_manual.setMinimumHeight(34)
        self.btn_guardar_dte_manual.clicked.connect(self._guardar_dte_manual)
        actions_row.addWidget(self.btn_guardar_dte_manual)
        self.btn_eliminar_venta = QPushButton("Eliminar venta y restaurar inventario")
        self.btn_eliminar_venta.setObjectName("DangerActionButton")
        self.btn_eliminar_venta.setMinimumHeight(34)
        self.btn_eliminar_venta.clicked.connect(self._eliminar_venta_y_restaurar)
        actions_row.addWidget(self.btn_eliminar_venta)
        left_layout.addLayout(actions_row)

        main_layout.addWidget(left_card, 3)

        # Panel derecho: Accesos a flujo de venta existente
        self.pos_card = QFrame()
        self.pos_card.setObjectName("ModernCard")
        right_layout = QVBoxLayout(self.pos_card)
        right_layout.setContentsMargins(16, 16, 16, 16)
        right_layout.setSpacing(12)

        title_right = QLabel("Registrar Venta")
        title_right.setFont(_adjust_font(title_right.font(), delta=3, bold=True))
        right_layout.addWidget(title_right)

        self.btn_cf = QPushButton("Venta Consumidor Final")
        self.btn_cf.setObjectName("PrimaryActionButton")
        self.btn_cf.setMinimumHeight(46)
        self.btn_cf.clicked.connect(self._abrir_venta_cf)

        self.btn_cfiscal = QPushButton("Venta Crédito Fiscal")
        self.btn_cfiscal.setObjectName("SecondaryActionButton")
        self.btn_cfiscal.setMinimumHeight(46)
        self.btn_cfiscal.clicked.connect(self._abrir_venta_cfiscal)

        right_layout.addWidget(self.btn_cf)
        right_layout.addWidget(self.btn_cfiscal)

        self.pos_content_layout = QVBoxLayout()
        self.pos_content_layout.setContentsMargins(0, 8, 0, 0)
        self.pos_content_layout.setSpacing(0)
        right_layout.addLayout(self.pos_content_layout, 1)
        self._setup_pos_card()

        # Widgets necesarios para la funcionalidad existente (no visibles aquí)
        self.preview_label = QLabel("Previsualización del PDF")
        self.preview_label.setVisible(False)
        self.info_label = QLabel()
        self.status_label = QLabel("Estado actual: ")
        self.gen_label = QLabel("Generado: ")
        self.sent_label = QLabel("Último envío: ")
        self.email_label = QLabel("Correo destinatario: ")
        self.email_subject_edit = QLineEdit()
        self.email_body_edit = QTextEdit()
        self.config_email_btn = QPushButton("Configurar correo")
        for w in (
            self.info_label,
            self.status_label,
            self.gen_label,
            self.sent_label,
            self.email_label,
            self.email_subject_edit,
            self.email_body_edit,
            self.config_email_btn,
        ):
            w.setVisible(False)

        main_layout.addWidget(self.pos_card, 2)

        self.sales_tabs.addTab(main_tab, "Listado")

        self.stats_tab = QWidget()
        self._setup_stats_tab()
        self.sales_tabs.addTab(self.stats_tab, "Estadística")
        self.sales_tabs.currentChanged.connect(self._on_inner_tab_changed)

    def _setup_pos_card(self):
        if not hasattr(self, "pos_content_layout"):
            return
        while self.pos_content_layout.count():
            item = self.pos_content_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                continue
            inner_layout = item.layout()
            if inner_layout is not None:
                self._clear_layout(inner_layout)

        self.pos_scroll = QScrollArea()
        self.pos_scroll.setWidgetResizable(True)
        self.pos_scroll.setFrameShape(QFrame.NoFrame)
        self.pos_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.pos_scroll.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.pos_scroll.setContextMenuPolicy(Qt.CustomContextMenu)
        self.pos_scroll.customContextMenuRequested.connect(self._show_pos_context_menu)

        self.pos_stack = QStackedWidget()
        self.pos_stack.setMaximumWidth(585)
        self.pos_scroll.setWidget(self.pos_stack)
        self.pos_content_layout.addWidget(self.pos_scroll)

        placeholder = QWidget()
        placeholder_layout = QVBoxLayout(placeholder)
        placeholder_layout.setContentsMargins(24, 24, 24, 24)
        placeholder_layout.addStretch(1)
        placeholder_label = QLabel("Seleccione el tipo de venta para comenzar.")
        placeholder_label.setAlignment(Qt.AlignCenter)
        placeholder_layout.addWidget(placeholder_label)
        placeholder_layout.addStretch(1)
        self.pos_stack.addWidget(placeholder)

        productos_lote = self._build_productos_lote()
        distribuidores_cf = [v.get("nombre", "") for v in getattr(self.manager, "_Distribuidores", [])]
        vendedores_trabajadores = self.manager.db.get_trabajadores(solo_vendedores=True)

        self.widget_cf = RegisterSaleDialog(productos_lote, distribuidores_cf, vendedores_trabajadores, self)
        self.widget_cf.setWindowFlags(Qt.Widget)
        self.widget_cf.setMaximumWidth(585)
        self.widget_cf.venta_validada.connect(self._on_cf_venta_validada)
        self._connect_pos_cancel(self.widget_cf)
        self.pos_stack.addWidget(self.widget_cf)

        distribuidores_cfiscal = [dict(v) for v in getattr(self.manager, "_Distribuidores", [])]
        self.widget_cfiscal = RegisterCreditoFiscalDialog(
            productos_lote,
            distribuidores_cfiscal,
            vendedores_trabajadores,
            self,
        )
        self.widget_cfiscal.set_productos_data(productos_lote)
        self.widget_cfiscal.setWindowFlags(Qt.Widget)
        self.widget_cfiscal.setMaximumWidth(585)
        self.widget_cfiscal.venta_validada.connect(self._on_cfiscal_venta_validada)
        self._connect_pos_cancel(self.widget_cfiscal)
        self.pos_stack.addWidget(self.widget_cfiscal)

        self.pos_stack.setCurrentIndex(0)

    def _build_productos_lote(self):
        productos_lote = []
        compras = self.manager.db.get_compras()
        productos_dict = {p["id"]: p for p in getattr(self.manager, "_products", [])}
        for compra in compras:
            detalles = self.manager.db.get_detalles_compra(compra["id"])
            for detalle in detalles:
                prod = productos_dict.get(detalle["producto_id"])
                if not prod:
                    continue
                if detalle.get("cantidad", 0) > 0:
                    productos_lote.append(
                        {
                            "lote_id": detalle.get("id"),
                            "producto_id": detalle.get("producto_id"),
                            "nombre": prod.get("nombre", ""),
                            "codigo": prod.get("codigo", ""),
                            "codigo_lote": detalle.get("codigo_lote", ""),
                            "registro_sanitario": detalle.get("registro_sanitario", ""),
                            "stock": detalle.get("cantidad", 0),
                            "precio_unitario": detalle.get("precio_unitario", 0),
                            "vendedor_id": prod.get("vendedor_id"),
                            "Distribuidor_id": compra.get("Distribuidor_id"),
                            "fecha_vencimiento": detalle.get("fecha_vencimiento", ""),
                            "precio_venta_minorista": prod.get("precio_venta_minorista", 0),
                            "precio_venta_mayorista": prod.get("precio_venta_mayorista", 0),
                        }
                    )
        return productos_lote

    def _connect_pos_cancel(self, dialog: QDialog):
        if not hasattr(self, "pos_stack"):
            return
        for attr in ("cancel_button", "btn_cancel", "btn_cancelar"):
            btn = getattr(dialog, attr, None)
            if btn is not None:
                btn.clicked.connect(lambda _: self.pos_stack.setCurrentIndex(0))
                break
        if hasattr(dialog, "rejected"):
            dialog.rejected.connect(lambda: self.pos_stack.setCurrentIndex(0))

    def _show_pos_context_menu(self, pos):
        menu = QMenu(self)
        refresh_action = menu.addAction("Actualizar inventario en POS")
        action = menu.exec_(self.pos_scroll.mapToGlobal(pos))
        if action == refresh_action:
            self._refresh_pos_data()

    def _refresh_pos_data(self):
        productos_lote = self._build_productos_lote()
        if hasattr(self, "widget_cf"):
            self.widget_cf.set_productos_data(productos_lote)
        if hasattr(self, "widget_cfiscal"):
            self.widget_cfiscal.set_productos_data(productos_lote)

    def _on_cf_venta_validada(self, data: dict):
        """Recibe la venta CF validada y delega al flujo principal."""
        if not self.main_window:
            return
        try:
            distrib = self.widget_cf.Distribuidor_combo.currentText()
        except Exception:
            distrib = ""
        try:
            self.main_window._procesar_venta_consumidor_final(data, distrib)
            if hasattr(self.widget_cf, "clear_carrito"):
                self.widget_cf.clear_carrito()
        except Exception as exc:
            QMessageBox.critical(self, "Venta", str(exc))

    def _on_cfiscal_venta_validada(self, data: dict):
        """Recibe la venta CCF validada y delega al flujo principal."""
        if not self.main_window:
            return
        try:
            distrib = self.widget_cfiscal.Distribuidor_combo.currentText()
        except Exception:
            distrib = ""
        try:
            self.main_window._procesar_venta_credito_fiscal(data, distrib)
            if hasattr(self.widget_cfiscal, "clear_carrito"):
                self.widget_cfiscal.clear_carrito()
        except Exception as exc:
            QMessageBox.critical(self, "Venta a Crédito Fiscal", str(exc))

    def _show_pos_page(self, index: int):
        if not hasattr(self, "pos_stack"):
            return
        target = {1: getattr(self, "widget_cf", None), 2: getattr(self, "widget_cfiscal", None)}.get(index)
        if target is not None:
            target.show()
        if 0 <= index < self.pos_stack.count():
            self.pos_stack.setCurrentIndex(index)
        else:
            self.pos_stack.setCurrentIndex(0)

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                continue
            child_layout = item.layout()
            if child_layout is not None:
                self._clear_layout(child_layout)

    def _abrir_venta_cf(self):
        if self.main_window and hasattr(self.main_window, "_ensure_last_invoice_sent"):
            if not self.main_window._ensure_last_invoice_sent():
                return
        self._show_pos_page(1)

    def _abrir_venta_cfiscal(self):
        if self.main_window and hasattr(self.main_window, "_ensure_last_invoice_sent"):
            if not self.main_window._ensure_last_invoice_sent():
                return
        self._show_pos_page(2)

    def _setup_stats_tab(self):
        main_layout = QVBoxLayout(self.stats_tab)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        filter_frame = QFrame()
        filter_frame.setObjectName("StatsFilterBar")
        filter_layout = QHBoxLayout(filter_frame)
        filter_layout.setContentsMargins(24, 16, 24, 16)
        filter_layout.setSpacing(12)

        filter_layout.addWidget(QLabel("Rango rápido:"))
        self.stats_quick_range = QComboBox()
        self.stats_quick_range.addItems(
            [
                "Personalizado",
                "Hoy",
                "Esta semana",
                "Este mes",
                "Este año",
                "Últimos 30 días",
            ]
        )
        filter_layout.addWidget(self.stats_quick_range)

        filter_layout.addWidget(QLabel("Desde:"))
        self.stats_date_from = QDateEdit(QDate.currentDate().addMonths(-1))
        self.stats_date_from.setCalendarPopup(True)
        filter_layout.addWidget(self.stats_date_from)

        filter_layout.addWidget(QLabel("Hasta:"))
        self.stats_date_to = QDateEdit(QDate.currentDate())
        self.stats_date_to.setCalendarPopup(True)
        filter_layout.addWidget(self.stats_date_to)

        self.stats_refresh_btn = QPushButton("Aplicar")
        self.stats_refresh_btn.setMinimumWidth(120)
        self.stats_refresh_btn.clicked.connect(self.refresh_statistics)
        filter_layout.addWidget(self.stats_refresh_btn)

        filter_layout.addStretch(1)

        self.stats_quick_range.currentIndexChanged.connect(self._stats_apply_quick_range)
        self.stats_date_from.dateChanged.connect(self._stats_on_manual_date_change)
        self.stats_date_to.dateChanged.connect(self._stats_on_manual_date_change)
        self.stats_date_from.setEnabled(False)
        self.stats_date_to.setEnabled(False)

        self.stats_timezone_label = QLabel("")
        self.stats_timezone_label.setObjectName("StatsTimezoneLabel")
        filter_layout.addWidget(self.stats_timezone_label)

        main_layout.addWidget(filter_frame)

        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        divider.setFrameShadow(QFrame.Sunken)
        main_layout.addWidget(divider)

        self.stats_scroll = QScrollArea()
        self.stats_scroll.setWidgetResizable(True)
        self.stats_scroll.setFrameShape(QFrame.NoFrame)
        main_layout.addWidget(self.stats_scroll)

        content_widget = QWidget()
        content_widget.setObjectName("StatsContent")
        self.stats_scroll.setWidget(content_widget)

        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(24, 24, 24, 24)
        content_layout.setSpacing(24)

        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(12)

        self.stats_period_label = QLabel("Período seleccionado: —")
        self.stats_period_label.setFont(_adjust_font(self.stats_period_label.font(), delta=1, bold=True))
        header_layout.addWidget(self.stats_period_label)
        header_layout.addStretch(1)

        self.stats_last_updated_label = QLabel("")
        self.stats_last_updated_label.setObjectName("StatsUpdatedLabel")
        header_layout.addWidget(self.stats_last_updated_label)
        content_layout.addLayout(header_layout)

        kpi_frame = QWidget()
        kpi_layout = QGridLayout(kpi_frame)
        kpi_layout.setContentsMargins(0, 0, 0, 0)
        kpi_layout.setHorizontalSpacing(16)
        kpi_layout.setVerticalSpacing(16)

        self.stats_kpi_cards = {
            "total_sales": _StatsKpiCard(
                "Ventas totales",
                "Monto total de ventas registradas en el período seleccionado.",
            ),
            "total_transactions": _StatsKpiCard(
                "Transacciones",
                "Cantidad de facturas o tickets emitidos en el período.",
            ),
            "average_ticket": _StatsKpiCard(
                "Ticket promedio",
                "Promedio por transacción: ventas totales ÷ transacciones.",
            ),
            "gross_margin": _StatsKpiCard(
                "Margen bruto",
                "Ventas totales menos el costo estimado de los productos.",
            ),
            "total_costs": _StatsKpiCard(
                "CMV estimado",
                "Costo de mercancía vendida estimado en el período.",
            ),
        }

        positions = {
            "total_sales": (0, 0),
            "total_transactions": (0, 1),
            "average_ticket": (1, 0),
            "gross_margin": (1, 1),
            "total_costs": (2, 0),
        }
        for key, card in self.stats_kpi_cards.items():
            row, col = positions[key]
            kpi_layout.addWidget(card, row, col)
        kpi_layout.setColumnStretch(0, 1)
        kpi_layout.setColumnStretch(1, 1)
        content_layout.addWidget(kpi_frame)

        self.stats_daily_section = _StatsSectionFrame("Tendencia diaria de ventas")
        self.stats_daily_chart = _StatsChartWidget()
        self.stats_daily_section.body_layout.addWidget(self.stats_daily_chart)
        if self.stats_daily_chart.has_canvas:
            hint_text = "Pase el cursor por los puntos para comparar montos diarios."
        else:
            hint_text = (
                "Instale la dependencia 'matplotlib' para visualizar la tendencia diaria."
            )
        self.stats_daily_hint = QLabel(hint_text)
        self.stats_daily_hint.setObjectName("SectionHint")
        self.stats_daily_section.body_layout.addWidget(self.stats_daily_hint)
        content_layout.addWidget(self.stats_daily_section)

        split_container = QWidget()
        split_layout = QHBoxLayout(split_container)
        split_layout.setContentsMargins(0, 0, 0, 0)
        split_layout.setSpacing(24)

        self.stats_top_section = _StatsSectionFrame("Top productos")
        self.stats_top_products_table = self._create_stats_table(
            ["Producto", "Unidades", "Ventas", "Margen", "Contribución"]
        )
        self.stats_top_section.body_layout.addWidget(self.stats_top_products_table)
        self.stats_top_empty_label = QLabel("No hay productos destacados en este período.")
        self.stats_top_empty_label.setAlignment(Qt.AlignCenter)
        self.stats_top_empty_label.hide()
        self.stats_top_section.body_layout.addWidget(self.stats_top_empty_label)

        split_layout.addWidget(self.stats_top_section, 1)

        self.stats_channel_section = _StatsSectionFrame("Ventas por vendedor/canal")
        self.stats_channel_table = self._create_stats_table(
            ["Canal", "Ventas", "Transacciones", "Ticket promedio"]
        )
        self.stats_channel_section.body_layout.addWidget(self.stats_channel_table)
        self.stats_channel_empty_label = QLabel(
            "No hay ventas registradas para los canales en este período."
        )
        self.stats_channel_empty_label.setAlignment(Qt.AlignCenter)
        self.stats_channel_empty_label.hide()
        self.stats_channel_section.body_layout.addWidget(self.stats_channel_empty_label)

        split_layout.addWidget(self.stats_channel_section, 1)
        content_layout.addWidget(split_container)

        self.stats_stock_section = _StatsSectionFrame("Existencias críticas")
        self.stats_stock_section.add_header_widget(QLabel("≤ 5 unidades disponibles"))
        self.stats_low_stock_table = self._create_stats_table(["Producto", "Stock"])
        self.stats_stock_section.body_layout.addWidget(self.stats_low_stock_table)
        self.stats_stock_empty_label = QLabel("Sin productos en estado crítico de stock.")
        self.stats_stock_empty_label.setAlignment(Qt.AlignCenter)
        self.stats_stock_empty_label.hide()
        self.stats_stock_section.body_layout.addWidget(self.stats_stock_empty_label)
        content_layout.addWidget(self.stats_stock_section)

        content_layout.addStretch(1)

        self.stats_tab.setStyleSheet(
            """
            QWidget#StatsContent {
                background: #f4f6f9;
            }
            QFrame#StatsFilterBar {
                background: #f9fbfd;
            }
            QLabel#StatsUpdatedLabel {
                color: #5f6b7a;
                font-size: 11px;
            }
            QLabel#StatsTimezoneLabel {
                color: #5f6b7a;
                font-size: 11px;
            }
            QFrame#StatsSection {
                background: #ffffff;
                border: 1px solid #dfe3eb;
                border-radius: 10px;
            }
            QFrame#StatsKpiCard {
                background: #ffffff;
                border: 1px solid #dfe3eb;
                border-radius: 10px;
            }
            QLabel#SectionHint {
                color: #5f6b7a;
                font-size: 11px;
            }
            QLabel#StatsEmptyLabel {
                color: #5f6b7a;
                font-style: italic;
            }
        """
        )

        try:
            tz_display = datetime.now().astimezone().tzname() or "UTC"
        except Exception:  # pragma: no cover - defensive fallback
            tz_display = "UTC"
        self.stats_timezone_label.setText(f"Zona horaria: {tz_display}")

        # Initialize default range (triggers refresh)
        self.stats_quick_range.setCurrentIndex(3)

    def _create_stats_table(self, headers):
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.NoSelection)
        table.setAlternatingRowColors(True)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.verticalHeader().setVisible(False)
        return table

    def _stats_apply_quick_range(self):
        option = self.stats_quick_range.currentText()
        custom = option == "Personalizado"
        self.stats_date_from.setEnabled(custom)
        self.stats_date_to.setEnabled(custom)
        if custom:
            self.refresh_statistics()
            return

        today = date.today()
        start = today
        end = today
        if option == "Hoy":
            start = end = today
        elif option == "Esta semana":
            start = today - timedelta(days=today.weekday())
            end = start + timedelta(days=6)
        elif option == "Este mes":
            start = today.replace(day=1)
            if today.month == 12:
                end = date(today.year, 12, 31)
            else:
                end = date(today.year, today.month + 1, 1) - timedelta(days=1)
        elif option == "Este año":
            start = date(today.year, 1, 1)
            end = date(today.year, 12, 31)
        elif option == "Últimos 30 días":
            end = today
            start = today - timedelta(days=29)
        else:
            return

        with QSignalBlocker(self.stats_date_from):
            self.stats_date_from.setDate(QDate(start.year, start.month, start.day))
        with QSignalBlocker(self.stats_date_to):
            self.stats_date_to.setDate(QDate(end.year, end.month, end.day))
        self.refresh_statistics()

    def _stats_on_manual_date_change(self):
        if self.stats_quick_range.currentIndex() != 0:
            with QSignalBlocker(self.stats_quick_range):
                self.stats_quick_range.setCurrentIndex(0)
            self.stats_date_from.setEnabled(True)
            self.stats_date_to.setEnabled(True)
        self.refresh_statistics()

    def _on_inner_tab_changed(self, index: int):
        if getattr(self, "stats_tab", None) is None:
            return
        if self.sales_tabs.widget(index) is self.stats_tab and self._stats_dirty:
            self.refresh_statistics()

    @staticmethod
    def _format_currency(value):
        try:
            amount = float(value or 0)
        except (TypeError, ValueError):
            amount = 0.0
        if abs(amount) < 0.005:
            amount = 0.0
        return f"${amount:,.2f}"

    @staticmethod
    def _format_number(value, integer: bool = False):
        try:
            number = float(value or 0)
        except (TypeError, ValueError):
            number = 0.0
        if integer:
            return f"{int(round(number)):,}"
        if abs(number - round(number)) < 0.01:
            return f"{int(round(number)):,}"
        return f"{number:,.2f}"

    @staticmethod
    def _format_percentage(value):
        try:
            ratio = float(value or 0)
        except (TypeError, ValueError):
            ratio = 0.0
        return f"{ratio:.1f}%"

    def refresh_statistics(self):
        if not hasattr(self, "stats_date_from"):
            return

        start = self.stats_date_from.date().toPyDate()
        end = self.stats_date_to.date().toPyDate()
        if start and end and start > end:
            start, end = end, start
            with QSignalBlocker(self.stats_date_from):
                self.stats_date_from.setDate(QDate(start.year, start.month, start.day))
            with QSignalBlocker(self.stats_date_to):
                self.stats_date_to.setDate(QDate(end.year, end.month, end.day))

        stats = self.manager.db.get_sales_statistics(start, end)
        summary = stats.get("summary", {})
        total_sales = summary.get("total_sales", 0) or 0
        total_transactions = summary.get("total_transactions", 0) or 0

        if start and end:
            self.stats_period_label.setText(
                f"Período seleccionado: {start.strftime('%d/%m/%Y')} – {end.strftime('%d/%m/%Y')}"
            )
        else:
            self.stats_period_label.setText("Período seleccionado: —")

        self.stats_kpi_cards["total_sales"].set_value(
            self._format_currency(total_sales)
        )
        self.stats_kpi_cards["total_transactions"].set_value(
            self._format_number(total_transactions, integer=True)
        )
        self.stats_kpi_cards["average_ticket"].set_value(
            self._format_currency(summary.get("average_ticket", 0))
        )
        self.stats_kpi_cards["gross_margin"].set_value(
            self._format_currency(summary.get("gross_margin", 0))
        )
        self.stats_kpi_cards["total_costs"].set_value(
            self._format_currency(summary.get("total_costs", 0))
        )

        periods = stats.get("periods", {})
        daily_rows = periods.get("daily", []) or []
        if not self.stats_daily_chart.has_canvas:
            self.stats_daily_chart.show_empty(
                "Instale la dependencia 'matplotlib' para visualizar el gráfico de tendencia."
            )
            self.stats_daily_hint.show()
        else:
            fig = self.stats_daily_chart.canvas.figure
            fig.set_size_inches(7, 3, forward=True)
            fig.clear()
            if daily_rows:
                ax = fig.subplots()
                dates = []
                values = []
                for row in daily_rows:
                    period_value = row.get("period")
                    try:
                        date_value = datetime.strptime(period_value, "%Y-%m-%d")
                    except (TypeError, ValueError):
                        continue
                    dates.append(date_value)
                    values.append(float(row.get("total", 0) or 0))
                if dates and values:
                    ax.plot(dates, values, marker="o", color="#4E79A7")
                    ax.fill_between(dates, values, color="#4E79A7", alpha=0.1)
                    ax.set_ylabel("Ventas")
                    ax.yaxis.set_major_formatter(
                        mticker.FuncFormatter(lambda x, _: f"{self._format_currency(x)}")
                    )
                    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m"))
                    ax.grid(True, linestyle="--", alpha=0.3)
                    for label in ax.get_xticklabels():
                        label.set_rotation(45)
                        label.set_horizontalalignment("right")
                    self.stats_daily_chart.canvas.draw()
                    self.stats_daily_chart.show_canvas()
                    self.stats_daily_hint.show()
                else:
                    self.stats_daily_chart.show_empty("No hay datos diarios para mostrar.")
                    self.stats_daily_hint.hide()
            else:
                self.stats_daily_chart.show_empty("No hay datos diarios para mostrar.")
                self.stats_daily_hint.hide()

        top_products = stats.get("top_products", []) or []
        self.stats_top_products_table.setRowCount(len(top_products))
        if top_products:
            self.stats_top_products_table.show()
            self.stats_top_empty_label.hide()
        else:
            self.stats_top_products_table.hide()
            self.stats_top_empty_label.show()
        for row_index, product in enumerate(top_products):
            self.stats_top_products_table.setItem(
                row_index, 0, QTableWidgetItem(product.get("name", ""))
            )
            units_item = QTableWidgetItem(
                self._format_number(product.get("units", 0), integer=True)
            )
            units_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.stats_top_products_table.setItem(row_index, 1, units_item)

            total_item = QTableWidgetItem(
                self._format_currency(product.get("total", 0))
            )
            total_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.stats_top_products_table.setItem(row_index, 2, total_item)

            margin_item = QTableWidgetItem(
                self._format_currency(product.get("margin", 0))
            )
            margin_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.stats_top_products_table.setItem(row_index, 3, margin_item)

            contribution = (
                (float(product.get("total", 0)) / total_sales * 100)
                if total_sales
                else 0.0
            )
            contrib_item = QTableWidgetItem(self._format_percentage(contribution))
            contrib_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.stats_top_products_table.setItem(row_index, 4, contrib_item)

        channels = stats.get("sales_by_channel", []) or []
        self.stats_channel_table.setRowCount(len(channels))
        if channels:
            self.stats_channel_table.show()
            self.stats_channel_empty_label.hide()
        else:
            self.stats_channel_table.hide()
            self.stats_channel_empty_label.show()
        for row_index, channel in enumerate(channels):
            self.stats_channel_table.setItem(
                row_index, 0, QTableWidgetItem(channel.get("channel", ""))
            )
            total_item = QTableWidgetItem(
                self._format_currency(channel.get("total", 0))
            )
            total_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.stats_channel_table.setItem(row_index, 1, total_item)

            transactions_item = QTableWidgetItem(
                self._format_number(channel.get("transactions", 0), integer=True)
            )
            transactions_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.stats_channel_table.setItem(row_index, 2, transactions_item)

            avg_item = QTableWidgetItem(
                self._format_currency(channel.get("average_ticket", 0))
            )
            avg_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.stats_channel_table.setItem(row_index, 3, avg_item)

        critical_stock = stats.get("critical_stock", []) or []
        self.stats_low_stock_table.setRowCount(len(critical_stock))
        if critical_stock:
            self.stats_low_stock_table.show()
            self.stats_stock_empty_label.hide()
        else:
            self.stats_low_stock_table.hide()
            self.stats_stock_empty_label.show()
        for row_index, product in enumerate(critical_stock):
            self.stats_low_stock_table.setItem(
                row_index, 0, QTableWidgetItem(product.get("name", ""))
            )
            stock_item = QTableWidgetItem(
                self._format_number(product.get("stock", 0), integer=True)
            )
            stock_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.stats_low_stock_table.setItem(row_index, 1, stock_item)

        now_text = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        self.stats_last_updated_label.setText(f"Última actualización: {now_text}")
        self._stats_dirty = False

    def _toggle_date_filter(self, checked):
        self.quick_range.setEnabled(checked)
        custom = self.quick_range.currentIndex() == 0
        self.date_from.setEnabled(checked and custom)
        self.date_to.setEnabled(checked and custom)
        if checked:
            self._apply_quick_range()
        else:
            self.load_sales()

    def _apply_quick_range(self):
        if not self.date_filter_cb.isChecked():
            return
        option = self.quick_range.currentText()
        today = date.today()
        if option == "Esta semana":
            start = today - timedelta(days=today.weekday())
            end = start + timedelta(days=6)
            self.date_from.setDate(QDate(start))
            self.date_to.setDate(QDate(end))
            self.date_from.setEnabled(False)
            self.date_to.setEnabled(False)
        elif option == "Este mes":
            start = today.replace(day=1)
            if today.month == 12:
                end = date(today.year, 12, 31)
            else:
                end = date(today.year, today.month + 1, 1) - timedelta(days=1)
            self.date_from.setDate(QDate(start))
            self.date_to.setDate(QDate(end))
            self.date_from.setEnabled(False)
            self.date_to.setEnabled(False)
        elif option == "Este año":
            start = date(today.year, 1, 1)
            end = date(today.year, 12, 31)
            self.date_from.setDate(QDate(start))
            self.date_to.setDate(QDate(end))
            self.date_from.setEnabled(False)
            self.date_to.setEnabled(False)
        else:
            self.date_from.setEnabled(True)
            self.date_to.setEnabled(True)
        self.load_sales()

    def load_sales(self):
        ventas = self.manager.db.get_ventas(sincronizada=1)
        search = self.search_bar.text().lower()
        cliente_filter = self.client_filter.text().lower()
        if self.date_filter_cb.isChecked():
            d_from = self.date_from.date().toPyDate()
            d_to = self.date_to.date().toPyDate()
        else:
            d_from = d_to = None
        rows = []
        for v in ventas:
            fecha = v.get("fecha")
            fdate = None
            if isinstance(fecha, str):
                try:
                    fdate = datetime.strptime(fecha, "%Y-%m-%d %H:%M:%S")
                except (ValueError, TypeError):
                    try:
                        fdate = datetime.strptime(fecha, "%Y-%m-%d")
                    except (ValueError, TypeError):
                        fdate = None
            else:
                # fecha no es una cadena o está ausente
                fdate = None
            if self.date_filter_cb.isChecked() and fdate and (
                (d_from and fdate.date() < d_from) or (d_to and fdate.date() > d_to)
            ):
                continue
            cliente = ""
            if v.get("cliente_id"):
                cli = next((c for c in self.manager._clientes if c["id"] == v["cliente_id"]), None)
                if cli:
                    cliente = cli.get("nombre", "")
            if cliente_filter and cliente_filter not in cliente.lower():
                continue
            if search and search not in str(v.get("id")).lower() and search not in cliente.lower():
                continue
            rows.append((v, cliente, fdate))

        rows.sort(key=lambda x: x[2] or datetime.min, reverse=True)

        self.sales_table.setRowCount(len(rows))
        for row, (venta, cli, _) in enumerate(rows):
            dte_estado = self._dte_status_for_sale(venta)
            dte_item = QTableWidgetItem(dte_estado)
            dte_item.setData(Qt.UserRole, venta.get("id"))
            dte_item.setTextAlignment(Qt.AlignCenter)
            self.sales_table.setItem(row, 0, dte_item)
            self.sales_table.setItem(row, 1, QTableWidgetItem(cli))
            self.sales_table.setItem(row, 2, QTableWidgetItem(venta.get("fecha", "")))
            self.sales_table.setItem(row, 3, QTableWidgetItem(f"${venta.get('total', 0):.2f}"))
            estado = venta.get("estado", "Pendiente")
            self.sales_table.setItem(row, 4, QTableWidgetItem(estado))
        self.sales_table.clearSelection()
        self.show_sale(clear=True)
        self._stats_dirty = True
        if (
            getattr(self, "sales_tabs", None)
            and self.sales_tabs.currentWidget() is self.stats_tab
        ):
            self.refresh_statistics()

    def _venta_id_from_row(self, row: int) -> int | None:
        if row < 0:
            return None
        item = self.sales_table.item(row, 0)
        if item is None:
            return None
        vid = item.data(Qt.UserRole)
        if vid is None:
            try:
                vid = int(item.text())
            except Exception:
                vid = None
        try:
            return int(vid)
        except Exception:
            return None

    def _dte_status_for_sale(self, venta: dict) -> str:
        """Devuelve estado DTE normalizado: Falta / Guardado / Enviado."""
        estado_venta = str(venta.get("estado") or "").strip()
        venta_id = venta.get("id")
        estado_ui = None
        estado_base = None
        tag = None
        cursor = getattr(self.manager.db, "cursor", None)
        if cursor is not None:
            try:
                row = cursor.execute(
                    "SELECT estado_ui, estado, estado_ui_tag FROM dte_envios WHERE venta_id=? ORDER BY id DESC LIMIT 1",
                    (venta_id,),
                ).fetchone()
            except Exception:
                row = None
        else:
            row = None
        if row:
            try:
                estado_ui = row["estado_ui"] if hasattr(row, "__getitem__") else row[0]
                estado_base = row["estado"] if hasattr(row, "__getitem__") else row[1]
                tag = row["estado_ui_tag"] if hasattr(row, "__getitem__") else row[2]
            except Exception:
                pass

        def norm(val):
            return str(val or "").strip().lower()

        ui = norm(estado_ui)
        base = norm(estado_base)
        tag = norm(tag)
        sent_states = {"enviado", "aceptado", "procesado", "recibido", "transmitido"}
        pending_states = {"pendiente"}
        if ui in sent_states or tag in sent_states or base in sent_states:
            return "Enviado"
        if ui in pending_states or base in pending_states:
            return "Guardado"
        if estado_venta.lower() == "pendiente de envío":
            return "Guardado"
        return "Falta"

    def show_sale(self, clear=False):
        if clear or self.sales_table.currentRow() < 0:
            self.preview_label.setText("Previsualización del PDF")
            self.info_label.setText("")
            self.status_label.setText("Estado actual: ")
            self.gen_label.setText("Generado: ")
            self.sent_label.setText("Último envío: ")
            self.email_label.setText("Correo destinatario: ")
            with QSignalBlocker(self.email_subject_edit):
                self.email_subject_edit.clear()
            with QSignalBlocker(self.email_body_edit):
                self.email_body_edit.clear()
            self._clear_preview_files()
            return

        row = self.sales_table.currentRow()
        venta_id = self._venta_id_from_row(row)
        if venta_id is None:
            QMessageBox.warning(
                self,
                "Venta no encontrada",
                "No se pudo identificar la venta seleccionada.",
            )
            self.show_sale(clear=True)
            return
        venta = next((v for v in self.manager.db.get_ventas() if v["id"] == venta_id), None)
        if not venta:
            QMessageBox.warning(
                self,
                "Venta no encontrada",
                f"No se encontraron datos para la venta seleccionada (ID {venta_id}).",
            )
            self.show_sale(clear=True)
            return
        cliente = ""
        cliente_email = ""
        if venta and venta.get("cliente_id"):
            cli = next((c for c in self.manager._clientes if c["id"] == venta["cliente_id"]), None)
            if cli:
                cliente = cli.get("nombre", "")
                cliente_email = cli.get("email", "")

        # Fetch credit-fiscal information for this sale
        self.current_credito_fiscal = self.manager.db.get_venta_credito_fiscal(venta_id)
        if not self.current_credito_fiscal and not venta.get("cliente_id"):
            self.info_label.setText(f"Ticket {venta_id}")
        elif self.current_credito_fiscal:
            self.info_label.setText(
                f"Factura {venta_id} - Crédito Fiscal - Cliente: {cliente}"
            )
        else:
            self.info_label.setText(f"Factura {venta_id} - Cliente: {cliente}")
        # Generate and display preview image for the selected invoice
        self.email_label.setText(f"Correo destinatario: {cliente_email}")
        self._update_preview(venta_id)
        self._update_email_preview()

    def show_sale_details(self):
        if self.sales_table.currentRow() < 0:
            QMessageBox.warning(self, "Estado", "Seleccione una venta")
            return
        row = self.sales_table.currentRow()
        venta_id = self._venta_id_from_row(row)
        if venta_id is None:
            QMessageBox.warning(self, "Estado", "No se encontró la venta seleccionada")
            return
        venta = next((v for v in self.manager.db.get_ventas() if v["id"] == venta_id), None)
        if not venta:
            QMessageBox.warning(self, "Estado", "No se encontró la venta seleccionada")
            return
        detalles = self.manager.db.get_detalles_venta(venta_id)
        from dialogs import VentaDetalleDialog
        dialog = VentaDetalleDialog(venta, detalles, self)
        dialog.exec_()

    def delete_sale(self):
        if self.sales_table.currentRow() < 0:
            QMessageBox.warning(self, "Eliminar venta", "Seleccione una venta")
            return
        row = self.sales_table.currentRow()
        venta_id = self._venta_id_from_row(row)
        if venta_id is None:
            QMessageBox.warning(self, "Eliminar venta", "No se pudo identificar la venta seleccionada.")
            return
        confirm = QMessageBox.question(
            self,
            "Eliminar venta",
            "¿Desea eliminar la venta seleccionada y restaurar el inventario?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        if not self.manager.db.delete_venta(venta_id):
            QMessageBox.critical(
                self,
                "Eliminar venta",
                "No se pudo eliminar la venta seleccionada.",
            )
            return
        self.manager.refresh_data()
        main_window = self.window()
        if main_window and hasattr(main_window, "_actualizar_inventario_actual"):
            try:
                main_window._actualizar_inventario_actual()
            except Exception:
                logger.exception("Error al actualizar inventario actual tras eliminar venta")
        self.load_sales()
        QMessageBox.information(
            self,
            "Eliminar venta",
            "La venta se eliminó y el inventario fue restaurado.",
        )

    def _guardar_dte_manual(self):
        if self.sales_table.currentRow() < 0:
            QMessageBox.warning(self, "Guardar DTE", "Seleccione una venta del historial.")
            return
        row = self.sales_table.currentRow()
        venta_id = self._venta_id_from_row(row)
        if venta_id is None:
            QMessageBox.warning(self, "Guardar DTE", "No se pudo identificar la venta seleccionada.")
            return

        # Enforce orden y bloqueos: no permitir nuevos DTE si hay pendientes sin enviar
        estados = self._get_ventas_dte_estado()
        success_states = {"transmitido", "recibido", "procesado", "aceptado"}
        pendientes_envio = [
            r for r in estados if r["estado"] and str(r["estado"]).strip().lower() not in success_states
        ]
        if pendientes_envio:
            bloqueante = pendientes_envio[0]
            QMessageBox.warning(
                self,
                "DTE pendiente",
                "Hay facturas con DTE generados pero NO enviados.\n"
                f"Primero envíe la venta ID {bloqueante['id']} (fecha {bloqueante['fecha']}).",
            )
            return

        sin_dte = [r for r in estados if r["estado"] is None]
        if sin_dte:
            primera = sin_dte[0]
            if venta_id != primera["id"]:
                QMessageBox.warning(
                    self,
                    "Orden de guardado",
                    "Guarde los DTE en orden de fecha y generación.\n"
                    f"Primero guarde la venta ID {primera['id']} (fecha {primera['fecha']}).",
                )
                return

        tipo_dte = "03" if self.manager.db.get_venta_credito_fiscal(venta_id) else "01"
        ok = False
        msg = ""
        target = self.main_window or self.window() or self.parent()
        if target is not None and hasattr(target, "_generar_dte_sin_enviar"):
            ok, msg = target._generar_dte_sin_enviar(venta_id, tipo_dte)
        else:
            try:
                data = dte.generar_dte_json(self.manager.db, venta_id, tipo_dte=tipo_dte)
                try:
                    dte.recalcular_totales(data, incluir_iva=True)
                except Exception:
                    pass
                try:
                    data = dte.apply_schema_patch(data)
                except Exception:
                    pass
                signed = sign_json(data)
                try:
                    dte._save_signed_dte(data, signed, fallido=False)
                except Exception:
                    pass
                ident = data.get("identificacion") or {}
                try:
                    self.manager.db.registrar_envio_dte(
                        venta_id,
                        "manual",
                        "Pendiente",
                        "",
                        codigo_generacion=ident.get("codigoGeneracion"),
                        numero_control=ident.get("numeroControl"),
                        ambiente=ident.get("ambiente"),
                    )
                except Exception:
                    pass
                ok = True
                msg = "DTE generado y guardado (pendiente de envío)."
            except Exception as exc:
                msg = str(exc)

        if ok:
            try:
                self.manager.db.update_venta_estado(venta_id, "Pendiente de Envío")
            except Exception:
                pass
            try:
                generate_invoice_pdf(self.manager, venta_id)
            except Exception:
                logger.exception("No se pudo generar PDF para venta_id=%s", venta_id)
            else:
                msg += "\nPDF guardado."
            QMessageBox.information(self, "Guardar DTE", msg)
        else:
            QMessageBox.warning(self, "Guardar DTE", f"No se pudo generar el DTE: {msg}")
        self.load_sales()

    def _eliminar_venta_y_restaurar(self):
        if self.sales_table.currentRow() < 0:
            QMessageBox.warning(self, "Eliminar venta", "Seleccione una venta del historial.")
            return
        row = self.sales_table.currentRow()
        venta_id = self._venta_id_from_row(row)
        if venta_id is None:
            QMessageBox.warning(self, "Eliminar venta", "No se pudo identificar la venta seleccionada.")
            return
        confirm = QMessageBox.question(
            self,
            "Eliminar venta",
            "¿Eliminar la venta y restaurar el inventario? Esto eliminará los registros DTE asociados.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        ok = False
        try:
            ok = self.manager.db.delete_venta(venta_id)
        except Exception as exc:
            logger.exception("No se pudo eliminar la venta %s", venta_id)
            QMessageBox.critical(self, "Eliminar venta", f"No se pudo eliminar la venta: {exc}")
            return
        if ok:
            try:
                self.manager.refresh_data()
                self.load_sales()
            except Exception:
                logger.exception("Error al refrescar tras eliminar venta")
            QMessageBox.information(
                self,
                "Venta eliminada",
                "La venta se eliminó y el inventario fue restaurado al estado previo.",
            )
        else:
            QMessageBox.warning(
                self,
                "Eliminar venta",
                "No se pudo eliminar la venta. Verifique los registros e intente nuevamente.",
            )

    def _get_ventas_dte_estado(self):
        """Devuelve ventas ordenadas por fecha con el estado de envío DTE más reciente."""
        try:
            rows = self.manager.db.cursor.execute(
                """
                SELECT v.id, v.fecha,
                    (SELECT estado FROM dte_envios de WHERE de.venta_id=v.id ORDER BY de.id DESC LIMIT 1) AS estado
                FROM ventas v
                ORDER BY datetime(v.fecha) ASC, v.id ASC
                """
            ).fetchall()
        except Exception:
            logger.exception("No se pudo obtener estados DTE de ventas")
            return []
        return [dict(row) for row in rows]

    def _clear_preview_files(self):
        """Remove temporary preview image without deleting stored PDFs."""
        if self.preview_image_file and os.path.exists(self.preview_image_file):
            try:
                os.remove(self.preview_image_file)
            except OSError:
                pass
        self.preview_pdf_file = None
        self.preview_image_file = None

    def _is_ticket_sale(self, venta):
        """Return True if the sale should be treated as a ticket."""
        getter_cf = getattr(self.manager.db, "get_venta_credito_fiscal", None)
        if getter_cf:
            try:
                if getter_cf(venta["id"]):
                    return False
            except Exception:
                pass
        cid = venta.get("cliente_id")
        if not cid:
            return True
        cliente = None
        getter = getattr(self.manager.db, "get_cliente", None)
        if getter:
            try:
                cliente = getter(cid)
            except Exception:
                cliente = None
        if not cliente:
            return True
        nit = (cliente.get("nit") or "").strip()
        dui = (cliente.get("dui") or "").strip()
        return not nit and not dui

    def _update_email_preview(self):
        self.email_subject_edit.setText(self.email_subject)
        self.email_body_edit.setPlainText(self.email_body)

    def edit_email(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Editar correo")
        layout = QVBoxLayout(dialog)
        subject_edit = QLineEdit(self.email_subject)
        body_edit = QTextEdit()
        body_edit.setPlainText(self.email_body)
        layout.addWidget(QLabel("Asunto:"))
        layout.addWidget(subject_edit)
        layout.addWidget(QLabel("Cuerpo:"))
        layout.addWidget(body_edit)
        btn_box = QHBoxLayout()
        ok_btn = QPushButton("Aceptar")
        cancel_btn = QPushButton("Cancelar")
        ok_btn.clicked.connect(dialog.accept)
        cancel_btn.clicked.connect(dialog.reject)
        btn_box.addWidget(ok_btn)
        btn_box.addWidget(cancel_btn)
        layout.addLayout(btn_box)
        if dialog.exec_() == QDialog.Accepted:
            self.email_subject = subject_edit.text()
            self.email_body = body_edit.toPlainText()
            self._update_email_preview()

    def configure_email(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Configurar correo")
        layout = QVBoxLayout(dialog)
        subject_edit = QLineEdit(self.email_subject)
        body_edit = QTextEdit()
        body_edit.setPlainText(self.email_body)
        layout.addWidget(QLabel("Asunto por defecto:"))
        layout.addWidget(subject_edit)
        layout.addWidget(QLabel("Mensaje por defecto:"))
        layout.addWidget(body_edit)
        btn_box = QHBoxLayout()
        ok_btn = QPushButton("Guardar")
        cancel_btn = QPushButton("Cancelar")
        ok_btn.clicked.connect(dialog.accept)
        cancel_btn.clicked.connect(dialog.reject)
        btn_box.addWidget(ok_btn)
        btn_box.addWidget(cancel_btn)
        layout.addLayout(btn_box)
        if dialog.exec_() == QDialog.Accepted:
            self.email_subject = subject_edit.text()
            self.email_body = body_edit.toPlainText()
            self._save_email_config()
            self._update_email_preview()

    def _load_email_config(self):
        path = DATOS_NEGOCIO_PATH
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.email_subject = data.get("default_email_subject", "")
                self.email_body = data.get("default_email_body", "")
            except Exception:
                pass
        self._update_email_preview()

    def _save_email_config(self):
        path = DATOS_NEGOCIO_PATH
        data = {}
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}
        data["default_email_subject"] = self.email_subject
        data["default_email_body"] = self.email_body
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _check_smtp_credentials(self):
        """Check for SMTP data and warn if any are missing.

        Returns a dict with the credentials if complete, otherwise ``None``.
        """
        path = DATOS_NEGOCIO_PATH
        headless = os.environ.get("QT_QPA_PLATFORM") in {"offscreen", "minimal"}
        msg = (
            "Credenciales SMTP incompletas. Configure sus datos en la opción 'Configuración de correo'."
        )

        suppress = os.environ.get("INVENTARIO_SUPPRESS_SMTP_WARNING")

        def warn():
            if headless:
                warnings.warn(msg)
            else:
                QMessageBox.warning(self, "Configuración de correo", msg)

        if not os.path.exists(path):
            if not suppress:
                warn()
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            if not suppress:
                warn()
            return None

        server = data.get("smtp_server")
        port = data.get("smtp_port")
        user = data.get("email_usuario") or data.get("email")
        password = os.getenv("INVENTARIO_EMAIL_PASSWORD") or data.get("email_contrasena")

        if not data.get("email_usuario") and user:
            data["email_usuario"] = user
            try:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

        if not all([server, port, user, password]):
            if not suppress:
                warn()
            return None

        return {
            "server": server,
            "port": port,
            "user": user,
            "password": password,
        }
    def _update_preview(self, venta_id):
        """Generate PDF preview image for the given sale ID and display it."""
        venta = next((v for v in self.manager.db.get_ventas() if v["id"] == venta_id), None)
        if not venta:
            self.preview_label.setText("Previsualización del PDF")
            return

        self._clear_preview_files()

        is_ticket = self._is_ticket_sale(venta)
        if is_ticket:
            pdf_path = self.manager.db.get_ticket_pdf(venta_id)
        else:
            pdf_path = self.manager.db.get_factura_pdf(venta_id)
        if not pdf_path or not os.path.exists(pdf_path):
            self.preview_label.setText("Documento no guardado")
            return

        prefix = tempfile.mktemp()
        try:
            png_path = prefix + ".png"
            if shutil.which("pdftoppm"):
                subprocess.run([
                    "pdftoppm",
                    "-png",
                    "-singlefile",
                    pdf_path,
                    prefix,
                ], check=True)
            else:
                import fitz

                doc = fitz.open(pdf_path)
                page = doc.load_page(0)
                pix = page.get_pixmap()
                pix.save(png_path)

            self.preview_pdf_file = pdf_path
            self.preview_image_file = png_path
            pixmap = QPixmap(png_path)
            if pixmap.isNull():
                raise RuntimeError("failed to load image")
            # Scale to fixed dimensions while preserving the PDF aspect ratio
            scaled = pixmap.scaled(
                600,
                800,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            self.preview_label.setPixmap(scaled)
            self.preview_label.setText("")
        except Exception:
            self.preview_label.setText("No se pudo generar previsualización")
            self._clear_preview_files()

    def _generate_invoice_pdf(self, venta_id):
        return generate_invoice_pdf(self.manager, venta_id)

    def _generate_ticket_pdf(self, venta_id):
        return generate_ticket_pdf(self.manager, venta_id)

    def _safe_generate(self, generator, venta_id, title, failure_message):
        """Run a document generator and handle unexpected errors gracefully."""
        try:
            with loading_dialog(self, "Creando DTE…"):
                result = generator(venta_id)
        except ValueError as exc:
            QMessageBox.warning(self, title, str(exc))
            return None
        except Exception as exc:  # pragma: no cover - defensive branch
            logger.exception("Error al generar documento para venta %s", venta_id)
            QMessageBox.critical(
                self,
                title,
                f"{failure_message}\nDetalles: {exc}",
            )
            return None
        if not result:
            QMessageBox.warning(self, title, failure_message)
            return None
        return result

    def _show_email_loading(self, message: str = "Enviando correo…") -> None:
        if self._email_loading_dialog:
            self._email_loading_dialog.finish()
        self._email_loading_dialog = create_loading_dialog(self, message)

    def _hide_email_loading(self) -> None:
        if self._email_loading_dialog:
            self._email_loading_dialog.finish()
            self._email_loading_dialog = None

    def save_invoice(self):
        """Generate and store the document for the selected sale."""
        if self.sales_table.currentRow() < 0:
            QMessageBox.warning(self, "Guardar factura", "Seleccione una venta primero.")
            return

        row = self.sales_table.currentRow()
        venta_id = int(self.sales_table.item(row, 0).text())
        venta = self.manager.db.get_venta_by_id(venta_id)
        if not venta or int(venta.get("id", 0)) != venta_id:
            QMessageBox.warning(self, "Guardar factura", "No se encontró la venta seleccionada.")
            return
        self.email_subject = self.email_subject_edit.text()
        self.email_body = self.email_body_edit.toPlainText()
        self._save_email_config()
        if self._is_ticket_sale(venta):
            doc_type = "Ticket"
            file_path = self._safe_generate(
                self._generate_ticket_pdf,
                venta_id,
                "Guardar factura",
                "No se pudo generar el ticket.",
            )
        else:
            doc_type = "Factura"
            file_path = self._safe_generate(
                self._generate_invoice_pdf,
                venta_id,
                "Guardar factura",
                "No se pudo generar la factura.",
            )
        if not file_path:
            return
        display_path = resolve_user_visible_path(file_path)
        QMessageBox.information(
            self,
            "Guardar factura",
            f"{doc_type} guardado en {display_path}",
        )
        cr_result = getattr(self.manager, "last_cr_result", None)
        if isinstance(cr_result, dict):
            status = cr_result.get("status")
            if status == "created":
                cr_path = cr_result.get("path")
                estado = str(cr_result.get("estado") or "PENDIENTE").capitalize()
                path_hint = resolve_user_visible_path(str(cr_path)) if cr_path else None
                path_display = path_hint or (str(cr_path) if cr_path else "N/D")
                QMessageBox.information(
                    self,
                    "Retención IVA",
                    f"CR-07 guardado (venta {venta_id}) – archivo: {path_display} – estado: {estado}",
                )
            elif status == "duplicate":
                dup_msg = cr_result.get("message") or f"Ya existe un CR-07 para la venta {venta_id}"
                QMessageBox.warning(self, "Retención IVA", dup_msg)
            elif status == "skipped":
                reason = cr_result.get("reason") or "CR omitido"
                QMessageBox.information(
                    self,
                    "Retención IVA",
                    f"CR-07 omitido: {reason}",
                )

    def save_ticket(self):
        """Generate a simple ticket PDF for the selected sale."""
        if self.sales_table.currentRow() < 0:
            QMessageBox.warning(self, "Ticket", "Seleccione una factura primero.")
            return

        row = self.sales_table.currentRow()
        venta_id = int(self.sales_table.item(row, 0).text())
        file_path = self._safe_generate(
            self._generate_ticket_pdf,
            venta_id,
            "Ticket",
            "No se pudo generar el ticket.",
        )
        if file_path:
            display_path = resolve_user_visible_path(file_path)
            QMessageBox.information(
                self,
                "Ticket",
                f"Ticket guardado en {display_path}",
            )
        
    def preview_pdf(self):
        """Open the saved PDF for the selected sale."""
        if self.sales_table.currentRow() < 0:
            QMessageBox.warning(self, "Previsualizar", "Seleccione una factura primero.")

            return

        row = self.sales_table.currentRow()
        venta_id = int(self.sales_table.item(row, 0).text())
        venta = next((v for v in self.manager.db.get_ventas() if v["id"] == venta_id), None)
        if not venta:
            QMessageBox.warning(self, "Previsualizar", "No se encontró la venta seleccionada.")

            return

        is_ticket = self._is_ticket_sale(venta)
        if is_ticket:
            pdf_path = self.manager.db.get_ticket_pdf(venta_id)
        else:
            pdf_path = self.manager.db.get_factura_pdf(venta_id)
        if not pdf_path or not os.path.exists(pdf_path):
            QMessageBox.warning(
                self, "Previsualizar", "No hay PDF guardado para esta venta."
            )
            return
        absolute_path = os.path.abspath(pdf_path)
        if not open_pdf_file(absolute_path):
            QMessageBox.warning(
                self,
                "Abrir PDF",
                (
                    "No se pudo abrir el archivo PDF automáticamente.\n"
                    "Puedes abrirlo manualmente desde:\n"
                    f"{absolute_path}"
                ),
            )

    def print_pdf(self):
        """Print the selected sale using the stored PDF file."""

        if self.sales_table.currentRow() < 0:
            QMessageBox.warning(self, "Imprimir", "Seleccione una factura primero.")
            return

        row = self.sales_table.currentRow()
        venta_id = int(self.sales_table.item(row, 0).text())
        venta = self.manager.db.get_venta_by_id(venta_id)
        if not venta or int(venta.get("id", 0)) != venta_id:
            QMessageBox.warning(self, "Imprimir", "No se encontró la venta seleccionada.")
            return

        title = "Imprimir"
        if self._is_ticket_sale(venta):
            pdf_path = self.manager.db.get_ticket_pdf(venta_id)
            failure_message = "No se pudo generar el ticket."
            if not pdf_path or not os.path.exists(pdf_path):
                pdf_path = self._safe_generate(
                    self._generate_ticket_pdf,
                    venta_id,
                    title,
                    failure_message,
                )
        else:
            pdf_path = self.manager.db.get_factura_pdf(venta_id)
            failure_message = "No se pudo generar la factura."
            if not pdf_path or not os.path.exists(pdf_path):
                pdf_path = self._safe_generate(
                    self._generate_invoice_pdf,
                    venta_id,
                    title,
                    failure_message,
                )

        if not pdf_path or not os.path.exists(pdf_path):
            return

        absolute_path = os.path.abspath(pdf_path)
        if not open_pdf_file(absolute_path):
            QMessageBox.warning(
                self,
                "Abrir PDF",
                (
                    "No se pudo abrir el archivo PDF automáticamente.\n"
                    "Puedes abrirlo manualmente desde:\n"
                    f"{absolute_path}"
                ),
            )

    def send_email(self):
        """Send the selected document via email in a background thread."""
        if self.sales_table.currentRow() < 0:
            QMessageBox.warning(self, "Enviar por correo", "No has seleccionado ninguna venta.")
            return

        row = self.sales_table.currentRow()
        venta_id = int(self.sales_table.item(row, 0).text())
        venta = self.manager.db.get_venta_by_id(venta_id)
        if not venta or int(venta.get("id", 0)) != venta_id:
            QMessageBox.warning(self, "Enviar por correo", "No se encontró la venta seleccionada.")
            return

        cliente_email = ""
        if venta.get("cliente_id"):
            cli = next((c for c in self.manager._clientes if c["id"] == venta["cliente_id"]), None)
            if cli:
                cliente_email = cli.get("email", "")
        if not cliente_email:
            QMessageBox.warning(self, "Enviar por correo", "El cliente no tiene correo registrado.")
            return

        dte_meta = {
            "subject": self.email_subject_edit.text(),
            "body": self.email_body_edit.toPlainText(),
        }
        self.email_subject = dte_meta["subject"]
        self.email_body = dte_meta["body"]
        self._save_email_config()

        if self._is_ticket_sale(venta):
            doc_type = "ticket"
            pdf_path = self.manager.db.get_ticket_pdf(venta_id)
            if not pdf_path or not os.path.exists(pdf_path):
                pdf_path = self._safe_generate(
                    self._generate_ticket_pdf,
                    venta_id,
                    "Enviar por correo",
                    "No se pudo generar el ticket.",
                )
        else:
            doc_type = "factura"
            pdf_path = self.manager.db.get_factura_pdf(venta_id)
            if not pdf_path or not os.path.exists(pdf_path):
                pdf_path = self._safe_generate(
                    self._generate_invoice_pdf,
                    venta_id,
                    "Enviar por correo",
                    "No se pudo generar la factura.",
                )
        if not pdf_path or not os.path.exists(pdf_path):
            return
        json_path = os.path.splitext(pdf_path)[0] + ".json"
        if not os.path.exists(json_path):
            if doc_type == "ticket":
                pdf_path = self._safe_generate(
                    self._generate_ticket_pdf,
                    venta_id,
                    "Enviar por correo",
                    "No se pudo generar el ticket.",
                )
            else:
                pdf_path = self._safe_generate(
                    self._generate_invoice_pdf,
                    venta_id,
                    "Enviar por correo",
                    "No se pudo generar la factura.",
                )
            if not pdf_path:
                return
            json_path = os.path.splitext(pdf_path)[0] + ".json"
            if not os.path.exists(json_path):
                QMessageBox.warning(self, "Enviar por correo", "No se encontró el JSON firmado.")
                return

        creds = self._check_smtp_credentials()
        if not creds:
            return
        server = creds["server"]
        port = creds["port"]
        user = creds["user"]
        password = creds["password"]

        email_data = build_email(
            cliente_email,
            dte_meta,
            pdf_path,
            json_path,
        )

        self.status_label.setText("Estado actual: Enviando...")

        self.email_thread = EmailSender(
            server,
            port,
            user,
            password,
            email_data["to"],
            email_data["subject"],
            email_data["body"],
            email_data["attachments"],
        )
        self.email_thread.finished.connect(self._on_email_sent)
        self._show_email_loading()
        self.email_thread.start()

    def print_invoice(self):
        """Abre el PDF de la venta seleccionada (lo genera si falta)."""
        if self.sales_table.currentRow() < 0:
            QMessageBox.warning(self, "Imprimir", "Seleccione una venta.")
            return
        row = self.sales_table.currentRow()
        venta_id = int(self.sales_table.item(row, 0).text())
        venta = self.manager.db.get_venta_by_id(venta_id)
        if not venta:
            QMessageBox.warning(self, "Imprimir", "No se encontró la venta seleccionada.")
            return
        if self._is_ticket_sale(venta):
            pdf_path = self.manager.db.get_ticket_pdf(venta_id)
            if not pdf_path or not os.path.exists(pdf_path):
                pdf_path = self._safe_generate(
                    self._generate_ticket_pdf,
                    venta_id,
                    "Imprimir",
                    "No se pudo generar el ticket.",
                )
        else:
            pdf_path = self.manager.db.get_factura_pdf(venta_id)
            if not pdf_path or not os.path.exists(pdf_path):
                pdf_path = self._safe_generate(
                    self._generate_invoice_pdf,
                    venta_id,
                    "Imprimir",
                    "No se pudo generar la factura.",
                )
        if pdf_path and os.path.exists(pdf_path):
            open_pdf_file(os.path.abspath(pdf_path))

    def _on_email_sent(self, success, message):
        self._hide_email_loading()
        if success:
            self.status_label.setText("Estado actual: Enviado")
            self.sent_label.setText("Último envío: " + datetime.now().strftime("%Y-%m-%d %H:%M"))
            QMessageBox.information(self, "Enviar por correo", message)
        else:
            self.status_label.setText("Estado actual: Error")
            QMessageBox.critical(self, "Enviar por correo", message)
        self.email_thread = None
