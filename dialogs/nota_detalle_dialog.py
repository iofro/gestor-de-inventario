from typing import List, Dict, Tuple
from decimal import Decimal, ROUND_HALF_UP
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

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            [
                "Producto",
                "Cantidad",
                "P. Unitario",
                "Descuento",
                "Total",
                "Ajuste cantidad",
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

            qty_spin = QDoubleSpinBox()
            qty_spin.setDecimals(4)
            qty_spin.setSingleStep(0.0001)
            if self.tipo == "credito":
                max_qty = float(qty) if qty else 0.0
            else:
                max_qty = 1_000_000.0
            qty_spin.setRange(0, max_qty)
            if self.tipo == "credito":
                qty_spin.setPrefix("-")
            qty_spin.setValue(0)
            qty_spin.valueChanged.connect(self._update_total)
            self.table.setCellWidget(row, 5, qty_spin)

            spin = QDoubleSpinBox()
            spin.setDecimals(4)
            spin.setSingleStep(0.0001)
            if self.tipo == "credito":
                spin.setPrefix("-")
            spin.setRange(0, 1_000_000)
            spin.setValue(0)
            spin.valueChanged.connect(self._update_total)
            self.table.setCellWidget(row, 6, spin)

    def _update_total(self):
        gravada = Decimal("0")
        exenta = Decimal("0")
        nosujeta = Decimal("0")
        iva = Decimal("0")
        for row, d in enumerate(self.detalles):
            monto_spin = self.table.cellWidget(row, 6)
            qty_spin = self.table.cellWidget(row, 5)
            monto_val = Decimal(str(abs(monto_spin.value()))) if isinstance(monto_spin, QDoubleSpinBox) else Decimal("0")
            qty_val = Decimal(str(abs(qty_spin.value()))) if isinstance(qty_spin, QDoubleSpinBox) else Decimal("0")

            afectacion = self._resolve_afectacion(d)
            if monto_val > 0:
                if afectacion == "gravada":
                    base = (monto_val / Decimal("1.13")).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
                    gravada += base
                    iva += (monto_val - base).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
                elif afectacion == "exenta":
                    exenta += monto_val
                else:
                    nosujeta += monto_val

            if qty_val > 0:
                base_unit = self._resolve_unit_base(d, afectacion)
                if base_unit is None:
                    base_unit = Decimal("0")
                base_total = (qty_val * base_unit).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
                if afectacion == "gravada":
                    gravada += base_total
                    iva += (base_total * Decimal("0.13")).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
                elif afectacion == "exenta":
                    exenta += base_total
                else:
                    nosujeta += base_total

        total = gravada + exenta + nosujeta + iva
        self.base_gravada_label.setText(f"Base gravada: {float(gravada):.4f}")
        self.exenta_label.setText(f"Exenta: {float(exenta):.4f}")
        self.nosujeta_label.setText(f"No sujeta: {float(nosujeta):.4f}")
        self.iva_label.setText(f"IVA (cód. 20): {float(iva):.4f}")
        self.total_label.setText(f"Total: {float(total):.4f}")
        self._totals = {
            "gravada": float(gravada),
            "exenta": float(exenta),
            "nosujeta": float(nosujeta),
            "iva": float(iva),
            "total": float(total),
        }

    def _resolve_afectacion(self, detalle: Dict) -> str:
        if detalle.get("ventas_gravadas"):
            return "gravada"
        if detalle.get("ventas_exentas"):
            return "exenta"
        if detalle.get("ventas_no_sujetas"):
            return "no_sujeta"
        return "gravada"

    def _resolve_unit_base(self, detalle: Dict, afectacion: str) -> Decimal | None:
        cantidad = Decimal(str(detalle.get("cantidad") or 0))
        if cantidad > 0:
            if afectacion == "gravada" and detalle.get("ventas_gravadas"):
                total = Decimal(str(detalle.get("ventas_gravadas") or 0))
                return total / cantidad
            if afectacion == "exenta" and detalle.get("ventas_exentas"):
                total = Decimal(str(detalle.get("ventas_exentas") or 0))
                return total / cantidad
            if afectacion == "no_sujeta" and detalle.get("ventas_no_sujetas"):
                total = Decimal(str(detalle.get("ventas_no_sujetas") or 0))
                return total / cantidad
        precio_unitario = detalle.get("precio_unitario")
        if precio_unitario is None:
            return None
        return Decimal(str(precio_unitario))

    def get_data(self) -> Tuple[float, str, List[Dict]]:
        self._update_total()
        detalles = []
        for row, d in enumerate(self.detalles):
            monto_spin = self.table.cellWidget(row, 6)
            qty_spin = self.table.cellWidget(row, 5)
            monto_val = float(monto_spin.value()) if isinstance(monto_spin, QDoubleSpinBox) else 0.0
            qty_val = float(qty_spin.value()) if isinstance(qty_spin, QDoubleSpinBox) else 0.0

            payload: Dict = {
                "detalle_id": d.get("id"),
                "producto_id": d.get("producto_id"),
            }

            if monto_val:
                payload["ajuste"] = -abs(monto_val) if self.tipo == "credito" else abs(monto_val)

            if qty_val:
                afectacion = self._resolve_afectacion(d)
                base_unit = self._resolve_unit_base(d, afectacion)
                payload.update(
                    {
                        "ajusteCantidad": True,
                        "cantidad": abs(qty_val),
                        "precio_unitario": float(base_unit) if base_unit is not None else None,
                        "afectacion": afectacion,
                    }
                )

            if any(key in payload for key in ("ajuste", "ajusteCantidad")):
                detalles.append(payload)
        total = self._totals.get("total", 0.0)
        return total, self.motivo_edit.text(), detalles
