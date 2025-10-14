"""Main window for the sales dashboard application."""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from PyQt5 import QtCore, QtWidgets
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from ..core.calculations import calcContribucion
from ..core.controller import DashboardController, FilterState, QuickRange
from ..core.formatters import format_currency, format_date, format_percentage
from ..core.metrics import CONTRIBUTION_KEY, MARGIN_KEY, DashboardData


class FilterBar(QtWidgets.QWidget):
    filtersApplied = QtCore.pyqtSignal(FilterState)

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._current_state: Optional[FilterState] = None
        self._applied_state: Optional[FilterState] = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(12)

        self.range_combo = QtWidgets.QComboBox()
        for option in QuickRange:
            self.range_combo.addItem(option.value, option)
        layout.addWidget(QtWidgets.QLabel("Rango rápido:"))
        layout.addWidget(self.range_combo)

        self.from_edit = QtWidgets.QDateEdit(calendarPopup=True)
        self.from_edit.setDisplayFormat("dd/MM/yyyy")
        self.to_edit = QtWidgets.QDateEdit(calendarPopup=True)
        self.to_edit.setDisplayFormat("dd/MM/yyyy")

        layout.addWidget(QtWidgets.QLabel("Desde:"))
        layout.addWidget(self.from_edit)
        layout.addWidget(QtWidgets.QLabel("Hasta:"))
        layout.addWidget(self.to_edit)

        self.apply_button = QtWidgets.QPushButton("Aplicar")
        self.apply_button.setEnabled(False)
        layout.addWidget(self.apply_button)

        layout.addStretch(1)

        self.tz_label = QtWidgets.QLabel()
        font = self.tz_label.font()
        font.setPointSize(font.pointSize() - 1)
        self.tz_label.setFont(font)
        self.tz_label.setStyleSheet("color: #555555;")
        layout.addWidget(self.tz_label)

        self.range_combo.currentIndexChanged.connect(self._on_range_changed)
        self.from_edit.dateChanged.connect(self._on_custom_changed)
        self.to_edit.dateChanged.connect(self._on_custom_changed)
        self.apply_button.clicked.connect(self._emit_filters)

    def set_timezone_label(self, text: str) -> None:
        self.tz_label.setText(text)

    def set_state(self, state: FilterState) -> None:
        self._current_state = state
        self._applied_state = state
        self._update_widgets_from_state(state)
        self.apply_button.setEnabled(False)

    def mark_applied(self, state: FilterState) -> None:
        self._applied_state = state
        self.apply_button.setEnabled(False)

    # Internal helpers -------------------------------------------------
    def _update_widgets_from_state(self, state: FilterState) -> None:
        idx = self.range_combo.findData(state.quick_range)
        if idx >= 0:
            self.range_combo.blockSignals(True)
            self.range_combo.setCurrentIndex(idx)
            self.range_combo.blockSignals(False)
        self._set_date_edits_enabled(state.quick_range == QuickRange.PERSONALIZADO)
        if state.start:
            self.from_edit.blockSignals(True)
            self.from_edit.setDate(state.start.date())
            self.from_edit.blockSignals(False)
        if state.end:
            self.to_edit.blockSignals(True)
            self.to_edit.setDate(state.end.date())
            self.to_edit.blockSignals(False)

    def _set_date_edits_enabled(self, enabled: bool) -> None:
        self.from_edit.setEnabled(enabled)
        self.to_edit.setEnabled(enabled)

    def _on_range_changed(self) -> None:
        quick_range: QuickRange = self.range_combo.currentData()
        if quick_range != QuickRange.PERSONALIZADO:
            self._set_date_edits_enabled(False)
        else:
            self._set_date_edits_enabled(True)
        if self._current_state:
            start = self._current_state.start
            end = self._current_state.end
        else:
            start = datetime.now()
            end = datetime.now()
        new_state = FilterState(quick_range=quick_range, start=start, end=end)
        self._current_state = new_state
        self.apply_button.setEnabled(new_state != self._applied_state)

    def _on_custom_changed(self) -> None:
        quick_range: QuickRange = self.range_combo.currentData()
        if quick_range != QuickRange.PERSONALIZADO:
            return
        start_dt = datetime.combine(self.from_edit.date().toPyDate(), datetime.min.time())
        end_dt = datetime.combine(self.to_edit.date().toPyDate(), datetime.max.time())
        new_state = FilterState(quick_range=quick_range, start=start_dt, end=end_dt)
        self._current_state = new_state
        self.apply_button.setEnabled(new_state != self._applied_state)

    def _emit_filters(self) -> None:
        if not self._current_state:
            return
        quick_range: QuickRange = self.range_combo.currentData()
        if quick_range != QuickRange.PERSONALIZADO:
            # Use the controller to compute the actual range when applied
            state = FilterState(quick_range=quick_range, start=None, end=None)
        else:
            state = self._current_state
        self.filtersApplied.emit(state)


