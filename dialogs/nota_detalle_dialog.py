from typing import List, Dict, Tuple
from decimal import Decimal
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

    def __init__(self, detalles: List[Dict], tipo: str, parent=None):
        super().__init__(parent)
        self.detalles = detalles
        self.tipo = tipo
        self.setWindowTitle("Detalle de Nota")
        self._build_ui()
        self._populate_table()
        self._update_total()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        table_layout = QHBoxLayout()
        layout.addLayout(table_layout)

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
        table_layout.addWidget(self.table)

        resumen_layout = QVBoxLayout()
        self.base_gravada_label = QLabel("Base gravada: 0.00")
        self.exenta_label = QLabel("Exenta: 0.00")
        self.nosujeta_label = QLabel("No sujeta: 0.00")
        self.iva_label = QLabel("IVA (cód. 20): 0.00")
        self.total_label = QLabel("Total: 0.00")
        for lbl in [
            self.base_gravada_label,
            self.exenta_label,
            self.nosujeta_label,
            self.iva_label,
            self.total_label,
        ]:
            resumen_layout.addWidget(lbl)
        resumen_layout.addStretch()
        table_layout.addLayout(resumen_layout)

        motivo_layout = QHBoxLayout()
        motivo_layout.addWidget(QLabel("Motivo:"))
        self.motivo_edit = QLineEdit()
        motivo_layout.addWidget(self.motivo_edit)
        layout.addLayout(motivo_layout)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _populate_table(self):
        self.table.setRowCount(len(self.detalles))
        for row, d in enumerate(self.detalles):
            prod = d.get("descripcion", "")
            qty = d.get("cantidad", 0)
            price_iva = d.get("precio_unitario_iva", Decimal("0"))
            desc_iva = d.get("descuento_iva", Decimal("0"))
            total_iva = d.get("total_linea", Decimal("0"))

            items = [
                QTableWidgetItem(str(prod)),
                QTableWidgetItem(f"{qty}"),
                QTableWidgetItem(f"{price_iva:.4f}"),
                QTableWidgetItem(f"{desc_iva:.4f}"),
                QTableWidgetItem(f"{total_iva:.4f}"),
            ]
            for col, item in enumerate(items):
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                self.table.setItem(row, col, item)

            spin = QDoubleSpinBox()
            spin.setDecimals(4)
            spin.setSingleStep(0.0001)
            if self.tipo == "credito":
                spin.setPrefix("-")
            spin.setRange(0, 1_000_000)
            spin.setValue(0)
            spin.valueChanged.connect(self._update_total)
            self.table.setCellWidget(row, 5, spin)

    def _update_total(self):
        gravada = exenta = nosujeta = iva = 0.0
        for row, d in enumerate(self.detalles):
            spin = self.table.cellWidget(row, 5)
            if not isinstance(spin, QDoubleSpinBox):
                continue
            val = abs(spin.value())
            if d.get("ventas_gravadas"):
                base = val / 1.13
                gravada += base
                iva += val - base
            elif d.get("ventas_exentas"):
                exenta += val
            elif d.get("ventas_no_sujetas"):
                nosujeta += val
            else:
                base = val / 1.13
                gravada += base
                iva += val - base
        total = gravada + exenta + nosujeta + iva
        self.base_gravada_label.setText(f"Base gravada: {gravada:.4f}")
        self.exenta_label.setText(f"Exenta: {exenta:.4f}")
        self.nosujeta_label.setText(f"No sujeta: {nosujeta:.4f}")
        self.iva_label.setText(f"IVA (cód. 20): {iva:.4f}")
        self.total_label.setText(f"Total: {total:.4f}")
        self._totals = {
            "gravada": gravada,
            "exenta": exenta,
            "nosujeta": nosujeta,
            "iva": iva,
            "total": total,
        }

    def get_data(self) -> Tuple[float, str, List[Dict]]:
        self._update_total()
        detalles = []
        for row, d in enumerate(self.detalles):
            spin = self.table.cellWidget(row, 5)
            if isinstance(spin, QDoubleSpinBox):
                val = float(spin.value())
                if self.tipo == "credito":
                    val = -abs(val)
                else:
                    val = abs(val)
                if val:
                    detalles.append(
                        {
                            "detalle_id": d.get("id"),
                            "producto_id": d.get("producto_id"),
                            "ajuste": val,
                        }
                    )
        total = self._totals.get("total", 0.0)
        return total, self.motivo_edit.text(), detalles
