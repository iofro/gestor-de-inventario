from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QDateEdit, QComboBox, QAbstractItemView, QHeaderView, QSizePolicy,
    QCheckBox, QMessageBox, QFrame
)
from PyQt5.QtCore import Qt, QDate, QSize, QPointF, QRectF
from PyQt5.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from datetime import datetime, date, timedelta

from dialogs import CompraDetalleDialog, RegisterPurchaseDialog
from utils.party_resolver import normalize_identifier, resolve_party_names
import logging


logger = logging.getLogger(__name__)


class HoverIconButton(QPushButton):
    """Flat icon button that swaps icon on hover for clearer affordance."""

    def __init__(self, role: str, normal_icon: QIcon, hover_icon: QIcon, parent=None) -> None:
        super().__init__(parent)
        self._normal_icon = normal_icon
        self._hover_icon = hover_icon or normal_icon
        self.setProperty("class", "table-icon-btn")
        self.setProperty("role", role)
        self.setCursor(Qt.PointingHandCursor)
        self.setFlat(True)
        self.setIcon(self._normal_icon)
        self.setIconSize(QSize(24, 24))
        self.setFixedSize(36, 36)
        self.setFocusPolicy(Qt.NoFocus)

    def enterEvent(self, event):  # noqa: N802
        self.setIcon(self._hover_icon)
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        self.setIcon(self._normal_icon)
        super().leaveEvent(event)


