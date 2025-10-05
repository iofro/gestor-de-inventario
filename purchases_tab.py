from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QDateEdit, QComboBox, QAbstractItemView, QHeaderView, QSizePolicy,
    QCheckBox,
)
from PyQt5.QtCore import Qt, QDate
from PyQt5.QtGui import QColor
from datetime import datetime, date, timedelta

from dialogs import CompraDetalleDialog, RegisterPurchaseDialog
import logging


logger = logging.getLogger(__name__)


class PurchasesTab(QWidget):
    """Tab to list and inspect purchases."""

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self._setup_ui()
        self.load_purchases()

    def refresh_filters(self):
        """Refresh distributor and vendor filter combos with current data."""
        self.distribuidor_combo.blockSignals(True)
        self.vendedor_combo.blockSignals(True)

        current_dist = self.distribuidor_combo.currentData()
        current_vend = self.vendedor_combo.currentData()

        self.distribuidor_combo.clear()
        self.distribuidor_combo.addItem("Todos", None)
        for d in self.manager._Distribuidores:
            self.distribuidor_combo.addItem(d["nombre"], d["id"])

        vendedores = self.manager.db.get_vendedores_distribuidores()
        self.vendedor_combo.clear()
        self.vendedor_combo.addItem("Todos", None)
        for v in vendedores:
            self.vendedor_combo.addItem(v["nombre"], v["id"])

        if current_dist in [d["id"] for d in self.manager._Distribuidores]:
            idx = self.distribuidor_combo.findData(current_dist)
            if idx >= 0:
                self.distribuidor_combo.setCurrentIndex(idx)
        else:
            self.distribuidor_combo.setCurrentIndex(0)

        if current_vend in [v["id"] for v in vendedores]:
            idx = self.vendedor_combo.findData(current_vend)
            if idx >= 0:
                self.vendedor_combo.setCurrentIndex(idx)
        else:
            self.vendedor_combo.setCurrentIndex(0)

        self.distribuidor_combo.blockSignals(False)
        self.vendedor_combo.blockSignals(False)

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Summary labels
        self.total_mes_label = QLabel()
        self.total_comision_label = QLabel()
        self.prod_mas_label = QLabel()
        self.dist_frec_label = QLabel()
        summary_layout = QHBoxLayout()
        summary_layout.addWidget(self.total_mes_label)
        summary_layout.addWidget(self.total_comision_label)
        summary_layout.addWidget(self.prod_mas_label)
        summary_layout.addWidget(self.dist_frec_label)
        layout.addLayout(summary_layout)

        # Filters
        filter_layout = QHBoxLayout()
        self.date_filter_cb = QCheckBox("Filtrar por fecha")
        self.quick_range = QComboBox()
        self.quick_range.addItems(["Personalizado", "Esta semana", "Este mes", "Este año"])
        self.date_from = QDateEdit(QDate.currentDate().addMonths(-1))
        self.date_from.setCalendarPopup(True)
        self.date_to = QDateEdit(QDate.currentDate())
        self.date_to.setCalendarPopup(True)
        self.distribuidor_combo = QComboBox()
        self.distribuidor_combo.addItem("Todos", None)
        for d in self.manager._Distribuidores:
            self.distribuidor_combo.addItem(d["nombre"], d["id"])
        self.vendedor_combo = QComboBox()
        self.vendedor_combo.addItem("Todos", None)
        for v in self.manager.db.get_vendedores_distribuidores():
            self.vendedor_combo.addItem(v["nombre"], v["id"])
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("ID o producto")

        self.quick_range.setEnabled(False)
        self.date_from.setEnabled(False)
        self.date_to.setEnabled(False)

        for w in [self.date_filter_cb, self.quick_range, QLabel("Desde"), self.date_from,
                  QLabel("Hasta"), self.date_to, self.distribuidor_combo,
                  self.vendedor_combo, self.search_bar]:
            filter_layout.addWidget(w)
        layout.addLayout(filter_layout)

        # Table and side buttons
        content_layout = QHBoxLayout()

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([
            "Fecha", "ID Compra", "Distribuidor", "Vendedor",
            "Total", "Comisión"
        ])
        self.table.verticalHeader().setDefaultSectionSize(60)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        content_layout.addWidget(self.table)

        side_layout = QVBoxLayout()
        self.btn_ver = QPushButton("Ver")
        self.btn_editar = QPushButton("Editar")
        side_layout.addWidget(self.btn_ver)
        side_layout.addWidget(self.btn_editar)
        side_layout.addStretch(1)
        content_layout.addLayout(side_layout)

        layout.addLayout(content_layout)

        # Connections
        self.date_filter_cb.toggled.connect(self._toggle_date_filter)
        self.quick_range.currentIndexChanged.connect(self._apply_quick_range)
        self.date_from.dateChanged.connect(self.load_purchases)
        self.date_to.dateChanged.connect(self.load_purchases)
        self.distribuidor_combo.currentIndexChanged.connect(self.load_purchases)
        self.vendedor_combo.currentIndexChanged.connect(self.load_purchases)
        self.search_bar.textChanged.connect(self.load_purchases)
        self.btn_ver.clicked.connect(self.show_selected_detail)
        self.btn_editar.clicked.connect(self.edit_selected_purchase)

    def _selected_compra_id(self):
        if self.table.currentRow() < 0:
            return None
        item = self.table.item(self.table.currentRow(), 1)
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
        compras = self.manager.db.get_compras()
        detalles_cache = {}
        productos = {p["id"]: p for p in self.manager.db.get_productos()}
        Distribuidores = {d["id"]: d["nombre"] for d in self.manager.db.get_Distribuidores()}
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
            dist = Distribuidores.get(c.get("Distribuidor_id"), "")
            vend = Vendedores.get(c.get("vendedor_id"), "")
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
            comision_total = 0.0
            for d in detalles_cache[c["id"]]:
                try:
                    comision_total += float(d.get("comision_monto", 0))
                except (TypeError, ValueError):
                    continue
            rows.append((c, dist, vend, comision_total, detalles_cache[c["id"]]))

        self.table.setRowCount(len(rows))
        total_mes = 0
        total_comision = 0
        prod_count = {}
        dist_count = {}
        today = date.today()

        for row, (compra, dist, vend, comision_total, detalles) in enumerate(rows):
            self.table.setItem(row, 0, QTableWidgetItem(compra.get("fecha", "")))
            self.table.setItem(row, 1, QTableWidgetItem(str(compra.get("id"))))
            self.table.setItem(row, 2, QTableWidgetItem(dist))
            self.table.setItem(row, 3, QTableWidgetItem(vend))
            self.table.setItem(row, 4, QTableWidgetItem(f"${compra.get('total', 0):.2f}"))
            self.table.setItem(row, 5, QTableWidgetItem(f"${comision_total:.2f}"))
            self.table.setRowHeight(row, 60)

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
            if compra.get("Distribuidor_id"):
                dist_count[compra["Distribuidor_id"]] = dist_count.get(compra["Distribuidor_id"], 0) + 1
            if expired:
                for col in range(6):
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
                total_comision += comision_total

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
        self.total_comision_label.setText(f"Comisiones: ${total_comision:.2f}")
        self.prod_mas_label.setText(f"Más comprado: {mas_prod}")
        self.dist_frec_label.setText(f"Distribuidor frecuente: {mas_dist}")

    def show_detail(self, compra_id):
        compras = self.manager.db.get_compras()
        compra = next((c for c in compras if c["id"] == compra_id), None)
        if not compra:
            return
        detalles = self.manager.db.get_detalles_compra(compra_id)
        dlg = CompraDetalleDialog(compra, detalles, self)
        dlg.exec_()

    def edit_purchase(self, compra_id):
        compras = self.manager.db.get_compras()
        compra = next((c for c in compras if c["id"] == compra_id), None)
        if not compra:
            return
        detalles = self.manager.db.get_detalles_compra(compra_id)

        productos = [dict(p) for p in self.manager.db.get_productos()]
        Distribuidores = [dict(d) for d in self.manager.db.get_Distribuidores()]
        proveedores = [dict(v) for v in self.manager.db.get_vendedores_distribuidores()]

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

