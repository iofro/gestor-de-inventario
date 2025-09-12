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
    QMessageBox,
)
from PyQt5.QtCore import Qt

from utils.catalogos import TRIBUTO_IVA
from .anular_factura_dialog import AnularFacturaDialog
import dte


class InvoiceDetailDialog(QDialog):
    """Simple read-only dialog showing invoice items and totals.

    When ``venta_id`` and ``numero_control`` are provided an additional
    button allows the user to start the invoice cancellation flow.
    """

    def __init__(
        self,
        items: List[Dict],
        resumen: Dict,
        venta_id: int | None = None,
        numero_control: str | None = None,
        factura: Dict | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.venta_id = venta_id
        self.numero_control = numero_control
        self.factura = factura or {}
        self.anulacion_result = None
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
        tribs = resumen.get("tributos") or []
        total_iva = float(next((t.get("valor", 0) for t in tribs if t.get("codigo") == TRIBUTO_IVA), 0))
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
        if self.venta_id and self.numero_control:
            anular_btn = buttons.addButton(
                "Anular factura", QDialogButtonBox.ActionRole
            )
            anular_btn.clicked.connect(self._anular)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    def _anular(self):
        negocio = dte._load_datos_negocio()
        receptor = self.factura.get("receptor", {})
        parent = self.parent()
        db = getattr(getattr(parent, "manager", None), "db", None)
        dlg = AnularFacturaDialog(
            self, responsable=negocio, solicitante=receptor, db=db
        )
        if dlg.exec_() != QDialog.Accepted:
            return
        form = dlg.get_data()
        if not db:
            QMessageBox.warning(self, "Anulación", "Base de datos no disponible")
            return
        row = db.cursor.execute(
            "SELECT sello FROM dte_envios WHERE venta_id=? ORDER BY id DESC LIMIT 1",
            (self.venta_id,),
        ).fetchone()
        sello = row["sello"] if row and row["sello"] else None
        if not sello:
            QMessageBox.warning(
                self, "Anulación", "No se encontró sello de recepción"
            )
            return
        try:
            evento = dte.generar_evento_anulacion(self.factura, form, sello)
            res = dte.enviar_evento_anulacion(db, self.venta_id, evento)
        except Exception as exc:  # pragma: no cover - UI feedback
            QMessageBox.warning(self, "Anulación", str(exc))
            return
        QMessageBox.information(self, "Anulación", res.get("estado", ""))
        self.anulacion_result = res
        self.accept()
