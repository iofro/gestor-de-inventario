from typing import List, Dict
from PyQt5.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QLabel,
    QDialogButtonBox,
    QHeaderView,
    QAbstractItemView,
)
from PyQt5.QtCore import Qt


class InvoiceDetailDialog(QDialog):
    """Simple read-only dialog showing invoice items and totals."""

    def __init__(self, items: List[Dict], resumen: Dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Detalle de factura")
        layout = QVBoxLayout(self)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels([
            "Descripción",
            "Cantidad",
            "P. Unitario",
            "Total",
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.table)

        for it in items:
            row = self.table.rowCount()
            self.table.insertRow(row)
            desc = it.get("descripcion", "")
            qty = it.get("cantidad", 0)
            price = it.get("precioUni", 0)
            try:
                price = float(price)
            except Exception:
                price = 0.0
            total = (
                float(it.get("ventaGravada", 0))
                + float(it.get("ventaExenta", 0))
                + float(it.get("ventaNoSuj", 0))
                + float(it.get("noGravado", 0))
            )
            self.table.setItem(row, 0, QTableWidgetItem(str(desc)))
            self.table.setItem(row, 1, QTableWidgetItem(f"{qty}"))
            self.table.setItem(row, 2, QTableWidgetItem(f"{price:.2f}"))
            self.table.setItem(row, 3, QTableWidgetItem(f"{total:.2f}"))

        totals_layout = QVBoxLayout()
        total_gravada = float(resumen.get("totalGravada", 0))
        total_exenta = float(resumen.get("totalExenta", 0))
        total_no_suj = float(resumen.get("totalNoSuj", 0))
        total_iva = float(resumen.get("totalIva", 0))
        total = float(resumen.get("totalPagar", resumen.get("montoTotalOperacion", 0)))
        for text in [
            f"Gravada: {total_gravada:.2f}",
            f"Exenta: {total_exenta:.2f}",
            f"No sujeta: {total_no_suj:.2f}",
            f"IVA: {total_iva:.2f}",
            f"Total: {total:.2f}",
        ]:
            totals_layout.addWidget(QLabel(text))
        totals_layout.addStretch()
        layout.addLayout(totals_layout)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.button(QDialogButtonBox.Ok).setText("Cerrar")
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
