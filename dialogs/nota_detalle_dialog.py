from typing import List, Dict, Tuple
from PyQt5.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QDoubleSpinBox,
    QLabel,
    QLineEdit,
    QDialogButtonBox,
    QHeaderView,
)
from PyQt5.QtCore import Qt


class NotaDetalleDialog(QDialog):
    """Dialogo para ajustar montos de una venta por partida."""

    def __init__(self, detalles: List[Dict], parent=None):
        super().__init__(parent)
        self.detalles = detalles
        self.setWindowTitle("Detalle de Nota")
        self._build_ui()
        self._populate_table()
        self._update_total()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            [
                "Producto",
                "Cantidad",
                "P. Unitario",
                "Descuento",
                "Total",
                "Ajuste",
            ]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.table)

        motivo_layout = QHBoxLayout()
        motivo_layout.addWidget(QLabel("Motivo:"))
        self.motivo_edit = QLineEdit()
        motivo_layout.addWidget(self.motivo_edit)
        layout.addLayout(motivo_layout)

        total_layout = QHBoxLayout()
        total_layout.addStretch()
        self.total_label = QLabel("Total: 0.00")
        total_layout.addWidget(self.total_label)
        layout.addLayout(total_layout)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _populate_table(self):
        self.table.setRowCount(len(self.detalles))
        for row, d in enumerate(self.detalles):
            prod = d.get("descripcion", "")
            qty = d.get("cantidad", 0)
            price = d.get("precio_unitario", 0)
            desc = d.get("descuento", 0)
            if d.get("descuento_tipo") == "%":
                desc = price * qty * d.get("descuento", 0) / 100
            total = price * qty - desc

            items = [
                QTableWidgetItem(str(prod)),
                QTableWidgetItem(f"{qty}"),
                QTableWidgetItem(f"{price:.2f}"),
                QTableWidgetItem(f"{desc:.2f}"),
                QTableWidgetItem(f"{total:.2f}"),
            ]
            for col, item in enumerate(items):
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                self.table.setItem(row, col, item)

            spin = QDoubleSpinBox()
            spin.setDecimals(2)
            spin.setRange(-1_000_000, 1_000_000)
            spin.setValue(0)
            spin.valueChanged.connect(self._update_total)
            self.table.setCellWidget(row, 5, spin)

    def _update_total(self):
        total = 0.0
        for row in range(self.table.rowCount()):
            spin = self.table.cellWidget(row, 5)
            if isinstance(spin, QDoubleSpinBox):
                total += spin.value()
        self.total_label.setText(f"Total: {total:.2f}")

    def get_data(self) -> Tuple[float, str, List[Dict]]:
        detalles = []
        total = 0.0
        for row, d in enumerate(self.detalles):
            spin = self.table.cellWidget(row, 5)
            if isinstance(spin, QDoubleSpinBox):
                val = float(spin.value())
                if val:
                    detalles.append(
                        {
                            "detalle_id": d.get("id"),
                            "producto_id": d.get("producto_id"),
                            "ajuste": val,
                        }
                    )
                    total += val
        return total, self.motivo_edit.text(), detalles
