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

        letras_layout = QHBoxLayout()
        letras_layout.addWidget(QLabel("Total en letras:"))
        self.total_letras_edit = QLineEdit()
        letras_layout.addWidget(self.total_letras_edit)
        layout.addLayout(letras_layout)

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

            has_iva = bool(d.get("ventas_gravadas"))
            mult = 1.13 if has_iva else 1

            price_iva = price * mult
            desc_iva = desc * mult
            total_iva = (price * qty - desc) * mult

            items = [
                QTableWidgetItem(str(prod)),
                QTableWidgetItem(f"{qty}"),
                QTableWidgetItem(f"{price_iva:.2f}"),
                QTableWidgetItem(f"{desc_iva:.2f}"),
                QTableWidgetItem(f"{total_iva:.2f}"),
            ]
            for col, item in enumerate(items):
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                self.table.setItem(row, col, item)

            spin = QDoubleSpinBox()
            spin.setDecimals(2)
            if self.tipo == "credito":
                spin.setRange(-1_000_000, 0)
            else:
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
        self.base_gravada_label.setText(f"Base gravada: {gravada:.2f}")
        self.exenta_label.setText(f"Exenta: {exenta:.2f}")
        self.nosujeta_label.setText(f"No sujeta: {nosujeta:.2f}")
        self.iva_label.setText(f"IVA (cód. 20): {iva:.2f}")
        self.total_label.setText(f"Total: {total:.2f}")
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
