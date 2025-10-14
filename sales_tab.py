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

    QHeaderView,
    QSizePolicy,
    QScrollArea,

    QDialog,
    QCheckBox,
    QComboBox,
    QTabWidget,
    QGridLayout,
)
from PyQt5.QtCore import Qt, QDate, QSize, QSignalBlocker
from PyQt5.QtGui import QPixmap
from datetime import datetime, date, timedelta
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


class SalesTab(QWidget):
    """Simple tab to list sales and preview invoices."""

    def __init__(self, manager, parent=None, check_smtp=True):
        super().__init__(parent)
        self.manager = manager
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

        listado_tab = QWidget()
        listado_layout = QHBoxLayout()
        listado_layout.setContentsMargins(0, 0, 0, 0)
        listado_tab.setLayout(listado_layout)

        # Left panel
        left_layout = QVBoxLayout()
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Buscar número o cliente")
        self.search_bar.textChanged.connect(self.load_sales)
        left_layout.addWidget(self.search_bar)

        filter_layout = QHBoxLayout()
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
        for w in [
            self.date_filter_cb,
            self.quick_range,
            QLabel("Desde"),
            self.date_from,
            QLabel("Hasta"),
            self.date_to,
        ]:
            filter_layout.addWidget(w)
        left_layout.addLayout(filter_layout)

        self.client_filter = QLineEdit()
        self.client_filter.setPlaceholderText("Cliente")
        self.client_filter.textChanged.connect(self.load_sales)
        left_layout.addWidget(self.client_filter)

        self.sales_table = QTableWidget(0, 5)
        self.sales_table.setHorizontalHeaderLabels([
            "Nº Factura",
            "Cliente",
            "Fecha",
            "Total",
            "Estado",
        ])
        self.sales_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.sales_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.sales_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.sales_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.sales_table.itemSelectionChanged.connect(self.show_sale)
        left_layout.addWidget(self.sales_table)

        self.btn_estado = QPushButton("Estado")
        self.btn_estado.clicked.connect(self.show_sale_details)
        left_layout.addWidget(self.btn_estado)

        self.btn_delete_sale = QPushButton("Eliminar venta")
        self.btn_delete_sale.setStyleSheet("background-color: #b71c1c; color: #fff;")
        self.btn_delete_sale.clicked.connect(self.delete_sale)
        left_layout.addWidget(self.btn_delete_sale)

        left_widget = QWidget()
        left_widget.setLayout(left_layout)

        # Right panel
        splitter = QSplitter(Qt.Vertical)

        preview_layout = QVBoxLayout()
        self.preview_label = QLabel("Previsualización del PDF")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setStyleSheet("background:#DDD; padding:20px;")
        self.preview_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.preview_label.setScaledContents(True)
        preview_scroll = QScrollArea()
        preview_scroll.setWidgetResizable(True)
        preview_scroll.setWidget(self.preview_label)
        preview_layout.addWidget(preview_scroll)

        self.info_label = QLabel()
        preview_layout.addWidget(self.info_label)

        btn_layout = QHBoxLayout()
        self.btn_guardar = QPushButton("Guardar factura")
        btn_layout.addWidget(self.btn_guardar)
        self.btn_guardar.clicked.connect(self.save_invoice)
        preview_layout.addLayout(btn_layout)

        preview_widget = QWidget()
        preview_widget.setLayout(preview_layout)

        status_layout = QVBoxLayout()
        self.status_label = QLabel("Estado actual: ")
        self.gen_label = QLabel("Generado: ")
        self.sent_label = QLabel("Último envío: ")
        self.email_label = QLabel("Correo destinatario: ")
        self.email_subject_edit = QLineEdit()
        self.email_body_edit = QTextEdit()
        self.config_email_btn = QPushButton("Configurar correo")
        self.email_subject_edit.textChanged.connect(lambda t: setattr(self, "email_subject", t))
        self.email_body_edit.textChanged.connect(
            lambda: setattr(self, "email_body", self.email_body_edit.toPlainText())
        )
        self.config_email_btn.clicked.connect(self.configure_email)
        status_layout.addWidget(self.status_label)
        status_layout.addWidget(self.gen_label)
        status_layout.addWidget(self.sent_label)
        status_layout.addWidget(self.email_label)
        status_layout.addWidget(QLabel("Asunto:"))
        status_layout.addWidget(self.email_subject_edit)
        status_layout.addWidget(QLabel("Mensaje:"))
        status_layout.addWidget(self.email_body_edit)
        status_layout.addWidget(self.config_email_btn)
        status_widget = QWidget()
        status_widget.setLayout(status_layout)

        splitter.addWidget(preview_widget)
        splitter.addWidget(status_widget)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)

        listado_layout.addWidget(left_widget)
        listado_layout.addWidget(splitter)
        listado_layout.setStretch(0, 2)
        listado_layout.setStretch(1, 3)

        self.sales_tabs.addTab(listado_tab, "Listado")

        self.stats_tab = QWidget()
        self._setup_stats_tab()
        self.sales_tabs.addTab(self.stats_tab, "Estadística")
        self.sales_tabs.currentChanged.connect(self._on_inner_tab_changed)

    def _setup_stats_tab(self):
        layout = QVBoxLayout(self.stats_tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        controls_layout = QHBoxLayout()
        controls_layout.addWidget(QLabel("Rango rápido:"))
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
        controls_layout.addWidget(self.stats_quick_range)
        controls_layout.addWidget(QLabel("Desde"))
        self.stats_date_from = QDateEdit(QDate.currentDate().addMonths(-1))
        self.stats_date_from.setCalendarPopup(True)
        controls_layout.addWidget(self.stats_date_from)
        controls_layout.addWidget(QLabel("Hasta"))
        self.stats_date_to = QDateEdit(QDate.currentDate())
        self.stats_date_to.setCalendarPopup(True)
        controls_layout.addWidget(self.stats_date_to)
        self.stats_refresh_btn = QPushButton("Actualizar")
        self.stats_refresh_btn.clicked.connect(self.refresh_statistics)
        controls_layout.addWidget(self.stats_refresh_btn)
        controls_layout.addStretch()
        layout.addLayout(controls_layout)

        self.stats_quick_range.currentIndexChanged.connect(self._stats_apply_quick_range)
        self.stats_date_from.dateChanged.connect(self._stats_on_manual_date_change)
        self.stats_date_to.dateChanged.connect(self._stats_on_manual_date_change)
        self.stats_date_from.setEnabled(False)
        self.stats_date_to.setEnabled(False)

        self.stats_last_updated_label = QLabel("")
        self.stats_last_updated_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.stats_last_updated_label.setStyleSheet("color:#555; font-size:11px;")
        layout.addWidget(self.stats_last_updated_label)

        summary_widget = QWidget()
        summary_layout = QGridLayout()
        summary_layout.setContentsMargins(0, 0, 0, 0)
        summary_layout.setHorizontalSpacing(24)
        summary_layout.setVerticalSpacing(8)
        summary_widget.setLayout(summary_layout)
        self.stats_summary_labels = {}
        summary_metrics = [
            ("Ventas totales", "total_sales"),
            ("Transacciones", "total_transactions"),
            ("Ticket promedio", "average_ticket"),
            ("Margen bruto", "gross_margin"),
            ("Costo estimado", "total_costs"),
        ]
        for idx, (label_text, key) in enumerate(summary_metrics):
            row = idx // 2
            col = (idx % 2) * 2
            title_label = QLabel(label_text)
            summary_layout.addWidget(title_label, row, col)
            value_label = QLabel("—")
            value_label.setStyleSheet("font-weight:bold; font-size:14px;")
            summary_layout.addWidget(value_label, row, col + 1)
            self.stats_summary_labels[key] = value_label
        summary_layout.setColumnStretch(1, 1)
        summary_layout.setColumnStretch(3, 1)
        layout.addWidget(summary_widget)

        self.stats_period_tabs = QTabWidget()
        self.stats_period_tables = {}
        for key, title in (("daily", "Diario"), ("monthly", "Mensual"), ("yearly", "Anual")):
            table = self._create_stats_table(
                ["Periodo", "Ventas", "Transacciones", "Ticket promedio"]
            )
            self.stats_period_tabs.addTab(table, title)
            self.stats_period_tables[key] = table
        layout.addWidget(self.stats_period_tabs)

        layout.addWidget(QLabel("Productos más vendidos"))
        self.stats_top_products_table = self._create_stats_table(
            ["Producto", "Unidades", "Ventas", "Margen", "Contribución"]
        )
        layout.addWidget(self.stats_top_products_table)

        layout.addWidget(QLabel("Ventas por vendedor/canal"))
        self.stats_channel_table = self._create_stats_table(
            ["Canal", "Ventas", "Transacciones", "Ticket promedio"]
        )
        layout.addWidget(self.stats_channel_table)

        layout.addWidget(QLabel("Existencias críticas (≤ 5 unidades)"))
        self.stats_low_stock_table = self._create_stats_table(["Producto", "Stock"])
        layout.addWidget(self.stats_low_stock_table)

        layout.addStretch(1)

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

    @staticmethod
    def _format_period_label(period_type: str, value: str) -> str:
        if not value:
            return ""
        try:
            if period_type == "daily":
                return datetime.strptime(value, "%Y-%m-%d").strftime("%d/%m/%Y")
            if period_type == "monthly":
                return datetime.strptime(value, "%Y-%m").strftime("%m/%Y")
            if period_type == "yearly":
                return value
        except ValueError:
            return value
        return value

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
        for key, label in self.stats_summary_labels.items():
            value = summary.get(key, 0)
            if key == "total_transactions":
                label.setText(self._format_number(value, integer=True))
            else:
                label.setText(self._format_currency(value))

        periods = stats.get("periods", {})
        for key, table in self.stats_period_tables.items():
            rows = periods.get(key, []) or []
            table.setRowCount(len(rows))
            for row_index, data in enumerate(rows):
                period_text = self._format_period_label(key, data.get("period"))
                table.setItem(row_index, 0, QTableWidgetItem(period_text))

                total_item = QTableWidgetItem(
                    self._format_currency(data.get("total", 0))
                )
                total_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                table.setItem(row_index, 1, total_item)

                transactions_item = QTableWidgetItem(
                    self._format_number(data.get("transactions", 0), integer=True)
                )
                transactions_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                table.setItem(row_index, 2, transactions_item)

                avg_item = QTableWidgetItem(
                    self._format_currency(data.get("average_ticket", 0))
                )
                avg_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                table.setItem(row_index, 3, avg_item)

        total_sales = summary.get("total_sales", 0) or 0
        top_products = stats.get("top_products", []) or []
        self.stats_top_products_table.setRowCount(len(top_products))
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
            self.sales_table.setItem(row, 0, QTableWidgetItem(str(venta.get("id"))))
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
        venta_id = int(self.sales_table.item(row, 0).text())
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
        venta_id = int(self.sales_table.item(row, 0).text())
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
        venta_id = int(self.sales_table.item(row, 0).text())
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



