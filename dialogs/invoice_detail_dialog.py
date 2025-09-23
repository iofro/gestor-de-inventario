from typing import List, Dict
import logging
import os
import shutil

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
from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtGui import QDesktopServices

from utils.catalogos import TRIBUTO_IVA
from utils.docs import get_document_paths, get_dte_document_paths
from .anular_factura_dialog import AnularFacturaDialog
import anulacion
import dte


logger = logging.getLogger(__name__)


_DOC_TYPE_BY_CODE = {
    "01": ("ConsumidorFinal", False),
    "03": ("CreditoFiscal", False),
    "04": ("NotaRemision", True),
    "05": ("NotaCredito", True),
    "06": ("NotaDebito", True),
}

_DOC_CODE_BY_DESC = {
    "consumidor final": "01",
    "credito fiscal": "03",
    "crédito fiscal": "03",
    "nota de remision": "04",
    "nota de remisión": "04",
    "nota de credito": "05",
    "nota de crédito": "05",
    "nota de debito": "06",
    "nota de débito": "06",
}


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
        json_path: str | None = None,
        pdf_path: str | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.venta_id = venta_id
        self.numero_control = numero_control
        self.factura = factura or {}
        self._json_path = json_path
        self._pdf_path = pdf_path
        self.anulacion_result = None
        self._open_button = None
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

        self._sync_standard_paths()
        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.button(QDialogButtonBox.Ok).setText("Cerrar")
        if self._should_add_open_button():
            self._open_button = buttons.addButton(
                "Abrir ubicación del archivo", QDialogButtonBox.ActionRole
            )
            self._open_button.clicked.connect(self._open_file_location)
            self._update_open_button_state()
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
            self,
            responsable=negocio,
            solicitante=receptor,
            db=db,
            factura=self.factura,
        )
        if dlg.exec_() != QDialog.Accepted:
            return
        form = dlg.get_data()
        if db is None:
            parent = self.parent()
            db = getattr(getattr(parent, "manager", None), "db", None)
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
            cfg = dte._load_dte_api_config()
            ambiente_cfg = str(cfg.get("ambiente", ""))
            amb = "01" if ambiente_cfg.lower().startswith("produc") else "00"
            factura_payload = dict(self.factura)
            factura_payload["selloRecibido"] = sello
            evento = anulacion.build_invalidacion_json(
                factura_payload,
                form,
                ambiente=amb,
                db=db,
            )
            res = anulacion.enviar_invalidacion(db, evento)
        except Exception as exc:  # pragma: no cover - UI feedback
            QMessageBox.warning(self, "Anulación", str(exc))
            return
        QMessageBox.information(self, "Anulación", res.get("estado", ""))
        self.anulacion_result = res
        self.accept()

    def _determine_file_path(self) -> str | None:
        """Return the most relevant file path for the current invoice."""

        for path in (self._pdf_path, self._json_path):
            if isinstance(path, str) and os.path.exists(path):
                return path
        return None

    def _should_add_open_button(self) -> bool:
        if self.venta_id or self.factura or self._pdf_path or self._json_path:
            return True
        if self.numero_control:
            return True
        factura_ident = (self.factura or {}).get("identificacion") or {}
        return bool(factura_ident.get("numeroControl") or factura_ident.get("codigoGeneracion"))

    def _update_open_button_state(self) -> None:
        if not self._open_button:
            return
        has_files = bool(self._determine_file_path())
        can_regenerate = bool(self.venta_id or self.factura)
        self._open_button.setEnabled(has_files or can_regenerate)

    def _open_file_location(self):
        path = self._determine_file_path()
        if not path:
            path = self._refresh_invoice_files()
        if not path:
            QMessageBox.warning(
                self,
                "Abrir ubicación",
                "No se encontró un archivo asociado a la factura.",
            )
            return
        directory = os.path.dirname(path)
        if not directory:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(directory))

    def _refresh_invoice_files(self) -> str | None:
        """Try to locate or regenerate the PDF/JSON for the invoice."""

        parent = self.parent()
        if parent is None:
            return None

        # First attempt to refresh paths from the database in case a new
        # record was created after regeneration elsewhere.
        if self.venta_id:
            manager = getattr(parent, "manager", None)
            db = getattr(manager, "db", None) if manager else None
            if db is not None:
                try:
                    pdf_path = db.get_factura_pdf(self.venta_id)
                except Exception:  # pragma: no cover - defensive
                    pdf_path = None
                if pdf_path:
                    self._pdf_path = pdf_path
                    json_candidate = os.path.splitext(pdf_path)[0] + ".json"
                    if os.path.exists(json_candidate):
                        self._json_path = json_candidate
                    self._sync_standard_paths()
                    refreshed = self._determine_file_path()
                    if refreshed:
                        self._update_open_button_state()
                        return refreshed

        # If the files are still missing try to regenerate them using the
        # parent tab helper.  This covers cases where old records were
        # imported without their corresponding files.
        if self.venta_id and hasattr(parent, "_generate_invoice_pdf"):
            try:
                pdf_path = parent._generate_invoice_pdf(self.venta_id)
            except Exception as exc:  # pragma: no cover - UI feedback
                logger.exception("No se pudo regenerar la factura", exc_info=True)
                QMessageBox.warning(
                    self,
                    "Abrir ubicación",
                    f"No se pudo regenerar la factura seleccionada: {exc}",
                )
                return None
            if pdf_path and os.path.exists(pdf_path):
                self._pdf_path = pdf_path
                json_candidate = os.path.splitext(pdf_path)[0] + ".json"
                if os.path.exists(json_candidate):
                    self._json_path = json_candidate
                self._sync_standard_paths()
                refreshed = self._determine_file_path()
                if refreshed:
                    self._update_open_button_state()
                return refreshed
        return None

    def _sync_standard_paths(self) -> None:
        pdf_path = self._pdf_path if isinstance(self._pdf_path, str) else None
        json_path = self._json_path if isinstance(self._json_path, str) else None
        pdf_path, json_path = self._ensure_standard_location(pdf_path, json_path)
        self._pdf_path = pdf_path
        self._json_path = json_path

    def _ensure_standard_location(
        self, pdf_path: str | None, json_path: str | None
    ) -> tuple[str | None, str | None]:
        expected = self._expected_storage_paths()
        if not expected:
            return pdf_path, json_path
        expected_pdf, expected_json = expected
        original_pdf = pdf_path
        original_json = json_path
        # ``get_document_paths``/``get_dte_document_paths`` already ensure
        # directories exist, so no extra checks are required here.
        if pdf_path and os.path.exists(pdf_path):
            try:
                if os.path.abspath(pdf_path) != os.path.abspath(expected_pdf):
                    shutil.copy2(pdf_path, expected_pdf)
                pdf_path = expected_pdf
            except Exception:
                logger.warning("No se pudo copiar PDF a ubicación estándar", exc_info=True)
        elif os.path.exists(expected_pdf):
            pdf_path = expected_pdf

        source_json = None
        if json_path and os.path.exists(json_path):
            source_json = json_path
        else:
            candidates = []
            if pdf_path:
                candidates.append(os.path.splitext(pdf_path)[0] + ".json")
            if original_pdf:
                candidates.append(os.path.splitext(original_pdf)[0] + ".json")
            if original_json:
                candidates.append(original_json)
            for candidate in candidates:
                if candidate and os.path.exists(candidate):
                    source_json = candidate
                    json_path = candidate
                    break

        if source_json:
            try:
                if os.path.abspath(source_json) != os.path.abspath(expected_json):
                    shutil.copy2(source_json, expected_json)
                json_path = expected_json
            except Exception:
                logger.warning("No se pudo copiar JSON a ubicación estándar", exc_info=True)
        elif os.path.exists(expected_json):
            json_path = expected_json

        return pdf_path, json_path

    def _expected_storage_paths(self) -> tuple[str, str] | None:
        factura = self.factura or {}
        ident = factura.get("identificacion") or {}
        raw_tipo = ident.get("tipoDte") or factura.get("tipoDte")
        tipo_doc = None
        if isinstance(raw_tipo, str):
            raw_tipo = raw_tipo.strip()
            if raw_tipo in _DOC_TYPE_BY_CODE:
                tipo_doc = raw_tipo
            else:
                tipo_doc = _DOC_CODE_BY_DESC.get(raw_tipo.lower())
        elif raw_tipo is not None:
            tipo_doc = _DOC_TYPE_BY_CODE.get(f"{int(raw_tipo):02d}") and f"{int(raw_tipo):02d}"

        if not tipo_doc:
            desc = factura.get("tipo_documento") or factura.get("tipoDocumento")
            if isinstance(desc, str):
                tipo_doc = _DOC_CODE_BY_DESC.get(desc.strip().lower())

        if not tipo_doc or tipo_doc not in _DOC_TYPE_BY_CODE:
            return None

        doc_name, use_dte_paths = _DOC_TYPE_BY_CODE[tipo_doc]
        fecha = (
            ident.get("fecEmi")
            or ident.get("fechaEmi")
            or ident.get("fechaGeneracion")
            or factura.get("fecha")
            or factura.get("fecha_emision")
        )
        receptor = factura.get("receptor") or {}
        cliente = (
            receptor.get("nombre")
            or receptor.get("nombreComercial")
            or receptor.get("nombre_comercial")
            or ""
        )
        numero_control = (
            ident.get("numeroControl")
            or ident.get("numero_control")
            or self.numero_control
            or factura.get("numero_control")
            or factura.get("codigo_generacion")
            or factura.get("codigoGeneracion")
            or self.venta_id
        )
        if use_dte_paths:
            pdf_path, json_path = get_dte_document_paths(
                fecha, cliente, numero_control, doc_name
            )
        else:
            pdf_path, json_path = get_document_paths(
                fecha, cliente, numero_control, doc_name
            )
        return pdf_path, json_path
