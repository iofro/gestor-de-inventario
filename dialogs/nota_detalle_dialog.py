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
    QWidget,
    QRadioButton,
    QAbstractItemView,
    QPushButton,
    QCheckBox,
)
from PyQt5.QtCore import Qt


class NotaDetalleDialog(QDialog):
    """Dialogo para ajustar montos de una venta por partida."""

    def __init__(self, detalles: List[Dict], tipo: str, parent=None):
        super().__init__(parent)
        self.detalles = detalles
        self.tipo = tipo
        self.setWindowTitle("Detalle de Nota")
        self.setMinimumSize(1100, 700)
        self.resize(1200, 750)
        self._mode_radios: Dict[int, Dict[str, QRadioButton]] = {}
        self._row_modes: Dict[int, str | None] = {}
        self._iva_checkboxes: Dict[int, QCheckBox] = {}
        self._suppress_radio_signal = False
        self._applying_mode = False

        self._build_ui()
        self._populate_table()
        self._update_total()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        table_layout = QHBoxLayout()
        layout.addLayout(table_layout)

        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(
            [
                "Producto",
                "Cantidad",
                "P. Unitario",
                "Descuento",
                "Total",
                "Modo de ajuste",
                "Ajuste cantidad",
                "Ajuste total",
                "Monto incluye IVA",
            ]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        table_layout.addWidget(self.table)

        actions_layout = QVBoxLayout()
        self.apply_button = QPushButton("Aplicar a filas seleccionadas", self)
        self.apply_button.clicked.connect(self._apply_to_selected_rows)
        actions_layout.addWidget(self.apply_button)
        actions_layout.addStretch()
        table_layout.addLayout(actions_layout)

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
            qty_spin.setObjectName(f"cantidad-input-{row}")
            qty_spin.valueChanged.connect(lambda value, r=row: self._on_qty_changed(r, value))

            monto_spin = QDoubleSpinBox()
            monto_spin.setDecimals(4)
            monto_spin.setSingleStep(0.0001)
            if self.tipo == "credito":
                monto_spin.setPrefix("-")
            monto_spin.setRange(0, 1_000_000)
            monto_spin.setValue(0)
            monto_spin.setObjectName(f"precio-input-{row}")
            monto_spin.valueChanged.connect(lambda value, r=row: self._on_price_changed(r, value))

            mode_widget = QWidget()
            mode_widget.setObjectName(f"mode-selector-{row}")
            mode_layout = QVBoxLayout(mode_widget)
            mode_layout.setContentsMargins(0, 0, 0, 0)
            qty_radio = QRadioButton("Modificar cantidad", mode_widget)
            qty_radio.setObjectName(f"mode-cantidad-{row}")
            qty_radio.setAutoExclusive(False)
            price_radio = QRadioButton("Modificar precio", mode_widget)
            price_radio.setObjectName(f"mode-precio-{row}")
            price_radio.setAutoExclusive(False)
            mode_layout.addWidget(qty_radio)
            mode_layout.addWidget(price_radio)
            qty_radio.toggled.connect(lambda checked, r=row: self._handle_mode_toggled(r, "cantidad", checked))
            price_radio.toggled.connect(lambda checked, r=row: self._handle_mode_toggled(r, "precio", checked))

            self.table.setCellWidget(row, 5, mode_widget)
            self.table.setCellWidget(row, 6, qty_spin)
            self.table.setCellWidget(row, 7, monto_spin)
            iva_checkbox = QCheckBox("Incluye IVA")
            iva_checkbox.setObjectName(f"iva-checkbox-{row}")
            iva_checkbox.setChecked(True)
            self.table.setCellWidget(row, 8, iva_checkbox)

            self._mode_radios[row] = {"cantidad": qty_radio, "precio": price_radio}
            self._row_modes[row] = None
            self._iva_checkboxes[row] = iva_checkbox

            # Ensure both inputs start enabled
            qty_spin.setEnabled(True)
            monto_spin.setEnabled(True)
            iva_checkbox.setEnabled(True)

    def _update_total(self):
        gravada = Decimal("0")
        exenta = Decimal("0")
        nosujeta = Decimal("0")
        iva = Decimal("0")
        for row, d in enumerate(self.detalles):
            monto_spin = self.table.cellWidget(row, 7)
            qty_spin = self.table.cellWidget(row, 6)
            iva_checkbox = self._iva_checkboxes.get(row)
            monto_val = Decimal(str(abs(monto_spin.value()))) if isinstance(monto_spin, QDoubleSpinBox) else Decimal("0")
            qty_val = Decimal(str(abs(qty_spin.value()))) if isinstance(qty_spin, QDoubleSpinBox) else Decimal("0")

            afectacion = self._resolve_afectacion(d)
            if monto_val > 0:
                includes_iva = iva_checkbox.isChecked() if isinstance(iva_checkbox, QCheckBox) else False
                if afectacion == "gravada":
                    if includes_iva:
                        base = (monto_val / Decimal("1.13")).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
                        iva_item = (monto_val - base).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
                    else:
                        base = monto_val.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
                        iva_item = (base * Decimal("0.13")).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
                    gravada += base
                    iva += iva_item
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
            monto_spin = self.table.cellWidget(row, 7)
            qty_spin = self.table.cellWidget(row, 6)
            iva_checkbox = self._iva_checkboxes.get(row)
            monto_val = float(monto_spin.value()) if isinstance(monto_spin, QDoubleSpinBox) else 0.0
            qty_val = float(qty_spin.value()) if isinstance(qty_spin, QDoubleSpinBox) else 0.0

            if monto_val > 0 and qty_val > 0:
                raise ValueError(
                    "Una fila no puede llevar cantidad y ajuste monetario a la vez; elige un modo"
                )

            payload: Dict = {
                "detalle_id": d.get("id"),
                "producto_id": d.get("producto_id"),
            }

            if monto_val:
                payload["ajuste"] = -abs(monto_val) if self.tipo == "credito" else abs(monto_val)
                if isinstance(iva_checkbox, QCheckBox):
                    payload["monto_incluye_iva"] = iva_checkbox.isChecked()

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

    def _handle_mode_toggled(self, row: int, mode: str, checked: bool):
        if self._suppress_radio_signal:
            return

        radios = self._mode_radios.get(row, {})
        other_mode = "precio" if mode == "cantidad" else "cantidad"
        other_radio = radios.get(other_mode)

        if checked:
            if other_radio and other_radio.isChecked():
                self._suppress_radio_signal = True
                other_radio.setChecked(False)
                self._suppress_radio_signal = False
            self._apply_mode(row, mode)
        else:
            if other_radio and other_radio.isChecked():
                return
            self._apply_mode(row, None)

    def _apply_mode(self, row: int, mode: str | None):
        qty_spin = self.table.cellWidget(row, 6)
        monto_spin = self.table.cellWidget(row, 7)
        iva_checkbox = self._iva_checkboxes.get(row)
        if not isinstance(qty_spin, QDoubleSpinBox) or not isinstance(monto_spin, QDoubleSpinBox):
            return

        self._applying_mode = True
        try:
            if mode == "cantidad":
                self._row_modes[row] = "cantidad"
                qty_spin.setEnabled(True)
                monto_spin.blockSignals(True)
                monto_spin.setValue(0)
                monto_spin.blockSignals(False)
                monto_spin.setEnabled(False)
                if isinstance(iva_checkbox, QCheckBox):
                    iva_checkbox.setChecked(False)
                    iva_checkbox.setEnabled(False)
            elif mode == "precio":
                self._row_modes[row] = "precio"
                monto_spin.setEnabled(True)
                qty_spin.blockSignals(True)
                qty_spin.setValue(0)
                qty_spin.blockSignals(False)
                qty_spin.setEnabled(False)
                if isinstance(iva_checkbox, QCheckBox):
                    iva_checkbox.setEnabled(True)
                    iva_checkbox.setChecked(True)
            else:
                self._row_modes[row] = None
                qty_spin.setEnabled(True)
                monto_spin.setEnabled(True)
                if isinstance(iva_checkbox, QCheckBox):
                    iva_checkbox.setEnabled(True)
                    iva_checkbox.setChecked(True)
        finally:
            self._applying_mode = False

        self._update_total()

    def _on_qty_changed(self, row: int, value: float):
        if self._applying_mode:
            self._update_total()
            return

        if self._row_modes.get(row) is None and value != 0:
            radio = self._mode_radios.get(row, {}).get("cantidad")
            if radio:
                radio.setChecked(True)
        self._update_total()

    def _on_price_changed(self, row: int, value: float):
        if self._applying_mode:
            self._update_total()
            return

        if self._row_modes.get(row) is None and value != 0:
            radio = self._mode_radios.get(row, {}).get("precio")
            if radio:
                radio.setChecked(True)
        self._update_total()

    def _apply_to_selected_rows(self):
        selection_model = self.table.selectionModel()
        if not selection_model:
            return
        selected_rows = {index.row() for index in selection_model.selectedRows()}
        source_row = self.table.currentRow()
        if source_row < 0 or source_row not in selected_rows:
            if selected_rows:
                source_row = next(iter(selected_rows))
            else:
                return
        source_mode = self._row_modes.get(source_row)
        qty_source = self.table.cellWidget(source_row, 6)
        monto_source = self.table.cellWidget(source_row, 7)
        iva_source = self._iva_checkboxes.get(source_row)
        if not isinstance(qty_source, QDoubleSpinBox) or not isinstance(monto_source, QDoubleSpinBox):
            return
        for row in selected_rows:
            if row == source_row:
                continue
            qty_widget = self.table.cellWidget(row, 6)
            monto_widget = self.table.cellWidget(row, 7)
            iva_widget = self._iva_checkboxes.get(row)
            if not isinstance(qty_widget, QDoubleSpinBox) or not isinstance(monto_widget, QDoubleSpinBox):
                continue
            if source_mode == "cantidad":
                radio = self._mode_radios.get(row, {}).get("cantidad")
                if radio:
                    radio.setChecked(True)
                qty_widget.setValue(qty_source.value())
            elif source_mode == "precio":
                radio = self._mode_radios.get(row, {}).get("precio")
                if radio:
                    radio.setChecked(True)
                monto_widget.setValue(monto_source.value())
                if isinstance(iva_widget, QCheckBox) and isinstance(iva_source, QCheckBox):
                    iva_widget.setChecked(iva_source.isChecked())
        self._update_total()