class PurchasesTab(QWidget):
    """Tab to list and inspect purchases."""

    _ACTION_ICON_COLORS = {
        "view": {"normal": "#94a3b8", "hover": "#475569"},
        "edit": {"normal": "#60a5fa", "hover": "#2563eb"},
        "delete": {"normal": "#fca5a5", "hover": "#ef4444"},
        "add": {"normal": "#ffffff", "hover": "#ffffff"},
    }
    _ICON_SIZE = 24

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self._compras_cache: dict[int, dict] = {}
        self._detalles_cache: dict[int, list[dict]] = {}
        self._icon_cache: dict[tuple[str, str], QIcon] = {}
        self._setup_ui()
        self.load_purchases()

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

    def refresh_filters(self):
        """Refresh distributor and vendor filter combos with current data."""
        self.distribuidor_combo.blockSignals(True)
        self.vendedor_combo.blockSignals(True)

        current_dist = self.distribuidor_combo.currentData()
        current_vend = self.vendedor_combo.currentData()

        self.distribuidor_combo.clear()
        self.distribuidor_combo.addItem("Todos", None)
        catalogs = getattr(self.manager, "catalogs", None)
        distributors = []
        if catalogs and catalogs.distributors:
            distributors = sorted(
                catalogs.distributors.values(),
                key=lambda entry: (entry.get("nombre") or "").lower(),
            )
        else:
            distributors = self.manager._Distribuidores
        for d in distributors:
            self.distribuidor_combo.addItem(d.get("nombre", ""), d.get("id"))

        if catalogs and catalogs.vendors:
            vendedores = sorted(
                catalogs.vendors.values(),
                key=lambda entry: (entry.get("nombre") or "").lower(),
            )
        else:
            vendedores = self.manager.db.get_vendedores_distribuidores()
        self.vendedor_combo.clear()
        self.vendedor_combo.addItem("Todos", None)
        for v in vendedores:
            self.vendedor_combo.addItem(v.get("nombre", ""), v.get("id"))

        if catalogs and catalogs.distributors:
            available_dist_ids = {normalize_identifier(d.get("id")) for d in catalogs.distributors.values()}
        else:
            available_dist_ids = {d["id"] for d in self.manager._Distribuidores}
        if current_dist in available_dist_ids:
            idx = self.distribuidor_combo.findData(current_dist)
            if idx >= 0:
                self.distribuidor_combo.setCurrentIndex(idx)
        else:
            self.distribuidor_combo.setCurrentIndex(0)

        if catalogs and catalogs.vendors:
            available_vend_ids = {normalize_identifier(v.get("id")) for v in catalogs.vendors.values()}
        else:
            available_vend_ids = {v["id"] for v in vendedores}
        if current_vend in available_vend_ids:
            idx = self.vendedor_combo.findData(current_vend)
            if idx >= 0:
                self.vendedor_combo.setCurrentIndex(idx)
        else:
            self.vendedor_combo.setCurrentIndex(0)

        self.distribuidor_combo.blockSignals(False)
        self.vendedor_combo.blockSignals(False)
    def _create_kpi_card(self, icon_text: str, title: str, value) -> QFrame:
        card = QFrame()
        card.setObjectName("ModernCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(6)

        icon_lbl = QLabel(icon_text)
        icon_font = icon_lbl.font()
        icon_font.setPointSize(icon_font.pointSize() + 6)
        icon_lbl.setFont(icon_font)
        layout.addWidget(icon_lbl, alignment=Qt.AlignLeft)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet("color: #6b7280; font-weight: 600;")
        layout.addWidget(title_lbl)

        if isinstance(value, QLabel):
            value_lbl = value
        else:
            value_lbl = QLabel(str(value))
        val_font = value_lbl.font()
        val_font.setPointSize(val_font.pointSize() + 4)
        val_font.setBold(True)
        value_lbl.setFont(val_font)
        layout.addWidget(value_lbl)

        return card

    def _create_line_icon(self, kind: str, color: QColor, size: int | None = None) -> QIcon:
        icon_size = size or self._ICON_SIZE
        pixmap = QPixmap(icon_size, icon_size)
        pixmap.fill(Qt.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(color)
        pen.setWidthF(2.1)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)

        if kind == "view":
            center_y = icon_size / 2
            width = icon_size * 0.7
            height = icon_size * 0.4
            left = (icon_size - width) / 2
            top = center_y - height / 2
            path = QPainterPath()
            path.moveTo(left, center_y)
            path.quadTo(left + width / 2, top, left + width, center_y)
            path.quadTo(left + width / 2, top + height, left, center_y)
            painter.drawPath(path)
            pupil_radius = icon_size * 0.08
            painter.setBrush(color)
            painter.drawEllipse(QPointF(icon_size / 2, center_y), pupil_radius, pupil_radius)
        elif kind == "edit":
            body = QPainterPath()
            body.moveTo(icon_size * 0.28, icon_size * 0.70)
            body.lineTo(icon_size * 0.72, icon_size * 0.26)
            painter.drawPath(body)
            painter.drawLine(QPointF(icon_size * 0.62, icon_size * 0.20), QPointF(icon_size * 0.80, icon_size * 0.38))
            painter.drawLine(QPointF(icon_size * 0.30, icon_size * 0.72), QPointF(icon_size * 0.42, icon_size * 0.84))
        elif kind == "delete":
            painter.drawRoundedRect(QRectF(icon_size * 0.30, icon_size * 0.34, icon_size * 0.40, icon_size * 0.42), 3, 3)
            painter.drawLine(QPointF(icon_size * 0.34, icon_size * 0.30), QPointF(icon_size * 0.66, icon_size * 0.30))
            painter.drawLine(QPointF(icon_size * 0.48, icon_size * 0.24), QPointF(icon_size * 0.52, icon_size * 0.24))
            painter.drawLine(QPointF(icon_size * 0.38, icon_size * 0.42), QPointF(icon_size * 0.38, icon_size * 0.66))
            painter.drawLine(QPointF(icon_size * 0.50, icon_size * 0.42), QPointF(icon_size * 0.50, icon_size * 0.66))
            painter.drawLine(QPointF(icon_size * 0.62, icon_size * 0.42), QPointF(icon_size * 0.62, icon_size * 0.66))
        else:  # add or fallback
            painter.drawLine(QPointF(icon_size * 0.50, icon_size * 0.24), QPointF(icon_size * 0.50, icon_size * 0.76))
            painter.drawLine(QPointF(icon_size * 0.24, icon_size * 0.50), QPointF(icon_size * 0.76, icon_size * 0.50))

        painter.end()
        return QIcon(pixmap)

    def _get_icon(self, kind: str, tone: str = "normal") -> QIcon:
        key = (kind, tone)
        if key not in self._icon_cache:
            palette = self._ACTION_ICON_COLORS.get(kind, self._ACTION_ICON_COLORS["view"])
            color_hex = palette.get(tone, palette.get("normal", "#94a3b8"))
            self._icon_cache[key] = self._create_line_icon(kind, QColor(color_hex))
        return self._icon_cache[key]

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(30, 30, 30, 30)
        main_layout.setSpacing(25)

        # KPI cards
        kpi_layout = QHBoxLayout()
        kpi_layout.setSpacing(12)
        self.total_mes_label = QLabel("$0.00")
        self.total_comision_label = QLabel("$0.00")
        self.prod_mas_label = QLabel("—")
        self.dist_frec_label = QLabel("—")
        kpi_layout.addWidget(self._create_kpi_card("💰", "Comprado este mes", self.total_mes_label))
        self.total_compras_label = QLabel("0")
        kpi_layout.addWidget(self._create_kpi_card("🧾", "Número de compras", self.total_compras_label))
        kpi_layout.addWidget(self._create_kpi_card("🏆", "Más comprado", self.prod_mas_label))
        kpi_layout.addWidget(self._create_kpi_card("🏢", "Distribuidor frecuente", self.dist_frec_label))
        kpi_layout.addStretch(1)
        main_layout.addLayout(kpi_layout)

        # Main card
        main_card = QFrame()
        main_card.setObjectName("ModernCard")
        card_layout = QVBoxLayout(main_card)
        card_layout.setContentsMargins(16, 16, 16, 16)
        card_layout.setSpacing(12)

        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)
        header_layout.addStretch(1)
        self.new_purchase_btn = QPushButton("Nueva compra")
        self.new_purchase_btn.setObjectName("PrimaryActionButton")
        self.new_purchase_btn.setCursor(Qt.PointingHandCursor)
        self.new_purchase_btn.setIcon(self._get_icon("add"))
        self.new_purchase_btn.setIconSize(QSize(22, 22))
        self.new_purchase_btn.setToolTip("Registrar una nueva compra")
        self.new_purchase_btn.setMinimumHeight(48)
        self.new_purchase_btn.setStyleSheet("font-size: 16px; padding: 12px 18px;")
        header_layout.addWidget(self.new_purchase_btn, alignment=Qt.AlignRight)
        card_layout.addLayout(header_layout)

        # Filters row
        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(8)
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Buscar compra por ID o producto...")
        self.search_bar.setMinimumHeight(48)
        self.search_bar.setStyleSheet("font-size: 15px;")
        filter_layout.addWidget(self.search_bar, 2)

        self.date_filter_cb = QCheckBox("Filtrar por fecha")
        self.date_filter_cb.setStyleSheet("font-size: 14px;")
        self.quick_range = QComboBox()
        self.quick_range.addItems(["Personalizado", "Esta semana", "Este mes", "Este año"])
        self.quick_range.setMinimumHeight(42)
        self.quick_range.setStyleSheet("font-size: 14px;")
        self.date_from = QDateEdit(QDate.currentDate().addMonths(-1))
        self.date_from.setCalendarPopup(True)
        self.date_from.setMinimumHeight(42)
        self.date_from.setStyleSheet("font-size: 14px;")
        self.date_to = QDateEdit(QDate.currentDate())
        self.date_to.setCalendarPopup(True)
        self.date_to.setMinimumHeight(42)
        self.date_to.setStyleSheet("font-size: 14px;")
        self.distribuidor_combo = QComboBox()
        self.distribuidor_combo.addItem("Todos", None)
        self.distribuidor_combo.setMinimumHeight(42)
        self.distribuidor_combo.setStyleSheet("font-size: 14px;")
        catalogs = getattr(self.manager, "catalogs", None)
        distributors = []
        if catalogs and catalogs.distributors:
            distributors = sorted(
                catalogs.distributors.values(),
                key=lambda entry: (entry.get("nombre") or "").lower(),
            )
        else:
            distributors = self.manager._Distribuidores
        for d in distributors:
            self.distribuidor_combo.addItem(d.get("nombre", ""), d.get("id"))
        self.vendedor_combo = QComboBox()
        self.vendedor_combo.addItem("Todos", None)
        self.vendedor_combo.setMinimumHeight(42)
        self.vendedor_combo.setStyleSheet("font-size: 14px;")
        if catalogs and catalogs.vendors:
            vendors = sorted(
                catalogs.vendors.values(),
                key=lambda entry: (entry.get("nombre") or "").lower(),
            )
        else:
            vendors = self.manager.db.get_vendedores_distribuidores()
        for v in vendors:
            self.vendedor_combo.addItem(v.get("nombre", ""), v.get("id"))

        self.quick_range.setEnabled(False)
        self.date_from.setEnabled(False)
        self.date_to.setEnabled(False)

        for w in [
            self.date_filter_cb,
            self.quick_range,
            QLabel("Desde"),
            self.date_from,
            QLabel("Hasta"),
            self.date_to,
            self.distribuidor_combo,
            self.vendedor_combo,
        ]:
            filter_layout.addWidget(w)
        filter_layout.addStretch(1)
        card_layout.addLayout(filter_layout)

        # Table
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels([
            "Fecha", "ID Compra", "Distribuidor", "Vendedor",
            "Total", "Sujeto excluido", "DTE SE", "Acciones"
        ])
        self.table.verticalHeader().hide()
        self.table.setFrameShape(QFrame.NoFrame)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().setDefaultSectionSize(72)
        self.table.setStyleSheet("font-size: 14px;")
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(7, QHeaderView.ResizeToContents)
        header.setDefaultAlignment(Qt.AlignCenter)
        card_layout.addWidget(self.table)

        # Placeholder for pagination (if added later)
        self.pagination_layout = QHBoxLayout()
        self.pagination_layout.addStretch(1)
        card_layout.addLayout(self.pagination_layout)

        main_layout.addWidget(main_card)

        # Connections
        self.new_purchase_btn.clicked.connect(self._handle_new_purchase)
        self.date_filter_cb.toggled.connect(self._toggle_date_filter)
        self.quick_range.currentIndexChanged.connect(self._apply_quick_range)
        self.date_from.dateChanged.connect(self.load_purchases)
        self.date_to.dateChanged.connect(self.load_purchases)
        self.distribuidor_combo.currentIndexChanged.connect(self.load_purchases)
        self.vendedor_combo.currentIndexChanged.connect(self.load_purchases)
        self.search_bar.textChanged.connect(self.load_purchases)

    def _set_action_cell(self, row: int):
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignCenter)

        btn_view = QPushButton("📄", container)
        btn_view.setProperty("class", "table-icon-btn")
        btn_view.setStyleSheet("color: #475569; font-size: 20px;")
        btn_view.setFixedSize(52, 48)
        btn_view.setToolTip("Ver detalles")
        btn_view.clicked.connect(lambda _, r=row: self._select_and_show(r))

        btn_edit = QPushButton("✏️", container)
        btn_edit.setProperty("class", "table-icon-btn")
        btn_edit.setStyleSheet("color: #2563EB; font-size: 20px;")
        btn_edit.setFixedSize(52, 48)
        btn_edit.setToolTip("Editar compra")
        btn_edit.clicked.connect(lambda _, r=row: self._select_and_edit(r))

        btn_delete = QPushButton("🗑️", container)
        btn_delete.setProperty("class", "table-icon-btn")
        btn_delete.setStyleSheet("color: #DC2626; font-size: 20px;")
        btn_delete.setFixedSize(52, 48)
        btn_delete.setToolTip("Eliminar compra")
        btn_delete.clicked.connect(lambda _, r=row: self._select_and_delete(r))

        layout.addWidget(btn_view)
        layout.addWidget(btn_edit)
        layout.addWidget(btn_delete)
        self.table.setCellWidget(row, 7, container)

    def _handle_new_purchase(self):
        parent = self.parent()
        if parent and hasattr(parent, "registrar_compra"):
            parent.registrar_compra()
            return

        try:
            productos = [dict(p) for p in self.manager.db.get_productos()]
            distribuidores = [dict(d) for d in self.manager.db.get_Distribuidores()]
            proveedores = [dict(v) for v in self.manager.db.get_vendedores_distribuidores()]
        except Exception:  # pragma: no cover - defensive UI handling
            logger.exception("No se pudo cargar catálogos para registrar compra desde pestaña de compras")
            QMessageBox.critical(
                self,
                "Registrar compra",
                "No fue posible cargar la información necesaria para registrar la compra.",
            )
            return

        dlg = RegisterPurchaseDialog(productos, distribuidores, proveedores, self)
        if dlg.exec_() == dlg.Accepted:
            try:
                self.manager.refresh_data()
            except Exception:  # pragma: no cover - defensive UI handling
                logger.exception("Error al refrescar datos tras nueva compra")
            self.refresh_filters()
            self.load_purchases()
            if parent and hasattr(parent, "_actualizar_inventario_actual"):
                try:
                    parent._actualizar_inventario_actual()
                except Exception:  # pragma: no cover - keep UI responsive
                    logger.exception("No se pudo refrescar inventario actual tras nueva compra")
            if parent and hasattr(parent, "_refresh_pos_if_available"):
                try:
                    parent._refresh_pos_if_available()
                except Exception:  # pragma: no cover - keep UI responsive
                    logger.exception("No se pudo refrescar POS tras nueva compra")
            if parent and hasattr(parent, "data_changed"):
                parent.data_changed.emit()

    def _select_and_show(self, row: int):
        if row >= 0:
            self.table.selectRow(row)
            self.show_selected_detail()

    def _select_and_edit(self, row: int):
        if row >= 0:
            self.table.selectRow(row)
            self.edit_selected_purchase()

    def _select_and_delete(self, row: int):
        if row >= 0:
            self.table.selectRow(row)
            self.delete_selected_purchase()

    def _selected_compra_id(self):
        row = self.table.currentRow()
        if row < 0:
            selection = self.table.selectionModel()
            if not selection:
                return None
            selected_rows = selection.selectedRows()
            if not selected_rows:
                return None
            row = selected_rows[0].row()
        item = self.table.item(row, 1)
        if not item:
            return None
        try:
            return int(item.text())
        except ValueError:
            return None

    def show_selected_detail(self):
        compra_id = self._selected_compra_id()
        if compra_id is not None:
            self.show_detail(compra_id)

    def edit_selected_purchase(self):
        compra_id = self._selected_compra_id()
        if compra_id is not None:
            self.edit_purchase(compra_id)

    def delete_selected_purchase(self):
        compra_id = self._selected_compra_id()
        if compra_id is None:
            QMessageBox.warning(
                self,
                "Eliminar compra",
                "Seleccione una compra para eliminar.",
            )
            return
        self.delete_purchase(compra_id)

    def delete_purchase(self, compra_id: int):
        compra = self._compras_cache.get(compra_id)
        if not compra:
            compra = self.manager.db.get_compra(compra_id)
        if not compra:
            QMessageBox.warning(
                self,
                "Compra no encontrada",
                "No fue posible cargar la compra seleccionada. Intente nuevamente.",
            )
            return

        if not self._confirm_inventory_conflict("esta compra"):
            return

        confirm = QMessageBox.question(
            self,
            "Eliminar compra",
            f"¿Está seguro de eliminar la compra #{compra_id}? Esta acción deshará el ingreso de sus lotes al inventario.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        try:
            self.manager.delete_compra(compra_id)
        except ValueError as exc:
            QMessageBox.warning(self, "Eliminar compra", str(exc))
            return
        except Exception as exc:  # pragma: no cover - defensive UI handling
            logger.exception("Error al eliminar la compra %s", compra_id)
            QMessageBox.critical(
                self,
                "Eliminar compra",
                "Ocurrió un error al eliminar la compra seleccionada.",
            )
            return

        self._compras_cache.pop(compra_id, None)
        self._detalles_cache.pop(compra_id, None)
        self.load_purchases()

        parent = self.parent()
        if parent and hasattr(parent, "_actualizar_inventario_actual"):
            try:
                parent._actualizar_inventario_actual()
            except Exception:  # pragma: no cover - keep UI responsive
                logger.exception("No se pudo refrescar el inventario actual tras eliminar la compra")
        if parent and hasattr(parent, "_refresh_pos_if_available"):
            try:
                parent._refresh_pos_if_available()
            except Exception:  # pragma: no cover - keep UI responsive
                logger.exception("No se pudo refrescar POS tras eliminar la compra")
        if parent and hasattr(parent, "data_changed"):
            parent.data_changed.emit()

        QMessageBox.information(
            self,
            "Eliminar compra",
            "La compra seleccionada se eliminó correctamente.",
        )

    def _toggle_date_filter(self, checked):
        self.quick_range.setEnabled(checked)
        custom = self.quick_range.currentIndex() == 0
        self.date_from.setEnabled(checked and custom)
        self.date_to.setEnabled(checked and custom)
        if checked:
            self._apply_quick_range()
        else:
            self.load_purchases()

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
        self.load_purchases()
    def load_purchases(self):
        catalogs = getattr(self.manager, "catalogs", None)
        compras = self.manager.db.get_compras()
        self._compras_cache = {
            c.get("id"): c
            for c in compras
            if isinstance(c, dict) and c.get("id") is not None
        }
        detalles_cache: dict[int, list[dict]] = {}
        if catalogs and catalogs.products:
            productos = catalogs.products
            Distribuidores = {
                did: info.get("nombre", "")
                for did, info in catalogs.distributors.items()
            }
            Vendedores = {
                vid: info.get("nombre", "")
                for vid, info in catalogs.vendors.items()
            }
        else:
            productos = {p["id"]: p for p in self.manager.db.get_productos()}
            Distribuidores = {
                d["id"]: d["nombre"] for d in self.manager.db.get_Distribuidores()
            }
            Vendedores = {
                v["id"]: v["nombre"]
                for v in self.manager.db.get_vendedores_distribuidores()
            }

        if self.date_filter_cb.isChecked():
            d_from = self.date_from.date().toPyDate()
            d_to = self.date_to.date().toPyDate()
        else:
            d_from = d_to = None
        dist_filter = self.distribuidor_combo.currentData()
        vend_filter = self.vendedor_combo.currentData()
        search = self.search_bar.text().lower()

        def _parse_fecha(value):
            if isinstance(value, datetime):
                return value
            if isinstance(value, date):
                return datetime.combine(value, datetime.min.time())
            if isinstance(value, str):
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
                    try:
                        return datetime.strptime(value, fmt)
                    except ValueError:
                        continue
            return datetime.min

        rows = []
        for c in compras:
            fecha = c.get("fecha")
            fdate = None
            if isinstance(fecha, str):
                try:
                    fdate = datetime.strptime(fecha, "%Y-%m-%d %H:%M:%S").date()
                except (ValueError, TypeError):
                    try:
                        fdate = datetime.strptime(fecha, "%Y-%m-%d").date()
                    except (ValueError, TypeError):
                        fdate = None
            if self.date_filter_cb.isChecked() and fdate and (
                (d_from and fdate < d_from) or (d_to and fdate > d_to)
            ):
                continue
            vend, dist = resolve_party_names(c, catalogs)
            if dist_filter and c.get("Distribuidor_id") != dist_filter:
                continue
            if vend_filter and c.get("vendedor_id") != vend_filter:
                continue
            if search:
                if search not in str(c.get("id", "")).lower():
                    detalles_cache[c["id"]] = detalles_cache.get(c["id"], self.manager.db.get_detalles_compra(c["id"]))
                    nombres = ", ".join(
                        productos.get(d["producto_id"], {}).get("nombre", "")
                        for d in detalles_cache[c["id"]]
                    ).lower()
                    if search not in nombres:
                        continue
            detalles_cache[c["id"]] = detalles_cache.get(c["id"], self.manager.db.get_detalles_compra(c["id"]))
            rows.append((c, dist, vend, 0.0, detalles_cache[c["id"]]))

        rows.sort(key=lambda entry: _parse_fecha(entry[0].get("fecha")), reverse=True)

        # Mantener los detalles en caché para reutilizarlos al mostrar el
        # diálogo de detalle.  Esto evita consultas redundantes y nos
        # garantiza que el botón "Ver" siempre recupere la misma información
        # que se usó para renderizar la tabla.
        self._detalles_cache = detalles_cache

        self.table.setRowCount(len(rows))
        total_mes = 0
        total_count = len(rows)
        prod_count = {}
        dist_count = {}
        today = date.today()

        def _center_item(text: str) -> QTableWidgetItem:
            item = QTableWidgetItem(text)
            item.setTextAlignment(Qt.AlignCenter)
            return item

        for row, (compra, dist, vend, _comision_total, detalles) in enumerate(rows):
            self.table.setItem(row, 0, _center_item(compra.get("fecha", "")))
            self.table.setItem(row, 1, _center_item(str(compra.get("id"))))
            self.table.setItem(row, 2, _center_item(dist))
            self.table.setItem(row, 3, _center_item(vend))
            self.table.setItem(row, 4, _center_item(f"${compra.get('total', 0):.2f}"))
            is_subject = bool(compra.get("is_subject_excluded_purchase"))
            dte_status = compra.get("subject_excluded_dte_status", "NO_APLICA") or "NO_APLICA"
            self.table.setItem(row, 5, _center_item("Sí" if is_subject else "No"))
            self.table.setItem(row, 6, _center_item(dte_status))
            self._set_action_cell(row)
            self.table.setRowHeight(row, 78)

            expired = False
            for d in detalles:
                fv = d.get("fecha_vencimiento")
                if fv:
                    try:
                        fv_date = datetime.strptime(fv, "%Y-%m-%d").date()
                        if fv_date < today:
                            expired = True
                    except (ValueError, TypeError):
                        logger.exception("Fecha de vencimiento inválida: %s", fv)
                prod_count[d["producto_id"]] = prod_count.get(d["producto_id"], 0) + d.get("cantidad", 0)
            dist_id = normalize_identifier(compra.get("Distribuidor_id"))
            if dist_id is not None:
                dist_count[dist_id] = dist_count.get(dist_id, 0) + 1
            if expired:
                for col in range(self.table.columnCount()):
                    item = self.table.item(row, col)
                    if item:
                        item.setBackground(QColor("#ffcccc"))

            try:
                fdate = datetime.strptime(compra.get("fecha", ""), "%Y-%m-%d %H:%M:%S").date()
            except ValueError:
                try:
                    fdate = datetime.strptime(compra.get("fecha", ""), "%Y-%m-%d").date()
                except ValueError:
                    fdate = None
            if fdate and fdate.year == today.year and fdate.month == today.month:
                total_mes += compra.get("total", 0)

        if prod_count:
            prod_id = max(prod_count, key=prod_count.get)
            mas_prod = productos.get(prod_id, {}).get("nombre", "")
        else:
            mas_prod = ""
        if dist_count:
            dist_id = max(dist_count, key=dist_count.get)
            mas_dist = Distribuidores.get(dist_id, "")
        else:
            mas_dist = ""
        self.total_mes_label.setText(f"Comprado este mes: ${total_mes:.2f}")
        self.total_compras_label.setText(str(total_count))
        self.prod_mas_label.setText(f"Más comprado: {mas_prod}")
        self.dist_frec_label.setText(f"Distribuidor frecuente: {mas_dist}")

    def refresh_purchases(self):
        try:
            self.manager.refresh_data()
        except Exception:  # pragma: no cover - defensive UI handling
            logger.exception("Error al refrescar los datos de compras")
            QMessageBox.critical(
                self,
                "Actualizar compras",
                "Ocurrió un error al intentar actualizar la información. Intente nuevamente.",
            )
            return

        self.refresh_filters()
        self.load_purchases()

    def show_detail(self, compra_id):
        logger.info(
            "Compras: solicitando detalle para compra %s (fila seleccionada)",
            compra_id,
        )

        cached_compra = self._compras_cache.get(compra_id)
        if cached_compra:
            logger.info(
                "Compras: compra %s obtenida desde caché local", compra_id
            )
        else:
            logger.info(
                "Compras: compra %s no está en caché", compra_id
            )

        logger.info(
            "Compras: refrescando compra %s desde base de datos para obtener últimos datos",
            compra_id,
        )
        compra = self.manager.db.get_compra(compra_id)
        if compra:
            logger.info(
                "Compras: compra %s recuperada desde base de datos", compra_id
            )
            self._compras_cache[compra_id] = compra
        else:
            logger.warning(
                "Compras: no fue posible refrescar la compra %s desde base de datos, usando caché",
                compra_id,
            )
            compra = cached_compra

        if not compra:
            logger.warning(
                "Compras: no se encontró información para la compra %s", compra_id
            )
            QMessageBox.warning(
                self,
                "Compra no encontrada",
                "No fue posible cargar la compra seleccionada. Intente nuevamente.",
            )
            return

        detalles = self._detalles_cache.get(compra_id)
        if detalles is None:
            logger.info(
                "Compras: detalles de compra %s no están en caché, consultando base de datos",
                compra_id,
            )
            detalles = self.manager.db.get_detalles_compra(compra_id)
            logger.info(
                "Compras: se recibieron %s partidas para la compra %s",
                len(detalles) if detalles is not None else 0,
                compra_id,
            )
            self._detalles_cache[compra_id] = detalles
        else:
            logger.info(
                "Compras: utilizando %s partidas en caché para la compra %s",
                len(detalles),
                compra_id,
            )

        catalogs = getattr(self.manager, "catalogs", None)
        dlg = CompraDetalleDialog(compra, detalles, self, catalogs=catalogs)
        dlg.exec_()

    def edit_purchase(self, compra_id):
        compra = self.manager.db.get_compra(compra_id)
        if not compra:
            compra = self._compras_cache.get(compra_id)
        if not compra:
            QMessageBox.warning(
                self,
                "Compra no encontrada",
                "No fue posible cargar la compra seleccionada. Intente nuevamente.",
            )
            return
        detalles = self.manager.db.get_detalles_compra(compra_id)

        productos = [dict(p) for p in self.manager.db.get_productos()]
        Distribuidores = [dict(d) for d in self.manager.db.get_Distribuidores()]
        proveedores = [dict(v) for v in self.manager.db.get_vendedores_distribuidores()]

        if not self._confirm_inventory_conflict("esta compra"):
            return

        dlg = RegisterPurchaseDialog(
            productos,
            Distribuidores,
            proveedores,
            self,
            compra=compra,
            detalles=detalles,
        )
        if dlg.exec_() == dlg.Accepted:
            self.manager.refresh_data()
            self.refresh_filters()
            self.load_purchases()
            parent = self.parent()
            if parent and hasattr(parent, "_actualizar_inventario_actual"):
                try:
                    parent._actualizar_inventario_actual()
                except Exception:  # pragma: no cover - keep UI responsive
                    logger.exception("No se pudo refrescar inventario actual tras editar compra")
            if parent and hasattr(parent, "_refresh_pos_if_available"):
                try:
                    parent._refresh_pos_if_available()
                except Exception:  # pragma: no cover - keep UI responsive
                    logger.exception("No se pudo refrescar POS tras editar compra")
