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
)
from PyQt5.QtCore import QDate

from ticket_pdf import generar_ticket_personalizado
import json


class FacturacionTab(QWidget):
    """Tab para gestionar facturas y notas."""

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self._setup_ui()
        self.load_invoices()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["ID", "Fecha", "Cliente", "Total", "Estado"])
        layout.addWidget(self.table)

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
        layout.addLayout(btns)

        self.btn_ticket.clicked.connect(self.create_ticket)
        self.btn_credito.clicked.connect(lambda: self.create_nota("credito"))
        self.btn_debito.clicked.connect(lambda: self.create_nota("debito"))
        self.btn_estado.clicked.connect(self.change_estado)

    def load_invoices(self):
        ventas = self.manager.db.get_ventas()
        clientes = {c["id"]: c["nombre"] for c in self.manager._clientes}
        self.table.setRowCount(len(ventas))
        for row, v in enumerate(ventas):
            self.table.setItem(row, 0, QTableWidgetItem(str(v.get("id"))))
            self.table.setItem(row, 1, QTableWidgetItem(v.get("fecha", "")))
            self.table.setItem(row, 2, QTableWidgetItem(clientes.get(v.get("cliente_id"), "")))
            self.table.setItem(row, 3, QTableWidgetItem(f"${v.get('total', 0):.2f}"))
            self.table.setItem(row, 4, QTableWidgetItem(v.get("estado", "")))
        if ventas:
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
