from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QDateEdit,
    QTableWidget,
    QAbstractItemView,
    QHeaderView,
    QPushButton,
    QSizePolicy,
)
from PyQt5.QtCore import QDate

class FacturacionVaciaTab(QWidget):
    """Pestaña de facturación con interfaz aún sin funcionalidades."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)

        # --- Barra de búsqueda ---
        search_layout = QHBoxLayout()
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Buscar por cliente o factura")
        search_layout.addWidget(self.search_bar)
        main_layout.addLayout(search_layout)

        # --- Filtros por fecha ---
        filter_layout = QHBoxLayout()
        self.date_from = QDateEdit(QDate.currentDate().addMonths(-1))
        self.date_from.setCalendarPopup(True)
        self.date_to = QDateEdit(QDate.currentDate())
        self.date_to.setCalendarPopup(True)
        filter_layout.addWidget(QLabel("Desde"))
        filter_layout.addWidget(self.date_from)
        filter_layout.addWidget(QLabel("Hasta"))
        filter_layout.addWidget(self.date_to)
        filter_layout.addStretch(1)
        main_layout.addLayout(filter_layout)

        # --- Información resumen ---
        info_layout = QHBoxLayout()
        self.total_label = QLabel("Total ventas: $0.00")
        self.count_label = QLabel("Número de ventas: 0")
        info_layout.addWidget(self.total_label)
        info_layout.addWidget(self.count_label)
        info_layout.addStretch(1)
        main_layout.addLayout(info_layout)

        # --- Tabla de facturas ---
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["ID", "Fecha", "Cliente", "Total", "Estado"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        main_layout.addWidget(self.table)

        # --- Botones de acciones ---
        btn_layout = QHBoxLayout()
        self.btn_ticket = QPushButton("Generar ticket")
        self.btn_debito = QPushButton("Generar nota de débito")
        self.btn_credito = QPushButton("Generar nota de crédito")
        self.btn_estado = QPushButton("Estado")
        btn_layout.addWidget(self.btn_ticket)
        btn_layout.addWidget(self.btn_debito)
        btn_layout.addWidget(self.btn_credito)
        btn_layout.addWidget(self.btn_estado)
        btn_layout.addStretch(1)
        main_layout.addLayout(btn_layout)

        self.btn_estado.clicked.connect(self.change_estado)

    def _selected_venta(self):
        if self.table.currentRow() < 0:
            return None
        item = self.table.item(self.table.currentRow(), 0)
        if item:
            try:
                return int(item.text())
            except ValueError:
                return None
        return None

    def change_estado(self):
        venta_id = self._selected_venta()
        if venta_id is None:
            return
        parent = self.parent()
        manager = getattr(parent, "manager", None) if parent else None
        if not manager:
            return
        venta = next((v for v in manager.db.get_ventas() if v["id"] == venta_id), None)
        if not venta:
            return
        from dialogs import EstadoVentaDialog
        dialog = EstadoVentaDialog(venta.get("estado", "Pagada"), self)
        if dialog.exec_():
            estado = dialog.get_estado()
            manager.db.update_venta_estado(venta_id, estado)


