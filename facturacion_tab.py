from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QPushButton,
    QFileDialog,
    QInputDialog,
    QMessageBox,
    QLineEdit,
    QDateEdit,
    QAbstractItemView,
    QHeaderView,
)
from PyQt5.QtCore import QDate

from ticket_pdf import generar_ticket_personalizado
import json
from datetime import datetime


class FacturacionTab(QWidget):
    """Tab para gestionar facturas y notas."""

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self._setup_ui()
        self.load_invoices()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)

        filter_layout = QHBoxLayout()
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Buscar número o cliente")
        filter_layout.addWidget(self.search_bar)
        self.date_from = QDateEdit(QDate.currentDate().addYears(-2))
        self.date_from.setCalendarPopup(True)
        self.date_to = QDateEdit(QDate.currentDate())
        self.date_to.setCalendarPopup(True)
        filter_layout.addWidget(self.date_from)
        filter_layout.addWidget(self.date_to)
        self.update_btn = QPushButton("Actualizar")
        filter_layout.addWidget(self.update_btn)
        filter_layout.addStretch(1)
        main_layout.addLayout(filter_layout)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["ID", "Fecha", "Cliente", "Total", "Estado"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        main_layout.addWidget(self.table)

        btns = QHBoxLayout()
        self.btn_ticket = QPushButton("Generar ticket virtual")
        self.btn_credito = QPushButton("Nota de crédito")
        self.btn_debito = QPushButton("Nota de débito")
        self.btn_estado = QPushButton("Estado")
        btns.addWidget(self.btn_ticket)
        btns.addWidget(self.btn_credito)
        btns.addWidget(self.btn_debito)
        btns.addWidget(self.btn_estado)
        btns.addStretch(1)
        main_layout.addLayout(btns)

        # Connect signals
        self.update_btn.clicked.connect(self.load_invoices)
        self.search_bar.textChanged.connect(self.load_invoices)
        self.date_from.dateChanged.connect(self.load_invoices)
        self.date_to.dateChanged.connect(self.load_invoices)
        
        self.btn_ticket.clicked.connect(self.create_ticket)
        self.btn_credito.clicked.connect(lambda: self.create_nota("credito"))
        self.btn_debito.clicked.connect(lambda: self.create_nota("debito"))
        self.btn_estado.clicked.connect(self.change_estado)

    def load_invoices(self):
        ventas = self.manager.db.get_ventas()
        clientes = {c["id"]: c["nombre"] for c in self.manager._clientes}
        search = self.search_bar.text().lower() if hasattr(self, "search_bar") else ""
        d_from = self.date_from.date().toPyDate() if hasattr(self, "date_from") else None
        d_to = self.date_to.date().toPyDate() if hasattr(self, "date_to") else None

        rows = []
        for v in ventas:
            fecha = v.get("fecha", "")
            try:
                fdate = datetime.strptime(fecha.split()[0], "%Y-%m-%d").date()
            except Exception:
                fdate = None
            if d_from and fdate and fdate < d_from:
                continue
            if d_to and fdate and fdate > d_to:
                continue
            cliente = clientes.get(v.get("cliente_id"), "")
            if search and search not in str(v.get("id", "")).lower() and search not in cliente.lower():
                continue
            rows.append(v)

        self.table.setRowCount(len(rows))
        for row, v in enumerate(rows):
            self.table.setItem(row, 0, QTableWidgetItem(str(v.get("id"))))
            self.table.setItem(row, 1, QTableWidgetItem(v.get("fecha", "")))
            self.table.setItem(row, 2, QTableWidgetItem(clientes.get(v.get("cliente_id"), "")))
            self.table.setItem(row, 3, QTableWidgetItem(f"${v.get('total', 0):.2f}"))
            self.table.setItem(row, 4, QTableWidgetItem(v.get("estado", "")))
        if rows:
            self.table.selectRow(0)

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

    def create_ticket(self):
        venta_id = self._selected_venta()
        if venta_id is None:
            QMessageBox.warning(self, "Ticket", "Seleccione una venta")
            return
        venta = next((v for v in self.manager.db.get_ventas() if v["id"] == venta_id), None)
        detalles = self.manager.db.get_detalles_venta(venta_id)
        extra = {}
        raw_extra = venta.get("extra") if venta else None
        if raw_extra:
            try:
                extra = json.loads(raw_extra)
            except Exception:
                extra = {}
        fname, _ = QFileDialog.getSaveFileName(self, "Guardar ticket", "ticket.pdf", "PDF (*.pdf)")
        if not fname:
            return
        generar_ticket_personalizado(venta, detalles, fname, dte_data=extra)
        QMessageBox.information(self, "Ticket", "Ticket generado correctamente")

    def create_nota(self, tipo):
        venta_id = self._selected_venta()
        if venta_id is None:
            QMessageBox.warning(self, "Nota", "Seleccione una venta")
            return
        monto, ok = QInputDialog.getDouble(self, "Monto", "Monto de la nota", 0, decimals=2)
        if not ok:
            return
        motivo, ok2 = QInputDialog.getText(self, "Motivo", "Motivo")
        if not ok2:
            return
        fecha = QDate.currentDate().toString("yyyy-MM-dd")
        self.manager.db.add_nota(venta_id, tipo, fecha, monto, motivo)
        QMessageBox.information(self, "Nota", "Nota registrada")
        self.load_invoices()

    def change_estado(self):
        venta_id = self._selected_venta()
        if venta_id is None:
            QMessageBox.warning(self, "Estado", "Seleccione una venta")
            return
        venta = next((v for v in self.manager.db.get_ventas() if v["id"] == venta_id), None)
        if not venta:
            QMessageBox.warning(self, "Estado", "No se encontró la venta seleccionada")
            return
        from dialogs import EstadoVentaDialog
        dialog = EstadoVentaDialog(venta.get("estado", "Pagada"), self)
        if dialog.exec_():
            estado = dialog.get_estado()
            self.manager.db.update_venta_estado(venta_id, estado)
            self.load_invoices()