class KpiCard(QtWidgets.QFrame):
    def __init__(self, title: str, tooltip: str, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.setObjectName("kpiCard")
        self.setToolTip(tooltip)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(4)

        title_label = QtWidgets.QLabel(title)
        title_font = title_label.font()
        title_font.setPointSize(title_font.pointSize() + 1)
        title_font.setBold(True)
        title_label.setFont(title_font)
        layout.addWidget(title_label)

        self.value_label = QtWidgets.QLabel("-")
        value_font = self.value_label.font()
        value_font.setPointSize(value_font.pointSize() + 6)
        value_font.setBold(True)
        self.value_label.setFont(value_font)
        self.value_label.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        layout.addWidget(self.value_label)

        self.detail_label = QtWidgets.QLabel("")
        detail_font = self.detail_label.font()
        detail_font.setPointSize(detail_font.pointSize() - 1)
        self.detail_label.setFont(detail_font)
        self.detail_label.setStyleSheet("color: #555555;")
        layout.addWidget(self.detail_label)

        layout.addStretch(1)

    def update_value(self, value: str, detail: str = "") -> None:
        self.value_label.setText(value)
        self.detail_label.setText(detail)


class LoadingLabel(QtWidgets.QLabel):
    def __init__(self, text: str = "Cargando...", parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(text, parent)
        self.setAlignment(QtCore.Qt.AlignCenter)
        font = self.font()
        font.setItalic(True)
        self.setFont(font)
        self.setStyleSheet("color: #666666;")


class ChartWidget(QtWidgets.QWidget):
    def __init__(self, title: Optional[str] = None, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.title_label: Optional[QtWidgets.QLabel] = None
        if title:
            self.title_label = QtWidgets.QLabel(title)
            title_font = self.title_label.font()
            title_font.setPointSize(title_font.pointSize() + 1)
            title_font.setBold(True)
            self.title_label.setFont(title_font)
            layout.addWidget(self.title_label)

        self.loading = LoadingLabel()
        layout.addWidget(self.loading)

        self.canvas = FigureCanvas(Figure(figsize=(5, 3)))
        layout.addWidget(self.canvas)
        self.canvas.hide()

        self.empty_label = QtWidgets.QLabel("No hay datos para mostrar")
        self.empty_label.setAlignment(QtCore.Qt.AlignCenter)
        self.empty_label.hide()
        layout.addWidget(self.empty_label)

    def show_loading(self) -> None:
        self.loading.show()
        self.canvas.hide()
        self.empty_label.hide()

    def show_empty(self, message: str) -> None:
        self.loading.hide()
        self.canvas.hide()
        self.empty_label.setText(message)
        self.empty_label.show()

    def show_canvas(self) -> None:
        self.loading.hide()
        self.empty_label.hide()
        self.canvas.show()


class SectionFrame(QtWidgets.QFrame):
    def __init__(self, title: str, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.setObjectName("sectionFrame")

        wrapper = QtWidgets.QVBoxLayout(self)
        wrapper.setContentsMargins(16, 16, 16, 16)
        wrapper.setSpacing(12)

        self.header_layout = QtWidgets.QHBoxLayout()
        self.header_layout.setContentsMargins(0, 0, 0, 0)
        self.header_layout.setSpacing(8)

        self.title_label = QtWidgets.QLabel(title)
        title_font = self.title_label.font()
        title_font.setPointSize(title_font.pointSize() + 1)
        title_font.setBold(True)
        self.title_label.setFont(title_font)
        self.header_layout.addWidget(self.title_label)

        self._header_spacer = QtWidgets.QWidget()
        self._header_spacer.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.Preferred,
        )
        self.header_layout.addWidget(self._header_spacer)

        wrapper.addLayout(self.header_layout)

        self.body_layout = QtWidgets.QVBoxLayout()
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(12)
        wrapper.addLayout(self.body_layout)

    def add_header_widget(self, widget: QtWidgets.QWidget) -> None:
        index = self.header_layout.indexOf(self._header_spacer)
        self.header_layout.insertWidget(index, widget)


class SalesDashboardWindow(QtWidgets.QMainWindow):
    def __init__(self, controller: DashboardController, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.setWindowTitle("Estadísticas de venta")
        self.resize(1280, 800)
        self.worker_pool = QtCore.QThreadPool(self)
        self._daily_points: List[Dict[str, float]] = []

        self._build_ui()
        self._connect_signals()
        self._apply_initial_state()

    # UI setup ---------------------------------------------------------
    def _build_ui(self) -> None:
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        main_layout = QtWidgets.QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.filter_bar = FilterBar()
        self.filter_bar.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        filter_container = QtWidgets.QFrame()
        filter_container.setFrameShape(QtWidgets.QFrame.NoFrame)
        filter_layout = QtWidgets.QVBoxLayout(filter_container)
        filter_layout.setContentsMargins(0, 0, 0, 0)
        filter_layout.setSpacing(0)
        filter_layout.addWidget(self.filter_bar)
        main_layout.addWidget(filter_container)

        divider = QtWidgets.QFrame()
        divider.setFrameShape(QtWidgets.QFrame.HLine)
        divider.setFrameShadow(QtWidgets.QFrame.Sunken)
        main_layout.addWidget(divider)

        self.scroll_area = QtWidgets.QScrollArea()
        self.scroll_area.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.scroll_area.setWidgetResizable(True)
        main_layout.addWidget(self.scroll_area)

        content = QtWidgets.QWidget()
        self.scroll_area.setWidget(content)
        content_layout = QtWidgets.QVBoxLayout(content)
        content_layout.setContentsMargins(24, 24, 24, 24)
        content_layout.setSpacing(24)

        self.period_label = QtWidgets.QLabel("Período: -")
        period_font = self.period_label.font()
        period_font.setPointSize(period_font.pointSize() + 1)
        period_font.setBold(True)
        self.period_label.setFont(period_font)
        content_layout.addWidget(self.period_label)

        kpi_frame = QtWidgets.QFrame()
        kpi_frame.setFrameShape(QtWidgets.QFrame.StyledPanel)
        kpi_layout = QtWidgets.QGridLayout(kpi_frame)
        kpi_layout.setContentsMargins(16, 16, 16, 16)
        kpi_layout.setHorizontalSpacing(16)
        kpi_layout.setVerticalSpacing(16)

        self.kpi_cards: Dict[str, KpiCard] = {
            "ventas": KpiCard("Ventas totales", "Ventas totales del período."),
            "transacciones": KpiCard("Transacciones", "Número de ventas (boletas/facturas)."),
            "ticket": KpiCard("Ticket promedio", "Ticket promedio: Ventas totales ÷ Transacciones del período."),
            "margen": KpiCard("Margen bruto", "Margen bruto: Ventas totales − CMV estimado."),
            "cmv": KpiCard("CMV estimado", "CMV estimado: Suma de costos unitarios de productos vendidos en el período."),
        }
        positions = {
            "ventas": (0, 0, 1, 1),
            "transacciones": (0, 1, 1, 1),
            "ticket": (1, 0, 1, 1),
            "margen": (1, 1, 1, 1),
            "cmv": (2, 0, 1, 2),
        }
        for key, card in self.kpi_cards.items():
            row, col, row_span, col_span = positions[key]
            kpi_layout.addWidget(card, row, col, row_span, col_span)
        kpi_layout.setColumnStretch(0, 1)
        kpi_layout.setColumnStretch(1, 1)
        content_layout.addWidget(kpi_frame)

        self.daily_section = SectionFrame("Tendencia diaria")
        self.daily_chart = ChartWidget()
        self.daily_section.body_layout.addWidget(self.daily_chart)
        content_layout.addWidget(self.daily_section)
        self.daily_chart.canvas.mpl_connect("motion_notify_event", self._on_daily_hover)

        split_container = QtWidgets.QWidget()
        split_container.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred
        )
        split_layout = QtWidgets.QHBoxLayout(split_container)
        split_layout.setContentsMargins(0, 0, 0, 0)
        split_layout.setSpacing(24)

        self.top_section = SectionFrame("Top productos")
        order_label = QtWidgets.QLabel("Ordenar por:")
        self.top_section.add_header_widget(order_label)
        self.top_order_combo = QtWidgets.QComboBox()
        self.top_order_combo.addItem("Ventas", "ventas")
        self.top_order_combo.addItem("Unidades", "unidades")
        self.top_order_combo.addItem("Margen", MARGIN_KEY)
        self.top_order_combo.addItem("Contribución", CONTRIBUTION_KEY)
        self.top_section.add_header_widget(self.top_order_combo)

        self.top_table = QtWidgets.QTableWidget(0, 5)
        self.top_table.setHorizontalHeaderLabels([
            "Producto",
            "Unidades",
            "Ventas",
            "Margen",
            "Contribución",
        ])
        self.top_table.horizontalHeader().setStretchLastSection(True)
        self.top_table.horizontalHeader().setHighlightSections(False)
        self.top_table.verticalHeader().setVisible(False)
        self.top_table.setAlternatingRowColors(True)
        self.top_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.top_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.top_table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.top_table.horizontalHeaderItem(3).setToolTip("Margen bruto: Ventas totales − CMV estimado.")
        self.top_table.horizontalHeaderItem(4).setToolTip("Contribución: Margen bruto ÷ Ventas totales.")
        self.top_section.body_layout.addWidget(self.top_table)

        self.top_empty_label = QtWidgets.QLabel("Sin productos destacados en este período")
        self.top_empty_label.setAlignment(QtCore.Qt.AlignCenter)
        self.top_empty_label.hide()
        self.top_section.body_layout.addWidget(self.top_empty_label)

        self.top_chart = ChartWidget("Top 5 (visual)")
        self.top_section.body_layout.addWidget(self.top_chart)

        self.channel_section = SectionFrame("Ventas por canal/vendedor")
        self.channel_table = QtWidgets.QTableWidget(0, 6)
        self.channel_table.setHorizontalHeaderLabels([
            "Canal/Vendedor",
            "Ventas",
            "Transacciones",
            "Ticket promedio",
            "Margen",
            "Contribución",
        ])
        self.channel_table.horizontalHeader().setStretchLastSection(True)
        self.channel_table.verticalHeader().setVisible(False)
        self.channel_table.setAlternatingRowColors(True)
        self.channel_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.channel_table.horizontalHeaderItem(4).setToolTip("Margen bruto: Ventas totales − CMV estimado.")
        self.channel_table.horizontalHeaderItem(5).setToolTip("Contribución: Margen bruto ÷ Ventas totales.")
        self.channel_section.body_layout.addWidget(self.channel_table)

        self.channel_empty_label = QtWidgets.QLabel("No hay ventas por canal en el período")
        self.channel_empty_label.setAlignment(QtCore.Qt.AlignCenter)
        self.channel_empty_label.hide()
        self.channel_section.body_layout.addWidget(self.channel_empty_label)

        self.channel_chart = ChartWidget("Participación por canal")
        self.channel_section.body_layout.addWidget(self.channel_chart)

        self.channel_note = QtWidgets.QLabel("* Los canales con menos del 3% de las ventas se agrupan en 'Otros'.")
        self.channel_note.setStyleSheet("color: #555555;")
        self.channel_section.body_layout.addWidget(self.channel_note)

        split_layout.addWidget(self.top_section, 1)
        split_layout.addWidget(self.channel_section, 1)

        content_layout.addWidget(split_container)

        self.stock_section = SectionFrame("Stock crítico")
        self.stock_table = QtWidgets.QTableWidget(0, 3)
        self.stock_table.setHorizontalHeaderLabels(["Producto", "Stock", "Rotación 30d"])
        self.stock_table.horizontalHeader().setStretchLastSection(True)
        self.stock_table.verticalHeader().setVisible(False)
        self.stock_table.setAlternatingRowColors(True)
        self.stock_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.stock_section.body_layout.addWidget(self.stock_table)

        self.stock_empty_label = QtWidgets.QLabel("Sin productos en estado crítico de stock")
        self.stock_empty_label.setAlignment(QtCore.Qt.AlignCenter)
        self.stock_empty_label.hide()
        self.stock_section.body_layout.addWidget(self.stock_empty_label)

        content_layout.addWidget(self.stock_section)
        content_layout.addStretch(1)

    def _connect_signals(self) -> None:
        self.filter_bar.filtersApplied.connect(self._on_filters_applied)
        self.top_order_combo.currentIndexChanged.connect(self._on_top_order_changed)

    def _apply_initial_state(self) -> None:
        self.filter_bar.set_timezone_label(self.controller.timezone_label())
        self.filter_bar.set_state(self.controller.state)
        self._refresh_dashboard()

    # Event handlers ---------------------------------------------------
    def _on_filters_applied(self, state: FilterState) -> None:
        if state.quick_range == QuickRange.PERSONALIZADO:
            self.controller.set_custom_dates(state.start, state.end)
        else:
            self.controller.set_quick_range(state.quick_range)
        self._refresh_dashboard()

    def _on_top_order_changed(self) -> None:
        metric = self.top_order_combo.currentData()
        self.controller.set_order_by(metric)
        self._refresh_dashboard(skip_filters=True)

    # Refresh logic ----------------------------------------------------
    def _refresh_dashboard(self, skip_filters: bool = False) -> None:
        self._set_loading_state()
        worker = DashboardWorker(self.controller)
        worker.signals.finished.connect(self._update_dashboard)
        worker.signals.error.connect(self._handle_error)
        self.worker_pool.start(worker)
        if not skip_filters:
            self.filter_bar.mark_applied(self.controller.state)

    def _set_loading_state(self) -> None:
        for card in self.kpi_cards.values():
            card.update_value("…", "")
        self.daily_chart.show_loading()
        self.top_chart.show_loading()
        self.channel_chart.show_loading()
        self.top_empty_label.hide()
        self.channel_empty_label.hide()
        self.channel_note.show()
        self.top_table.show()
        self.channel_table.show()
        self.stock_empty_label.hide()
        self.stock_table.show()

    def _update_dashboard(self, data: DashboardData) -> None:
        self.filter_bar.set_state(self.controller.state)
        self._update_period_label(self.controller.state)
        self._update_kpis(data)
        self._update_daily_chart(data)
        self._update_top_products(data)
        self._update_channels(data)
        self._update_stock(data)

    def _handle_error(self, message: str) -> None:
        QtWidgets.QMessageBox.critical(self, "Error", message)

    # UI update helpers ------------------------------------------------
    def _update_period_label(self, state: FilterState) -> None:
        if not state.start or not state.end:
            self.period_label.setText("Período: -")
            return
        self.period_label.setText(
            f"Período: {format_date(state.start)} – {format_date(state.end)}"
        )

    def _update_kpis(self, data: DashboardData) -> None:
        kpis = data.kpis
        trans_str = f"{kpis.transacciones:,}"
        self.kpi_cards["ventas"].update_value(format_currency(kpis.ventas), f"Transacciones: {trans_str}")
        self.kpi_cards["transacciones"].update_value(trans_str, f"Ticket promedio: {format_currency(kpis.ticket_promedio)}")
        self.kpi_cards["ticket"].update_value(
            format_currency(kpis.ticket_promedio), f"Ventas totales: {format_currency(kpis.ventas)}"
        )
        contrib = calcContribucion(kpis.margen_bruto, kpis.ventas)
        self.kpi_cards["margen"].update_value(
            format_currency(kpis.margen_bruto), f"Contribución: {format_percentage(contrib)}"
        )
        cmv_ratio = calcContribucion(kpis.cmv, kpis.ventas) if kpis.ventas else 0.0
        self.kpi_cards["cmv"].update_value(
            format_currency(kpis.cmv), f"Equivale al {format_percentage(cmv_ratio)} de las ventas"
        )

    def _update_daily_chart(self, data: DashboardData) -> None:
        df = data.daily
        if df.empty:
            self.daily_chart.show_empty("No hubo ventas en el período seleccionado")
            self._daily_points = []
            return
        canvas = self.daily_chart.canvas
        fig = canvas.figure
        fig.clear()
        ax = fig.add_subplot(111)
        x = list(range(len(df)))
        ax2 = ax.twinx()
        bars = ax.bar(x, df["transacciones"], color="#4E79A7", alpha=0.6, label="Transacciones")
        ax.set_ylabel("Transacciones")
        ax2.plot(x, df["ventas"], color="#F28E2B", marker="o", label="Ventas")
        ax2.set_ylabel("Ventas ($)")
        ax.set_xticks(x)
        labels = [format_date(row) for row in df["fecha"]]
        ax.set_xticklabels(labels, rotation=45, ha="right")
        ax.grid(True, axis="y", linestyle="--", alpha=0.3)
        fig.tight_layout()
        canvas.draw()
        self.daily_chart.show_canvas()
        self._daily_points = []
        for idx, row in df.iterrows():
            self._daily_points.append(
                {
                    "x": idx,
                    "fecha": format_date(row["fecha"]),
                    "ventas": format_currency(row["ventas"]),
                    "transacciones": f"{int(row['transacciones'])}",
                    "ticket": format_currency(row["ticket_promedio"]),
                }
            )

    def _on_daily_hover(self, event) -> None:
        if not self._daily_points or event.xdata is None or event.ydata is None:
            QtWidgets.QToolTip.hideText()
            return
        idx = int(round(event.xdata))
        if idx < 0 or idx >= len(self._daily_points):
            QtWidgets.QToolTip.hideText()
            return
        point = self._daily_points[idx]
        text = (
            f"{point['fecha']}\nVentas: {point['ventas']}\n"
            f"Transacciones: {point['transacciones']}\nTicket promedio: {point['ticket']}"
        )
        if event.guiEvent is not None:
            pos = self.daily_chart.canvas.mapToGlobal(event.guiEvent.pos())
            QtWidgets.QToolTip.showText(pos, text, self.daily_chart.canvas)

    def _update_top_products(self, data: DashboardData) -> None:
        records = data.top_products
        self.top_table.setRowCount(len(records))
        if not records:
            self.top_table.hide()
            self.top_empty_label.show()
            self.top_chart.show_empty("Sin productos destacados en este período")
            return
        self.top_table.show()
        self.top_empty_label.hide()
        for row_idx, record in enumerate(records):
            self._set_table_item(self.top_table, row_idx, 0, record.get("producto", ""))
            self._set_table_item(
                self.top_table,
                row_idx,
                1,
                f"{int(record.get('unidades', 0)):,}",
                alignment=QtCore.Qt.AlignRight,
            )
            self._set_table_item(
                self.top_table,
                row_idx,
                2,
                format_currency(record.get("ventas", 0.0)),
                alignment=QtCore.Qt.AlignRight,
            )
            self._set_table_item(
                self.top_table,
                row_idx,
                3,
                format_currency(record.get(MARGIN_KEY, 0.0)),
                alignment=QtCore.Qt.AlignRight,
            )
            self._set_table_item(
                self.top_table,
                row_idx,
                4,
                format_percentage(record.get(CONTRIBUTION_KEY, 0.0)),
                alignment=QtCore.Qt.AlignRight,
            )
        self.top_table.resizeColumnsToContents()
        self.top_table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)

        top5 = records[:5]
        fig = self.top_chart.canvas.figure
        fig.clear()
        ax = fig.add_subplot(111)
        metric_key = self.controller.order_by
        if metric_key == CONTRIBUTION_KEY:
            values = [item.get(metric_key, 0.0) * 100 for item in top5]
            axis_label = "Contribución (%)"
        else:
            values = [item.get(metric_key, 0.0) for item in top5]
            axis_label = {
                "ventas": "Ventas ($)",
                "unidades": "Unidades",
                MARGIN_KEY: "Margen ($)",
            }.get(metric_key, metric_key.capitalize())
        names = [item.get("producto", "") for item in top5]
        indices = list(range(len(top5)))
        ax.barh(indices[::-1], values[::-1], color="#59A14F")
        ax.set_yticks(indices[::-1])
        ax.set_yticklabels(names[::-1])
        ax.set_xlabel(axis_label)
        ax.grid(True, axis="x", linestyle="--", alpha=0.3)
        fig.tight_layout()
        self.top_chart.canvas.draw()
        self.top_chart.show_canvas()

    def _update_channels(self, data: DashboardData) -> None:
        df = data.channel_summary
        self.channel_table.setRowCount(len(df))
        if df.empty:
            self.channel_table.hide()
            self.channel_empty_label.show()
            self.channel_note.hide()
            self.channel_chart.show_empty("No hay ventas por canal en el período")
            return
        self.channel_table.show()
        self.channel_empty_label.hide()
        self.channel_note.show()
        for row_idx, row in df.iterrows():
            self._set_table_item(self.channel_table, row_idx, 0, row["canal"])
            self._set_table_item(
                self.channel_table,
                row_idx,
                1,
                format_currency(row["ventas"]),
                alignment=QtCore.Qt.AlignRight,
            )
            self._set_table_item(
                self.channel_table,
                row_idx,
                2,
                f"{int(row['transacciones']):,}",
                alignment=QtCore.Qt.AlignRight,
            )
            self._set_table_item(
                self.channel_table,
                row_idx,
                3,
                format_currency(row["ticket_promedio"]),
                alignment=QtCore.Qt.AlignRight,
            )
            self._set_table_item(
                self.channel_table,
                row_idx,
                4,
                format_currency(row[MARGIN_KEY]),
                alignment=QtCore.Qt.AlignRight,
            )
            self._set_table_item(
                self.channel_table,
                row_idx,
                5,
                format_percentage(row[CONTRIBUTION_KEY]),
                alignment=QtCore.Qt.AlignRight,
            )
        self.channel_table.resizeColumnsToContents()
        self.channel_table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)

        fig = self.channel_chart.canvas.figure
        fig.clear()
        ax = fig.add_subplot(111)
        ax.pie(
            df["ventas"],
            labels=df["canal"],
            autopct=lambda pct: f"{pct:.1f}%",
            startangle=90,
            colors=["#4E79A7", "#F28E2B", "#E15759", "#76B7B2", "#59A14F", "#EDC948"],
        )
        ax.axis("equal")
        fig.tight_layout()
        self.channel_chart.canvas.draw()
        self.channel_chart.show_canvas()

    def _update_stock(self, data: DashboardData) -> None:
        df = data.stock_alerts
        self.stock_table.setRowCount(len(df))
        if df.empty:
            self.stock_table.hide()
            self.stock_empty_label.show()
            return
        self.stock_table.show()
        self.stock_empty_label.hide()
        for row_idx, row in df.iterrows():
            self._set_table_item(self.stock_table, row_idx, 0, row["producto"])
            self._set_table_item(
                self.stock_table,
                row_idx,
                1,
                f"{row['stock']:,}",
                alignment=QtCore.Qt.AlignRight,
            )
            self._set_table_item(
                self.stock_table,
                row_idx,
                2,
                f"{row['rotacion_30d']:,}",
                alignment=QtCore.Qt.AlignRight,
            )
        self.stock_table.resizeColumnsToContents()
        self.stock_table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)

    def _set_table_item(
        self,
        table: QtWidgets.QTableWidget,
        row: int,
        column: int,
        text: str,
        alignment: QtCore.Qt.AlignmentFlag = QtCore.Qt.AlignLeft,
    ) -> None:
        item = QtWidgets.QTableWidgetItem(text)
        item.setTextAlignment(alignment | QtCore.Qt.AlignVCenter)
        table.setItem(row, column, item)


class WorkerSignals(QtCore.QObject):
    finished = QtCore.pyqtSignal(DashboardData)
    error = QtCore.pyqtSignal(str)


class DashboardWorker(QtCore.QRunnable):
    def __init__(self, controller: DashboardController) -> None:
        super().__init__()
        self.controller = controller
        self.signals = WorkerSignals()

    @QtCore.pyqtSlot()
    def run(self) -> None:
        try:
            data = self.controller.apply()
        except Exception as exc:  # pragma: no cover - defensive UI handling
            self.signals.error.emit(str(exc))
            return
        self.signals.finished.emit(data)
