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
    QApplication,
    QLineEdit,
    QDateEdit,
    QDateTimeEdit,
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QCheckBox,
    QRadioButton,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QSizePolicy,
    QScrollArea,
    QMenu,
    QAction,
    QFormLayout,
    QTabWidget,
)
from PyQt5.QtCore import QDate, QDateTime, QTime, Qt, QUrl, QTimer, QEvent, QSize
from PyQt5.QtGui import QPixmap, QDesktopServices, QCursor, QImage, QColor, QBrush
import os
import re
import logging
import glob
import hashlib
from pathlib import Path
from typing import Any, List, Mapping
from pprint import pformat
from collections import Counter

from ticket_pdf import generar_ticket_personalizado
from factura_sv import (
    generar_factura_electronica_pdf,
    generar_nota_credito_pdf,
    generar_nota_debito_pdf,
    generar_nota_remision_pdf,
)
from dte import (
    transmitir_dte,
    enviar_nota_remision,
)
from nota_debito_electronica import generar_nde_desde_dte
from nota_remision import generar_nota_remision_desde_db
import nota_credito_electronica
from utils.docs import (
    get_document_paths,
    get_dte_document_paths,
    write_pdf_atomically,
    persist_client_json,
    sync_client_json_with_canonical,
)
from utils.ticket_adapters import dte_to_legacy_ticket_payload
from utils.doc_generation import generate_invoice_pdf
from utils.email_sender import EmailSender
from utils.jws import sign_and_save
# ``sign_and_save`` generates both JSON and JWS files so no manual
# stable JSON utilities are required here.
from utils.sanitize import limpiar_doc, solo_digitos
from utils.printing import open_pdf as open_pdf_file
from utils import catalogos
from utils.loading import create_loading_dialog, loading_dialog
from paths import (
    DATOS_NEGOCIO_PATH,
    FACTURAS_CONSUMIDOR_FINAL_DIR,
    FACTURAS_CREDITO_FISCAL_DIR,
    TICKETS_OUTPUT_DIR,
    NOTAS_DEBITO_DIR as NOTAS_DEBITO_OUTPUT_DIR,
    NOTAS_CREDITO_DIR as NOTAS_CREDITO_OUTPUT_DIR,
    NOTAS_REMISION_DIR as NOTAS_REMISION_OUTPUT_DIR,
    DTES_DIR,
    DTE_FALLIDOS_DIR,
    DTES_PENDIENTES_DIR,
    FACTURAS_ARCHIVE_CF_DIR,
    FACTURAS_ARCHIVE_CREDITO_DIR,
    resolve_user_visible_path,
)
import tempfile
import subprocess
import shutil
import uuid
import dte
import anulacion
from declaracion.anexo_contribuyentes import (
    VentaContribuyente,
    on_click_generar_contribuyentes,
)
from declaracion.anexo_consumidor_final import (
    VentaCF,
    on_click_generar_consumidor_final,
)
from declaracion.anexo_xix import DTEAnulado, on_click_generar_anulaciones
from db import DB
from dialogs.nota_detalle_dialog import NotaDetalleDialog
from dialogs.invoice_detail_dialog import InvoiceDetailDialog
from dialogs.anular_factura_dialog import AnularFacturaDialog
from dialogs.seleccionar_dte_dialog import SeleccionarDteDialog
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from utils.monto import iva_item, monto_a_texto_sv
from utils.snapshot import SnapshotNotFoundError
from utils.catalogos import TRIBUTO_IVA, TIPO_INVALIDACION, TIPO_DOC_REC
from utils.fecha import TZ_EL_SALVADOR
from utils.stable_json import stable_stringify
from utils.facturacion_records import (
    CANONICAL_TIPO_LABELS,
    TIPO_DTE_DESC,
    TIPO_DTE_CODE_BY_DESC,
    detectar_estado_factura,
    format_envio_state,
    get_facturacion_rows,
    infer_tipo_from_name,
    map_envio_state,
)
from evento_contingencia import (
    collect_contingencia_dtes,
    make_event_filename,
    save_evento_contingencia_json,
)

logger = logging.getLogger(__name__)

SNAPSHOT_MISSING_MESSAGE = (
    "No se encontró el snapshot del documento base para esta nota. "
    "Seleccione el documento original o regenere el snapshot antes de enviar."
)
GENERIC_SEND_ERROR = "No se pudo enviar el documento. Revise los registros y reintente."
SIGNER_DOWN_WARNING = (
    "El firmador no está corriendo, si desea proceder enviando el DTE hay altas "
    "probabilidades de ser rechazado, se recomienda iniciar el firmador en "
    "configuración y luego enviar el DTE"
)

# Directory where debit notes will be stored
# Paths are provided by ``paths`` to keep user data outside the installation
# directory.
NOTAS_DEBITO_DIR = NOTAS_DEBITO_OUTPUT_DIR
# Directory where credit notes will be stored
NOTAS_CREDITO_DIR = NOTAS_CREDITO_OUTPUT_DIR
# Directory where remision notes will be stored
NOTAS_REMISION_DIR = NOTAS_REMISION_OUTPUT_DIR
import json
from datetime import datetime, date, timedelta
import fitz

CF_DIR = FACTURAS_CONSUMIDOR_FINAL_DIR
CREDITO_DIR = FACTURAS_CREDITO_FISCAL_DIR
TICKETS_DIR = TICKETS_OUTPUT_DIR
# Additional locations where invoices may be stored
ADDITIONAL_DIRS = [
    FACTURAS_ARCHIVE_CF_DIR,
    FACTURAS_ARCHIVE_CREDITO_DIR,
]

# Common directories where invoice related files may reside
INVOICE_DIRS = [
    CF_DIR,
    CREDITO_DIR,
    TICKETS_DIR,
    NOTAS_DEBITO_DIR,
    NOTAS_CREDITO_DIR,
    NOTAS_REMISION_DIR,
    DTES_DIR,
    DTE_FALLIDOS_DIR,
    DTES_PENDIENTES_DIR,
]

# Pattern for file names generated by the system
DOC_PATTERN = re.compile(r"^\d{8}_.+_(ConsumidorFinal|CreditoFiscal|Ticket|NotaDebito|NotaCredito|NotaRemision)$")

# Document types that can be rendered using the ticket format.
TICKET_ELIGIBLE_TIPOS = {"01", "03", "04", "05", "06"}

# Short labels displayed in the "Tipo de DTE" column.
TIPO_DTE_SHORT_DESC = {
    "consumidor final": "cons final",
    "crédito fiscal": "cred fiscal",
    "credito fiscal": "cred fiscal",
    "nota de crédito": "not crédito",
    "nota de credito": "not crédito",
    "nota de débito": "not debito",
    "nota de debito": "not debito",
    "nota de remisión": "not remisión",
    "nota de remision": "not remisión",
}

# Fallback mapping used when ``tipoDte`` is not available but the
# human-readable description is known.
TIPO_DTE_CODE_BY_DESC = {
    "ticket": "01",
    "consumidor final": "01",
    "crédito fiscal": "03",
    "credito fiscal": "03",
    "nota de remisión": "04",
    "nota de remision": "04",
    "nota de crédito": "05",
    "nota de credito": "05",
    "nota de débito": "06",
    "nota de debito": "06",
}


class PdfPreviewDialog(QDialog):
    """Simple PDF preview dialog used before sending a document to print."""

    def __init__(self, pdf_path: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pdf_path = pdf_path
        self._load_error: str | None = None

        self.setWindowTitle("Vista previa de impresión")
        self.resize(900, 700)

        layout = QVBoxLayout(self)

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        layout.addWidget(self._scroll)

        self._pages_widget = QWidget(self._scroll)
        self._pages_layout = QVBoxLayout(self._pages_widget)
        self._pages_layout.setAlignment(Qt.AlignTop)
        self._scroll.setWidget(self._pages_widget)

        self._info_label = QLabel("Generando vista previa…", self)
        self._info_label.setAlignment(Qt.AlignCenter)
        self._info_label.setWordWrap(True)
        self._pages_layout.addWidget(self._info_label)

        self._button_box = QDialogButtonBox(
            QDialogButtonBox.Cancel,
            parent=self,
        )
        self._print_button: QPushButton = self._button_box.addButton(
            "Imprimir", QDialogButtonBox.AcceptRole
        )
        self._button_box.accepted.connect(self.accept)
        self._button_box.rejected.connect(self.reject)
        layout.addWidget(self._button_box)

        QTimer.singleShot(0, self._load_preview)

    def _load_preview(self) -> None:
        print_button = self._print_button
        try:
            document = fitz.open(self._pdf_path)
        except Exception as exc:  # pragma: no cover - defensive
            self._load_error = str(exc)
            self._info_label.setText(
                "No se pudo abrir el PDF para la vista previa.\n"
                f"Detalle: {exc}"
            )
            if print_button is not None:
                print_button.setEnabled(False)
            return

        self._pages_layout.removeWidget(self._info_label)
        self._info_label.deleteLater()

        try:
            for page_index in range(document.page_count):
                page = document.load_page(page_index)
                zoom = 1.5  # ~108 DPI
                matrix = fitz.Matrix(zoom, zoom)
                pix = page.get_pixmap(matrix=matrix, alpha=False)
                image = QImage(
                    pix.samples,
                    pix.width,
                    pix.height,
                    pix.stride,
                    QImage.Format_RGB888,
                )
                qt_image = image.copy()
                label = QLabel(self)
                label.setAlignment(Qt.AlignCenter)
                label.setStyleSheet(
                    "background-color: #f0f0f0; border: 1px solid #d0d0d0; padding: 12px;"
                )
                label.setPixmap(QPixmap.fromImage(qt_image))
                self._pages_layout.addWidget(label)
        finally:
            document.close()

        self._pages_layout.addStretch(1)

        if print_button is not None:
            print_button.setEnabled(True)

    def has_error(self) -> bool:
        return self._load_error is not None


def _tipo_code_from_desc(tipo: str | None) -> str | None:
    if not tipo:
        return None
    return TIPO_DTE_CODE_BY_DESC.get(str(tipo).strip().lower())


DUPLICATE_HINTS = (
    "ya existe un registro con ese valor",
    "duplicado",
    "ya registrado",
)


def _gather_rejection_texts(*values):
    texts = []
    for value in values:
        if isinstance(value, dict):
            texts.extend(_gather_rejection_texts(*value.values()))
        elif isinstance(value, (list, tuple, set)):
            for item in value:
                texts.extend(_gather_rejection_texts(item))
        elif value not in (None, ""):
            texts.append(str(value))
    return texts


class SendOptionsDialog(QDialog):
    """Simple dialog to choose where to send the invoice."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Enviar factura")
        layout = QVBoxLayout(self)
        self.email_cb = QCheckBox("Enviar por correo")
        self.hacienda_cb = QCheckBox("Enviar a Hacienda")
        self.email_cb.setChecked(True)
        self.hacienda_cb.setChecked(True)
        layout.addWidget(self.email_cb)
        layout.addWidget(self.hacienda_cb)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)



class DTERechazadoDialog(QDialog):
    def __init__(self, numero_control: str, codigo_generacion: str, motivo: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("DTE rechazado por Hacienda")
        layout = QVBoxLayout(self)

        info_layout = QFormLayout()

        numero_lbl = QLabel(numero_control or "Desconocido")
        numero_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        info_layout.addRow("Número de control:", numero_lbl)

        codigo_lbl = QLabel(codigo_generacion or "Desconocido")
        codigo_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        info_layout.addRow("Código de generación:", codigo_lbl)

        motivo_lbl = QLabel(motivo or "Sin detalle disponible")
        motivo_lbl.setWordWrap(True)
        motivo_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        info_layout.addRow("Motivo:", motivo_lbl)

        layout.addLayout(info_layout)

        pregunta_lbl = QLabel(
            "¿Desea regresar el correlativo al valor anterior para mantener la secuencia?"
        )
        pregunta_lbl.setWordWrap(True)
        layout.addWidget(pregunta_lbl)

        buttons = QDialogButtonBox()
        self.accept_btn = buttons.addButton(
            "Sí, regresar correlativo", QDialogButtonBox.AcceptRole
        )
        self.reject_btn = buttons.addButton("No, mantener", QDialogButtonBox.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class AnularDteDialog(QDialog):
    def __init__(
        self,
        responsable: dict | None = None,
        solicitante: dict | None = None,
        parent=None,
        db: DB | None = None,
        factura: dict | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Anular DTE")
        self.db = db
        self._factura = factura or {}
        ident = self._factura.get("identificacion") or {}
        tipo_val = ident.get("tipoDte")
        self._original_tipo = str(tipo_val).zfill(2) if tipo_val is not None else None
        codigo_val = ident.get("codigoGeneracion")
        self._original_uuid = str(codigo_val or "").strip().upper() or None
        self._original_ambiente = anulacion.normalize_ambiente(ident.get("ambiente"))
        self._receptor_docs: set[str] = set()
        receptor_data = (self._factura.get("receptor") or {})
        for key in ("numDocumento", "nit", "dui"):
            val = receptor_data.get(key)
            if val:
                self._receptor_docs.add(str(val))
        layout = QFormLayout(self)

        self.tipo_cb = QComboBox()
        for code, desc in sorted(TIPO_INVALIDACION.items()):
            self.tipo_cb.addItem(f"{code} - {desc}", str(code))
        layout.addRow("Tipo anulación", self.tipo_cb)

        self.motivo_edit = QLineEdit()
        layout.addRow("Motivo", self.motivo_edit)

        self.codigo_reemplazo_label = QLabel("Documento que reemplaza")
        self.codigo_reemplazo_edit = QLineEdit()
        self.codigo_reemplazo_edit.setReadOnly(True)
        self.codigo_reemplazo_edit.setPlaceholderText(
            "Selecciona con el botón…"
        )
        codigo_row = QHBoxLayout()
        codigo_row.addWidget(self.codigo_reemplazo_edit)
        self.buscar_codigo_btn = QPushButton("Buscar…")
        self.buscar_codigo_btn.clicked.connect(self._abrir_selector)
        codigo_row.addWidget(self.buscar_codigo_btn)
        layout.addRow(self.codigo_reemplazo_label, codigo_row)

        self.nombre_resp = QLineEdit((responsable or {}).get("nombre", ""))
        self.tipdoc_resp = QComboBox()
        for code, desc in sorted(TIPO_DOC_REC.items()):
            self.tipdoc_resp.addItem(f"{code} - {desc}", str(code))
        if responsable and responsable.get("tipDoc"):
            idx = self.tipdoc_resp.findData(responsable.get("tipDoc"))
            if idx >= 0:
                self.tipdoc_resp.setCurrentIndex(idx)
        self.numdoc_resp = QLineEdit((responsable or {}).get("numDoc", ""))
        layout.addRow("Resp. nombre", self.nombre_resp)
        layout.addRow("Resp. tipo doc", self.tipdoc_resp)
        layout.addRow("Resp. núm. doc", self.numdoc_resp)

        self.nombre_sol = QLineEdit((solicitante or {}).get("nombre", ""))
        self.tipdoc_sol = QComboBox()
        for code, desc in sorted(TIPO_DOC_REC.items()):
            self.tipdoc_sol.addItem(f"{code} - {desc}", str(code))
        if solicitante and solicitante.get("tipDoc"):
            idx = self.tipdoc_sol.findData(solicitante.get("tipDoc"))
            if idx >= 0:
                self.tipdoc_sol.setCurrentIndex(idx)
        self.numdoc_sol = QLineEdit((solicitante or {}).get("numDoc", ""))
        layout.addRow("Solicita nombre", self.nombre_sol)
        layout.addRow("Solicita tipo doc", self.tipdoc_sol)
        layout.addRow("Solicita núm. doc", self.numdoc_sol)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

        self.tipo_cb.currentIndexChanged.connect(self._on_tipo_changed)
        self._on_tipo_changed(self.tipo_cb.currentIndex())

    def _on_tipo_changed(self, index: int) -> None:
        tipo = self.tipo_cb.itemData(index)
        requires = tipo in {"1", "3"}
        self.codigo_reemplazo_label.setVisible(requires)
        self.codigo_reemplazo_edit.setVisible(requires)
        self.buscar_codigo_btn.setVisible(requires)
        self.buscar_codigo_btn.setEnabled(requires and self.db is not None)
        if not requires:
            self.codigo_reemplazo_edit.clear()

    def _abrir_selector(self) -> None:
        if self.db is None:
            return
        dlg = SeleccionarDteDialog(
            self.db,
            tipo_dte=self._original_tipo,
            ambiente=self._original_ambiente,
            receptor_documentos=sorted(self._receptor_docs),
            exclude_uuid=self._original_uuid,
            parent=self,
        )
        if dlg.exec_() == QDialog.Accepted and dlg.selected_uuid:
            self.codigo_reemplazo_edit.setText(dlg.selected_uuid.upper())

    def _on_accept(self) -> None:
        if not self._validate():
            return
        self.accept()

    def _validate(self) -> bool:
        tipo = self.tipo_cb.currentData()
        motivo = self.motivo_edit.text().strip()
        if tipo == "3":
            if len(motivo) < 5 or len(motivo) > 250:
                QMessageBox.warning(self, "Anulación", "Motivo inválido")
                return False
        elif motivo and (len(motivo) < 5 or len(motivo) > 250):
            QMessageBox.warning(self, "Anulación", "Motivo inválido")
            return False

        codigo = self.codigo_reemplazo_edit.text().strip()
        if tipo in {"1", "3"}:
            if not codigo:
                QMessageBox.warning(
                    self,
                    "Anulación",
                    "Primero emite el DTE corregido y captura su código de generación (con sello). "
                    "Ingresa ese código en 'Documento que reemplaza'.",
                )
                return False
            codigo_upper = codigo.upper()
            if not anulacion.UUID36_RE.fullmatch(codigo_upper):
                QMessageBox.warning(
                    self,
                    "Anulación",
                    "El código de generación debe ser un UUID de 36 caracteres en mayúsculas con guiones.",
                )
                return False
            if self._original_uuid and codigo_upper == self._original_uuid:
                QMessageBox.warning(
                    self,
                    "Anulación",
                    anulacion.ERROR_REEMPLAZO_DISTINTO,
                )
                return False
            if self.codigo_reemplazo_edit.text() != codigo_upper:
                self.codigo_reemplazo_edit.setText(codigo_upper)

        for name, line in [
            ("Responsable", self.nombre_resp),
            ("Solicitante", self.nombre_sol),
        ]:
            val = line.text().strip()
            if len(val) < 5 or len(val) > 100:
                QMessageBox.warning(self, "Anulación", f"Nombre de {name} inválido")
                return False
        for name, line in [
            ("Documento responsable", self.numdoc_resp),
            ("Documento solicitante", self.numdoc_sol),
        ]:
            val = line.text().strip()
            if len(val) < 3 or len(val) > 20:
                QMessageBox.warning(self, "Anulación", f"Número de {name} inválido")
                return False
        return True

    def get_data(self) -> dict:
        tipo = self.tipo_cb.currentData()
        codigo = self.codigo_reemplazo_edit.text().strip().upper()
        if tipo not in {"1", "3"}:
            codigo = None
        return {
            "tipoAnulacion": self.tipo_cb.currentData(),
            "motivoAnulacion": self.motivo_edit.text().strip(),
            "nombreResponsable": self.nombre_resp.text().strip(),
            "tipDocResponsable": self.tipdoc_resp.currentData(),
            "numDocResponsable": self.numdoc_resp.text().strip(),
            "nombreSolicita": self.nombre_sol.text().strip(),
            "tipDocSolicita": self.tipdoc_sol.currentData(),
            "numDocSolicita": self.numdoc_sol.text().strip(),
            "codigoGeneracionR": codigo if codigo else None,
        }


class NotaRemisionExtWidget(QWidget):
    """Widget reutilizable para capturar datos de entrega de la NR."""

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.cli_data = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Persona que entrega
        layout.addWidget(QLabel("Persona que entrega"))
        self.emp_search = QLineEdit()
        self.emp_search.setPlaceholderText("Buscar empleado por nombre, DUI o NIT…")
        layout.addWidget(self.emp_search)
        self.emp_results = QListWidget()
        self.emp_results.addItem("Escribe para buscar…")
        self.emp_results.item(0).setFlags(Qt.NoItemFlags)
        layout.addWidget(self.emp_results)

        self.nomb_entrega = QLineEdit()
        self.docu_entrega = QLineEdit()
        self.tipo_entrega_cb = QComboBox()
        self.tipo_entrega_cb.addItem("DUI", "13")
        self.tipo_entrega_cb.addItem("NIT", "36")
        self.docu_entrega.setMaxLength(10)
        self.docu_entrega.textChanged.connect(self._aplicar_mascara_dui)
        self.tipo_entrega_cb.currentIndexChanged.connect(
            lambda _: self._actualizar_tipo_doc(self.docu_entrega)
        )
        for label, widget, extra in [
            ("Nombre entrega:", self.nomb_entrega, None),
            ("Documento entrega:", self.docu_entrega, self.tipo_entrega_cb),
        ]:
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
            row.addWidget(widget)
            if extra:
                row.addWidget(extra)
            layout.addLayout(row)

        # Persona que recibe
        layout.addWidget(QLabel("Persona que recibe"))
        self.cli_search = QLineEdit()
        self.cli_search.setPlaceholderText("Buscar cliente por nombre, DUI/NIT, NRC…")
        layout.addWidget(self.cli_search)
        self.cli_results = QListWidget()
        self.cli_results.addItem("Escribe para buscar…")
        self.cli_results.item(0).setFlags(Qt.NoItemFlags)
        layout.addWidget(self.cli_results)

        self.nomb_recibe = QLineEdit()
        self.docu_recibe = QLineEdit()
        self.docu_recibe.setMaxLength(10)
        self.docu_recibe.textChanged.connect(self._aplicar_mascara_dui)
        self.tipo_recibe_cb = QComboBox()
        self.tipo_recibe_cb.addItem("DUI", "13")
        self.tipo_recibe_cb.addItem("NIT", "36")
        self.tipo_recibe_cb.currentIndexChanged.connect(
            lambda _: self._actualizar_tipo_doc(self.docu_recibe, receptor=True)
        )
        self.nrc_recibe = QLineEdit()
        self.nrc_recibe.setEnabled(False)
        self.ext_obs = QPlainTextEdit()
        for label, widget, extra in [
            ("Nombre recibe:", self.nomb_recibe, None),
            ("Documento recibe:", self.docu_recibe, self.tipo_recibe_cb),
            ("NRC:", self.nrc_recibe, None),
            ("Observaciones:", self.ext_obs, None),
        ]:
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
            row.addWidget(widget)
            if extra:
                row.addWidget(extra)
            layout.addLayout(row)

        self.tipo_doc_recibe = "13"

        # Search handlers and timers
        self.emp_timer = QTimer(self)
        self.emp_timer.setSingleShot(True)
        self.emp_timer.setInterval(250)
        self.emp_search.textChanged.connect(self.emp_timer.start)
        self.emp_timer.timeout.connect(self._buscar_empleado)
        self.emp_results.itemActivated.connect(self._seleccionar_empleado)
        self.emp_results.itemClicked.connect(self._seleccionar_empleado)

        self.cli_timer = QTimer(self)
        self.cli_timer.setSingleShot(True)
        self.cli_timer.setInterval(250)
        self.cli_search.textChanged.connect(self.cli_timer.start)
        self.cli_timer.timeout.connect(self._buscar_cliente)
        self.cli_results.itemActivated.connect(self._seleccionar_cliente)
        self.cli_results.itemClicked.connect(self._seleccionar_cliente)

        for w in [
            self.emp_search,
            self.emp_results,
            self.cli_search,
            self.cli_results,
        ]:
            w.installEventFilter(self)

    def _aplicar_mascara_dui(self, text: str):
        line = self.sender()
        if not isinstance(line, QLineEdit):
            return
        digits = solo_digitos(text)[:9]
        if len(digits) > 8:
            formatted = f"{digits[:8]}-{digits[8:]}"
        else:
            formatted = digits
        if line.text() != formatted:
            line.blockSignals(True)
            line.setText(formatted)
            line.blockSignals(False)

    def _solo_digitos(self, text: str):
        line = self.sender()
        if not isinstance(line, QLineEdit):
            return
        digits = solo_digitos(text)[: line.maxLength()]
        if line.text() != digits:
            line.blockSignals(True)
            line.setText(digits)
            line.blockSignals(False)

    def _actualizar_tipo_doc(self, line_edit: QLineEdit, receptor: bool = False):
        combo = self.sender()
        tipo = combo.currentData() if isinstance(combo, QComboBox) else "13"
        for fn in (self._aplicar_mascara_dui, self._solo_digitos):
            try:
                line_edit.textChanged.disconnect(fn)
            except TypeError:
                pass
        if tipo == "13":  # DUI
            line_edit.setMaxLength(10)
            line_edit.textChanged.connect(self._aplicar_mascara_dui)
            self._aplicar_mascara_dui(line_edit.text())
            if receptor:
                self.nrc_recibe.clear()
                self.nrc_recibe.setEnabled(False)
        else:  # NIT
            line_edit.setMaxLength(14)
            line_edit.textChanged.connect(self._solo_digitos)
            self._solo_digitos(line_edit.text())
            if receptor:
                self.nrc_recibe.setEnabled(True)
        if receptor:
            self.tipo_doc_recibe = tipo

    def _populate_results(self, widget, items, formatter):
        widget.clear()
        if not items:
            widget.addItem("Sin resultados. Puedes escribir manualmente.")
            widget.item(0).setFlags(Qt.NoItemFlags)
            return
        for itm in items:
            text, data = formatter(itm)
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, data)
            widget.addItem(item)
        widget.setCurrentRow(0)

    def _buscar_empleado(self):
        text = self.emp_search.text().strip()
        if not text:
            self.emp_results.clear()
            self.emp_results.addItem("Escribe para buscar…")
            self.emp_results.item(0).setFlags(Qt.NoItemFlags)
            return
        try:
            empleados = self.db.get_trabajadores(search=text)
        except Exception:
            empleados = []
        self._populate_results(
            self.emp_results,
            empleados,
            lambda e: (
                f"{e.get('nombre', '')} - {e.get('dui') or e.get('nit') or ''}",
                e,
            ),
        )

    def _seleccionar_empleado(self, item):
        data = item.data(Qt.UserRole) if item else None
        if isinstance(data, dict):
            self.nomb_entrega.setText(data.get("nombre", ""))
            doc_dui = data.get("dui")
            doc_nit = data.get("nit")
            if doc_nit and not doc_dui:
                self.tipo_entrega_cb.setCurrentIndex(1)
            else:
                self.tipo_entrega_cb.setCurrentIndex(0)
            self.tipo_entrega_cb.currentIndexChanged.emit(
                self.tipo_entrega_cb.currentIndex()
            )
            self.docu_entrega.setText(limpiar_doc(doc_dui or doc_nit or ""))

    def _buscar_cliente(self):
        text = self.cli_search.text().strip()
        if not text:
            self.cli_results.clear()
            self.cli_results.addItem("Escribe para buscar…")
            self.cli_results.item(0).setFlags(Qt.NoItemFlags)
            return
        try:
            clientes = self.db.get_clientes(search=text)
        except Exception:
            clientes = []
        self._populate_results(
            self.cli_results,
            clientes,
            lambda c: (
                f"{c.get('nombre', '')} - {c.get('dui') or c.get('nit') or c.get('nrc') or ''}",
                c,
            ),
        )

    def _seleccionar_cliente(self, item):
        data = item.data(Qt.UserRole) if item else None
        if isinstance(data, dict):
            self.cli_data = data
            self.nomb_recibe.setText(data.get("nombre", ""))
            nrc = data.get("nrc") or ""
            doc_dui = data.get("dui")
            doc_nit = data.get("nit")
            if nrc or (doc_nit and not doc_dui):
                self.tipo_recibe_cb.setCurrentIndex(1)
            else:
                self.tipo_recibe_cb.setCurrentIndex(0)
            self.tipo_recibe_cb.currentIndexChanged.emit(
                self.tipo_recibe_cb.currentIndex()
            )
            if self.tipo_recibe_cb.currentData() == "36":
                self.docu_recibe.setText(limpiar_doc(doc_nit or ""))
                self.nrc_recibe.setText(limpiar_doc(nrc))
            else:
                self.docu_recibe.setText(limpiar_doc(doc_dui or doc_nit or ""))
                self.nrc_recibe.clear()
        else:
            self.cli_data = None

    def eventFilter(self, obj, event):
        if event.type() == QEvent.KeyPress:
            if obj in (self.emp_search, self.cli_search) and event.key() in (
                Qt.Key_Down,
                Qt.Key_Up,
            ):
                lst = self.emp_results if obj is self.emp_search else self.cli_results
                if lst.count():
                    lst.setFocus()
                    lst.setCurrentRow(0)
                    return True
            if obj in (self.emp_results, self.cli_results) and event.key() in (
                Qt.Key_Return,
                Qt.Key_Enter,
            ):
                current = obj.currentItem()
                if current:
                    obj.itemActivated.emit(current)
                    return True
        return super().eventFilter(obj, event)

    def get_data(self):
        return {
            "nombEntrega": self.nomb_entrega.text(),
            "docuEntrega": limpiar_doc(self.docu_entrega.text()),
            "nombRecibe": self.nomb_recibe.text(),
            "docuRecibe": limpiar_doc(self.docu_recibe.text()),
            "nrcRecibe": limpiar_doc(self.nrc_recibe.text()),
            "tipoDocRecibe": self.tipo_recibe_cb.currentData(),
            "observaciones": self.ext_obs.toPlainText(),
        }

    def validate(self) -> bool:
        checks = [
            self.nomb_entrega.text().strip(),
            limpiar_doc(self.docu_entrega.text()),
            self.nomb_recibe.text().strip(),
            limpiar_doc(self.docu_recibe.text()),
        ]
        if not all(checks):
            QMessageBox.warning(
                self,
                "Nota",
                "Todos los campos de entrega/recepción son obligatorios",
            )
            return False
        doc = solo_digitos(self.docu_recibe.text())
        if self.tipo_doc_recibe == "36":
            if len(doc) not in (9, 10, 14):
                QMessageBox.warning(
                    self,
                    "Nota",
                    "NIT debe tener 9, 10 o 14 dígitos (sin guiones)",
                )
                return False
            nrc = solo_digitos(self.nrc_recibe.text())
            if len(nrc) not in (6, 7):
                QMessageBox.warning(
                    self, "Nota", "NRC requerido (6–7 dígitos)"
                )
                return False
        else:
            if len(doc) != 9:
                QMessageBox.warning(
                    self, "Nota", "DUI debe tener 9 dígitos (sin guiones)"
                )
                return False
        return True


class NotaRemisionExtDialog(QDialog):
    """Diálogo que envuelve :class:`NotaRemisionExtWidget` con encabezado."""

    def __init__(self, db, factura=None, parent=None):
        super().__init__(parent)
        self.db = db
        self.factura = factura or {}
        self.setWindowTitle("Datos de entrega")
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        if self.factura:
            ident = self.factura.get("identificacion", {})
            receptor = self.factura.get("receptor", {})
            resumen = self.factura.get("resumen", {})
            tipo = ident.get("tipoDte")
            numero = ident.get("numeroControl")
            fecha = ident.get("fecEmi")
            uuid = (ident.get("codigoGeneracion") or "")[:8]
            cliente = receptor.get("nombre") or receptor.get("nombreComercial") or ""
            total = resumen.get("montoTotalOperacion") or resumen.get("totalPagar")
            header = QHBoxLayout()
            header.addWidget(QLabel(f"Factura origen: {tipo} {numero} {fecha} {uuid}"))
            header.addWidget(QLabel(f"Cliente: {cliente}"))
            if total is not None:
                header.addWidget(QLabel(f"Total: {total}"))
            layout.addLayout(header)

        self.panel = NotaRemisionExtWidget(self.db, self)
        layout.addWidget(self.panel)
        # Expose fields for backward compatibility/tests
        self.nomb_entrega = self.panel.nomb_entrega
        self.docu_entrega = self.panel.docu_entrega
        self.nomb_recibe = self.panel.nomb_recibe
        self.docu_recibe = self.panel.docu_recibe
        self.nrc_recibe = self.panel.nrc_recibe
        self.ext_obs = self.panel.ext_obs
        self._seleccionar_empleado = self.panel._seleccionar_empleado
        self._seleccionar_cliente = self.panel._seleccionar_cliente

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self):
        if not self.panel.validate():
            return
        super().accept()

    def get_data(self):
        return self.panel.get_data()


class _LimitedPlainTextEdit(QPlainTextEdit):
    """Plain text edit with a hard character limit."""

    def __init__(self, max_chars: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._max_chars = max_chars
        self._block_updates = False
        self.textChanged.connect(self._enforce_limit)

    def insertFromMimeData(self, source) -> None:  # type: ignore[override]
        if source is None:
            return
        text = source.text()
        if not text:
            super().insertFromMimeData(source)
            return
        remaining = self._max_chars - len(self.toPlainText())
        if remaining <= 0:
            return
        clipped = text[:remaining]
        if not clipped:
            return
        cursor = self.textCursor()
        cursor.insertText(clipped)

    def _enforce_limit(self) -> None:
        if self._block_updates:
            return
        text = self.toPlainText()
        if len(text) <= self._max_chars:
            return
        cursor = self.textCursor()
        position = cursor.position()
        self._block_updates = True
        self.setPlainText(text[: self._max_chars])
        cursor.setPosition(min(position, self._max_chars))
        self.setTextCursor(cursor)
        self._block_updates = False


class EventoContingenciaDialog(QDialog):
    """Diálogo para preparar un borrador de evento de contingencia."""

    MOTIVO_MAX_CHARS = 500
    EVENTO_MAX_DTES = 1000

    def __init__(self, manager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.manager = manager
        self.setWindowTitle("Crear evento de contingencia")
        self.resize(820, 720)

        self.evento_listo = False
        self._validation_active = False
        self._filtered_dtes: list[dict] = []
        self._current_payload: dict | None = None
        self._suggested_filename: str | None = None
        self._last_save_dir: Path | None = None
        (
            self._default_tipo,
            self._default_motivo,
        ) = self._load_defaults()

        self._build_ui()
        self._update_end_minimum()
        self._handle_range_change()
        self._update_motivo_counter()
        self._update_motivo_visibility()
        self._update_preview()
        self._update_action_state()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        now = datetime.now(TZ_EL_SALVADOR).replace(tzinfo=None)
        start_default = now - timedelta(hours=1)

        # 1. Rango de la contingencia
        rango_title = QLabel("1. Rango de la contingencia", self)
        rango_title.setStyleSheet("font-weight: 600;")
        layout.addWidget(rango_title)

        rango_form = QFormLayout()
        rango_form.setFormAlignment(Qt.AlignTop)
        rango_form.setLabelAlignment(Qt.AlignLeft)
        rango_form.setHorizontalSpacing(12)
        rango_form.setVerticalSpacing(6)

        self.inicio_edit = QDateTimeEdit(self)
        self.inicio_edit.setCalendarPopup(True)
        self.inicio_edit.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.inicio_edit.setDateTime(self._to_qdatetime(start_default))
        inicio_widget, self.inicio_error_label = self._wrap_with_error(self.inicio_edit)
        rango_form.addRow("Fecha/hora inicio:", inicio_widget)

        self.fin_edit = QDateTimeEdit(self)
        self.fin_edit.setCalendarPopup(True)
        self.fin_edit.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.fin_edit.setDateTime(self._to_qdatetime(now))
        fin_widget, self.fin_error_label = self._wrap_with_error(self.fin_edit)
        rango_form.addRow("Fecha/hora fin:", fin_widget)

        layout.addLayout(rango_form)

        # 2. Datos del evento
        datos_title = QLabel("2. Datos del evento", self)
        datos_title.setStyleSheet("font-weight: 600;")
        layout.addWidget(datos_title)

        datos_form = QFormLayout()
        datos_form.setFormAlignment(Qt.AlignTop)
        datos_form.setLabelAlignment(Qt.AlignLeft)
        datos_form.setHorizontalSpacing(12)
        datos_form.setVerticalSpacing(6)

        self.tipo_combo = QComboBox(self)
        for key in sorted(catalogos.CONTINGENCIA):
            label = catalogos.CONTINGENCIA[key]
            self.tipo_combo.addItem(f"{key} – {label}", key)
        tipo_index = -1
        if self._default_tipo is not None:
            tipo_index = self.tipo_combo.findData(self._default_tipo)
        if tipo_index != -1:
            self.tipo_combo.setCurrentIndex(tipo_index)
        tipo_widget, self.tipo_error_label = self._wrap_with_error(self.tipo_combo)
        datos_form.addRow("Tipo (CAT-005):", tipo_widget)

        self.motivo_edit = _LimitedPlainTextEdit(self.MOTIVO_MAX_CHARS, self)
        self.motivo_edit.setTabChangesFocus(True)
        self.motivo_edit.setPlaceholderText(
            "Describe el motivo (máx. 500 caracteres)."
        )
        self.motivo_edit.setPlainText(self._default_motivo)

        self.motivo_row_widget = QWidget(self)
        motivo_layout = QVBoxLayout(self.motivo_row_widget)
        motivo_layout.setContentsMargins(0, 0, 0, 0)
        motivo_layout.setSpacing(3)
        motivo_layout.addWidget(self.motivo_edit)

        self.motivo_counter = QLabel("0/500", self.motivo_row_widget)
        self.motivo_counter.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.motivo_counter.setStyleSheet("color: #57606a; font-size: 11px;")
        motivo_layout.addWidget(self.motivo_counter)

        self.motivo_error_label = QLabel("", self.motivo_row_widget)
        self.motivo_error_label.setWordWrap(True)
        self.motivo_error_label.setStyleSheet("color: #b3261e;")
        self.motivo_error_label.setVisible(False)
        motivo_layout.addWidget(self.motivo_error_label)

        datos_form.addRow("Motivo:", self.motivo_row_widget)

        layout.addLayout(datos_form)

        # 3. DTE a incluir
        dte_title = QLabel("3. DTE a incluir", self)
        dte_title.setStyleSheet("font-weight: 600;")
        layout.addWidget(dte_title)

        self.dte_counter_label = QLabel("", self)
        self.dte_counter_label.setStyleSheet("color: #57606a;")
        layout.addWidget(self.dte_counter_label)

        self.dte_list = QListWidget(self)
        self.dte_list.setSelectionMode(QAbstractItemView.NoSelection)
        self.dte_list.setAlternatingRowColors(True)
        self.dte_list.setFocusPolicy(Qt.StrongFocus)
        self.dte_list.setMinimumHeight(200)
        layout.addWidget(self.dte_list)

        self.dte_empty_label = QLabel(
            "No hay DTE pendientes en este rango.", self
        )
        self.dte_empty_label.setAlignment(Qt.AlignCenter)
        self.dte_empty_label.setWordWrap(True)
        self.dte_empty_label.setStyleSheet(
            "color: #6c757d; border: 1px dashed #d0d0d0; padding: 18px;"
        )
        self.dte_empty_label.setVisible(False)
        layout.addWidget(self.dte_empty_label)

        self.dte_warning_label = QLabel(
            "Máximo 1000 por evento. Se deberá dividir en varios eventos.",
            self,
        )
        self.dte_warning_label.setStyleSheet("color: #b35f00;")
        self.dte_warning_label.setWordWrap(True)
        self.dte_warning_label.setVisible(False)
        layout.addWidget(self.dte_warning_label)

        self.dtes_error_label = QLabel("", self)
        self.dtes_error_label.setStyleSheet("color: #b3261e;")
        self.dtes_error_label.setWordWrap(True)
        self.dtes_error_label.setVisible(False)
        layout.addWidget(self.dtes_error_label)

        # 4. Previsualización
        preview_title = QLabel("4. Previsualización JSON", self)
        preview_title.setStyleSheet("font-weight: 600;")
        layout.addWidget(preview_title)

        self.preview_edit = QPlainTextEdit(self)
        self.preview_edit.setReadOnly(True)
        self.preview_edit.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.preview_edit.setMinimumHeight(220)
        self.preview_edit.setStyleSheet(
            "font-family: 'Fira Code', 'Cascadia Code', 'Courier New', monospace;"
        )
        self.preview_edit.setPlaceholderText(
            "La previsualización se actualizará automáticamente."
        )
        layout.addWidget(self.preview_edit)

        # Acciones
        self.button_box = QDialogButtonBox(QDialogButtonBox.Close, self)
        self.generate_btn = self.button_box.addButton(
            "Generar borrador", QDialogButtonBox.ActionRole
        )
        self.generate_btn.setDefault(True)
        self.generate_btn.setEnabled(False)
        self.save_btn = self.button_box.addButton(
            "Guardar…", QDialogButtonBox.ActionRole
        )
        self.save_btn.setEnabled(False)
        self.btn_enviar_evento = self.button_box.addButton(
            "Enviar a Hacienda", QDialogButtonBox.ActionRole
        )
        self.btn_enviar_evento.setEnabled(False)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        self.draft_message_label = QLabel("", self)
        self.draft_message_label.setStyleSheet("color: #0a7a4f; font-weight: 600;")
        self.draft_message_label.setWordWrap(True)
        self.draft_message_label.setVisible(False)
        layout.addWidget(self.draft_message_label)

        # Señales
        self.inicio_edit.dateTimeChanged.connect(self._on_start_changed)
        self.fin_edit.dateTimeChanged.connect(self._on_end_changed)
        self.tipo_combo.currentIndexChanged.connect(self._on_tipo_changed)
        self.motivo_edit.textChanged.connect(self._on_motivo_changed)
        self.generate_btn.clicked.connect(self._on_generate_clicked)
        self.save_btn.clicked.connect(self._on_save_clicked)
        self.btn_enviar_evento.clicked.connect(self._on_enviar_evento_clicked)

    @staticmethod
    def _to_qdatetime(value: datetime) -> QDateTime:
        return QDateTime(
            QDate(value.year, value.month, value.day),
            QTime(value.hour, value.minute, value.second),
        )

    @staticmethod
    def _wrap_with_error(widget: QWidget) -> tuple[QWidget, QLabel]:
        container = QWidget(widget.parent())
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        layout.addWidget(widget)
        error_label = QLabel("", container)
        error_label.setWordWrap(True)
        error_label.setStyleSheet("color: #b3261e;")
        error_label.setVisible(False)
        layout.addWidget(error_label)
        return container, error_label

    def _load_defaults(self) -> tuple[int | None, str]:
        tipo: int | None = None
        motivo = ""
        try:
            datos = dte._load_datos_negocio()
        except Exception:
            datos = {}
        dte_api = datos.get("dte_api") or {}

        tipo_raw = dte_api.get("tipo_contingencia")
        try:
            tipo_val = int(str(tipo_raw).strip())
        except Exception:
            tipo_val = None
        if tipo_val in catalogos.CONTINGENCIA:
            tipo = tipo_val

        motivo = str(dte_api.get("motivo_contin") or "").strip()

        return tipo, motivo[: self.MOTIVO_MAX_CHARS]

    def _on_start_changed(self, _value: QDateTime) -> None:
        self._update_end_minimum()
        self._handle_range_change()

    def _on_end_changed(self, _value: QDateTime) -> None:
        self._handle_range_change()

    def _handle_range_change(self) -> None:
        self._clear_draft_message()
        self._refresh_filtered_dtes()
        self._update_dte_list()
        self._update_preview()
        self._update_action_state()

    def _update_end_minimum(self) -> None:
        start_dt = self.inicio_edit.dateTime()
        if start_dt.isValid():
            self.fin_edit.setMinimumDateTime(start_dt.addSecs(1))

    @staticmethod
    def _normalize_range_input(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=TZ_EL_SALVADOR)
        return value.astimezone(TZ_EL_SALVADOR)

    def _refresh_filtered_dtes(self) -> None:
        start_raw = self._to_py_datetime(self.inicio_edit.dateTime())
        end_raw = self._to_py_datetime(self.fin_edit.dateTime())
        start_py = self._normalize_range_input(start_raw)
        end_py = self._normalize_range_input(end_raw)
        if not (start_py and end_py):
            self._filtered_dtes = []
            return

        db = getattr(getattr(self, "manager", None), "db", None)
        try:
            collected = collect_contingencia_dtes(db, start_py, end_py)
        except Exception:
            logger.exception("Error al recolectar DTE en contingencia")
            collected = []

        enriched: list[dict] = []
        for entry in collected:
            codigo = entry.get("codigoGeneracion")
            tipo_doc = entry.get("tipoDoc")
            timestamp = entry.get("timestamp")
            if not codigo or not tipo_doc or not isinstance(timestamp, datetime):
                continue
            if timestamp.tzinfo is None:
                ts_local = timestamp.replace(tzinfo=TZ_EL_SALVADOR)
            else:
                ts_local = timestamp.astimezone(TZ_EL_SALVADOR)
            enriched.append(
                {
                    "codigoGeneracion": str(codigo).strip().upper(),
                    "tipoDoc": str(tipo_doc).zfill(2),
                    "timestamp": timestamp,
                    "timestamp_local": ts_local,
                    "tipo_desc": TIPO_DTE_DESC.get(str(tipo_doc).zfill(2), str(tipo_doc).zfill(2)),
                }
            )

        self._filtered_dtes = enriched

    @staticmethod
    def _to_py_datetime(value: QDateTime) -> datetime | None:
        if not value or not value.isValid():
            return None
        return value.toPyDateTime()

    def _update_dte_list(self) -> None:
        self.dte_list.setUpdatesEnabled(False)
        self.dte_list.clear()
        for entry in self._filtered_dtes[: self.EVENTO_MAX_DTES]:
            timestamp = entry.get("timestamp_local") or entry.get("timestamp")
            if isinstance(timestamp, datetime):
                fecha = timestamp.strftime("%Y-%m-%d %H:%M")
            else:
                fecha = ""
            descripcion = entry.get("tipo_desc") or entry.get("tipoDoc")
            codigo = entry.get("codigoGeneracion") or entry.get("codigo")
            item = QListWidgetItem(f"{fecha} · {descripcion} · {codigo}")
            self.dte_list.addItem(item)
        self.dte_list.setUpdatesEnabled(True)

        total = len(self._filtered_dtes)
        if total == 1:
            counter_text = "1 DTE pendiente en este rango."
        else:
            counter_text = f"{total} DTE pendientes en este rango."
        self.dte_counter_label.setText(counter_text)

        self.dte_empty_label.setVisible(total == 0)
        if total > self.EVENTO_MAX_DTES:
            self.dte_warning_label.setText(
                (
                    "Se mostrarán los primeros "
                    f"{self.EVENTO_MAX_DTES} de {total} DTE pendientes. "
                    "Máximo 1000 por evento."
                )
            )
            self.dte_warning_label.setVisible(True)
        else:
            self.dte_warning_label.setVisible(False)

    def _current_tipo(self) -> int | None:
        data = self.tipo_combo.currentData()
        if isinstance(data, int):
            return data
        if data is None:
            return None
        try:
            return int(data)
        except Exception:
            return None

    def _current_motivo(self) -> str:
        return self.motivo_edit.toPlainText().strip()

    def _collect_validation_errors(self) -> tuple[dict[str, str], str | None]:
        errors: dict[str, str] = {}
        first_key: str | None = None

        tipo = self._current_tipo()
        if tipo is None or tipo not in catalogos.CONTINGENCIA:
            errors["tipo"] = "Selecciona un tipo de contingencia (CAT-005)."
            first_key = first_key or "tipo"

        if tipo == 5:
            motivo = self._current_motivo()
            if not motivo:
                errors["motivo"] = (
                    "Motivo es obligatorio cuando el tipo es “Otro” (máx. 500)."
                )
                first_key = first_key or "motivo"
            elif len(motivo) > self.MOTIVO_MAX_CHARS:
                errors["motivo"] = "El motivo no puede exceder 500 caracteres."
                first_key = first_key or "motivo"

        inicio_dt = self._to_py_datetime(self.inicio_edit.dateTime())
        fin_dt = self._to_py_datetime(self.fin_edit.dateTime())

        if inicio_dt is None:
            errors["inicio"] = "Completa la fecha y hora de inicio."
            first_key = first_key or "inicio"
        if fin_dt is None:
            errors["fin"] = "Completa la fecha y hora de fin."
            first_key = first_key or "fin"

        total = len(self._filtered_dtes)
        if total == 0:
            errors["dtes"] = "Debe existir al menos un DTE pendiente."
            first_key = first_key or "dtes"

        return errors, first_key

    def _apply_errors(self, errors: dict[str, str]) -> None:
        self.tipo_error_label.setVisible("tipo" in errors)
        self.tipo_error_label.setText(errors.get("tipo", ""))

        show_motivo_error = "motivo" in errors and self._current_tipo() == 5
        self.motivo_error_label.setVisible(show_motivo_error)
        self.motivo_error_label.setText(errors.get("motivo", ""))

        self.inicio_error_label.setVisible("inicio" in errors)
        self.inicio_error_label.setText(errors.get("inicio", ""))

        self.fin_error_label.setVisible("fin" in errors)
        self.fin_error_label.setText(errors.get("fin", ""))

        self.dtes_error_label.setVisible("dtes" in errors)
        self.dtes_error_label.setText(errors.get("dtes", ""))

    def _focus_field(self, key: str | None) -> None:
        if key == "tipo":
            self.tipo_combo.setFocus()
        elif key == "motivo":
            self.motivo_edit.setFocus()
        elif key == "inicio":
            self.inicio_edit.setFocus()
        elif key == "fin":
            self.fin_edit.setFocus()
        elif key == "dtes":
            self.dte_list.setFocus()

    def _update_action_state(self) -> tuple[dict[str, str], str | None]:
        errors, first_key = self._collect_validation_errors()
        self.generate_btn.setEnabled(len(errors) == 0)
        if self._validation_active:
            self._apply_errors(errors)
        else:
            self._apply_errors({})
        self._update_save_button()
        self._update_send_button()
        return errors, first_key

    def _update_preview(self) -> None:
        if self._current_payload:
            try:
                texto = stable_stringify(self._current_payload, indent=2)
            except Exception:
                try:
                    texto = json.dumps(
                        self._current_payload, indent=2, ensure_ascii=False
                    )
                except Exception:
                    texto = ""
        else:
            texto = ""
        self.preview_edit.setPlainText(texto)

    def _update_save_button(self) -> None:
        can_save = self.evento_listo and self._current_payload is not None
        self.save_btn.setEnabled(bool(can_save))

    def _preview_evento_dict(self) -> dict | None:
        if self._current_payload is not None:
            return self._current_payload
        return self._build_event_payload(show_errors=False)

    def _update_send_button(self) -> None:
        if not hasattr(self, "btn_enviar_evento"):
            return
        try:
            payload = self._preview_evento_dict()
        except Exception:
            payload = None
        self.btn_enviar_evento.setEnabled(self._is_payload_valid_for_send(payload))

    def _is_payload_valid_for_send(self, payload: Mapping[str, Any] | None) -> bool:
        if not isinstance(payload, Mapping):
            return False

        ident = payload.get("identificacion")
        if not isinstance(ident, Mapping):
            return False
        version = str(ident.get("version") or "").strip()
        if version != "3":
            return False

        detalle = payload.get("detalleDTE")
        if not isinstance(detalle, list) or not (1 <= len(detalle) <= self.EVENTO_MAX_DTES):
            return False
        for item in detalle:
            if not isinstance(item, Mapping):
                return False
            codigo = str(item.get("codigoGeneracion") or "").strip()
            tipo = str(item.get("tipoDoc") or "").strip()
            if not codigo or not tipo:
                return False

        motivo = payload.get("motivo")
        if not isinstance(motivo, Mapping):
            return False
        raw_tipo = motivo.get("tipoContingencia", motivo.get("tipo"))
        try:
            tipo_val = int(str(raw_tipo))
        except Exception:
            tipo_val = None
        if tipo_val not in {1, 2, 3, 4, 5}:
            return False
        if tipo_val == 5:
            motivo_text = motivo.get("motivoContingencia", motivo.get("motivo"))
            if not isinstance(motivo_text, str) or not motivo_text.strip():
                return False

        emisor = payload.get("emisor")
        if not isinstance(emisor, Mapping):
            return False
        nit_text = str(emisor.get("nit") or "").strip()
        nit_digits = solo_digitos(nit_text)
        if not nit_digits or len(nit_digits) not in {9, 14}:
            return False

        return True

    def _format_observaciones_text(self, resp: Mapping[str, Any] | None) -> str:
        if not isinstance(resp, Mapping):
            return ""

        textos = []
        textos.extend(_gather_rejection_texts(resp.get("observaciones")))

        detalle = resp.get("detalle")
        if detalle is not None:
            textos.extend(_gather_rejection_texts(detalle))

        errores = resp.get("errores")
        if errores is not None:
            textos.extend(_gather_rejection_texts(errores))

        cleaned: list[str] = []
        seen: set[str] = set()
        for texto in textos:
            text = str(texto).strip()
            if text and text not in seen:
                cleaned.append(text)
                seen.add(text)
        if not cleaned:
            return ""
        formatted = "\n".join(f"- {line}" for line in cleaned)
        return f"Observaciones:\n{formatted}"

    def _get_or_create_evento_id(self, payload: Mapping[str, Any]) -> int:
        db = getattr(getattr(self, "manager", None), "db", None)
        codigo = ""
        ident = payload.get("identificacion") if isinstance(payload, Mapping) else None
        if isinstance(ident, Mapping):
            codigo = str(ident.get("codigoGeneracion") or "").strip().upper()

        if db is not None and codigo:
            try:
                db.ensure_column("dte_envios", "codigo_generacion", "TEXT")
            except Exception:
                pass
            try:
                row = db.cursor.execute(
                    """
                    SELECT venta_id
                    FROM dte_envios
                    WHERE modo=? AND codigo_generacion=? AND venta_id IS NOT NULL
                    ORDER BY id DESC LIMIT 1
                    """,
                    ("evento", codigo),
                ).fetchone()
            except Exception:
                row = None
            if row:
                existing = row[0] if isinstance(row, tuple) else row["venta_id"]
                if isinstance(existing, int) and existing:
                    return int(existing)

        candidate = self._generate_evento_id_from_payload(payload)

        if db is not None:
            try:
                while self._evento_id_exists(db, candidate):
                    candidate = (candidate + 1) % 2_000_000_000 or 1
            except Exception:
                pass

        return candidate

    def _generate_evento_id_from_payload(self, payload: Mapping[str, Any]) -> int:
        ident = payload.get("identificacion") if isinstance(payload, Mapping) else None
        if isinstance(ident, Mapping):
            codigo = str(ident.get("codigoGeneracion") or "").strip()
            if codigo:
                try:
                    value = uuid.UUID(codigo).int % 2_000_000_000
                    if value:
                        return value
                except Exception:
                    digits = solo_digitos(codigo)
                    if digits:
                        try:
                            return int(digits[-9:])
                        except Exception:
                            pass

        timestamp = datetime.now(TZ_EL_SALVADOR).timestamp()
        candidate = int(timestamp * 1000) % 2_000_000_000
        return candidate or 1

    @staticmethod
    def _evento_id_exists(db: Any, candidate: int) -> bool:
        if db is None:
            return False
        try:
            row = db.cursor.execute(
                "SELECT 1 FROM dte_envios WHERE venta_id=? LIMIT 1",
                (candidate,),
            ).fetchone()
        except Exception:
            return False
        return row is not None

    def _update_motivo_counter(self) -> None:
        texto = self.motivo_edit.toPlainText()
        self.motivo_counter.setText(f"{len(texto)}/{self.MOTIVO_MAX_CHARS}")

    def _update_motivo_visibility(self) -> None:
        visible = self._current_tipo() == 5
        self.motivo_row_widget.setVisible(visible)
        if not visible:
            self.motivo_error_label.setVisible(False)

    def _on_tipo_changed(self, _index: int) -> None:
        self._clear_draft_message()
        self._update_motivo_visibility()
        self._update_action_state()
        self._update_preview()

    def _on_motivo_changed(self) -> None:
        self._clear_draft_message()
        self._update_motivo_counter()
        self._update_action_state()
        self._update_preview()

    def _clear_draft_message(self) -> None:
        if (
            self.evento_listo
            or self.draft_message_label.isVisible()
            or self._current_payload is not None
        ):
            self.evento_listo = False
            self._current_payload = None
            self._suggested_filename = None
            self.draft_message_label.clear()
            self.draft_message_label.setVisible(False)
            self._update_preview()
            self._update_save_button()
            self._update_send_button()

    def _on_generate_clicked(self) -> None:
        self._validation_active = True
        errors, first_key = self._update_action_state()
        if errors:
            self._focus_field(first_key)
            return
        payload = self._build_event_payload()
        if payload is None:
            return
        self._current_payload = payload
        try:
            self._suggested_filename = make_event_filename(payload)
        except Exception:
            self._suggested_filename = None
        self.evento_listo = True
        self.draft_message_label.setText(
            "Borrador generado. Revisa la previsualización antes de guardar."
        )
        self.draft_message_label.setVisible(True)
        self._update_preview()
        self._update_save_button()
        self._update_send_button()

    def _build_event_payload(self, *, show_errors: bool = True) -> dict | None:
        tipo = self._current_tipo()
        inicio_raw = self._to_py_datetime(self.inicio_edit.dateTime())
        fin_raw = self._to_py_datetime(self.fin_edit.dateTime())
        inicio_dt = self._normalize_range_input(inicio_raw)
        fin_dt = self._normalize_range_input(fin_raw)
        if tipo is None or inicio_dt is None or fin_dt is None:
            return None

        detalle = self._build_detalle_items()
        if not detalle:
            return None

        if fin_dt < inicio_dt:
            inicio_dt, fin_dt = fin_dt, inicio_dt

        motivo = self._current_motivo() if tipo == 5 else None

        try:
            payload = dte.generar_evento_contingencia(
                detalle,
                f_inicio=inicio_dt.strftime("%Y-%m-%d"),
                f_fin=fin_dt.strftime("%Y-%m-%d"),
                h_inicio=inicio_dt.strftime("%H:%M:%S"),
                h_fin=fin_dt.strftime("%H:%M:%S"),
                tipo_contingencia=tipo,
                motivo_contingencia=motivo,
            )
        except Exception as exc:
            logger.exception("Error al construir el evento de contingencia")
            if show_errors:
                QMessageBox.critical(
                    self,
                    "Error al generar",
                    f"No se pudo generar el borrador del evento:\n{exc}",
                )
            return None

        return payload

    def _build_detalle_items(self) -> list[dict[str, str]]:
        detalle: list[dict[str, str]] = []
        for entry in self._filtered_dtes[: self.EVENTO_MAX_DTES]:
            codigo = entry.get("codigoGeneracion") or entry.get("codigo")
            tipo_doc = (
                entry.get("tipoDoc")
                or entry.get("tipoDte")
                or entry.get("tipoDocumento")
            )
            if not codigo or not tipo_doc:
                continue
            codigo_text = str(codigo).strip().upper()
            tipo_text = str(tipo_doc).zfill(2)
            if not codigo_text or not tipo_text:
                continue
            detalle.append(
                {
                    "codigoGeneracion": codigo_text,
                    "tipoDoc": tipo_text,
                }
            )
        return detalle

    def _on_save_clicked(self) -> None:
        if not self._current_payload:
            return

        suggested = self._suggested_filename
        if not suggested:
            try:
                suggested = make_event_filename(self._current_payload)
            except Exception:
                suggested = "evento_contingencia.json"

        base_dir = self._last_save_dir or Path(DTES_PENDIENTES_DIR)
        base_dir = Path(base_dir)
        try:
            base_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            logger.exception("No se pudo preparar el directorio de guardado")
            QMessageBox.critical(
                self,
                "Error al guardar",
                "No se pudo preparar la carpeta destino para el evento.",
            )
            return

        initial_path = base_dir / suggested

        fname, _ = QFileDialog.getSaveFileName(
            self,
            "Guardar evento de contingencia",
            str(initial_path),
            "Archivos JSON (*.json)",
            options=QFileDialog.DontUseNativeDialog,
        )
        if not fname:
            return

        try:
            saved_path = save_evento_contingencia_json(self._current_payload, fname)
        except Exception as exc:
            logger.exception("Error al guardar el evento de contingencia")
            QMessageBox.critical(
                self,
                "Error al guardar",
                f"No se pudo guardar el evento de contingencia:\n{exc}",
            )
            return

        self._last_save_dir = Path(saved_path).parent

        msg = QMessageBox(self)
        msg.setWindowTitle("Evento de contingencia")
        msg.setIcon(QMessageBox.Information)
        msg.setText("Evento guardado correctamente.")
        msg.setInformativeText(saved_path)
        open_btn = msg.addButton("Abrir carpeta", QMessageBox.ActionRole)
        msg.addButton(QMessageBox.Ok)
        msg.exec_()
        if msg.clickedButton() is open_btn:
            QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(Path(saved_path).parent))
            )

    def _on_enviar_evento_clicked(self) -> None:
        self._validation_active = True
        errors, first_key = self._update_action_state()
        if errors:
            if first_key:
                self._focus_field(first_key)
            QMessageBox.warning(
                self,
                "Evento de contingencia",
                "Completa los campos requeridos antes de enviar.",
            )
            return

        payload = self._build_event_payload(show_errors=True)
        if payload is None:
            self._update_send_button()
            return

        if not self._is_payload_valid_for_send(payload):
            QMessageBox.warning(
                self,
                "Evento de contingencia",
                "El evento generado no cumple con los requisitos mínimos.",
            )
            self._update_send_button()
            return

        confirm = QMessageBox.question(
            self,
            "Enviar Evento",
            "¿Enviar el Evento de Contingencia a Hacienda?",
        )
        if confirm != QMessageBox.Yes:
            self._update_send_button()
            return

        try:
            evento_id = self._get_or_create_evento_id(payload)
        except Exception as exc:
            logger.exception("No se pudo preparar el ID del evento", exc_info=exc)
            QMessageBox.critical(
                self,
                "Evento de contingencia",
                "No se pudo preparar un identificador válido para el evento.",
            )
            self._update_send_button()
            return

        db = getattr(self.manager, "db", None)
        if db is None:
            QMessageBox.critical(
                self,
                "Evento de contingencia",
                "No se encontró la conexión a la base de datos.",
            )
            self._update_send_button()
            return

        self.btn_enviar_evento.setEnabled(False)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            resp = dte.enviar_evento_contingencia(db, evento_id, payload)
        except Exception as exc:
            logger.exception("Error al enviar evento de contingencia", exc_info=exc)
            QMessageBox.critical(
                self,
                "Enviar a Hacienda",
                str(exc),
            )
            resp = None
        finally:
            QApplication.restoreOverrideCursor()
            self._update_send_button()

        if not isinstance(resp, dict):
            return

        estado = str(resp.get("estado") or "").strip()
        sello = str(resp.get("sello") or "").strip()
        obs_text = self._format_observaciones_text(resp)

        estado_ok = estado.lower() in {"recibido", "aceptado", "procesado"}

        if estado_ok and sello:
            partes = [f"Estado: {estado}"]
            if sello:
                partes.append(f"Sello: {sello}")
            if obs_text:
                partes.append(obs_text)
            QMessageBox.information(
                self,
                "Evento enviado",
                "\n\n".join(partes),
            )
            return

        detalle = resp.get("detalle")
        errores = resp.get("errores")

        partes = [f"Estado: {estado or 'Desconocido'}"]
        if sello:
            partes.append(f"Sello: {sello}")

        if detalle:
            textos = _gather_rejection_texts(detalle)
            if textos:
                partes.append("\n".join(textos))
            else:
                partes.append(str(detalle))

        if errores:
            textos = _gather_rejection_texts(errores)
            if textos:
                partes.append(
                    "Errores:\n" + "\n".join(f"- {line}" for line in textos if line.strip())
                )
            else:
                partes.append(str(errores))

        if obs_text:
            partes.append(obs_text)

        QMessageBox.warning(
            self,
            "Evento no aceptado",
            "\n\n".join(partes),
        )


class FacturacionTab(QWidget):
    """Tab para gestionar facturas y notas."""

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self._anexo_xix_registros_provider = getattr(manager, "get_anexo_xix_registros", None)
        self._anexo_contribuyentes_registros_provider = getattr(
            manager, "get_anexo_contribuyentes_registros", None
        )
        self._anexo_consumidor_final_registros_provider = getattr(
            manager, "get_anexo_consumidor_final_registros", None
        )
        self.email_thread = None
        self._email_loading_dialog = None
        self._setup_ui()
        # Clean up any stale invoice references before loading
        # documents into the table. This prevents entries tied to
        # deleted sales or missing files from showing as "Sin venta".
        self._get_invoices_from_db()
        self.load_invoices()
        # Periodically refresh to show newly generated invoices without
        # requiring the user to press the "Actualizar" button. This keeps
        # the table in sync with the underlying data and any invoices
        # created from other parts of the application.
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(10000)  # 10 seconds
        self._refresh_timer.timeout.connect(self.refresh_and_reload)
        self._refresh_timer.start()

    def _setup_ui(self):
        root_layout = QVBoxLayout(self)

        self.section_tabs = QTabWidget(self)
        root_layout.addWidget(self.section_tabs)

        facturacion_container = QWidget()
        self.section_tabs.addTab(facturacion_container, "Facturación")

        main_layout = QHBoxLayout(facturacion_container)

        left_layout = QVBoxLayout()

        filter_layout = QHBoxLayout()
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Buscar número o cliente")
        filter_layout.addWidget(self.search_bar)

        self.client_filter = QComboBox()
        self.client_filter.addItem("Todos", None)
        for c in self.manager._clientes:
            self.client_filter.addItem(c.get("nombre", ""), c.get("id"))
        filter_layout.addWidget(self.client_filter)

        self.vendedor_filter = QComboBox()
        self.vendedor_filter.addItem("Todos", None)
        for v in self.manager.db.get_trabajadores(solo_vendedores=True):
            self.vendedor_filter.addItem(v.get("nombre", ""), v.get("id"))
        filter_layout.addWidget(self.vendedor_filter)

        self.tipo_filter = QComboBox()
        self.tipo_filter.addItems([
            "Todos",
            "Consumidor final",
            "Crédito fiscal",
            "Ticket",
            "Nota de débito",
            "Nota de crédito",
            "Nota de remisión",
        ])
        filter_layout.addWidget(self.tipo_filter)

        self.date_filter_cb = QCheckBox("Filtrar por fecha")
        self.quick_range = QComboBox()
        self.quick_range.addItems(["Personalizado", "Hoy", "Esta semana", "Este mes", "Este año"])
        self.date_from = QDateEdit(QDate.currentDate().addYears(-2))
        self.date_from.setCalendarPopup(True)
        self.date_to = QDateEdit(QDate.currentDate())
        self.date_to.setCalendarPopup(True)
        self.quick_range.setEnabled(False)
        self.date_from.setEnabled(False)
        self.date_to.setEnabled(False)
        for w in [self.date_filter_cb, self.quick_range, QLabel("Desde"), self.date_from,
                  QLabel("Hasta"), self.date_to]:
            filter_layout.addWidget(w)
        self.date_filter_cb.toggled.connect(self._toggle_date_filter)
        self.quick_range.currentIndexChanged.connect(self._apply_quick_range)
        self.update_btn = QPushButton("Actualizar")
        filter_layout.addWidget(self.update_btn)
        self.sent_filter_cb = QCheckBox("Ver solo DTE enviados")
        filter_layout.addWidget(self.sent_filter_cb)
        self.sent_filter_cb.toggled.connect(self.load_invoices)
        filter_layout.addStretch(1)
        left_layout.addLayout(filter_layout)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["ID", "Fecha", "Cliente", "Total", "Estado", "Envio"]
        )
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        left_layout.addWidget(self.table)

        btns = QHBoxLayout()
        # Botón para crear notas asociadas a la factura seleccionada
        self.btn_nota = QPushButton("Nota crédito / débito")
        self.btn_nota.clicked.connect(self.abrir_dialogo_tipo_nota)
        self.btn_remision = QPushButton("Nota remisión")
        self.btn_remision.clicked.connect(self.abrir_dialogo_nota_remision)
        self.btn_enviar = QPushButton("Enviar")
        self.btn_enviar.setEnabled(False)
        self.btn_evento_contingencia = QPushButton("Evento de contingencia…")

        self.btn_imprimir = QPushButton("Imprimir")
        self.btn_abrir_pdf = QPushButton("Abrir PDF")
        self.btn_eliminar = QPushButton("Eliminar")
        self.btn_eliminar.setStyleSheet(
            "background-color: #b71c1c; color: #fff; border-radius: 6px;",
        )
        btns.addWidget(self.btn_nota)
        btns.addWidget(self.btn_remision)
        btns.addWidget(self.btn_enviar)
        btns.addWidget(self.btn_evento_contingencia)
        btns.addWidget(self.btn_imprimir)
        btns.addWidget(self.btn_abrir_pdf)
        btns.addWidget(self.btn_eliminar)
        btns.addStretch(1)
        left_layout.addLayout(btns)

        main_layout.addLayout(left_layout, 3)

        preview_layout = QVBoxLayout()
        self.preview_label = QLabel("Previsualización del PDF")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setStyleSheet("background:#DDD; padding:20px;")
        self.preview_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.preview_label.setScaledContents(True)
        preview_scroll = QScrollArea()
        preview_scroll.setWidgetResizable(True)
        preview_scroll.setWidget(self.preview_label)
        preview_layout.addWidget(preview_scroll)
        main_layout.addLayout(preview_layout, 2)

        # Connect signals
        self.update_btn.clicked.connect(self.refresh_and_reload)
        self.search_bar.returnPressed.connect(self.load_invoices)
        self.client_filter.currentIndexChanged.connect(self.load_invoices)
        self.vendedor_filter.currentIndexChanged.connect(self.load_invoices)
        self.tipo_filter.currentIndexChanged.connect(self.load_invoices)
        self.date_from.dateChanged.connect(self.load_invoices)
        self.date_to.dateChanged.connect(self.load_invoices)
        self.table.itemSelectionChanged.connect(self.show_invoice)
        self.table.itemSelectionChanged.connect(self._update_send_btn)
        self.table.itemDoubleClicked.connect(self.mostrar_detalle_factura)

        self.btn_enviar.clicked.connect(self.send_selected_invoice)
        self.btn_evento_contingencia.clicked.connect(self._enviar_evento_contingencia)
        self.btn_imprimir.clicked.connect(self.print_invoice)
        self.btn_abrir_pdf.clicked.connect(self.open_pdf)
        self.btn_eliminar.clicked.connect(self.delete_invoice)

        self._setup_declaracion_tab()

    def _setup_declaracion_tab(self):
        declaracion_widget = QWidget()
        layout = QVBoxLayout(declaracion_widget)
        layout.setSpacing(12)

        intro = QLabel(
            "Cargue la lista de documentos del período y luego genere la planilla"
            " en formato XLSX/CSV."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form_layout = QFormLayout()

        periodo_container = QWidget()
        periodo_layout = QHBoxLayout(periodo_container)
        periodo_layout.setContentsMargins(0, 0, 0, 0)
        periodo_layout.setSpacing(6)

        self.declaracion_mes_combo = QComboBox()
        meses = [
            ("Enero", "01"),
            ("Febrero", "02"),
            ("Marzo", "03"),
            ("Abril", "04"),
            ("Mayo", "05"),
            ("Junio", "06"),
            ("Julio", "07"),
            ("Agosto", "08"),
            ("Septiembre", "09"),
            ("Octubre", "10"),
            ("Noviembre", "11"),
            ("Diciembre", "12"),
        ]
        for nombre, numero in meses:
            self.declaracion_mes_combo.addItem(nombre, numero)

        today = date.today()
        self.declaracion_mes_combo.setCurrentIndex(today.month - 1)

        self.declaracion_anio_input = QLineEdit()
        self.declaracion_anio_input.setPlaceholderText("AAAA")
        self.declaracion_anio_input.setMaxLength(4)
        self.declaracion_anio_input.setText(str(today.year))

        periodo_layout.addWidget(self.declaracion_mes_combo)
        periodo_layout.addWidget(self.declaracion_anio_input)

        form_layout.addRow("Período:", periodo_container)

        output_container = QWidget()
        output_layout = QHBoxLayout(output_container)
        output_layout.setContentsMargins(0, 0, 0, 0)
        self.declaracion_output_dir_edit = QLineEdit()
        self.declaracion_output_dir_edit.setPlaceholderText("Selecciona la carpeta de salida")
        output_layout.addWidget(self.declaracion_output_dir_edit)
        browse_btn = QPushButton("Seleccionar carpeta…")
        browse_btn.clicked.connect(self._browse_declaracion_output_dir)
        output_layout.addWidget(browse_btn)
        form_layout.addRow("Carpeta de salida:", output_container)

        layout.addLayout(form_layout)

        buttons_layout = QHBoxLayout()
        buttons_layout.setContentsMargins(0, 0, 0, 0)

        self.declaracion_cargar_contribuyentes_btn = QPushButton("Contribuyentes")
        self.declaracion_cargar_contribuyentes_btn.clicked.connect(
            self._handle_cargar_contribuyentes
        )
        buttons_layout.addWidget(self.declaracion_cargar_contribuyentes_btn)

        self.declaracion_cargar_cf_btn = QPushButton("Consumidor final")
        self.declaracion_cargar_cf_btn.clicked.connect(self._handle_cargar_cf)
        buttons_layout.addWidget(self.declaracion_cargar_cf_btn)

        self.declaracion_cargar_xix_btn = QPushButton("Anulaciones")
        self.declaracion_cargar_xix_btn.clicked.connect(self._handle_cargar_xix)
        buttons_layout.addWidget(self.declaracion_cargar_xix_btn)

        buttons_layout.addStretch(1)

        self.declaracion_generar_planilla_btn = QPushButton("Generar planilla")
        self.declaracion_generar_planilla_btn.setEnabled(False)
        self.declaracion_generar_planilla_btn.clicked.connect(
            self._handle_generar_planilla
        )
        buttons_layout.addWidget(self.declaracion_generar_planilla_btn)

        layout.addLayout(buttons_layout)

        self.declaracion_table = QTableWidget()
        self.declaracion_table.setColumnCount(0)
        self.declaracion_table.setRowCount(0)
        self.declaracion_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.declaracion_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.declaracion_table.setAlternatingRowColors(True)
        self.declaracion_table.setFocusPolicy(Qt.StrongFocus)
        layout.addWidget(self.declaracion_table)

        header = self.declaracion_table.horizontalHeader()
        header.setStretchLastSection(True)

        self._declaracion_context: str | None = None

        self.declaracion_result_box = QPlainTextEdit()
        self.declaracion_result_box.setReadOnly(True)
        self.declaracion_result_box.setPlaceholderText(
            "Aquí se mostrará el resumen de los DTE cargados y el resultado de la generación."
        )
        self.declaracion_result_box.setMinimumHeight(120)
        layout.addWidget(self.declaracion_result_box)

        layout.addStretch(1)

        self.section_tabs.addTab(declaracion_widget, "Declaración")

    def _browse_declaracion_output_dir(self):
        current_dir = self.declaracion_output_dir_edit.text().strip() or str(Path.home())
        directory = QFileDialog.getExistingDirectory(
            self,
            "Seleccionar carpeta de salida",
            current_dir,
        )
        if directory:
            self.declaracion_output_dir_edit.setText(directory)

    def _obtener_anexo_xix_registros(self, periodo: str) -> List[DTEAnulado]:
        provider = self._anexo_xix_registros_provider
        if callable(provider):
            registros = provider(periodo)
            return list(registros or [])

        manager_provider = getattr(self.manager, "get_anexo_xix_registros", None)
        if callable(manager_provider):
            registros = manager_provider(periodo)
            return list(registros or [])

        return []

    def _obtener_anexo_contribuyentes_registros(
        self, periodo: str
    ) -> List[VentaContribuyente]:
        provider = getattr(self, "_anexo_contribuyentes_registros_provider", None)
        if callable(provider):
            registros = provider(periodo)
            return list(registros or [])

        manager_provider = getattr(self.manager, "get_anexo_contribuyentes_registros", None)
        if callable(manager_provider):
            registros = manager_provider(periodo)
            return list(registros or [])

        return []

    def _obtener_anexo_consumidor_final_registros(self, periodo: str) -> List[VentaCF]:
        provider = getattr(self, "_anexo_consumidor_final_registros_provider", None)
        if callable(provider):
            registros = provider(periodo)
            return list(registros or [])

        manager_provider = getattr(self.manager, "get_anexo_consumidor_final_registros", None)
        if callable(manager_provider):
            registros = manager_provider(periodo)
            return list(registros or [])

        return []

    def _obtener_periodo_declaracion(self, titulo: str) -> str | None:
        anio = self.declaracion_anio_input.text().strip()
        if not re.fullmatch(r"\d{4}", anio):
            QMessageBox.warning(self, titulo, "El año debe tener 4 dígitos.")
            return None

        mes = self.declaracion_mes_combo.currentData()
        return f"{anio}{mes}"

    def _obtener_parametros_declaracion(self, titulo: str) -> tuple[str, str] | None:
        output_dir = self.declaracion_output_dir_edit.text().strip()
        if not output_dir:
            QMessageBox.warning(self, titulo, "Seleccione la carpeta de salida.")
            return None

        periodo = self._obtener_periodo_declaracion(titulo)
        if not periodo:
            return None

        return output_dir, periodo

    @staticmethod
    def _create_table_item(texto: str) -> QTableWidgetItem:
        item = QTableWidgetItem(texto)
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        return item

    def _configure_declaracion_table(self, headers: List[str]) -> None:
        self.declaracion_table.clear()
        self.declaracion_table.setColumnCount(len(headers))
        self.declaracion_table.setHorizontalHeaderLabels(headers)
        header = self.declaracion_table.horizontalHeader()
        if header is not None:
            for index in range(len(headers)):
                if index == 0:
                    header.setSectionResizeMode(index, QHeaderView.ResizeToContents)
                else:
                    header.setSectionResizeMode(index, QHeaderView.Stretch)

    def _clear_declaracion_table(self) -> None:
        self.declaracion_table.clear()
        self.declaracion_table.setRowCount(0)
        self.declaracion_table.setColumnCount(0)
        self._declaracion_context = None
        self.declaracion_generar_planilla_btn.setEnabled(False)

    def _estado_fuente_texto(self, registro: object) -> str:
        estado = getattr(registro, "estado_manual", None) or getattr(registro, "estado", None)
        estado_text = str(estado).strip() if isinstance(estado, str) and estado.strip() else "—"
        fuente = getattr(registro, "estado_fuente", None)
        if not fuente:
            ruta = getattr(registro, "json_path", None)
            if ruta:
                fuente = os.path.basename(str(ruta))
        if fuente:
            fuente_text = str(fuente)
            return f"{estado_text} · {fuente_text}" if estado_text != "—" else fuente_text
        return estado_text

    @staticmethod
    def _cf_tipo_resumen(registros: List[VentaCF]) -> str:
        if not registros:
            return ""
        conteo = Counter(getattr(registro, "tipo", "") or "" for registro in registros)
        partes = [f"{codigo}: {conteo.get(codigo, 0)}" for codigo in ("01", "02", "10", "11")]
        return " | ".join(partes)

    def _populate_table_cf(self, registros: List[VentaCF]) -> None:
        headers = [
            "✔",
            "Fecha",
            "Tipo",
            "Código (Generación)",
            "N° Control",
            "Total (T)",
            "Estado / Fuente",
        ]
        self._configure_declaracion_table(headers)
        self.declaracion_table.setRowCount(len(registros))
        self._declaracion_context = "II"

        for row, registro in enumerate(registros):
            checkbox = QTableWidgetItem()
            checkbox.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            checkbox.setCheckState(Qt.Checked)
            checkbox.setData(Qt.UserRole, registro)
            self.declaracion_table.setItem(row, 0, checkbox)

            fecha = getattr(registro, "fecha", "") or ""
            self.declaracion_table.setItem(row, 1, self._create_table_item(str(fecha)))

            tipo = getattr(registro, "tipo", "") or ""
            self.declaracion_table.setItem(row, 2, self._create_table_item(str(tipo)))

            codigo = getattr(registro, "numero_doc_del", None) or getattr(
                registro, "codigo_generacion", ""
            )
            self.declaracion_table.setItem(row, 3, self._create_table_item(str(codigo)))

            numero_control = getattr(registro, "numero_control", "") or ""
            self.declaracion_table.setItem(
                row, 4, self._create_table_item(str(numero_control))
            )

            total = getattr(registro, "total_ventas", "0.00") or "0.00"
            self.declaracion_table.setItem(row, 5, self._create_table_item(str(total)))

            estado_texto = self._estado_fuente_texto(registro)
            self.declaracion_table.setItem(row, 6, self._create_table_item(estado_texto))

        self.declaracion_generar_planilla_btn.setEnabled(bool(registros))
        self.declaracion_table.resizeRowsToContents()

    def _populate_table_contribuyentes(
        self, registros: List[VentaContribuyente]
    ) -> None:
        headers = [
            "✔",
            "Fecha",
            "Tipo",
            "Código (Generación)",
            "N° Control",
            "Cliente",
            "Total (P)",
            "Estado / Fuente",
            "Sello",
        ]
        self._configure_declaracion_table(headers)
        self.declaracion_table.setRowCount(len(registros))
        self._declaracion_context = "I"

        for row, registro in enumerate(registros):
            checkbox = QTableWidgetItem()
            checkbox.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            checkbox.setCheckState(Qt.Checked)
            checkbox.setData(Qt.UserRole, registro)
            self.declaracion_table.setItem(row, 0, checkbox)

            fecha = getattr(registro, "fecha_emision", "") or ""
            self.declaracion_table.setItem(row, 1, self._create_table_item(str(fecha)))

            tipo = getattr(registro, "tipo", "") or ""
            self.declaracion_table.setItem(row, 2, self._create_table_item(str(tipo)))

            codigo = getattr(registro, "codigo_generacion", "") or ""
            self.declaracion_table.setItem(row, 3, self._create_table_item(str(codigo)))

            numero_control = getattr(registro, "numero_control", "") or ""
            self.declaracion_table.setItem(
                row, 4, self._create_table_item(str(numero_control))
            )

            cliente = getattr(registro, "nombre_cliente", "") or ""
            self.declaracion_table.setItem(row, 5, self._create_table_item(str(cliente)))

            total = getattr(registro, "total_ventas", "0") or "0"
            self.declaracion_table.setItem(row, 6, self._create_table_item(str(total)))

            estado_texto = self._estado_fuente_texto(registro)
            self.declaracion_table.setItem(row, 7, self._create_table_item(estado_texto))

            sello = getattr(registro, "sello_recepcion", "") or ""
            self.declaracion_table.setItem(row, 8, self._create_table_item(str(sello)))

        self.declaracion_generar_planilla_btn.setEnabled(bool(registros))
        self.declaracion_table.resizeRowsToContents()

    def _populate_table_xix(self, registros: List[DTEAnulado]) -> None:
        headers = [
            "✔",
            "Tipo",
            "Estado",
            "Sello",
            "Código (Generación)",
            "N° Control",
        ]
        self._configure_declaracion_table(headers)
        self.declaracion_table.setRowCount(len(registros))
        self._declaracion_context = "XIX"

        for row, registro in enumerate(registros):
            checkbox = QTableWidgetItem()
            checkbox.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            checkbox.setCheckState(Qt.Checked)
            checkbox.setData(Qt.UserRole, registro)
            self.declaracion_table.setItem(row, 0, checkbox)

            tipo = getattr(registro, "tipo_documento", "") or ""
            self.declaracion_table.setItem(row, 1, self._create_table_item(str(tipo)))

            estado = getattr(registro, "estado", "") or ""
            self.declaracion_table.setItem(row, 2, self._create_table_item(str(estado)))

            sello = getattr(registro, "sello_recepcion", "") or ""
            self.declaracion_table.setItem(row, 3, self._create_table_item(str(sello)))

            codigo = getattr(registro, "codigo_generacion", "") or ""
            self.declaracion_table.setItem(row, 4, self._create_table_item(str(codigo)))

            numero_control = getattr(registro, "numero_control", "") or ""
            self.declaracion_table.setItem(
                row, 5, self._create_table_item(str(numero_control))
            )

        self.declaracion_generar_planilla_btn.setEnabled(bool(registros))
        self.declaracion_table.resizeRowsToContents()

    def _selected_registros_from_table(self) -> List[object]:
        registros: List[object] = []
        for row in range(self.declaracion_table.rowCount()):
            item = self.declaracion_table.item(row, 0)
            if item is None:
                continue
            if item.checkState() != Qt.Checked:
                continue
            registro = item.data(Qt.UserRole)
            if registro is not None:
                registros.append(registro)
        return registros

    def _handle_cargar_contribuyentes(self):
        periodo = self._obtener_periodo_declaracion("Anexo I")
        if not periodo:
            return

        try:
            registros = self._obtener_anexo_contribuyentes_registros(periodo)
        except Exception as exc:  # pragma: no cover - errores del proveedor
            mensaje = f"No se pudo obtener la lista de contribuyentes: {exc}"
            self._clear_declaracion_table()
            self.declaracion_result_box.setPlainText(mensaje)
            QMessageBox.warning(self, "Anexo I", mensaje)
            return

        if not registros:
            self._clear_declaracion_table()
            mensaje = "No hay DTE de contribuyentes para este período."
            self.declaracion_result_box.setPlainText(mensaje)
            QMessageBox.information(self, "Anexo I", mensaje)
            return

        self._populate_table_contribuyentes(registros)
        self.declaracion_result_box.setPlainText(
            f"{len(registros)} DTE listos para generar el Anexo I."
        )

    def _handle_cargar_cf(self):
        periodo = self._obtener_periodo_declaracion("Anexo II")
        if not periodo:
            return

        try:
            registros = self._obtener_anexo_consumidor_final_registros(periodo)
        except Exception as exc:  # pragma: no cover - errores del proveedor
            mensaje = f"No se pudo obtener la lista de ventas: {exc}"
            self._clear_declaracion_table()
            self.declaracion_result_box.setPlainText(mensaje)
            QMessageBox.warning(self, "Anexo II", mensaje)
            return

        if not registros:
            self._clear_declaracion_table()
            mensaje = "No hay DTE para mostrar en este período."
            self.declaracion_result_box.setPlainText(mensaje)
            QMessageBox.information(self, "Anexo II", mensaje)
            return

        self._populate_table_cf(registros)
        resumen = self._cf_tipo_resumen(registros)
        mensaje = f"{len(registros)} DTE listos para generar el Anexo II."
        if resumen:
            mensaje = f"{mensaje} ({resumen})"
        self.declaracion_result_box.setPlainText(mensaje)

    def _handle_cargar_xix(self):
        periodo = self._obtener_periodo_declaracion("Anexo XIX")
        if not periodo:
            return

        try:
            registros = self._obtener_anexo_xix_registros(periodo)
        except Exception as exc:  # pragma: no cover - errores del proveedor
            mensaje = f"No se pudo obtener la lista de anulaciones: {exc}"
            self._clear_declaracion_table()
            self.declaracion_result_box.setPlainText(mensaje)
            QMessageBox.warning(self, "Anexo XIX", mensaje)
            return

        if not registros:
            self._clear_declaracion_table()
            mensaje = "No hay DTE anulados/invalidados para este período."
            self.declaracion_result_box.setPlainText(mensaje)
            QMessageBox.information(self, "Anexo XIX", mensaje)
            return

        self._populate_table_xix(registros)
        self.declaracion_result_box.setPlainText(
            f"{len(registros)} DTE listos para generar el Anexo XIX."
        )

    def _handle_generar_planilla(self):
        registros = self._selected_registros_from_table()
        if not registros:
            QMessageBox.warning(self, "Declaración", "Seleccione al menos un DTE.")
            return

        contexto = self._declaracion_context
        if contexto not in {"I", "II", "XIX"}:
            QMessageBox.warning(
                self,
                "Declaración",
                "Primero cargue la lista de Contribuyentes, Consumidor final o Anulaciones.",
            )
            return

        parametros = self._obtener_parametros_declaracion("Declaración")
        if not parametros:
            return

        output_dir, periodo = parametros

        self.declaracion_generar_planilla_btn.setEnabled(False)
        resultado: dict[str, object]
        if contexto == "I":
            titulo = "Anexo I"
        elif contexto == "II":
            titulo = "Anexo II"
        else:
            titulo = "Anexo XIX"
        try:
            if contexto == "I":
                resultado = on_click_generar_contribuyentes(output_dir, periodo, registros)
            elif contexto == "II":
                resultado = on_click_generar_consumidor_final(output_dir, periodo, registros)
            else:
                resultado = on_click_generar_anulaciones(output_dir, periodo, registros)
        except Exception as exc:  # pragma: no cover - errores inesperados
            resultado = {
                "success": False,
                "message": f"No se pudo generar la planilla: {exc}",
            }
        finally:
            self.declaracion_generar_planilla_btn.setEnabled(True)

        mensaje = str(resultado.get("message") or "")
        self.declaracion_result_box.setPlainText(mensaje)
        if resultado.get("success"):
            QMessageBox.information(self, titulo, mensaje)
        else:
            QMessageBox.warning(self, titulo, mensaje)

    def _toggle_date_filter(self, checked):
        self.quick_range.setEnabled(checked)
        custom = self.quick_range.currentText() == "Personalizado"
        self.date_from.setEnabled(checked and custom)
        self.date_to.setEnabled(checked and custom)
        if checked:
            self._apply_quick_range()
        else:
            self.load_invoices()

    def _apply_quick_range(self):
        if not self.date_filter_cb.isChecked():
            return
        option = self.quick_range.currentText()
        today = date.today()
        if option == "Hoy":
            self.date_from.setDate(QDate(today))
            self.date_to.setDate(QDate(today))
            self.date_from.setEnabled(False)
            self.date_to.setEnabled(False)
        elif option == "Esta semana":
            start = today - timedelta(days=today.weekday())
            end = start + timedelta(days=6)
            self.date_from.setDate(QDate(start))
            self.date_to.setDate(QDate(end))
            self.date_from.setEnabled(False)
            self.date_to.setEnabled(False)
        elif option == "Este mes":
            start = today.replace(day=1)
            if today.month == 12:
                end = date(today.year, 12, 31)
            else:
                end = date(today.year, today.month + 1, 1) - timedelta(days=1)
            self.date_from.setDate(QDate(start))
            self.date_to.setDate(QDate(end))
            self.date_from.setEnabled(False)
            self.date_to.setEnabled(False)
        elif option == "Este año":
            start = date(today.year, 1, 1)
            end = date(today.year, 12, 31)
            self.date_from.setDate(QDate(start))
            self.date_to.setDate(QDate(end))
            self.date_from.setEnabled(False)
            self.date_to.setEnabled(False)
        else:  # Personalizado
            self.date_from.setEnabled(True)
            self.date_to.setEnabled(True)
        self.load_invoices()

    def refresh_filters(self):
        """Update client and vendor filter combos with latest data."""
        self.client_filter.blockSignals(True)
        self.vendedor_filter.blockSignals(True)

        current_client = self.client_filter.currentData()
        current_vend = self.vendedor_filter.currentData()

        self.client_filter.clear()
        self.client_filter.addItem("Todos", None)
        for c in self.manager._clientes:
            self.client_filter.addItem(c.get("nombre", ""), c.get("id"))

        self.vendedor_filter.clear()
        self.vendedor_filter.addItem("Todos", None)
        for v in self.manager.db.get_trabajadores(solo_vendedores=True):
            self.vendedor_filter.addItem(v.get("nombre", ""), v.get("id"))

        def _restore(combo, value):
            if value is None:
                combo.setCurrentIndex(0)
                return
            for i in range(combo.count()):
                if combo.itemData(i) == value:
                    combo.setCurrentIndex(i)
                    return
            combo.setCurrentIndex(0)

        _restore(self.client_filter, current_client)
        _restore(self.vendedor_filter, current_vend)

        self.client_filter.blockSignals(False)
        self.vendedor_filter.blockSignals(False)

    @staticmethod
    def _map_envio_state(state):
        return map_envio_state(state)

    @classmethod
    def _format_envio_state(cls, estado_ui, estado_ui_tag, estado_raw):
        return format_envio_state(estado_ui, estado_ui_tag, estado_raw)

    @staticmethod
    def _has_successful_envio_status(envio: str | None) -> bool:
        if not envio:
            return False
        envio_norm = str(envio).strip().lower()
        for prefix in ("enviado", "aceptado", "recibido", "procesado"):
            if envio_norm.startswith(prefix):
                return True
        return False

    @staticmethod
    def _get_envio_status_color(envio: str | None) -> QColor | None:
        if not envio:
            return None
        status = str(envio).strip().lower()
        if not status:
            return None

        # Remove parenthetical notes like "Enviado (manual)"
        if "(" in status:
            status = status.split("(", 1)[0].strip()

        def _color(code: str) -> QColor:
            return QColor(code)

        if status.startswith("enviado") or status.startswith("transmitido") or status.startswith("recibido") or status.startswith("procesado"):
            return _color("#43A047")  # Green for shipped documents (lighter tone)
        if status.startswith("aceptado"):
            return _color("#66BB6A")  # Green for accepted (lighter tone)
        if status.startswith("rechazado"):
            return _color("#EF5350")  # Red for rejected shipments (lighter tone)
        if status.startswith("anulad"):
            return _color("#42A5F5")  # Blue for voided documents (lighter tone)
        if status.startswith("pendiente"):
            return _color("#FFA726")  # Orange for pending shipments (lighter tone)
        if status.startswith("error"):
            return _color("#6C757D")  # Gray for error states
        return None

    @staticmethod
    def _should_bold_envio_status(envio: str | None) -> bool:
        if not envio:
            return False
        status = str(envio).strip().lower()
        if not status:
            return False
        if "(" in status:
            status = status.split("(", 1)[0].strip()
        return not status.startswith("pendiente")

    @classmethod
    def _detectar_estado_factura(
        cls,
        venta,
        pdf_path=None,
        json_path=None,
        cur=None,
        *,
        venta_id=None,
        numero_control=None,
        codigo_generacion=None,
        doc_tipo=None,
    ):
        return detectar_estado_factura(
            venta,
            pdf_path,
            json_path,
            cur,
            venta_id=venta_id,
            numero_control=numero_control,
            codigo_generacion=codigo_generacion,
            doc_tipo=doc_tipo,
        )

    def _get_available_envio_states(self, current_state: str | None = None) -> list[str]:
        base_states = [
            "Pendiente de envío",
            "Enviado",
            "Aceptado",
            "Rechazado",
            "Anulado",
        ]
        options: list[str] = []
        seen: set[str] = set()

        for state in base_states:
            text = str(state or "").strip()
            if text and text not in seen:
                options.append(text)
                seen.add(text)

        extras: set[str] = set()
        manager = getattr(self, "manager", None)
        db = getattr(manager, "db", None) if manager else None
        cur = getattr(db, "cursor", None) if db else None
        if cur is not None:
            rows = []
            try:
                cur.execute("SELECT estado_ui, estado_ui_tag, estado FROM dte_envios")
                rows = cur.fetchall()
            except Exception:
                try:
                    cur.execute("SELECT estado FROM dte_envios")
                    rows = cur.fetchall()
                except Exception:
                    rows = []
            for raw_row in rows:
                try:
                    row_dict = dict(raw_row)
                except Exception:
                    row_dict = {}
                    if isinstance(raw_row, (list, tuple)):
                        if len(raw_row) >= 3:
                            row_dict = {
                                "estado_ui": raw_row[0],
                                "estado_ui_tag": raw_row[1],
                                "estado": raw_row[2],
                            }
                        elif raw_row:
                            row_dict = {"estado": raw_row[0]}
                formatted = self._format_envio_state(
                    row_dict.get("estado_ui"),
                    row_dict.get("estado_ui_tag"),
                    row_dict.get("estado"),
                )
                formatted_text = str(formatted or "").strip()
                if formatted_text and formatted_text not in seen:
                    extras.add(formatted_text)

        for extra in sorted(extras, key=lambda s: s.lower()):
            if extra not in seen:
                options.append(extra)
                seen.add(extra)

        if current_state:
            current_text = str(current_state).strip()
            if current_text and current_text not in seen:
                options.append(current_text)
                seen.add(current_text)

        return options

    def _update_invoice_envio_state(
        self,
        entry: Mapping[str, Any] | None,
        factura_info: Mapping[str, Any] | None,
        factura_json: Mapping[str, Any] | None,
        new_state: str,
    ) -> str:
        manager = getattr(self, "manager", None)
        db = getattr(manager, "db", None) if manager else None
        if db is None:
            raise ValueError("Base de datos no disponible")

        state_text = str(new_state or "").strip()
        if not state_text:
            raise ValueError("Seleccione un estado válido")

        match = re.match(r"^(.*?)(?:\s*\(([^)]+)\))?$", state_text)
        base = match.group(1).strip() if match else state_text
        tag = match.group(2).strip().lower() if match and match.group(2) else ""
        if not base:
            raise ValueError("Seleccione un estado válido")

        base_lower = base.lower()
        if base_lower in {"pendiente de envío", "pendiente de envio"}:
            stored_base = "Pendiente"
        else:
            stored_base = base

        stored_tag = tag if stored_base in {"Enviado", "Rechazado"} else ""

        numero_control = None
        codigo_generacion = None
        venta_id = None

        if isinstance(factura_info, Mapping):
            numero_control = factura_info.get("control") or factura_info.get("numero_control")
            venta_id = factura_info.get("venta_id")

        if isinstance(entry, Mapping):
            numero_control = numero_control or entry.get("numero_control")
            if venta_id is None:
                venta_id = entry.get("venta_id")

        ident = factura_json.get("identificacion") if isinstance(factura_json, Mapping) else None
        if isinstance(ident, Mapping):
            numero_control = numero_control or ident.get("numeroControl")
            codigo_generacion = ident.get("codigoGeneracion")

        updated = db.update_envio_estado_ui(
            venta_id=venta_id,
            numero_control=numero_control,
            codigo_generacion=codigo_generacion,
            estado_ui=stored_base,
            estado_ui_tag=stored_tag or None,
        )
        if not updated:
            raise ValueError("No se encontró un registro de envío para esta factura")

        return self._format_envio_state(stored_base, stored_tag, None)

    def _get_invoices_from_db(self):
        """Return invoice entries stored in the database.

        Unlike the previous implementation, records are no longer
        deleted when their corresponding sale or files are missing. Such
        entries are kept and flagged through the ``estado`` field so they
        can be inspected from the UI. Additionally, the transmission
        state stored in ``dte_envios`` is exposed via the ``envio`` key.
        """

        return get_facturacion_rows(self.manager.db)

    def refresh_and_reload(self):
        """Refresh manager data and reload invoices."""
        self.manager.refresh_data()
        self.refresh_filters()
        self.load_invoices()

    def load_invoices(self):
        # Remember which invoice is currently selected so that automatic
        # refreshes do not interfere with the user's selection.
        selected_id = None
        current_items = self.table.selectedItems()
        if current_items:
            data = current_items[0].data(Qt.UserRole)
            if isinstance(data, dict):
                selected_id = data.get("id")

        search = self.search_bar.text().lower() if hasattr(self, "search_bar") else ""
        if self.date_filter_cb.isChecked():
            d_from = self.date_from.date().toPyDate()
            d_to = self.date_to.date().toPyDate()
        else:
            d_from = d_to = None
        tipo = self.tipo_filter.currentText()
        cliente_filter_value = None
        vendedor_filter_value = None
        if hasattr(self, "client_filter"):
            cliente_filter_value = self.client_filter.currentData()
            if cliente_filter_value is not None:
                cliente_filter_value = str(cliente_filter_value)
        if hasattr(self, "vendedor_filter"):
            vendedor_filter_value = self.vendedor_filter.currentData()
            if vendedor_filter_value is not None:
                vendedor_filter_value = str(vendedor_filter_value)

        rows = self._scan_documents()

        for r in list(rows):
            fdate = r.get("_parsed_fecha")
            if self.date_filter_cb.isChecked():
                if d_from and fdate and fdate.date() < d_from:
                    rows.remove(r)
                    continue
                if d_to and fdate and fdate.date() > d_to:
                    rows.remove(r)
                    continue
            if tipo != "Todos" and r.get("tipo") != tipo:
                rows.remove(r)
                continue
            if cliente_filter_value is not None:
                if str(r.get("cliente_id")) != cliente_filter_value:
                    rows.remove(r)
                    continue
            if vendedor_filter_value is not None:
                if str(r.get("vendedor_id")) != vendedor_filter_value:
                    rows.remove(r)
                    continue
            cliente = r.get("cliente", "")
            if search and search not in r.get("name", "").lower() and search not in cliente.lower():
                rows.remove(r)
                continue
            envio = r.get("envio", "")
            if (
                getattr(self, "sent_filter_cb", None)
                and self.sent_filter_cb.isChecked()
                and envio not in {"Aceptado", "Rechazado", "Error"}
            ):
                rows.remove(r)
                continue

        rows.sort(
            key=lambda r: (
                r.get("_parsed_fecha") is None,
                -(r.get("_parsed_fecha").timestamp() if r.get("_parsed_fecha") else 0),
            )
        )

        self.table.setRowCount(len(rows))
        selected_row = None
        for row, v in enumerate(rows):
            tipo_item_text = self._format_tipo_display(v)
            if not tipo_item_text:
                codigo = v.get("codigo") or ""
                tipo = v.get("tipo") or ""
                if codigo:
                    tipo_item_text = f"{codigo} {tipo}".strip()
                else:
                    tipo_item_text = tipo or v.get("name", "")
            self.table.setItem(row, 0, QTableWidgetItem(tipo_item_text))
            self.table.setItem(row, 1, QTableWidgetItem(v.get("fecha", "")))
            cliente_item = QTableWidgetItem(self._format_cliente_display(v))
            self.table.setItem(row, 2, cliente_item)
            total = v.get("total")
            signo = v.get("sign", 1)
            if isinstance(total, (int, float)):
                display = f"${abs(total):.2f}"
                if v.get("tipo") in ("Nota de crédito", "Nota de débito"):
                    pref = "+" if signo >= 0 else "−"
                    display = f"{pref}{display}"
                self.table.setItem(row, 3, QTableWidgetItem(display))
            else:
                self.table.setItem(row, 3, QTableWidgetItem(""))
            estado_text = v.get("estado", "")
            estado_item = QTableWidgetItem(estado_text)
            if estado_text and estado_text.strip().lower() == "contingencia":
                estado_font = estado_item.font()
                estado_font.setBold(True)
                estado_item.setFont(estado_font)
                estado_item.setForeground(QBrush(QColor("#D9534F")))
            self.table.setItem(row, 4, estado_item)
            envio_text = v.get("envio", "")
            envio_item = QTableWidgetItem(envio_text)
            envio_color = self._get_envio_status_color(envio_text)
            if envio_color:
                envio_item.setForeground(QBrush(envio_color))
            if self._should_bold_envio_status(envio_text):
                envio_font = envio_item.font()
                envio_font.setBold(True)
                envio_item.setFont(envio_font)
            self.table.setItem(row, 5, envio_item)
            for col in range(6):
                item = self.table.item(row, col)
                if item:
                    item.setData(Qt.UserRole, v)
            if selected_id is not None and v.get("id") == selected_id:
                selected_row = row

        if selected_row is not None:
            self.table.selectRow(selected_row)
        elif selected_id is None and rows:
            self.table.selectRow(0)
        else:
            self.table.clearSelection()
        self._update_send_btn()

    def _format_cliente_display(self, entry: dict) -> str:
        """Return the client label without correlativo information."""

        return entry.get("cliente") or ""

    def _format_tipo_display(self, entry: dict) -> str:
        """Return the DTE type label including correlativo when available."""

        tipo = str(entry.get("tipo") or "").strip()
        tipo_label = TIPO_DTE_SHORT_DESC.get(tipo.lower(), tipo)

        numero_control = entry.get("numero_control") or entry.get("name") or ""
        correlativo = self._extract_correlativo(numero_control)

        if correlativo:
            if tipo_label:
                return f"{tipo_label} {correlativo}".strip()
            return correlativo
        return tipo_label

    def _infer_tipo_from_name(self, base_name: str | None, fallback: str | None = None) -> str | None:
        return infer_tipo_from_name(base_name, fallback)

    @staticmethod
    def _extract_correlativo(numero_control: str | None) -> str:
        """Extract the correlativo number without leading zeros for display."""

        if not numero_control:
            return ""
        numero = str(numero_control).strip()
        if not numero:
            return ""
        match = re.search(r"(\d+)$", numero)
        if not match:
            return ""
        digits = match.group(1)
        # Remove only the leading zeros while keeping all remaining digits,
        # including any trailing zero that is part of the correlativo value.
        trimmed = re.sub(r"^0+(?=\d)", "", digits)
        return trimmed or digits or "0"

    def _scan_documents(self):
        result = self._get_invoices_from_db()
        seen = {r.get("name") for r in result}
        cur = self.manager.db.cursor
        folders = [
            CF_DIR,
            CREDITO_DIR,
            TICKETS_DIR,
            NOTAS_DEBITO_DIR,
            NOTAS_CREDITO_DIR,
            NOTAS_REMISION_DIR,
        ] + ADDITIONAL_DIRS
        files = {}
        for folder in folders:
            if not os.path.isdir(folder):
                continue
            if folder == CF_DIR or "consumidor_final" in folder:
                folder_tipo = "Consumidor final"
            elif folder == CREDITO_DIR or "credito_fiscal" in folder:
                folder_tipo = "Crédito fiscal"
            elif folder == TICKETS_DIR or "tickets" in folder:
                folder_tipo = "Ticket"
            elif folder == NOTAS_DEBITO_DIR or "notas_debito" in folder:
                folder_tipo = "Nota de débito"
            elif folder == NOTAS_CREDITO_DIR or "notas_credito" in folder:
                folder_tipo = "Nota de crédito"
            elif folder == NOTAS_REMISION_DIR or "notas_remision" in folder:
                folder_tipo = "Nota de remisión"
            else:
                folder_tipo = None
            for root, _dirs, fnames in os.walk(folder):
                for fname in fnames:
                    base, ext = os.path.splitext(fname)
                    if ext.lower() not in (".pdf", ".json"):
                        continue
                    match = DOC_PATTERN.match(base)
                    if not match:
                        continue
                    doc_suffix = match.group(1).lower()
                    if doc_suffix == "ticket" and ext.lower() == ".pdf":
                        # Los archivos PDF en formato ticket corresponden a la misma
                        # factura y no deben mostrarse como registros separados,
                        # sin importar en qué carpeta estén almacenados. Se permite
                        # procesar archivos complementarios (por ejemplo JSON) para
                        # conservar su información asociada.
                        continue
                    tipo_hint = folder_tipo
                    if not tipo_hint:
                        tipo_hint = {
                            "consumidorfinal": "Consumidor final",
                            "creditofiscal": "Crédito fiscal",
                            "notadebito": "Nota de débito",
                            "notacredito": "Nota de crédito",
                            "notaremision": "Nota de remisión",
                        }.get(doc_suffix)
                    canonical_tipo = self._infer_tipo_from_name(base, tipo_hint or doc_suffix)
                    entry_tipo = canonical_tipo
                    if doc_suffix == "ticket":
                        entry_tipo = canonical_tipo or "Ticket"
                    if base in seen:
                        continue
                    entry = files.setdefault(base, {"tipo": entry_tipo})
                    entry.setdefault(ext.lower(), os.path.join(root, fname))
                    if entry_tipo:
                        entry["tipo"] = entry_tipo
                    elif canonical_tipo:
                        entry.setdefault("tipo", canonical_tipo)

        for base, paths in files.items():
            pdf = paths.get(".pdf")
            js = paths.get(".json")
            tipo = paths.get("tipo")
            tipo = self._infer_tipo_from_name(base, tipo)
            if tipo == "Ticket":
                # Los PDFs generados en formato ticket corresponden a la misma
                # factura y no deben mostrarse como documentos independientes
                # en la lista de facturación.
                continue
            estado, envio = self._detectar_estado_factura(
                None,
                pdf,
                js,
                cur,
                doc_tipo=tipo,
            )
            numero = base
            fecha = ""
            cliente = ""
            total = None
            signo = 1
            fdate = None
            codigo = None
            codigo_gen = None
            if js and os.path.exists(js):
                try:
                    with open(js, "r", encoding="utf-8") as fh:
                        data = json.load(fh)
                    ident = data.get("identificacion", {})
                    numero = ident.get("numeroControl", numero)
                    codigo = ident.get("tipoDte")
                    if codigo is None:
                        codigo = _tipo_code_from_desc(tipo)
                    if codigo is not None:
                        try:
                            codigo = str(codigo).zfill(2)
                        except Exception:
                            codigo = None
                    codigo_gen = ident.get("codigoGeneracion")
                    fecha = ident.get("fecEmi", "")
                    hora = ident.get("horEmi", "")
                    cliente = data.get("receptor", {}).get("nombre", "")

                    resumen = data.get("resumen", {})
                    if tipo in ("Nota de crédito", "Nota de débito"):
                        total = resumen.get("montoTotalOperacion")
                        signo = -1 if tipo == "Nota de crédito" else 1
                    else:
                        total = resumen.get("totalPagar")
                    try:
                        total = abs(float(total))
                    except (TypeError, ValueError):
                        total = None

                    if fecha:
                        try:
                            if hora:
                                fdate = datetime.strptime(
                                    f"{fecha} {hora}", "%Y-%m-%d %H:%M:%S"
                                )
                                fecha = fdate.strftime("%Y-%m-%d %H:%M")
                            else:
                                fdate = datetime.strptime(fecha, "%Y-%m-%d")
                                fecha = fdate.strftime("%Y-%m-%d")
                        except Exception:
                            fdate = None

                    estado, envio = self._detectar_estado_factura(
                        None,
                        pdf,
                        js,
                        cur,
                        numero_control=numero,
                        codigo_generacion=codigo_gen,
                        doc_tipo=tipo,
                    )
                except Exception:
                    estado = "Incompleta"
                    envio = "Pendiente de envío"
            uid_src = js or pdf or base
            row_id = hashlib.sha1(uid_src.encode("utf-8")).hexdigest()
            result.append(
                {
                    "row_type": "orphan",
                    "id": row_id,
                    "venta_id": None,
                    "name": numero,
                    "numero_control": numero,
                    "codigo": codigo,
                    "pdf": pdf,
                    "json": js,
                    "fecha": fecha,
                    "_parsed_fecha": fdate,
                    "estado": estado,
                    "envio": envio,
                    "cliente": cliente,
                    "cliente_id": None,
                    "vendedor_id": None,
                    "total": total,
                    "sign": signo,
                    "tipo": tipo,
                }
            )
        return result


    def _selected_entry(self):
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            return None
        row = selected_rows[0].row()
        item = self.table.item(row, 0)
        return item.data(Qt.UserRole) if item else None

    @staticmethod
    def _normalize_factura_payload(payload):
        """Return a dict exposing DTE fields at the top level.

        Factura JSON files generated by :func:`persist_client_json` wrap the
        canonical DTE inside a ``dteJson`` key while keeping metadata such as
        ``selloRecibido`` alongside it.  Several workflows – including
        invalidation – expect the identification fields to live at the root
        mapping, so this helper flattens the structure while preserving the
        additional metadata.  When ``payload`` already exposes the canonical
        layout the original object is returned unchanged.
        """

        if isinstance(payload, dict):
            inner = payload.get("dteJson")
            if isinstance(inner, Mapping):
                merged = dict(inner)
                merged.setdefault("dteJson", dict(inner))
                for key, value in payload.items():
                    if key == "dteJson":
                        continue
                    merged.setdefault(key, value)
                payload.clear()
                payload.update(merged)
            return payload

        if isinstance(payload, Mapping):
            inner = payload.get("dteJson")
            if isinstance(inner, Mapping):
                merged = dict(inner)
                merged.setdefault("dteJson", dict(inner))
                for key, value in payload.items():
                    if key == "dteJson":
                        continue
                    merged.setdefault(key, value)
                return merged
            return dict(payload)

        return {} if payload is None else payload

    def _selected_factura(self):
        """Return information about the selected invoice.

        The returned dictionary contains at least the JSON path and
        control number. If the invoice is associated with a sale the
        corresponding ``venta_id`` is also included. ``None`` is
        returned if the selection does not correspond to a valid
        invoice.
        """

        data = self._selected_entry()
        if not data:
            return None
        rtype = data.get("row_type")
        if rtype in {"venta", "ticket"}:
            venta_id = data.get("venta_id")
            pdf_path = None
            json_path = None
            if rtype == "venta":
                pdf_path = self.manager.db.get_factura_pdf(venta_id)
                if not pdf_path:
                    return None
                json_path = os.path.splitext(pdf_path)[0] + ".json"
            else:
                _, ticket_path, json_path = self._get_invoice_paths(
                    venta_id, entry=data
                )
                pdf_path = ticket_path or self.manager.db.get_factura_pdf(venta_id)
            if not json_path or not os.path.exists(json_path):
                return None
            control = None
            try:
                with open(json_path, "r", encoding="utf-8") as fh:
                    jdata = json.load(fh)
                jdata = self._normalize_factura_payload(jdata)
                control = jdata.get("identificacion", {}).get("numeroControl")
            except Exception:
                pass
            return {
                "venta_id": venta_id,
                "json": json_path,
                "pdf": pdf_path,
                "control": control,
            }
        if rtype == "orphan":
            json_path = data.get("json")
            pdf_path = data.get("pdf")
            if not json_path or not os.path.exists(json_path):
                return None
            if not pdf_path or not os.path.exists(pdf_path):
                return None
            return {
                "venta_id": data.get("venta_id"),
                "json": json_path,
                "pdf": pdf_path,
                "control": data.get("name"),
            }
        return None

    def _update_send_btn(self):
        entry = self._selected_entry()
        enabled = False
        if entry:
            rtype = entry.get("row_type")
            if rtype in ("venta", "ticket"):
                enabled = True
            elif rtype == "orphan" and entry.get("json") and entry.get("estado") != "Incompleta":
                enabled = True
        self.btn_enviar.setEnabled(enabled)

    def _determine_tipo_dte(self, entry: dict | None) -> str:
        """Return the DTE type code associated with the given entry.

        Sales that correspond to credit-fiscal invoices must be transmitted
        using code ``"03"`` while consumer final invoices and tickets use
        ``"01"``.  The information can be obtained either from the database
        (``ventas_credito_fiscal``) or from the entry metadata which
        includes the human readable ``tipo`` stored in ``facturas_pdf``.
        """

        if not isinstance(entry, dict):
            return "01"

        row_type = entry.get("row_type")
        if row_type == "ticket":
            return "01"

        if row_type != "venta":
            return "01"

        venta_id = entry.get("venta_id")
        manager = getattr(self, "manager", None)
        db = getattr(manager, "db", None) if manager else None

        getter_cf = getattr(db, "get_venta_credito_fiscal", None) if db else None
        if callable(getter_cf) and venta_id is not None:
            try:
                if getter_cf(venta_id):
                    return "03"
            except Exception:
                pass

        tipo_raw = entry.get("tipo")
        if isinstance(tipo_raw, str):
            tipo_lower = tipo_raw.lower()
            tokens_cf = ("crédito fiscal", "credito fiscal", "ccf")
            if any(token in tipo_lower for token in tokens_cf):
                return "03"

        def _tipo_from_json(path: str | None) -> str | None:
            if not path or not isinstance(path, str):
                return None
            if not os.path.exists(path):
                return None
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except Exception:
                return None
            tipo_json = data.get("identificacion", {}).get("tipoDte")
            if isinstance(tipo_json, str):
                tipo_json = tipo_json.strip()
                if tipo_json in {"01", "03"}:
                    return tipo_json
            return None

        tipo_from_json = _tipo_from_json(entry.get("json"))
        if tipo_from_json:
            return tipo_from_json

        getter_pdf = getattr(db, "get_factura_pdf", None) if db else None
        if callable(getter_pdf) and venta_id is not None:
            try:
                pdf_path = getter_pdf(venta_id)
            except Exception:
                pdf_path = None
            if pdf_path:
                tipo_from_json = _tipo_from_json(os.path.splitext(pdf_path)[0] + ".json")
                if tipo_from_json:
                    return tipo_from_json

        return "01"

    def _show_validation_errors(self, errors, json_path):
        """Display validation errors and allow opening a report."""
        msg = QMessageBox(self)
        msg.setWindowTitle("Enviar a Hacienda")
        msg.setIcon(QMessageBox.Warning)
        msg.setText("El DTE contiene errores de validación:")
        msg.setInformativeText("\n".join(f"- {e}" for e in errors))
        open_btn = msg.addButton("Abrir reporte", QMessageBox.ActionRole)
        msg.addButton(QMessageBox.Close)
        msg.exec_()
        if msg.clickedButton() == open_btn and json_path:
            report_path = os.path.splitext(json_path)[0] + ".md"
            with open(report_path, "w", encoding="utf-8") as fh:
                fh.write("# Errores de validación\n\n")
                for e in errors:
                    fh.write(f"- {e}\n")
            QDesktopServices.openUrl(QUrl.fromLocalFile(report_path))

    def _is_duplicate_rejection(self, resp: dict) -> bool:
        texts = _gather_rejection_texts(
            resp.get("detalle"),
            resp.get("errores"),
            resp.get("mensaje"),
            resp.get("descripcion"),
        )
        combined = " ".join(text.lower() for text in texts)
        return any(hint in combined for hint in DUPLICATE_HINTS)

    def _extract_rejection_reason(self, resp: dict) -> tuple[str | None, str | None]:
        codigo: str | None = None
        descripcion: str | None = None

        def inspect(value):
            nonlocal codigo, descripcion
            if isinstance(value, dict):
                for key in ("codigoMsg", "codigo", "codigoError", "codError"):
                    if codigo is None and value.get(key):
                        codigo = str(value.get(key))
                for key in ("descripcionMsg", "descripcion", "mensaje", "observaciones"):
                    if descripcion is None and value.get(key):
                        raw = value.get(key)
                        if isinstance(raw, (list, tuple, set)):
                            textos = _gather_rejection_texts(raw)
                            if textos:
                                descripcion = textos[0]
                        else:
                            descripcion = str(raw)
                if codigo and descripcion:
                    return
                for val in value.values():
                    inspect(val)
            elif isinstance(value, (list, tuple, set)):
                for item in value:
                    inspect(item)

        inspect(resp.get("detalle"))
        if not descripcion:
            inspect(resp.get("errores"))
        if not descripcion:
            textos = _gather_rejection_texts(resp.get("detalle"), resp.get("errores"))
            if textos:
                descripcion = textos[0]
        return codigo, descripcion

    def _format_rejection_reason(self, resp: dict) -> str:
        codigo, descripcion = self._extract_rejection_reason(resp)
        if codigo and descripcion:
            return f"{codigo} - {descripcion}"
        if descripcion:
            return descripcion
        if codigo:
            return str(codigo)
        return "Sin detalle disponible"

    @staticmethod
    def _parse_numero_control(numero_control: str | None) -> dict | None:
        if not numero_control:
            return None
        match = re.match(r"^DTE-(\d{2})-S(\d{3})P(\d{3})-(\d{15})$", str(numero_control))
        if not match:
            return None
        tipo, sucursal, punto, correlativo = match.groups()
        try:
            correlativo_int = int(correlativo)
        except ValueError:
            return None
        return {
            "tipo": tipo,
            "sucursal": sucursal,
            "punto": punto,
            "correlativo": correlativo_int,
        }

    def _revert_correlativo(self, ident_info: dict) -> bool:
        numero_control = ident_info.get("numeroControl")
        serie = self._parse_numero_control(numero_control)
        if not serie:
            QMessageBox.warning(
                self,
                "Enviar a Hacienda",
                "No se pudo revertir el correlativo porque el número de control es inválido.",
            )
            return False

        tipo = serie["tipo"]
        sucursal = serie["sucursal"]
        punto = serie["punto"]
        correlativo = serie["correlativo"]
        try:
            reverted, motivo = self.manager.db.revert_dte_correlativo(
                tipo, sucursal, punto, correlativo
            )
        except Exception as exc:
            logger.exception("Error al intentar revertir correlativo")
            QMessageBox.warning(
                self,
                "Enviar a Hacienda",
                "Ocurrió un error al intentar regresar el correlativo: "
                f"{exc}",
            )
            return False

        if not reverted:
            detalle = motivo or "La numeración de la serie cambió y no se puede deshacer."
            QMessageBox.warning(
                self,
                "Enviar a Hacienda",
                "No se pudo revertir el correlativo.\n" + detalle,
            )
            return False

        nuevo = self.manager.db.get_dte_correlativo(tipo, sucursal, punto)
        logger.info(
            "Correlativo revertido tipo=%s sucursal=%s punto=%s ambiente=%s de %s a %s",
            tipo,
            sucursal,
            punto,
            ident_info.get("ambiente") or "desconocido",
            correlativo,
            nuevo,
        )
        QMessageBox.information(
            self,
            "Enviar a Hacienda",
            "Correlativo regresado al valor anterior.",
        )
        return True

    def _handle_hacienda_rejection(
        self,
        resp: dict,
        *,
        tipo_dte: str | None = None,
        entry: dict | None = None,
        factura: dict | None = None,
    ) -> bool:
        if self._is_duplicate_rejection(resp):
            QMessageBox.information(
                self,
                "Enviar a Hacienda",
                "Este número ya está registrado en Hacienda. No se ofrece revertir correlativo.",
            )
            return True

        ident_info = dict(resp.get("identificacion") or {})
        if tipo_dte and not ident_info.get("tipoDte"):
            ident_info["tipoDte"] = tipo_dte

        numero_control = ident_info.get("numeroControl")
        codigo_generacion = ident_info.get("codigoGeneracion")

        if not numero_control and factura and factura.get("control"):
            numero_control = factura.get("control")
        if not numero_control and entry:
            numero_control = entry.get("name") or entry.get("control")

        if not codigo_generacion and entry:
            codigo_generacion = entry.get("codigo")

        if (factura and factura.get("json")) and (not numero_control or not codigo_generacion):
            try:
                with open(factura.get("json"), "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                ident = data.get("identificacion") or {}
                numero_control = numero_control or ident.get("numeroControl")
                codigo_generacion = codigo_generacion or ident.get("codigoGeneracion")
            except Exception:
                pass

        if numero_control:
            ident_info["numeroControl"] = numero_control
        if codigo_generacion:
            ident_info["codigoGeneracion"] = codigo_generacion

        motivo = self._format_rejection_reason(resp)
        resumen = motivo or "La factura fue rechazada por Hacienda."
        self._show_send_error_dialog(resumen, "Enviar a Hacienda", resp)
        dialog = DTERechazadoDialog(
            numero_control or "Desconocido",
            codigo_generacion or "Desconocido",
            motivo,
            parent=self,
        )
        if dialog.exec_() == QDialog.Accepted:
            if self._revert_correlativo(ident_info):
                QMessageBox.information(
                    self,
                    "Enviar a Hacienda",
                    "La factura será eliminada del sistema.",
                )
                try:
                    self._archive_rejected_invoice(entry, factura)
                except Exception:
                    logger.exception("Error al archivar factura rechazada")
                    QMessageBox.warning(
                        self,
                        "Enviar a Hacienda",
                        "Ocurrió un error al archivar la factura rechazada.",
                    )
        return True

    @staticmethod
    def _stringify_token_detail(detalle):
        if isinstance(detalle, dict):
            for key in ("descripcionMsg", "observaciones", "message", "detalle"):
                val = detalle.get(key)
                if isinstance(val, str) and val.strip():
                    return val.strip()
            if detalle:
                try:
                    return json.dumps(detalle, ensure_ascii=False)
                except TypeError:
                    return str(detalle)
            return ""
        if isinstance(detalle, str):
            return detalle.strip()
        if detalle is None:
            return ""
        try:
            return json.dumps(detalle, ensure_ascii=False)
        except TypeError:
            return str(detalle)

    @classmethod
    def _token_warning_message(cls, response: dict, default: str) -> str:
        detalle = cls._stringify_token_detail(response.get("detalle"))
        if not detalle:
            for key in ("descripcionMsg", "observaciones", "message"):
                value = response.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            return default
        return detalle

    @staticmethod
    def _is_auth_runtime_error(exc: Exception) -> bool:
        text = str(exc or "").strip().lower()
        if not text:
            return False
        keywords = (
            "token",
            "autentic",
            "bearer",
            "credencial",
            "jwt",
        )
        return any(keyword in text for keyword in keywords)

    @staticmethod
    def _is_signer_connection_error(exc: Exception) -> bool:
        text = str(exc or "").strip().lower()
        if not text or "error al firmar" not in text:
            return False
        connection_keywords = (
            "failed to establish a new connection",
            "connection refused",
            "no se puede establecer una conexión",
            "max retries exceeded",
        )
        if any(keyword in text for keyword in connection_keywords):
            return True
        cause = getattr(exc, "__cause__", None)
        while cause is not None:
            if isinstance(cause, ConnectionRefusedError):
                return True
            cause = getattr(cause, "__cause__", None)
        return False

    def _confirm_send_without_signer(self) -> bool:
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Warning)
        msg.setWindowTitle("Enviar a Hacienda")
        msg.setText(SIGNER_DOWN_WARNING)
        send_button = msg.addButton("Enviar sin el firmador", QMessageBox.AcceptRole)
        cancel_button = msg.addButton("Cancelar", QMessageBox.RejectRole)
        msg.setDefaultButton(cancel_button)
        msg.exec_()
        return msg.clickedButton() == send_button

    def _report_snapshot_missing(self, exc: SnapshotNotFoundError) -> None:
        venta_id = getattr(exc, "venta_id", None)
        nota_id = getattr(exc, "nota_id", None)
        print(
            "UI: SHOW_ERROR=snapshot_missing",
            f"venta={venta_id if venta_id is not None else 'n/a'}",
            f"nota={nota_id if nota_id is not None else 'n/a'}",
        )
        QMessageBox.warning(self, "Enviar a Hacienda", SNAPSHOT_MISSING_MESSAGE)

    def _auth_error_message(self, response: dict, default: str) -> str:
        if response.get("auth_error", True):
            return self._token_warning_message(response, default)
        detalle = self._stringify_token_detail(response.get("detalle"))
        if detalle:
            return detalle
        descripcion = self._stringify_token_detail(response.get("descripcionMsg"))
        if descripcion:
            return descripcion
        status = response.get("http_status")
        if status:
            return f"Hacienda devolvió HTTP {status} sin detalle"
        return "La recepción de Hacienda devolvió un error sin detalle"

    @staticmethod
    def _format_observaciones_message(resp: dict | None) -> str:
        """Return a human readable message with Hacienda observations."""

        def collect(value):
            textos: list[str] = []
            if isinstance(value, dict):
                if "observaciones" in value:
                    textos.extend(
                        _gather_rejection_texts(value.get("observaciones"))
                    )
                for key, item in value.items():
                    if key == "observaciones":
                        continue
                    textos.extend(collect(item))
            elif isinstance(value, (list, tuple, set)):
                for item in value:
                    textos.extend(collect(item))
            return textos

        if not isinstance(resp, dict):
            return ""

        textos = collect(resp)
        cleaned: list[str] = []
        seen: set[str] = set()
        for texto in textos:
            text = str(texto).strip()
            if text and text not in seen:
                cleaned.append(text)
                seen.add(text)
        if not cleaned:
            return ""
        formatted = "\n".join(f"- {text}" for text in cleaned)
        return f"Observaciones:\n{formatted}"

    @staticmethod
    def _json_default(value: Any) -> Any:
        if isinstance(value, (set, frozenset)):
            return list(value)
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        return str(value)

    def _format_hacienda_details(self, payload: Any) -> str:
        if payload is None:
            return ""
        if isinstance(payload, str):
            return payload.strip()
        if isinstance(payload, (bytes, bytearray)):
            try:
                return payload.decode("utf-8", errors="replace")
            except Exception:
                return repr(payload)
        try:
            return json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                default=self._json_default,
            )
        except Exception:
            try:
                return pformat(payload, width=80, compact=False)
            except Exception:
                return str(payload)

    def _show_send_error_dialog(
        self,
        summary: str,
        title: str,
        details_payload: Any | None = None,
    ) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.setModal(True)
        layout = QVBoxLayout(dialog)

        summary_text = (summary or "").strip() or "Ocurrió un error al enviar la factura."
        summary_label = QLabel(summary_text)
        summary_label.setWordWrap(True)
        layout.addWidget(summary_label)

        details_text = self._format_hacienda_details(details_payload)
        details_widget: QPlainTextEdit | None = None
        if details_text:
            toggle_button = QPushButton("Ver detalles")
            toggle_button.setCheckable(True)
            layout.addWidget(toggle_button, alignment=Qt.AlignLeft)

            details_widget = QPlainTextEdit()
            details_widget.setReadOnly(True)
            details_widget.setPlainText(details_text)
            details_widget.setLineWrapMode(QPlainTextEdit.NoWrap)
            details_widget.setMinimumHeight(200)
            details_widget.hide()
            layout.addWidget(details_widget)

            def _toggle_details(checked: bool) -> None:
                if not details_widget:
                    return
                details_widget.setVisible(checked)
                toggle_button.setText("Ocultar detalles" if checked else "Ver detalles")
                if checked and details_widget.document().blockCount() > 30:
                    dialog.resize(dialog.width(), max(dialog.height(), 500))

            toggle_button.toggled.connect(_toggle_details)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok)
        button_box.accepted.connect(dialog.accept)
        layout.addWidget(button_box)

        if details_widget:
            dialog.resize(max(dialog.sizeHint().width(), 480), dialog.sizeHint().height())

        dialog.exec_()

    def _mostrar_respuesta_hacienda(
        self, resp: dict | None, title: str = "Enviar a Hacienda"
    ) -> None:
        if not isinstance(resp, dict):
            return

        estado_value = resp.get("estado")
        estado = str(estado_value or "").strip()
        estado_line = f"Estado: {estado or 'Desconocido'}"

        detail_values = [
            resp.get("detalle"),
            resp.get("errores"),
            resp.get("descripcionMsg"),
            resp.get("message"),
        ]
        textos_detalle = _gather_rejection_texts(*detail_values)
        detalle_limpio: list[str] = []
        vistos: set[str] = set()
        for texto in textos_detalle:
            text = str(texto).strip()
            if text and text not in vistos:
                detalle_limpio.append(text)
                vistos.add(text)

        obs_text = self._format_observaciones_message(resp)

        secciones = [estado_line]
        if detalle_limpio:
            secciones.append("\n".join(detalle_limpio))
        if obs_text:
            secciones.append(obs_text)
        mensaje = "\n\n".join(secciones)

        estado_normalizado = estado.lower()
        aceptado = estado_normalizado.startswith("acept")
        recibido = estado_normalizado.startswith("recib")
        transmitido = estado_normalizado.startswith("transmit")
        procesado = estado_normalizado.startswith("proces")

        if aceptado or recibido or transmitido or procesado:
            QMessageBox.information(self, title, mensaje)
        else:
            self._show_send_error_dialog(mensaje, title, resp)

    def _document_already_sent(self, entry: dict | None, factura: dict | None) -> bool:
        if not entry:
            return False

        envio_val = entry.get("envio")
        if self._has_successful_envio_status(envio_val):
            return True

        db = getattr(self.manager, "db", None)
        if db is None:
            return False

        venta_id = entry.get("venta_id")
        if factura and factura.get("venta_id"):
            venta_id = venta_id or factura.get("venta_id")

        envio_state = None
        if venta_id:
            try:
                row = db.cursor.execute(
                    "SELECT estado_ui, estado FROM dte_envios WHERE venta_id=? ORDER BY estado_ui_manual DESC, id DESC LIMIT 1",
                    (venta_id,),
                ).fetchone()
            except Exception:
                row = None
            if row:
                envio_state = row["estado_ui"]
                if not (isinstance(envio_state, str) and envio_state.strip()):
                    envio_state = self._map_envio_state(row["estado"])
                if self._has_successful_envio_status(envio_state):
                    return True

        json_path = factura.get("json") if factura else None
        numero_control = None
        codigo_generacion = None
        if factura:
            numero_control = factura.get("control")
        if json_path and os.path.exists(json_path):
            try:
                with open(json_path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                ident = data.get("identificacion") or data.get("identificador") or {}
                numero_control = ident.get("numeroControl") or numero_control
                codigo_generacion = ident.get("codigoGeneracion") or codigo_generacion
            except Exception:
                pass
        if not numero_control and isinstance(entry.get("name"), str):
            maybe_ctrl = entry.get("name").strip()
            if maybe_ctrl:
                numero_control = numero_control or maybe_ctrl

        cur = getattr(db, "cursor", None)
        if cur is not None:
            try:
                _, envio_state = self._detectar_estado_factura(
                    None,
                    None,
                    json_path,
                    cur,
                    venta_id=venta_id,
                    numero_control=numero_control,
                    codigo_generacion=codigo_generacion,
                    doc_tipo=entry.get("tipo"),
                )
            except Exception:
                envio_state = None
            if self._has_successful_envio_status(envio_state):
                return True

        return False

    def send_selected_invoice(self):
        print("UI: SEND_START")
        entry = self._selected_entry()
        if not entry:
            QMessageBox.warning(self, "Enviar", "Seleccione un documento")
            return

        token_msg = (
            "El token está desactualizado. Debe generar uno nuevo desde la configuración de facturación."
        )

        factura = None
        rtype = entry.get("row_type")
        if rtype in ("venta", "orphan"):
            factura = self._selected_factura()
            if not factura:
                QMessageBox.warning(self, "Enviar", "Seleccione una factura válida")
                return

        dialog = SendOptionsDialog(self)
        dialog.email_cb.setChecked(True)
        dialog.hacienda_cb.setChecked(True)
        if dialog.exec_() != QDialog.Accepted:
            return

        send_email = dialog.email_cb.isChecked()
        send_hacienda = dialog.hacienda_cb.isChecked()

        mh_success = False
        mh_response: dict | None = None

        if send_hacienda:
            if self._document_already_sent(entry, factura):
                answer = QMessageBox.question(
                    self,
                    "Enviar a Hacienda",
                    "Este documento ya fue enviado. Enviarlo nuevamente puede causar conflictos. ¿Estás seguro de continuar?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if answer != QMessageBox.Yes:
                    return
            if rtype == "orphan" and factura:
                json_path = factura.get("json")
                try:
                    print("UI: CALL_ENVIAR_DOCUMENTO")
                    with loading_dialog(self, "Enviando a Hacienda…"):
                        note_kind = self._resolve_orphan_note_kind(entry)
                        if note_kind == "credito":
                            resp = self._reenviar_nota_credito(entry, factura)
                        elif note_kind == "debito":
                            resp = self._reenviar_nota_debito(entry, factura)
                        else:
                            resp = dte.transmitir_dte_orphan(
                                self.manager.db, json_path
                            )
                    if resp.get("http_status") in {401, 403}:
                        message = self._auth_error_message(resp, token_msg)
                        QMessageBox.warning(self, "Enviar a Hacienda", message)
                        return
                    estado = resp.get("estado")
                    estado_norm = str(estado or "").strip().lower()
                    sello_val = (
                        resp.get("sello")
                        or resp.get("selloRecibido")
                        or resp.get("selloRecepcion")
                        or ""
                    )
                    sello_norm = str(sello_val).strip()
                    if estado_norm in {"aceptado", "procesado"} and sello_norm:
                        mh_success = True
                        mh_response = resp
                    if estado == "Error" and resp.get("detalle") == "Sin conexión a Internet":
                        self._show_send_error_dialog(
                            "No hay conexión a Internet. Active la conexión antes de reenviar.",
                            "Enviar a Hacienda",
                            resp,
                        )
                    elif estado in {"Transmitido", "Recibido", "PROCESADO"}:
                        message = "Documento enviado y recibido correctamente"
                        obs_text = self._format_observaciones_message(resp)
                        if obs_text:
                            message = f"{message}\n\n{obs_text}"
                        QMessageBox.information(
                            self,
                            "Enviar a Hacienda",
                            message,
                        )
                    else:
                        detalle = resp.get("detalle")
                        if detalle:
                            logger.debug(
                                "Detalle de respuesta de Hacienda: %s", detalle
                            )
                        if str(estado).lower() == "rechazado":
                            if self._handle_hacienda_rejection(
                                resp, entry=entry, factura=factura
                            ):
                                return
                        mensaje = resp.get("errores")
                        if not mensaje:
                            detalle_dict = detalle if isinstance(detalle, dict) else {}
                            mensaje = detalle_dict.get("descripcionMsg")
                        if mensaje:
                            textos = _gather_rejection_texts(mensaje)
                            mensaje = "\n".join(textos) if textos else str(mensaje)
                        else:
                            mensaje = "Fallo al enviar"
                        obs_text = self._format_observaciones_message(resp)
                        if obs_text:
                            mensaje = f"{mensaje}\n\n{obs_text}"
                        self._show_send_error_dialog(
                            mensaje,
                            "Enviar a Hacienda",
                            resp,
                        )
                except dte.DTEValidationError as exc:
                    print("UI: EXC_CAUGHT", type(exc).__name__, str(exc)[:200])
                    QMessageBox.critical(
                        self, "Enviar a Hacienda", "\n".join(exc.errors)
                    )
                except SnapshotNotFoundError as exc:
                    self._report_snapshot_missing(exc)
                    return
                except RuntimeError as exc:
                    print("UI: EXC_CAUGHT", type(exc).__name__, str(exc)[:200])
                    exc_message = str(exc)
                    if "CERT_ACCESS" in exc_message or "Certificado no accesible" in exc_message:
                        QMessageBox.critical(
                            self,
                            "Firma",
                            "Error de firma: no se pudo acceder al certificado.",
                        )
                        return
                    if self._is_auth_runtime_error(exc):
                        QMessageBox.warning(self, "Enviar a Hacienda", token_msg)
                    else:
                        if self._is_signer_connection_error(exc):
                            logger.warning(
                                "Firmador no disponible al enviar documento",
                                exc_info=exc,
                            )
                            if not self._confirm_send_without_signer():
                                return
                        else:
                            logger.exception("Error al enviar documento", exc_info=exc)
                            QMessageBox.critical(
                                self,
                                "Enviar a Hacienda",
                                GENERIC_SEND_ERROR,
                            )
                except Exception as exc:
                    print("UI: EXC_CAUGHT", type(exc).__name__, str(exc)[:200])
                    logger.exception("Error inesperado al enviar documento", exc_info=exc)
                    QMessageBox.critical(
                        self,
                        "Enviar a Hacienda",
                        GENERIC_SEND_ERROR,
                    )
            else:
                tipo_dte = self._determine_tipo_dte(entry)
                try:
                    print("UI: CALL_ENVIAR_DOCUMENTO")
                    with loading_dialog(self, "Enviando a Hacienda…"):
                        resp = transmitir_dte(
                            self.manager.db,
                            entry.get("venta_id"),
                            tipo_dte=tipo_dte,
                        )  # tickets también se transmiten con tipo "01"
                    if resp.get("http_status") in {401, 403}:
                        message = self._auth_error_message(resp, token_msg)
                        QMessageBox.warning(self, "Enviar a Hacienda", message)
                        return
                    estado = resp.get("estado")
                    estado_norm = str(estado or "").strip().lower()
                    sello_val = (
                        resp.get("sello")
                        or resp.get("selloRecibido")
                        or resp.get("selloRecepcion")
                        or ""
                    )
                    sello_norm = str(sello_val).strip()
                    if estado_norm in {"aceptado", "procesado"} and sello_norm:
                        mh_success = True
                        mh_response = resp
                        if rtype == "venta":
                            venta_id = entry.get("venta_id")
                            if venta_id:
                                try:
                                    self._update_invoice_assets_after_mh(venta_id, resp)
                                except Exception:
                                    logger.exception(
                                        "No se pudo actualizar el PDF posterior al envío",
                                        exc_info=True,
                                    )
                    if estado == "Error" and resp.get("detalle") == "Sin conexión a Internet":
                        self._show_send_error_dialog(
                            "No hay conexión a Internet. Active la conexión antes de reenviar.",
                            "Enviar a Hacienda",
                            resp,
                        )
                    elif estado in {"Transmitido", "Recibido", "PROCESADO"}:
                        message = "Documento enviado y recibido correctamente"
                        obs_text = self._format_observaciones_message(resp)
                        if obs_text:
                            message = f"{message}\n\n{obs_text}"
                        QMessageBox.information(
                            self,
                            "Enviar a Hacienda",
                            message,
                        )
                    else:
                        detalle = resp.get("detalle")
                        if detalle:
                            logger.debug(
                                "Detalle de respuesta de Hacienda: %s", detalle
                            )
                        if str(estado).lower() == "rechazado":
                            if self._handle_hacienda_rejection(
                                resp,
                                tipo_dte=tipo_dte,
                                entry=entry,
                                factura=factura,
                            ):
                                return
                        mensaje = resp.get("errores")
                        if not mensaje:
                            detalle_dict = detalle if isinstance(detalle, dict) else {}
                            mensaje = detalle_dict.get("descripcionMsg")
                        if mensaje:
                            textos = _gather_rejection_texts(mensaje)
                            mensaje = "\n".join(textos) if textos else str(mensaje)
                        else:
                            mensaje = "Fallo al enviar"
                        obs_text = self._format_observaciones_message(resp)
                        if obs_text:
                            mensaje = f"{mensaje}\n\n{obs_text}"
                        self._show_send_error_dialog(
                            mensaje,
                            "Enviar a Hacienda",
                            resp,
                        )
                except dte.DTEValidationError as exc:
                    print("UI: EXC_CAUGHT", type(exc).__name__, str(exc)[:200])
                    QMessageBox.critical(
                        self, "Enviar a Hacienda", "\n".join(exc.errors)
                    )
                except SnapshotNotFoundError as exc:
                    self._report_snapshot_missing(exc)
                    return
                except RuntimeError as exc:
                    print("UI: EXC_CAUGHT", type(exc).__name__, str(exc)[:200])
                    exc_message = str(exc)
                    if "CERT_ACCESS" in exc_message or "Certificado no accesible" in exc_message:
                        QMessageBox.critical(
                            self,
                            "Firma",
                            "Error de firma: no se pudo acceder al certificado.",
                        )
                        return
                    if self._is_auth_runtime_error(exc):
                        QMessageBox.warning(self, "Enviar a Hacienda", token_msg)
                    else:
                        logger.exception("Error al enviar documento", exc_info=exc)
                        QMessageBox.critical(
                            self,
                            "Enviar a Hacienda",
                            GENERIC_SEND_ERROR,
                        )
                except Exception as exc:
                    print("UI: EXC_CAUGHT", type(exc).__name__, str(exc)[:200])
                    logger.exception("Error inesperado al enviar documento", exc_info=exc)
                    QMessageBox.critical(
                        self,
                        "Enviar a Hacienda",
                        GENERIC_SEND_ERROR,
                    )

        if not send_email:
            return

        if rtype == "venta" and factura:
            venta_id = factura.get("venta_id")
            if send_hacienda and not mh_success:
                QMessageBox.warning(
                    self,
                    "Enviar por correo",
                    (
                        "No se enviará el correo porque Hacienda no aceptó el documento."
                        " Reintente cuando el envío sea exitoso."
                    ),
                )
                return
            codigo_generacion = None
            sello_resp = None
            if mh_response:
                ident = (
                    mh_response.get("identificacion")
                    or mh_response.get("identificador")
                    or {}
                )
                codigo_generacion = (
                    (ident.get("codigoGeneracion") or "").strip().upper()
                    or None
                )
                sello_resp = (
                    mh_response.get("sello")
                    or mh_response.get("selloRecibido")
                    or mh_response.get("selloRecepcion")
                )
                if sello_resp:
                    sello_resp = str(sello_resp).strip()
            self._send_invoice_email(
                venta_id,
                force_regenerate=bool(send_hacienda and mh_success),
                expected_codigo=codigo_generacion,
                expected_sello=sello_resp,
            )
        elif rtype == "ticket":
            if send_hacienda and not mh_success:
                QMessageBox.warning(
                    self,
                    "Enviar por correo",
                    (
                        "No se enviará el correo porque Hacienda no aceptó el documento."
                        " Reintente cuando el envío sea exitoso."
                    ),
                )
                return
            self._send_ticket_email(entry.get("venta_id"))
        elif rtype == "orphan" and factura:
            if send_hacienda and not mh_success:
                QMessageBox.warning(
                    self,
                    "Enviar por correo",
                    (
                        "No se enviará el correo porque Hacienda no aceptó el documento."
                        " Reintente cuando el envío sea exitoso."
                    ),
                )
                return
            self._send_orphan_email(entry)

    def _enviar_evento_contingencia(self) -> None:
        dialog = EventoContingenciaDialog(self.manager, self)
        dialog.exec_()


    def _resolve_orphan_note_kind(self, entry: dict | None) -> str | None:
        if not entry:
            return None
        tipo = str(entry.get("tipo") or "").strip().lower()
        if tipo in {"nota de crédito", "nota de credito"}:
            return "credito"
        if tipo in {"nota de débito", "nota de debito"}:
            return "debito"
        return None

    def _reenviar_nota_credito(self, entry: dict, factura: dict) -> dict:
        return self._reenviar_nota(entry, factura, "credito")

    def _reenviar_nota_debito(self, entry: dict, factura: dict) -> dict:
        return self._reenviar_nota(entry, factura, "debito")

    def _reenviar_nota(self, entry: dict, factura: dict, expected_tipo: str) -> dict:
        nota_id = None
        nota_error: ValueError | None = None
        try:
            nota_id = self._buscar_nota_id(factura, expected_tipo)
        except ValueError as exc:
            nota_error = exc

        if nota_id is not None:
            if expected_tipo == "credito":
                resp = dte.enviar_nota_credito(self.manager.db, nota_id)
            else:
                resp = dte.enviar_nota_debito(self.manager.db, nota_id)
            try:
                self.load_invoices()
            except Exception:
                pass
            return resp

        json_path = factura.get("json") if factura else None
        if json_path and os.path.exists(json_path):
            if nota_error:
                logger.warning(
                    'No se pudo localizar la nota en la base de datos, se reenviará "%s" como DTE huérfano: %s',
                    expected_tipo,
                    nota_error,
                )

            resp = dte.transmitir_dte_orphan(self.manager.db, json_path)
            try:
                self.load_invoices()
            except Exception:
                pass
            return resp

        if nota_error:
            raise nota_error
        raise ValueError("No se encontró la nota asociada al documento seleccionado")

    def _buscar_nota_id(self, factura: dict, expected_tipo: str) -> int | None:
        json_path = factura.get("json") if factura else None
        if not json_path or not os.path.exists(json_path):
            raise ValueError("El archivo JSON de la nota no está disponible")
        try:
            with open(json_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as exc:
            raise ValueError(f"No se pudo leer el JSON de la nota: {exc}") from exc
        ident = data.get("identificacion") or data.get("identificador") or {}
        numero_control = str(ident.get("numeroControl") or "").strip()
        codigo_generacion = str(ident.get("codigoGeneracion") or "").strip().upper()
        if not numero_control and not codigo_generacion:
            raise ValueError("El JSON de la nota no contiene identificadores válidos")
        db = self.manager.db
        try:
            db.ensure_column("dte_envios", "numero_control", "TEXT")
            db.ensure_column("dte_envios", "codigo_generacion", "TEXT")
        except Exception:
            pass
        clauses = []
        params: list[str] = []
        if numero_control:
            clauses.append("UPPER(e.numero_control)=?")
            params.append(numero_control.upper())
        if codigo_generacion:
            clauses.append("e.codigo_generacion=?")
            params.append(codigo_generacion)
        if not clauses:
            return None
        query = (
            "SELECT n.id, n.tipo FROM notas AS n "
            "JOIN dte_envios AS e ON n.id = e.venta_id "
            f"WHERE {' OR '.join(clauses)} ORDER BY e.id DESC"
        )
        rows = db.cursor.execute(query, params).fetchall()
        expected = expected_tipo.lower()
        for row in rows:
            nota_tipo = str(row["tipo"]).strip().lower()
            if nota_tipo == expected:
                return row["id"]
        return None

    def _resolve_pdf_path(self, entry: dict | None) -> str | None:
        if not entry:
            return None

        pdf_path = None
        rtype = entry.get("row_type")
        if rtype == "venta":
            venta_id = entry.get("venta_id")
            pdf_path = self.manager.db.get_factura_pdf(venta_id)
            if not pdf_path or not os.path.exists(pdf_path):
                pdf_path = self._generate_invoice_pdf(venta_id)
        elif rtype == "ticket":
            venta_id = entry.get("venta_id")
            pdf_path = self.manager.db.get_ticket_pdf(venta_id)
            if not pdf_path or not os.path.exists(pdf_path):
                pdf_path = self._generate_ticket_pdf(venta_id)
        else:
            pdf_path = entry.get("pdf")

        if pdf_path and os.path.exists(pdf_path):
            return pdf_path

        fallback_pdf = self._build_invoice_pdf_from_json(entry, base_pdf_path=pdf_path)
        if fallback_pdf and os.path.exists(fallback_pdf):
            return fallback_pdf
        return None

    def _resolve_ticket_pdf(
        self,
        entry: dict | None,
        base_pdf_path: str | None = None,
    ) -> str | None:
        if not entry:
            return None

        stored_entry_ticket = entry.get("ticket_pdf") or entry.get("ticket_path")
        if stored_entry_ticket and os.path.exists(stored_entry_ticket):
            return stored_entry_ticket

        derived_path = None
        if base_pdf_path:
            derived_path = self._derive_ticket_path(base_pdf_path)
            if derived_path and os.path.exists(derived_path):
                return derived_path

        if not derived_path and entry:
            entry_pdf = entry.get("pdf")
            if entry_pdf:
                fallback_path = self._derive_ticket_path(entry_pdf)
                if fallback_path and os.path.exists(fallback_path):
                    return fallback_path

        venta_id = entry.get("venta_id")
        if venta_id:
            try:
                stored_path = self.manager.db.get_ticket_pdf(venta_id)
            except Exception:
                stored_path = None
            if stored_path:
                canonical = os.fspath(stored_path)
                if os.path.exists(canonical):
                    return canonical

        return self._build_ticket_format_pdf(entry, base_pdf_path)

    def open_pdf(self):
        entry = self._selected_entry()
        if not entry:
            QMessageBox.warning(self, "Abrir PDF", "No se ha seleccionado ninguna factura.")
            return

        pdf_path = self._resolve_pdf_path(entry)

        if pdf_path:
            logical_path = os.path.abspath(pdf_path)
            visible_path = resolve_user_visible_path(logical_path)
            path_to_open = visible_path or logical_path
            logger.info(
                "Intentando abrir PDF desde FacturacionTab.open_pdf: %s",
                logical_path,
            )
            if not open_pdf_file(path_to_open):
                QMessageBox.warning(
                    self,
                    "Abrir PDF",
                    (
                        "No se pudo abrir el archivo PDF automáticamente.\n"
                        "Puedes abrirlo manualmente desde:\n"
                        f"{path_to_open}"
                    ),
                )
        else:
            QMessageBox.warning(self, "Abrir PDF", "No se encontró el archivo PDF.")

    def print_invoice(self):
        entry = self._selected_entry()
        if not entry:
            QMessageBox.warning(self, "Imprimir", "No se ha seleccionado ninguna factura.")
            return

        venta_id = entry.get("venta_id")
        tipo_entry = str(entry.get("tipo") or "").strip().lower()
        is_note = tipo_entry.startswith("nota")
        base_pdf_path = self._resolve_pdf_path(entry)

        supports_format_choice = self._supports_ticket_format(entry, base_pdf_path)

        preferred_format = None
        if supports_format_choice:

            format_dialog = QMessageBox(self)
            format_dialog.setIcon(QMessageBox.Question)
            format_dialog.setWindowTitle("Formato de impresión")
            format_dialog.setText(
                "¿Desea imprimir el documento en papel tamaño carta o formato ticket?"
            )
            carta_button = format_dialog.addButton("Carta", QMessageBox.AcceptRole)
            ticket_button = format_dialog.addButton("Ticket", QMessageBox.AcceptRole)
            cancel_button = format_dialog.addButton(QMessageBox.Cancel)
            last_choice = getattr(self, "_last_print_format", None)
            if last_choice == "ticket":
                format_dialog.setDefaultButton(ticket_button)
            else:
                format_dialog.setDefaultButton(carta_button)
            format_dialog.exec_()
            clicked_button = format_dialog.clickedButton()
            if clicked_button == cancel_button or clicked_button is None:
                return
            if clicked_button == ticket_button:
                preferred_format = "ticket"
            else:
                preferred_format = "carta"
            self._last_print_format = preferred_format

            carta_pdf_path = None
            if preferred_format in ("carta", "ticket"):
                if venta_id and not is_note:
                    try:
                        carta_pdf_path = self.manager.db.get_factura_pdf(venta_id)
                    except Exception:
                        carta_pdf_path = None
                    if not carta_pdf_path or not os.path.exists(carta_pdf_path):
                        carta_pdf_path = self._generate_invoice_pdf(venta_id)
                if not venta_id:
                    if base_pdf_path and os.path.exists(base_pdf_path):
                        carta_pdf_path = base_pdf_path
                if (not carta_pdf_path or not os.path.exists(carta_pdf_path)) and preferred_format in (
                    "carta",
                    "ticket",
                ):
                    carta_pdf_path = self._build_invoice_pdf_from_json(
                        entry,
                        base_pdf_path=base_pdf_path,
                    )

            if preferred_format == "ticket":
                pdf_path = self._resolve_ticket_pdf(entry, carta_pdf_path)
            elif preferred_format == "carta":
                if carta_pdf_path and os.path.exists(carta_pdf_path):
                    pdf_path = carta_pdf_path
                else:
                    QMessageBox.warning(
                        self,
                        "Imprimir",
                        "No se pudo generar la factura en carta.",
                    )
                    return
            else:
                return

        else:
            pdf_path = base_pdf_path

        if not pdf_path or not os.path.exists(pdf_path):
            QMessageBox.warning(self, "Imprimir", "No se encontró el archivo PDF.")
            return

        preview_dialog = PdfPreviewDialog(pdf_path, self)
        if (
            preview_dialog.exec_() != QDialog.Accepted
            or preview_dialog.has_error()
        ):
            QMessageBox.warning(
                self,
                "Imprimir",
                "No se pudo generar la vista previa del documento.",
            )
            return

        logical_path = os.path.abspath(pdf_path)
        visible_path = resolve_user_visible_path(logical_path)
        path_to_open = visible_path or logical_path
        logger.info(
            "Intentando abrir PDF para impresión desde FacturacionTab.print_invoice: %s",
            logical_path,
        )
        if not open_pdf_file(path_to_open):
            QMessageBox.warning(
                self,
                "Abrir PDF",
                (
                    "No se pudo abrir el archivo PDF automáticamente.\n"
                    "Puedes abrirlo manualmente desde:\n"
                    f"{path_to_open}"
                ),
            )

    def _safe_remove(self, path: str | None) -> None:
        if not path:
            return
        try:
            os.remove(path)
        except OSError:
            pass

    def _is_ticket_eligible(self, entry: dict | None) -> bool:
        if not entry:
            return False

        json_path = entry.get("json")
        if json_path and os.path.exists(json_path):
            try:
                with open(json_path, "r", encoding="utf-8") as fh:
                    payload = json.load(fh)
                tipo_dte = str(
                    payload.get("identificacion", {}).get("tipoDte", "")
                ).zfill(2)
                if tipo_dte in TICKET_ELIGIBLE_TIPOS:
                    return True
            except Exception:
                pass

        tipo_codigo = entry.get("tipo_codigo")
        if tipo_codigo is not None:
            try:
                tipo_codigo_str = str(tipo_codigo).zfill(2)
            except Exception:
                tipo_codigo_str = str(tipo_codigo)
            if tipo_codigo_str in TICKET_ELIGIBLE_TIPOS:
                return True

        tipo_desc = str(entry.get("tipo") or "").strip().lower()
        if not tipo_desc:
            return False

        tipo_from_desc = TIPO_DTE_CODE_BY_DESC.get(tipo_desc)
        if tipo_from_desc and tipo_from_desc in TICKET_ELIGIBLE_TIPOS:
            return True

        return False

    def _supports_ticket_format(
        self, entry: dict | None, base_pdf_path: str | None
    ) -> bool:
        """Return True if the entry can be printed using the ticket format."""

        if not entry or not self._is_ticket_eligible(entry):
            return False

        venta_id = entry.get("venta_id")
        if venta_id:
            return True

        ticket_pdf = entry.get("ticket_pdf")
        if isinstance(ticket_pdf, str) and os.path.exists(ticket_pdf):
            return True

        if base_pdf_path:
            derived = self._derive_ticket_path(base_pdf_path)
            if derived and os.path.exists(derived):
                return True

            candidate_json = os.path.splitext(base_pdf_path)[0] + ".json"
            if os.path.exists(candidate_json):
                return True

        json_path = entry.get("json")
        if isinstance(json_path, str) and os.path.exists(json_path):
            return True

        return False

    def _build_invoice_pdf_from_json(
        self,
        entry: dict,
        base_pdf_path: str | None = None,
    ) -> str | None:
        if not entry:
            return None

        json_path = entry.get("json")
        if not json_path and base_pdf_path:
            candidate = os.path.splitext(base_pdf_path)[0] + ".json"
            if os.path.exists(candidate):
                json_path = candidate

        if not json_path or not os.path.exists(json_path):
            QMessageBox.warning(
                self,
                "Imprimir",
                "No se encontró la información de la factura en formato JSON.",
            )
            return None

        try:
            with open(json_path, "r", encoding="utf-8") as fh:
                payload_data = json.load(fh)
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Imprimir",
                f"No se pudo leer la información de la factura: {exc}",
            )
            return None

        if isinstance(payload_data, dict) and "dteJson" in payload_data:
            dte_payload = payload_data.get("dteJson") or {}
        else:
            dte_payload = payload_data if isinstance(payload_data, dict) else {}

        if not isinstance(dte_payload, dict) or not dte_payload:
            QMessageBox.warning(
                self,
                "Imprimir",
                "El documento JSON no contiene datos válidos para la factura.",
            )
            return None

        ident = dte_payload.get("identificacion") or {}
        resumen = dte_payload.get("resumen") or {}
        receptor = dte_payload.get("receptor") or {}
        cuerpo = dte_payload.get("cuerpoDocumento") or []

        numero_control = ident.get("numeroControl")
        codigo_generacion = ident.get("codigoGeneracion")
        if not numero_control or not codigo_generacion:
            QMessageBox.warning(
                self,
                "Imprimir",
                "El JSON no contiene identificadores necesarios para generar la factura.",
            )
            return None

        tipo_dte = str(ident.get("tipoDte") or "").strip().zfill(2)
        doc_label = "Crédito Fiscal" if tipo_dte == "03" else "Consumidor Final"

        sello = (
            payload_data.get("selloRecibido")
            or payload_data.get("sello")
            or payload_data.get("acuseRecibo")
        )
        if not sello:
            respuesta = payload_data.get("respuesta")
            if isinstance(respuesta, dict):
                sello = respuesta.get("selloRecibido") or respuesta.get("sello")
        if not sello and isinstance(dte_payload, dict):
            sello = (
                dte_payload.get("selloRecibido")
                or dte_payload.get("sello")
                or dte_payload.get("acuseRecibo")
            )

        def _to_float(value: Any) -> float | None:
            if isinstance(value, (int, float)):
                return float(value)
            if value in (None, ""):
                return None
            try:
                return float(Decimal(str(value)))
            except (InvalidOperation, ValueError, TypeError):
                return None

        venta_data: dict[str, Any] = {}
        fecha_emi = ident.get("fecEmi") or ident.get("fechaEmi")
        if isinstance(fecha_emi, str) and fecha_emi.strip():
            venta_data["fecha"] = fecha_emi.strip()
        venta_data["numero_control"] = numero_control
        venta_data["codigo_generacion"] = codigo_generacion
        if sello:
            venta_data["sello_recepcion"] = sello

        ambiente = ident.get("ambiente") or "00"
        tipo_modelo = _to_float(dte_payload.get("tipoModelo"))
        tipo_operacion = _to_float(dte_payload.get("tipoOperacion"))
        try:
            tipo_modelo_int = int(tipo_modelo) if tipo_modelo is not None else 1
        except (ValueError, TypeError):
            tipo_modelo_int = 1
        try:
            tipo_operacion_int = int(tipo_operacion) if tipo_operacion is not None else 1
        except (ValueError, TypeError):
            tipo_operacion_int = 1

        def _resumen_value(*keys):
            for key in keys:
                value = resumen.get(key)
                if value not in (None, ""):
                    return value
            return None

        def _update(target_keys: tuple[str, ...], *source_keys: str) -> None:
            value = _resumen_value(*source_keys)
            normalized = _to_float(value)
            if normalized is None:
                return
            for key in target_keys:
                venta_data[key] = normalized

        _update(("sumas", "subTotalVentas"), "sumas", "subTotalVentas")
        _update(("descuentos", "totalDescu"), "descuentos", "totalDescu")
        _update(("subtotal", "subTotal"), "subTotal", "subtotal", "subTotalVentas")
        _update(("ventas_exentas",), "totalExenta", "ventasExentas")
        _update(("ventas_no_sujetas",), "totalNoSuj", "ventasNoSujetas")
        _update(("ventas_gravadas",), "totalGravada", "ventasGravadas", "ventaGravada")

        iva_val = _resumen_value("totalIva", "iva", "ivaPerci1")
        iva_norm = _to_float(iva_val)
        if iva_norm is not None:
            venta_data["iva"] = iva_norm
            venta_data["totalIva"] = iva_norm

        total_val = _resumen_value("totalPagar", "total", "montoTotalOperacion")
        total_norm = _to_float(total_val)
        if total_norm is not None:
            venta_data["total"] = total_norm
            try:
                venta_data.setdefault("total_letras", monto_a_texto_sv(total_norm))
            except Exception:
                venta_data.setdefault("total_letras", "")

        detalles: list[dict[str, Any]] = []

        def _first(value_map: Mapping[str, Any], *keys: str) -> Any:
            for key in keys:
                if key in value_map:
                    candidate = value_map.get(key)
                    if candidate not in (None, ""):
                        return candidate
            return None

        for item in cuerpo:
            if not isinstance(item, Mapping):
                continue
            detalle: dict[str, Any] = {}
            descripcion = _first(
                item,
                "descripcion",
                "descripcionProducto",
                "producto",
                "nombre",
            )
            detalle["descripcion"] = str(descripcion or "")

            cantidad = _to_float(
                _first(item, "cantidad", "cantidadUniMedida", "uniCantidad")
            )
            if cantidad is not None:
                detalle["cantidad"] = cantidad

            precio = _to_float(
                _first(item, "precioUni", "precioUnitario", "precioUnit", "precio")
            )
            if precio is not None:
                detalle["precio_unitario"] = precio

            descuento = _to_float(_first(item, "montoDescu", "descuento"))
            if descuento not in (None, 0):
                detalle["descuento"] = descuento

            gravada = _to_float(_first(item, "ventaGravada", "ventaGrav"))
            exenta = _to_float(_first(item, "ventaExenta", "ventaExentaLiq"))
            no_suj = _to_float(_first(item, "ventaNoSuj", "ventaNoSujeta"))
            iva_item_val = _to_float(_first(item, "ivaItem", "iva", "montoIva"))

            if gravada is not None:
                detalle["ventas_gravadas"] = gravada
            if exenta is not None:
                detalle["ventas_exentas"] = exenta
            if no_suj is not None:
                detalle["ventas_no_sujetas"] = no_suj
            if iva_item_val is not None:
                detalle["iva"] = iva_item_val

            detalles.append(detalle)

        if not detalles:
            detalles.append({"descripcion": ""})

        cliente_payload = {}
        for dest, candidates in (
            ("nombre", ("nombre", "razonSocial", "denominacionSocial")),
            ("nit", ("nit",)),
            ("dui", ("dui", "numDocumento")),
            ("nrc", ("nrc",)),
            ("direccion", ("direccion",)),
            ("correo", ("correo", "email")),
        ):
            value = _first(receptor, *candidates)
            if value not in (None, ""):
                cliente_payload[dest] = value

        try:
            datos_negocio = dte._load_datos_negocio() or {}
        except Exception:
            datos_negocio = {}

        if base_pdf_path:
            output_path = base_pdf_path
        else:
            entry_pdf = entry.get("pdf")
            if entry_pdf:
                output_path = entry_pdf
            else:
                output_path = os.path.splitext(json_path)[0] + ".pdf"

        if not output_path:
            fallback_dir = CREDITO_DIR if doc_label == "Crédito Fiscal" else CF_DIR
            try:
                os.makedirs(fallback_dir, exist_ok=True)
            except OSError:
                pass
            base_name = numero_control or codigo_generacion or f"invoice_{uuid.uuid4().hex}"
            sanitized = re.sub(r"[^A-Za-z0-9_-]+", "_", str(base_name))
            output_path = os.path.join(fallback_dir, f"{sanitized}.pdf")

        try:
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        except OSError:
            pass

        fecha_generacion = (
            payload_data.get("fechaGeneracion")
            or payload_data.get("fecha_generacion")
            or datetime.now().strftime("%d/%m/%Y, %I:%M %p")
        )

        def _render_invoice(tmp_path: Path) -> None:
            try:
                generar_factura_electronica_pdf(
                    venta_data,
                    detalles,
                    cliente_payload,
                    {},
                    doc_label,
                    archivo=str(tmp_path),
                    datos_negocio=datos_negocio,
                    codigo_generacion=str(codigo_generacion or ""),
                    numero_control=str(numero_control or ""),
                    sello_recepcion=str(sello or ""),
                    tipo_modelo=tipo_modelo_int,
                    tipo_operacion=tipo_operacion_int,
                    fecha_generacion=str(fecha_generacion),
                    ambiente=str(ambiente or "00"),
                )
            except Exception as exc:  # pragma: no cover - defensive
                raise RuntimeError(str(exc)) from exc

        try:
            write_pdf_atomically(output_path, _render_invoice)
        except RuntimeError as exc:
            QMessageBox.critical(
                self,
                "Imprimir",
                f"No se pudo generar la factura en PDF: {exc}",
            )
            return None
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Imprimir",
                f"No se pudo escribir la factura: {exc}",
            )
            return None

        return output_path

    def _derive_ticket_path(self, base_pdf_path: str | None) -> str | None:
        if not base_pdf_path:
            return None

        try:
            output_dir = os.path.dirname(base_pdf_path)
            base_name = os.path.splitext(os.path.basename(base_pdf_path))[0]
        except Exception:
            return None

        if not base_name:
            return None

        lower_name = base_name.lower()
        for suffix in (
            "_consumidorfinal",
            "_creditofiscal",
            "_ticket",
            "_notacredito",
            "_notadebito",
            "_notaremision",
            "-consumidorfinal",
            "-creditofiscal",
            "-ticket",
            "-notacredito",
            "-notadebito",
            "-notaremision",
        ):
            if lower_name.endswith(suffix):
                base_name = base_name[: -len(suffix)] + "_Ticket"
                break
        else:
            base_name = f"{base_name}_Ticket"

        return os.path.join(output_dir, f"{base_name}.pdf")

    def _build_ticket_format_pdf(
        self,
        entry: dict,
        base_pdf_path: str | None = None,
    ) -> str | None:
        if not entry:
            return None

        venta_id = entry.get("venta_id")
        json_path = entry.get("json")
        if not json_path and base_pdf_path:
            candidate = os.path.splitext(base_pdf_path)[0] + ".json"
            if os.path.exists(candidate):
                json_path = candidate

        venta = None
        extra_data = {}
        if venta_id:
            venta = next(
                (v for v in self.manager.db.get_ventas() if v["id"] == venta_id),
                None,
            )
            if venta:
                raw_extra = venta.get("extra")
                if raw_extra:
                    try:
                        extra_data = json.loads(raw_extra)
                    except Exception:
                        extra_data = {}
                if not json_path:
                    candidate = extra_data.get("dteJsonPath")
                    if candidate and os.path.exists(candidate):
                        json_path = candidate

        detalles_venta = []
        if venta_id:
            try:
                detalles_venta = self.manager.db.get_detalles_venta(venta_id)
            except Exception:
                detalles_venta = []

        if not json_path or not os.path.exists(json_path):
            QMessageBox.warning(
                self,
                "Imprimir",
                "No se encontró la información del documento para el formato ticket.",
            )
            return None

        try:
            with open(json_path, "r", encoding="utf-8") as fh:
                payload_data = json.load(fh)
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Imprimir",
                f"No se pudo leer la información del documento: {exc}",
            )
            return None

        if isinstance(payload_data, dict) and "dteJson" in payload_data:
            dte_payload = payload_data.get("dteJson") or {}
        else:
            dte_payload = payload_data if isinstance(payload_data, dict) else {}

        if not isinstance(dte_payload, dict) or not dte_payload:
            QMessageBox.warning(
                self,
                "Imprimir",
                "El documento JSON no contiene datos válidos para el formato ticket.",
            )
            return None

        sello = None
        firma = None
        if isinstance(payload_data, dict):
            sello = (
                payload_data.get("selloRecibido")
                or payload_data.get("sello")
                or payload_data.get("acuseRecibo")
            )
            if not sello:
                respuesta = payload_data.get("respuesta")
                if isinstance(respuesta, dict):
                    sello = respuesta.get("selloRecibido") or respuesta.get("sello")
            firma = (
                payload_data.get("firmaElectronica")
                or payload_data.get("firma")
                or payload_data.get("acuseFirma")
            )
            if not firma:
                respuesta = payload_data.get("respuesta")
                if isinstance(respuesta, dict):
                    firma = respuesta.get("firmaElectronica") or respuesta.get("firma")
        if extra_data:
            if not sello:
                sello = extra_data.get("selloRecibido") or extra_data.get("sello")
            if not firma:
                firma = extra_data.get("firmaElectronica") or extra_data.get("firma")
        if isinstance(dte_payload, dict):
            if not sello:
                sello = dte_payload.get("selloRecibido") or dte_payload.get("acuseRecibo")
            if not firma:
                firma = dte_payload.get("firmaElectronica") or dte_payload.get("firma")

        try:
            datos_negocio = dte._load_datos_negocio() or {}
        except Exception:
            datos_negocio = {}

        payload_raw = dte_to_legacy_ticket_payload(
            dte_payload,
            venta or {},
            detalles_venta,
            datos_negocio,
        )
        if isinstance(payload_raw, Mapping):
            payload: dict[str, Any] = dict(payload_raw)
        else:
            payload = {}

        dte_payload_data = payload.get("dte_data") if payload else None
        if isinstance(dte_payload_data, Mapping):
            dte_data = dict(dte_payload_data)
        else:
            dte_data = {}

        if sello:
            dte_data.setdefault("selloRecibido", sello)
        if firma:
            dte_data.setdefault("firmaElectronica", firma)

        if payload is not None:
            payload["dte_data"] = dte_data

        venta_payload = payload.get("venta") if payload else None
        if not venta_payload:
            venta_payload = venta or {}
        elif isinstance(venta_payload, Mapping) and not isinstance(venta_payload, dict):
            venta_payload = dict(venta_payload)

        detalles_payload = payload.get("detalles") if payload else None
        if not detalles_payload:
            detalles_payload = detalles_venta or []

        datos_negocio_payload = payload.get("datos_negocio") if payload else None
        if not isinstance(datos_negocio_payload, Mapping):
            datos_negocio_payload = datos_negocio or {}
        else:
            datos_negocio_payload = dict(datos_negocio_payload)

        if isinstance(detalles_payload, list):
            detalles_for_render = detalles_payload
        elif isinstance(detalles_payload, tuple):
            detalles_for_render = list(detalles_payload)
        else:
            detalles_for_render = detalles_payload or []

        venta_id = entry.get("venta_id")
        output_path = None
        output_dir = None
        ticket_base = None
        if base_pdf_path:
            output_path = self._derive_ticket_path(base_pdf_path)
            if output_path:
                output_dir = os.path.dirname(output_path)
                ticket_base = os.path.splitext(os.path.basename(output_path))[0]

        if not output_path and entry:
            entry_pdf = entry.get("pdf")
            if entry_pdf:
                candidate = self._derive_ticket_path(entry_pdf)
                if candidate:
                    output_path = candidate
                    output_dir = os.path.dirname(candidate)
                    ticket_base = os.path.splitext(os.path.basename(candidate))[0]
        if not output_dir:
            tipo_entry = str(entry.get("tipo") or "").strip().lower()
            if tipo_entry == "consumidor final":
                output_dir = CF_DIR
            elif tipo_entry in {"crédito fiscal", "credito fiscal"}:
                output_dir = CREDITO_DIR
            elif tipo_entry in {"nota de crédito", "nota de credito"}:
                output_dir = NOTAS_CREDITO_DIR
            elif tipo_entry in {"nota de débito", "nota de debito"}:
                output_dir = NOTAS_DEBITO_DIR
            elif tipo_entry in {"nota de remisión", "nota de remision"}:
                output_dir = NOTAS_REMISION_DIR
        if not output_dir:
            output_dir = TICKETS_DIR

        try:
            os.makedirs(output_dir, exist_ok=True)
        except OSError:
            pass

        if not output_path:
            ident = {}
            if isinstance(dte_payload, dict):
                ident = dte_payload.get("identificacion") or {}

            def _sanitize_ticket_name(value: str | None) -> str | None:
                if not value:
                    return None
                cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_")
                if not cleaned:
                    return None
                if cleaned.lower().endswith("_ticket"):
                    cleaned = cleaned[: -7] + "_Ticket"
                else:
                    cleaned = f"{cleaned}_Ticket"
                return cleaned

            ticket_base = None
            numero_control = ident.get("numeroControl")
            if isinstance(numero_control, str) and numero_control.strip():
                ticket_base = _sanitize_ticket_name(numero_control.strip())
            if not ticket_base:
                codigo_generacion = ident.get("codigoGeneracion")
                if isinstance(codigo_generacion, str) and codigo_generacion.strip():
                    ticket_base = _sanitize_ticket_name(codigo_generacion.strip())
            if not ticket_base:
                ticket_base = f"ticket_print_{uuid.uuid4().hex}"

            output_path = os.path.join(output_dir, f"{ticket_base}.pdf")

        def _render_ticket(tmp_path):
            try:
                generar_ticket_personalizado(
                    venta_payload,
                    detalles_for_render,
                    archivo=str(tmp_path),
                    datos_negocio=datos_negocio_payload,
                    dte_data=dte_data,
                )
            except Exception as exc:  # pragma: no cover - defensive
                raise RuntimeError(str(exc)) from exc

        try:
            write_pdf_atomically(output_path, _render_ticket)
        except RuntimeError as exc:
            QMessageBox.critical(
                self,
                "Imprimir",
                f"No se pudo generar el ticket en PDF: {exc}",
            )
            return None
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Imprimir",
                f"No se pudo escribir el ticket: {exc}",
            )
            return None

        return output_path

    def mostrar_detalle_factura(self, item=None):
        entry = self._selected_entry()
        factura = self._selected_factura()
        if not factura:
            QMessageBox.warning(self, "Detalle", "Seleccione una factura válida")
            return
        json_path = factura.get("json")
        if not json_path or not os.path.exists(json_path):
            QMessageBox.warning(self, "Detalle", "No se encontró el archivo JSON")
            return
        try:
            with open(json_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            data = self._normalize_factura_payload(data)
        except Exception:
            QMessageBox.warning(self, "Detalle", "Error al leer el archivo JSON")
            return

        menu = QMenu(self)
        ver_act = QAction("Ver detalle", self)
        menu.addAction(ver_act)
        anular_act = QAction("Anular", self)
        menu.addAction(anular_act)
        chosen = menu.exec_(QCursor.pos())
        if chosen == anular_act:
            self._anular_dte(factura, data)
            return
        if chosen != ver_act:
            return

        items = data.get("cuerpoDocumento") or []
        resumen = data.get("resumen") or {}
        ident = data.get("identificacion") or {}
        current_envio = None
        if isinstance(entry, Mapping):
            current_envio = entry.get("envio")
        envio_options = self._get_available_envio_states(current_envio)

        def _apply_envio_change(selected_state: str) -> str:
            return self._update_invoice_envio_state(entry, factura, data, selected_state)

        dlg = InvoiceDetailDialog(
            items,
            resumen,
            venta_id=factura.get("venta_id"),
            numero_control=ident.get("numeroControl"),
            factura=data,
            json_path=json_path,
            pdf_path=factura.get("pdf"),
            envio_state=current_envio,
            envio_options=envio_options,
            on_envio_change=_apply_envio_change if envio_options else None,
            parent=self,
        )
        dlg.exec_()
        if getattr(dlg, "anulacion_result", None) or getattr(dlg, "envio_updated", False):
            self.refresh_and_reload()

    def _anular_dte(self, factura, data):
        data = self._normalize_factura_payload(data)
        venta_id = factura.get("venta_id")
        venta = self.manager.db.get_venta_by_id(venta_id) if venta_id else None
        extra = {}
        if venta:
            extra_raw = venta.get("extra")
            if extra_raw:
                try:
                    extra = json.loads(extra_raw)
                except Exception:
                    extra = {}
        sello = data.get("selloRecibido") or extra.get("selloRecibido")
        if not sello and venta_id:
            row = self.manager.db.cursor.execute(
                "SELECT sello, respuesta FROM dte_envios WHERE venta_id=? AND TRIM(sello)<>'' ORDER BY id DESC LIMIT 1",
                (venta_id,),
            ).fetchone()
            if not row:
                row = self.manager.db.cursor.execute(
                    "SELECT sello, respuesta FROM dte_envios WHERE venta_id=? ORDER BY id DESC LIMIT 1",
                    (venta_id,),
                ).fetchone()
            if row:
                sello = row["sello"]
                if not sello:
                    resp = row["respuesta"]
                    if resp:
                        try:
                            resp_json = json.loads(resp)
                            sello = resp_json.get("selloRecibido") or resp_json.get("sello")
                        except Exception:
                            pass
        ident = data.get("identificacion", {})
        if not (ident.get("codigoGeneracion") and ident.get("numeroControl") and sello):
            QMessageBox.critical(
                self,
                "Anular DTE",
                "No se puede anular: falta acuse de recepción (selloRecibido)",
            )
            return
        data["selloRecibido"] = sello

        negocio = dte._load_datos_negocio()
        responsable_nit = negocio.get("nit", "")
        responsable_dui = negocio.get("dui", "")
        responsable = {
            "nombre": negocio.get("nombre", ""),
            "nit": responsable_nit,
            "dui": responsable_dui,
            "nrc": negocio.get("nrc", ""),
        }
        responsable_nit_digits = solo_digitos(responsable_nit)
        responsable_dui_digits = solo_digitos(responsable_dui)
        if responsable_dui:
            responsable["tipDoc"] = "13"
            responsable["numDoc"] = (
                responsable_dui if "-" in str(responsable_dui) else responsable_dui_digits
            )
        elif responsable_nit_digits:
            responsable["tipDoc"] = "36"
            responsable["numDoc"] = responsable_nit_digits
        else:
            responsable["tipDoc"] = "36"
            responsable["numDoc"] = solo_digitos(negocio.get("nrc", "")) or ""

        receptor = data.get("receptor") or {}
        solicitante_nit = receptor.get("nit", "")
        solicitante_dui = receptor.get("dui", "")
        solicitante_numdoc = receptor.get("numDocumento", "")
        solicitante = {
            "nombre": receptor.get("nombre", ""),
            "nit": solicitante_nit,
            "dui": solicitante_dui,
            "numDocumento": solicitante_numdoc,
            "nrc": receptor.get("nrc", ""),
        }
        tipo_doc = receptor.get("tipoDocumento")
        if not tipo_doc:
            if solicitante_dui or (
                solicitante_numdoc and len(solo_digitos(solicitante_numdoc)) == 9
            ):
                tipo_doc = "13"
            elif solicitante_nit:
                tipo_doc = "36"
            else:
                tipo_doc = "13"
        solicitante["tipDoc"] = tipo_doc
        solicitante["numDoc"] = (
            solicitante_dui
            or (solo_digitos(solicitante_nit) if solicitante_nit else "")
            or solicitante_numdoc
            or solo_digitos(receptor.get("nrc", ""))
        )
        dlg = AnularFacturaDialog(
            self,
            responsable=responsable,
            solicitante=solicitante,
            db=self.manager.db,
            factura=data,
        )
        if dlg.exec_() != QDialog.Accepted:
            return
        ui_data = dlg.get_data()
        try:
            cfg = dte._load_dte_api_config()
            amb = "01" if str(cfg.get("ambiente", "")).lower().startswith("produc") else "00"
            anul_json = anulacion.build_invalidacion_json(
                data, ui_data, ambiente=amb, db=self.manager.db
            )
            resp = anulacion.enviar_invalidacion(self.manager.db, anul_json)
        except ValueError as exc:
            QMessageBox.warning(self, "Anular DTE", str(exc))
            return
        estado = resp.get("estado", "")
        if estado.lower() != "rechazado":
            if venta_id:
                self.manager.db.update_venta_estado(venta_id, "Anulada")
            QMessageBox.information(self, "Anular DTE", "Anulación enviada correctamente")
            self.refresh_and_reload()
        else:
            detalle = resp.get("detalle")
            detalle_text = ""

            if isinstance(detalle, (dict, list)):
                try:
                    detalle_text = json.dumps(detalle, ensure_ascii=False, indent=2)
                except (TypeError, ValueError):
                    detalle_text = str(detalle)
            elif detalle:
                detalle_text = str(detalle)
            else:
                errores = resp.get("errores")
                if isinstance(errores, (dict, list)):
                    try:
                        detalle_text = json.dumps(errores, ensure_ascii=False, indent=2)
                    except (TypeError, ValueError):
                        detalle_text = str(errores)
                elif errores:
                    detalle_text = str(errores)
                else:
                    detalle_text = ""

            if not detalle_text:
                detalle_text = "Rechazado (sin detalles legibles)"

            QMessageBox.warning(self, "Anular DTE", detalle_text)

    def _update_invoice_assets_after_mh(self, venta_id: int, response: dict | None) -> None:
        if not venta_id:
            return
        response = response or {}
        ident = response.get("identificacion") or response.get("identificador") or {}
        codigo = (ident.get("codigoGeneracion") or "").strip().upper()
        numero_control = (ident.get("numeroControl") or "").strip()
        ambiente = (ident.get("ambiente") or "").strip()
        sello = (
            response.get("sello")
            or response.get("selloRecibido")
            or response.get("selloRecepcion")
            or ""
        )
        sello = str(sello).strip()

        try:
            self.manager.db.update_venta_extra(
                venta_id,
                {
                    "codigoGeneracion": codigo or None,
                    "numeroControl": numero_control or None,
                    "ambiente": ambiente or None,
                    "selloRecibido": sello or None,
                },
            )
        except Exception:
            logger.exception(
                "No se pudo actualizar datos MH para la venta %s", venta_id
            )

        pdf_path = None
        try:
            pdf_path = self._generate_invoice_pdf(venta_id)
        except Exception:
            logger.exception("No se pudo regenerar la factura después del envío")
        if not pdf_path or not os.path.exists(pdf_path):
            return
        json_path = os.path.splitext(pdf_path)[0] + ".json"
        if not os.path.exists(json_path):
            return

        codigo_sync, sello_sync = self._ensure_invoice_json_metadata(
            json_path,
            codigo=codigo or None,
            sello=sello or None,
        )
        if codigo_sync:
            codigo = codigo_sync
        if sello_sync:
            sello = sello_sync

    def _show_email_loading(self, message: str = "Enviando correo…") -> None:
        if self._email_loading_dialog:
            self._email_loading_dialog.finish()
        self._email_loading_dialog = create_loading_dialog(self, message)

    def _hide_email_loading(self) -> None:
        if self._email_loading_dialog:
            self._email_loading_dialog.finish()
            self._email_loading_dialog = None

    def _send_invoice_email(
        self,
        venta_id,
        *,
        force_regenerate: bool = False,
        expected_codigo: str | None = None,
        expected_sello: str | None = None,
    ):
        venta = next((v for v in self.manager.db.get_ventas() if v["id"] == venta_id), None)
        if not venta:
            QMessageBox.warning(self, "Enviar por correo", "No se encontró la venta seleccionada.")
            return

        cliente_email = ""
        if venta.get("cliente_id"):
            cli = next((c for c in self.manager._clientes if c["id"] == venta["cliente_id"]), None)
            if cli:
                cliente_email = cli.get("email", "")
        if not cliente_email:
            QMessageBox.warning(self, "Enviar por correo", "El cliente no tiene correo registrado.")
            return

        pdf_path = None
        if force_regenerate:
            pdf_path = self._generate_invoice_pdf(venta_id)
        if not pdf_path:
            pdf_path = self.manager.db.get_factura_pdf(venta_id)
        if not pdf_path or not os.path.exists(pdf_path):
            pdf_path = self._generate_invoice_pdf(venta_id)
        if not pdf_path or not os.path.exists(pdf_path):
            QMessageBox.warning(self, "Enviar por correo", "No se pudo generar el PDF.")
            return
        json_path = os.path.splitext(pdf_path)[0] + ".json"
        if not os.path.exists(json_path):
            pdf_path = self._generate_invoice_pdf(venta_id)
            json_path = os.path.splitext(pdf_path)[0] + ".json"
            if not os.path.exists(json_path):
                QMessageBox.warning(self, "Enviar por correo", "No se encontró el JSON firmado.")
                return

        codigo_meta = (expected_codigo or "").strip().upper()
        sello_meta = (expected_sello or "").strip()
        extra_raw = venta.get("extra")
        extra = {}
        if isinstance(extra_raw, str) and extra_raw:
            try:
                extra = json.loads(extra_raw)
            except Exception:
                extra = {}
        elif isinstance(extra_raw, dict):
            extra = extra_raw
        if not codigo_meta:
            codigo_meta = str(extra.get("codigoGeneracion") or "").strip().upper()
        if not sello_meta:
            sello_meta = str(
                extra.get("selloRecibido")
                or extra.get("sello")
                or extra.get("selloRecepcion")
                or ""
            ).strip()

        if codigo_meta or sello_meta:
            codigo_meta, sello_meta = self._ensure_invoice_json_metadata(
                json_path,
                codigo=codigo_meta or None,
                sello=sello_meta or None,
            )

        expected_codigo_norm = (codigo_meta or "").strip().upper()
        expected_sello_norm = (sello_meta or "").strip()
        attempts = 0
        while True:
            try:
                with open(json_path, "r", encoding="utf-8") as fh:
                    payload = json.load(fh)
            except Exception:
                QMessageBox.warning(
                    self,
                    "Enviar por correo",
                    "No se pudo leer el JSON firmado para validar los datos.",
                )
                return

            codigo_json = self._extract_codigo_generacion_from_payload(payload)
            sello_json = (
                payload.get("selloRecibido")
                or payload.get("sello")
                or payload.get("selloRecepcion")
                or ""
            )
            sello_json = str(sello_json).strip()

            if expected_codigo_norm and codigo_json != expected_codigo_norm:
                if attempts == 0:
                    pdf_path = self._generate_invoice_pdf(venta_id)
                    if not pdf_path or not os.path.exists(pdf_path):
                        QMessageBox.warning(
                            self,
                            "Enviar por correo",
                            "No se pudo regenerar la factura con los datos actualizados.",
                        )
                        return
                    json_path = os.path.splitext(pdf_path)[0] + ".json"
                    if not os.path.exists(json_path):
                        QMessageBox.warning(
                            self,
                            "Enviar por correo",
                            "No se encontró el JSON firmado después de regenerar la factura.",
                        )
                        return
                    if expected_codigo_norm or expected_sello_norm:
                        new_code, new_sello = self._ensure_invoice_json_metadata(
                            json_path,
                            codigo=expected_codigo_norm or None,
                            sello=expected_sello_norm or None,
                        )
                        if new_code:
                            expected_codigo_norm = str(new_code).strip().upper()
                        if new_sello:
                            expected_sello_norm = str(new_sello).strip()
                    attempts += 1
                    continue

                QMessageBox.warning(
                    self,
                    "Enviar por correo",
                    "El JSON firmado no coincide con el código de generación aceptado por Hacienda.",
                )
                return

            if not codigo_json:
                QMessageBox.warning(
                    self,
                    "Enviar por correo",
                    "El documento JSON no contiene un código de generación válido.",
                )
                return

            if expected_sello_norm and sello_json.upper() != expected_sello_norm.upper():
                if attempts == 0:
                    pdf_path = self._generate_invoice_pdf(venta_id)
                    if not pdf_path or not os.path.exists(pdf_path):
                        QMessageBox.warning(
                            self,
                            "Enviar por correo",
                            "No se pudo regenerar la factura con el sello aceptado.",
                        )
                        return
                    json_path = os.path.splitext(pdf_path)[0] + ".json"
                    if not os.path.exists(json_path):
                        QMessageBox.warning(
                            self,
                            "Enviar por correo",
                            "No se encontró el JSON firmado después de regenerar la factura.",
                        )
                        return
                    if expected_codigo_norm or expected_sello_norm:
                        new_code, new_sello = self._ensure_invoice_json_metadata(
                            json_path,
                            codigo=expected_codigo_norm or None,
                            sello=expected_sello_norm or None,
                        )
                        if new_code:
                            expected_codigo_norm = str(new_code).strip().upper()
                        if new_sello:
                            expected_sello_norm = str(new_sello).strip()
                    attempts += 1
                    continue

                QMessageBox.warning(
                    self,
                    "Enviar por correo",
                    "El sello del documento no coincide con el recibido de Hacienda.",
                )
                return

            if not sello_json:
                QMessageBox.warning(
                    self,
                    "Enviar por correo",
                    "El documento no contiene sello de recepción de Hacienda.",
                )
                return

            break

        creds = {}
        if os.path.exists(DATOS_NEGOCIO_PATH):
            try:
                with open(DATOS_NEGOCIO_PATH, "r", encoding="utf-8") as f:
                    creds = json.load(f)
            except Exception:
                creds = {}
        server = creds.get("smtp_server")
        port = creds.get("smtp_port")
        user = creds.get("email_usuario")
        password = os.getenv("INVENTARIO_EMAIL_PASSWORD") or creds.get("email_contrasena")
        if not all([server, port, user, password]):
            QMessageBox.warning(self, "Enviar por correo", "Credenciales SMTP incompletas.")
            return

        subject = "Factura"
        body = (
            "Adjunto se envía la representación gráfica en PDF y el documento firmado en formato JSON"
        )

        self.btn_enviar.setEnabled(False)
        self.email_thread = EmailSender(
            server,
            port,
            user,
            password,
            cliente_email,
            subject,
            body,
            [pdf_path, json_path],
        )
        self.email_thread.finished.connect(self._on_email_sent)
        self._show_email_loading()
        self.email_thread.start()

    def _send_note_email(
        self,
        *,
        nota_tipo: str,
        venta_id: int | None,
        cliente_info: Mapping[str, Any] | None,
        pdf_path: str,
        json_path: str,
        codigo: str | None = None,
        sello: str | None = None,
    ) -> None:
        if not pdf_path or not os.path.exists(pdf_path):
            QMessageBox.warning(
                self,
                "Enviar por correo",
                "No se encontró el PDF generado para la nota.",
            )
            return
        if not json_path or not os.path.exists(json_path):
            QMessageBox.warning(
                self,
                "Enviar por correo",
                "No se encontró el JSON firmado de la nota.",
            )
            return

        if codigo or sello:
            self._ensure_invoice_json_metadata(json_path, codigo=codigo, sello=sello)

        cliente_email = ""
        if isinstance(cliente_info, Mapping):
            for key in ("correo", "email"):
                value = cliente_info.get(key)
                if value:
                    cliente_email = str(value).strip()
                    if cliente_email:
                        break

        venta_data = None
        if venta_id:
            try:
                ventas_getter = getattr(self.manager.db, "get_ventas", None)
                if callable(ventas_getter):
                    venta_data = next(
                        (v for v in ventas_getter() if v.get("id") == venta_id),
                        None,
                    )
            except Exception:
                venta_data = None
            if not venta_data:
                venta_getter = getattr(self.manager.db, "get_venta_by_id", None)
                if callable(venta_getter):
                    try:
                        venta_data = venta_getter(venta_id)
                    except Exception:
                        venta_data = None

        cliente_id = None
        if isinstance(venta_data, Mapping):
            cliente_id = venta_data.get("cliente_id")

        if (not cliente_email) and cliente_id:
            clientes_cache = getattr(self.manager, "_clientes", [])
            cliente_cache = next(
                (c for c in clientes_cache if c.get("id") == cliente_id),
                None,
            )
            if isinstance(cliente_cache, Mapping):
                for key in ("email", "correo"):
                    value = cliente_cache.get(key)
                    if value:
                        cliente_email = str(value).strip()
                        if cliente_email:
                            break

        if (not cliente_email) and cliente_id:
            get_cliente = getattr(self.manager.db, "get_cliente", None)
            if callable(get_cliente):
                try:
                    cliente_row = get_cliente(cliente_id)
                except Exception:
                    cliente_row = None
                if isinstance(cliente_row, Mapping):
                    for key in ("email", "correo"):
                        value = cliente_row.get(key)
                        if value:
                            cliente_email = str(value).strip()
                            if cliente_email:
                                break

        if not cliente_email:
            QMessageBox.warning(
                self,
                "Enviar por correo",
                "El cliente no tiene correo registrado.",
            )
            return

        creds = {}
        if os.path.exists(DATOS_NEGOCIO_PATH):
            try:
                with open(DATOS_NEGOCIO_PATH, "r", encoding="utf-8") as f:
                    creds = json.load(f)
            except Exception:
                creds = {}
        server = creds.get("smtp_server")
        port = creds.get("smtp_port")
        user = creds.get("email_usuario")
        password = os.getenv("INVENTARIO_EMAIL_PASSWORD") or creds.get("email_contrasena")
        if not all([server, port, user, password]):
            QMessageBox.warning(self, "Enviar por correo", "Credenciales SMTP incompletas.")
            return

        subject_map = {"credito": "Nota de crédito", "debito": "Nota de débito"}
        subject = subject_map.get(nota_tipo, "Documento electrónico")
        body = (
            "Adjunto se envía la representación gráfica en PDF y el documento firmado en formato JSON"
        )

        self.btn_enviar.setEnabled(False)
        self.email_thread = EmailSender(
            server,
            port,
            user,
            password,
            cliente_email,
            subject,
            body,
            [pdf_path, json_path],
        )
        self.email_thread.finished.connect(self._on_email_sent)
        self._show_email_loading()
        self.email_thread.start()

    def _ensure_invoice_json_metadata(
        self,
        json_path: str,
        *,
        codigo: str | None = None,
        sello: str | None = None,
    ) -> tuple[str | None, str | None]:
        codigo_val = (codigo or "").strip()
        sello_val = sello
        codigo_norm = codigo_val.upper() if codigo_val else ""

        sync_code, sync_sello = sync_client_json_with_canonical(
            json_path,
            codigo=codigo_norm or None,
            sello=sello_val,
            base_dir=DTES_DIR,
        )
        if sync_code:
            codigo_val = sync_code
            codigo_norm = sync_code.upper()
        if sync_sello:
            sello_val = sync_sello

        if not json_path or not os.path.exists(json_path):
            return (codigo_norm or None, sello_val)
        try:
            with open(json_path, "r", encoding="utf-8") as fh:
                payload = json.load(fh)
        except Exception:
            return (codigo_norm or None, sello_val)

        if not isinstance(payload, dict):
            return (codigo_norm or None, sello_val)

        dte_payload = payload.get("dteJson") if isinstance(payload, dict) else None
        if not isinstance(dte_payload, Mapping):
            dte_payload = payload
        if not isinstance(dte_payload, Mapping):
            return (codigo_norm or None, sello_val)

        dte_data = dict(dte_payload)
        ident = dict(dte_data.get("identificacion") or dte_data.get("identificador") or {})
        changed = False

        if codigo_val:
            codigo_norm = codigo_val.upper()
            current = (ident.get("codigoGeneracion") or "").strip().upper()
            if codigo_norm and codigo_norm != current:
                ident["codigoGeneracion"] = codigo_val
                changed = True

        if ident != dte_data.get("identificacion"):
            dte_data["identificacion"] = ident
            dte_data.pop("identificador", None)

        def _norm_sello(value):
            if value is None:
                return None
            try:
                text = str(value).strip()
            except Exception:
                return None
            if not text:
                return None
            if re.fullmatch(r"[0-9A-Fa-f]{40}", text):
                return text.upper()
            return text

        existing_sello = None
        if isinstance(payload, dict):
            existing_sello = _norm_sello(payload.get("selloRecibido"))
            if not existing_sello:
                respuesta = payload.get("respuesta")
                if isinstance(respuesta, dict):
                    existing_sello = _norm_sello(respuesta.get("selloRecibido"))

        sello_norm = _norm_sello(sello_val)
        if sello_norm and sello_norm != existing_sello:
            changed = True

        needs_format = not (isinstance(payload, dict) and "dteJson" in payload)
        firma_val = payload.get("firmaElectronica") if isinstance(payload, dict) else None
        sello_to_use = sello_norm or existing_sello

        if changed or needs_format or sello_to_use or firma_val:
            try:
                persist_client_json(
                    json_path,
                    dte_data,
                    firma=firma_val,
                    sello=sello_to_use,
                    existing_payload=payload,
                )
            except Exception:
                logger.exception(
                    "No se pudo actualizar metadatos de JSON en %s", json_path
                )

        return (codigo_norm or None, sello_norm or sello_val)

    @staticmethod
    def _extract_codigo_generacion_from_payload(
        payload: Mapping[str, Any] | None,
    ) -> str:
        if not isinstance(payload, Mapping):
            return ""

        containers: list[Mapping[str, Any]] = []
        dte_payload = payload.get("dteJson")
        if isinstance(dte_payload, Mapping):
            containers.append(dte_payload)
        containers.append(payload)

        for candidate in containers:
            ident = candidate.get("identificacion") or candidate.get("identificador")
            if not isinstance(ident, Mapping):
                continue
            codigo_val = ident.get("codigoGeneracion")
            if isinstance(codigo_val, str):
                codigo_norm = codigo_val.strip()
                if codigo_norm:
                    return codigo_norm.upper()
        return ""

    def _send_orphan_email(self, entry):
        json_path = entry.get("json") if isinstance(entry, dict) else None
        pdf_path = entry.get("pdf") if isinstance(entry, dict) else None
        default_email = ""
        if json_path and os.path.exists(json_path):
            try:
                with open(json_path, "r", encoding="utf-8") as fh:
                    json_data = json.load(fh)
                receptor = json_data.get("receptor", {}) if isinstance(json_data, dict) else {}
                if isinstance(receptor, dict):
                    default_email = (
                        receptor.get("correo")
                        or receptor.get("email")
                        or ""
                    )
            except Exception:
                default_email = ""

        if not default_email and isinstance(entry, dict):
            cliente_id = entry.get("cliente_id")
            db = getattr(getattr(self, "manager", None), "db", None)
            cliente_getter = getattr(db, "get_cliente", None) if db else None
            if cliente_id and callable(cliente_getter):
                try:
                    cliente_data = cliente_getter(cliente_id)
                except Exception:
                    cliente_data = None
                if isinstance(cliente_data, dict):
                    default_email = (
                        cliente_data.get("correo")
                        or cliente_data.get("email")
                        or ""
                    )

        dest, ok = QInputDialog.getText(
            self,
            "Enviar por correo",
            "Correo del destinatario:",
            text=default_email,
        )
        if not ok or not dest:
            return
        if not json_path or not os.path.exists(json_path):
            QMessageBox.warning(self, "Enviar por correo", "No se encontró el JSON.")
            return
        attachments = [json_path]
        if pdf_path and os.path.exists(pdf_path):
            attachments.insert(0, pdf_path)
        else:
            QMessageBox.warning(
                self, "Enviar por correo", "No se encontró PDF. Solo se adjuntará el JSON."
            )
        creds = {}
        if os.path.exists(DATOS_NEGOCIO_PATH):
            try:
                with open(DATOS_NEGOCIO_PATH, "r", encoding="utf-8") as f:
                    creds = json.load(f)
            except Exception:
                creds = {}
        server = creds.get("smtp_server")
        port = creds.get("smtp_port")
        user = creds.get("email_usuario")
        password = os.getenv("INVENTARIO_EMAIL_PASSWORD") or creds.get("email_contrasena")
        if not all([server, port, user, password]):
            QMessageBox.warning(self, "Enviar por correo", "Credenciales SMTP incompletas.")
            return
        subject = "Factura"
        body = (
            "Adjunto se envía la representación gráfica en PDF y el documento firmado en formato JSON"
        )
        self.btn_enviar.setEnabled(False)
        self.email_thread = EmailSender(
            server,
            port,
            user,
            password,
            dest,
            subject,
            body,
            attachments,
        )
        self.email_thread.finished.connect(self._on_email_sent)
        self._show_email_loading()
        self.email_thread.start()

    def _on_email_sent(self, success, message):
        self.btn_enviar.setEnabled(True)
        self._hide_email_loading()
        if success:
            QMessageBox.information(self, "Enviar por correo", message)
        else:
            QMessageBox.critical(self, "Enviar por correo", message)
        self.email_thread = None

    def create_ticket(self):
        entry = self._selected_entry()
        if not entry or entry.get("row_type") not in ("venta", "ticket"):
            raise ValueError("No sale selected")
        venta_id = entry.get("venta_id")
        venta = next((v for v in self.manager.db.get_ventas() if v["id"] == venta_id), None)
        detalles = self.manager.db.get_detalles_venta(venta_id)
        extra = {}
        raw_extra = venta.get("extra") if venta else None
        if raw_extra:
            try:
                extra = json.loads(raw_extra)
            except Exception:
                extra = {}
        fname, _ = QFileDialog.getSaveFileName(
            self,
            "Guardar ticket",
            "ticket.pdf",
            "PDF (*.pdf)",
            options=QFileDialog.DontUseNativeDialog,
        )
        if not fname:
            return
        ticket_json = dte.generar_ticket_json(self.manager.db, venta_id)
        data = dict(extra)
        data["dteJson"] = ticket_json
        generar_ticket_personalizado(venta, detalles, fname, dte_data=data)
        QMessageBox.information(self, "Ticket", "Ticket generado correctamente")

    def abrir_dialogo_tipo_nota(self):
        factura = self._selected_factura()
        if not factura:
            QMessageBox.warning(self, "Nota", "Seleccione una factura")
            return
        # Diálogo inicial para elegir el tipo de nota
        dialog = QDialog(self)
        dialog.setWindowTitle("Nota crédito / débito")
        layout = QVBoxLayout(dialog)

        radio_credito = QRadioButton("Nota de crédito", dialog)
        radio_debito = QRadioButton("Nota de débito", dialog)
        radio_credito.setChecked(True)
        layout.addWidget(radio_credito)
        layout.addWidget(radio_debito)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        # Cambiar el texto del botón de aceptación a "Continuar"
        buttons.button(QDialogButtonBox.Ok).setText("Continuar")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec_() == QDialog.Accepted:
            tipo = "credito" if radio_credito.isChecked() else "debito"
            self.create_nota(tipo, factura)

    def abrir_dialogo_nota_remision(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Nota de remisión")
        layout = QVBoxLayout(dialog)

        radio_factura = QRadioButton("Desde factura", dialog)
        radio_factura.setChecked(True)
        layout.addWidget(radio_factura)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Continuar")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec_() == QDialog.Accepted:
            self.crear_nota_remision_desde_factura()

    def _guardar_archivos_nota_remision(
        self, nota_json, nota_id=None, transmitir=False, venta_id=None
    ):
        resumen_nota = nota_json.get("resumen", {})
        tributos = {t.get("codigo"): t.get("valor", 0) for t in resumen_nota.get("tributos", []) or []}
        venta_data = {
            "sumas": float(resumen_nota.get("subTotalVentas", 0)),
            "descuentos": float(resumen_nota.get("totalDescu", 0)),
            "iva": float(tributos.get("20", 0)),
            "ventas_exentas": float(resumen_nota.get("totalExenta", 0)),
            "ventas_no_sujetas": float(resumen_nota.get("totalNoSuj", 0)),
            "subtotal": float(resumen_nota.get("subTotal", 0)),
            "total": float(resumen_nota.get("montoTotalOperacion", 0)),
            "total_letras": resumen_nota.get("totalLetras", ""),
        }
        detalles_pdf = []
        for d in nota_json.get("cuerpoDocumento", []) or []:
            detalles_pdf.append(
                {
                    "cantidad": float(d.get("cantidad", 1)),
                    "descripcion": d.get("descripcion", ""),
                    "precio_unitario": float(d.get("precioUni", 0)),
                    "iva": float(iva_item(Decimal(str(d.get("ventaGravada", 0)))) if TRIBUTO_IVA in (d.get("tributos") or []) else 0),
                    "ventas_gravadas": float(d.get("ventaGravada", 0)),
                    "ventas_exentas": float(d.get("ventaExenta", 0)),
                    "ventas_no_sujetas": float(d.get("ventaNoSuj", 0)),
                }
            )
        cliente = nota_json.get("receptor", {}) or {}
        extension = nota_json.get("extension", {}) or {}
        pdf_path, json_path = get_dte_document_paths(
            nota_json["identificacion"].get("fecEmi"),
            cliente.get("nombre") or cliente.get("nombreComercial") or "",
            nota_json["identificacion"].get("numeroControl"),
            "NotaRemision",
        )
        generar_nota_remision_pdf(
            venta_data,
            detalles_pdf,
            cliente,
            extension,
            archivo=str(pdf_path),
            codigo_generacion=nota_json["identificacion"].get("codigoGeneracion"),
            numero_control=nota_json["identificacion"].get("numeroControl"),
        )
        db = getattr(getattr(self, "manager", None), "db", None)
        if db is not None:
            try:
                db.add_factura_pdf(venta_id, "Nota de remisión", str(pdf_path))
            except Exception:
                logger.exception(
                    "No se pudo registrar la nota de remisión en facturas_pdf"
                )
        token = None
        try:
            _, token = sign_and_save(nota_json, str(json_path), return_token=True)
        except Exception:
            logger.exception("No se pudo firmar nota de remisión en %s", json_path)
        try:
            persist_client_json(json_path, nota_json, firma=token)
        except Exception:
            logger.exception(
                "No se pudo preparar la versión para cliente de la nota en %s", json_path
            )
        if transmitir and nota_id is not None:
            try:
                resp = enviar_nota_remision(self.manager.db, nota_id)
                estado = str(resp.get("estado", "") if resp else "").lower()
                if estado == "error":
                    self._mostrar_respuesta_hacienda(resp, title="Nota")
                else:
                    QMessageBox.information(
                        self, "Nota", "Nota registrada y transmitida"
                    )
                    if resp:
                        self._mostrar_respuesta_hacienda(resp, title="Nota")
            except dte.DTEValidationError as exc:
                self._show_validation_errors(exc.errors, exc.json_path)
            except Exception as exc:
                QMessageBox.critical(self, "Nota", str(exc))

    def crear_nota_remision_desde_factura(self):
        factura = self._selected_factura()
        if not factura:
            QMessageBox.warning(self, "Nota", "Seleccione una factura")
            return
        venta_id = factura.get("venta_id")
        json_path = factura.get("json")
        try:
            with open(json_path, "r", encoding="utf-8") as fh:
                factura_json = json.load(fh)
        except Exception:
            QMessageBox.warning(self, "Nota", "No se pudo leer la factura")
            return
        if not venta_id:
            QMessageBox.warning(self, "Nota", "Factura sin venta asociada")
        dialog = NotaRemisionExtDialog(self.manager.db, factura=factura_json, parent=self)
        if dialog.exec_() != QDialog.Accepted:
            return
        extension = dialog.get_data()
        fecha = QDate.currentDate().toString("yyyy-MM-dd")
        extra = {"extension": extension}
        if not venta_id:
            extra["factura"] = factura_json
        nota_id = self.manager.db.agregar_nota(
            "remision", venta_id, fecha, 0, "Remision", detalles=extra
        )
        nota_json = generar_nota_remision_desde_db(self.manager.db, nota_id)
        self._guardar_archivos_nota_remision(
            nota_json, nota_id=nota_id, venta_id=venta_id
        )
        QMessageBox.information(
            self, "Nota", "Nota de remisión generada correctamente"
        )
        try:
            self.load_invoices()
        except Exception:
            logger.exception("No se pudo actualizar la tabla de facturación")


    def _resolve_modo_transmision(self) -> str:
        getter = getattr(self.manager, "get_modo_transmision_actual", None)
        modo_value: str | None = None
        if callable(getter):
            try:
                modo_value = getter()
            except Exception:
                modo_value = None
        elif hasattr(self.manager, "modo_transmision"):
            modo_value = getattr(self.manager, "modo_transmision")

        if modo_value is None or str(modo_value).strip() == "":
            return dte.get_default_modo_transmision()

        return modo_value

    def create_nota(self, tipo, factura=None):
        factura = factura or self._selected_factura()
        if not factura:
            QMessageBox.warning(self, "Nota", "Seleccione una factura")
            return
        json_path = factura.get("json")
        venta_id = factura.get("venta_id")
        try:
            with open(json_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            QMessageBox.warning(self, "Nota", "No se pudo leer la factura")
            return

        tipo_dte = str(data.get("identificacion", {}).get("tipoDte", "")).zfill(2)
        if tipo in {"credito", "debito"} and tipo_dte == "01":
            QMessageBox.warning(
                self,
                "Nota",
                "No se pueden crear notas de crédito y débito a partir de facturas de consumidor final.",
            )
            return

        # Intenta obtener el sello de recepción desde dte_envios
        sello = data.get("selloRecibido")
        if not sello and venta_id:
            resp_envio = self.manager.db.consultar_envio_dte(venta_id) or {}
            sello = resp_envio.get("selloRecibido") or resp_envio.get("sello")
            if not sello:
                row = self.manager.db.cursor.execute(
                    "SELECT sello, respuesta FROM dte_envios WHERE venta_id=? ORDER BY id DESC LIMIT 1",
                    (venta_id,),
                ).fetchone()
                if row:
                    sello = row["sello"]
                    if not sello:
                        resp = row["respuesta"]
                        if resp:
                            try:
                                resp_json = json.loads(resp)
                                sello = resp_json.get("selloRecibido") or resp_json.get("sello")
                            except Exception:
                                pass
        if sello:
            data["selloRecibido"] = sello

        detalles_venta = []
        for d in data.get("cuerpoDocumento", []) or []:
            detalles_venta.append(
                {
                    "id": d.get("numItem"),
                    "producto_id": d.get("codigo"),
                    "descripcion": d.get("descripcion", ""),
                    "cantidad": float(d.get("cantidad", 0)),
                    "precio_unitario": float(d.get("precioUni", 0)),
                    "descuento": float(d.get("montoDescu", 0)),
                    "descuento_tipo": "$",
                    "ventas_gravadas": float(d.get("ventaGravada", 0)),
                    "ventas_exentas": float(d.get("ventaExenta", 0)),
                    "ventas_no_sujetas": float(d.get("ventaNoSuj", 0)),
                    "precio_unitario_iva": iva_item(Decimal(str(d.get("ventaGravada", 0)))) if TRIBUTO_IVA in (d.get("tributos") or []) else Decimal("0"),
                    "descuento_iva": Decimal(str(d.get("montoDescu", 0))),
                    "total_linea": Decimal(str(d.get("ventaGravada", 0))),
                    "uniMedida": d.get("uniMedida"),
                    "tipoItem": d.get("tipoItem"),
                }
            )

        detalle_map = {d["id"]: d for d in detalles_venta}

        dialog = NotaDetalleDialog(detalles_venta, tipo, self)
        if dialog.exec_() != QDialog.Accepted:
            return
        try:
            monto, motivo, detalles_nota = dialog.get_data()
        except ValueError as exc:
            QMessageBox.warning(self, "Nota", str(exc))
            return
        def _round4(value: float) -> float:
            return float(Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))

        for det in detalles_nota or []:
            src = detalle_map.get(det.get("detalle_id"))
            ajuste_total = abs(det.get("ajuste", 0)) if det.get("ajuste") is not None else 0.0
            if det.get("ajusteCantidad"):
                cantidad = abs(det.get("cantidad", 0))
                if not cantidad:
                    continue
                afectacion = det.get("afectacion")
                if not afectacion and src:
                    if src.get("ventas_gravadas"):
                        afectacion = "gravada"
                    elif src.get("ventas_exentas"):
                        afectacion = "exenta"
                    elif src.get("ventas_no_sujetas"):
                        afectacion = "no_sujeta"
                precio_unitario = det.get("precio_unitario")
                if precio_unitario is None and src:
                    cantidad_src = src.get("cantidad") or 0
                    if cantidad_src:
                        if src.get("ventas_gravadas"):
                            precio_unitario = src.get("ventas_gravadas", 0) / cantidad_src
                        elif src.get("ventas_exentas"):
                            precio_unitario = src.get("ventas_exentas", 0) / cantidad_src
                        elif src.get("ventas_no_sujetas"):
                            precio_unitario = src.get("ventas_no_sujetas", 0) / cantidad_src
                    if precio_unitario is None:
                        precio_unitario = src.get("precio_unitario")
                precio_unitario = float(precio_unitario or 0)
                precio_unitario = _round4(precio_unitario)
                total_base = _round4(precio_unitario * cantidad)
                det.update(
                    {
                        "cantidad": _round4(cantidad),
                        "precio_unitario": precio_unitario,
                        "ajusteCantidad": True,
                    }
                )
                if src:
                    det.setdefault("producto_id", src.get("producto_id"))
                    det.setdefault("descripcion", src.get("descripcion"))
                    det.setdefault("uniMedida", src.get("uniMedida"))
                    det.setdefault("tipoItem", src.get("tipoItem"))
                if afectacion == "exenta":
                    det.update({
                        "ventas_exentas": total_base,
                        "iva": 0.0,
                    })
                elif afectacion == "no_sujeta":
                    det.update({
                        "ventas_no_sujetas": total_base,
                        "iva": 0.0,
                    })
                else:
                    iva = _round4(total_base * 0.13)
                    det.update({
                        "ventas_gravadas": total_base,
                        "iva": iva,
                    })

            if ajuste_total == 0:
                continue

            incluye_iva = bool(det.get("monto_incluye_iva", False))
            if src and src.get("ventas_gravadas"):
                if incluye_iva:
                    base = ajuste_total / 1.13
                    iva = ajuste_total - base
                else:
                    base = ajuste_total
                    iva = base * 0.13
                base = _round4(base)
                iva = _round4(iva)
                det.update({
                    "ventas_gravadas": base,
                    "iva": iva,
                    "precio_unitario": base,
                })
            elif src and src.get("ventas_exentas"):
                base_exenta = _round4(ajuste_total)
                det.update({
                    "ventas_exentas": base_exenta,
                    "iva": 0.0,
                    "precio_unitario": base_exenta,
                })
            elif src and src.get("ventas_no_sujetas"):
                base_no_suj = _round4(ajuste_total)
                det.update({
                    "ventas_no_sujetas": base_no_suj,
                    "iva": 0.0,
                    "precio_unitario": base_no_suj,
                })
            else:
                if incluye_iva:
                    base = ajuste_total / 1.13
                    iva = ajuste_total - base
                else:
                    base = ajuste_total
                    iva = base * 0.13
                base = _round4(base)
                iva = _round4(iva)
                det.update({
                    "ventas_gravadas": base,
                    "iva": iva,
                    "precio_unitario": base,
                })
            det.pop("monto_incluye_iva", None)
        if monto == 0:
            QMessageBox.warning(self, "Nota", "El monto total debe ser diferente de cero")
            return
        fecha = QDate.currentDate().toString("yyyy-MM-dd")
        resumen_factura = data.get("resumen", {}) or {}
        total_original = float(
            resumen_factura.get("totalPagar")
            or resumen_factura.get("montoTotalOperacion")
            or 0
        )
        if tipo == "debito":
            total_ajustado = total_original + monto
        elif tipo == "credito":
            total_ajustado = total_original - monto
        else:
            total_ajustado = total_original
        resumen = (
            f"Total original: {total_original:.2f}\n"
            f"Ajuste: {monto:.2f}\n"
            f"Total ajustado: {total_ajustado:.2f}\n\n"
            "¿Desea continuar?"
        )
        if QMessageBox.question(self, "Confirmar", resumen, QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return

        nota_id = self.manager.db.agregar_nota(
            tipo, venta_id, fecha, monto, motivo, detalles=detalles_nota
        )

        detalles_pdf = []
        for det in detalles_nota or []:
            src = detalle_map.get(det.get("detalle_id"))
            if not src:
                continue
            if det.get("ajusteCantidad"):
                detalle = {
                    "cantidad": det.get("cantidad", 0),
                    "descripcion": src.get("descripcion", ""),
                    "precio_unitario": det.get("precio_unitario", 0),
                    "iva": det.get("iva", 0),
                    "ventas_gravadas": det.get("ventas_gravadas", 0),
                    "ventas_exentas": det.get("ventas_exentas", 0),
                    "ventas_no_sujetas": det.get("ventas_no_sujetas", 0),
                }
            else:
                detalle = {
                    "cantidad": 1,
                    "descripcion": src.get("descripcion", ""),
                    "precio_unitario": det.get("precio_unitario", 0),
                    "iva": det.get("iva", 0),
                    "ventas_gravadas": det.get("ventas_gravadas", 0),
                    "ventas_exentas": det.get("ventas_exentas", 0),
                    "ventas_no_sujetas": det.get("ventas_no_sujetas", 0),
                }
            detalles_pdf.append(detalle)

        if tipo == "credito":
            ratio = None
            if not detalles_pdf:
                ratio = Decimal(str(monto / total_original))
            nota_json = nota_credito_electronica.generar_nce_desde_dte(
                self.manager.db,
                data,
                ratio,
                detalles=detalles_pdf or None,
                motivo=motivo,
            )
        elif tipo == "debito":
            nota_json = generar_nde_desde_dte(
                self.manager.db, data, detalles_pdf or None, monto, motivo
            )
        else:
            nota_json = generar_nota_remision_desde_db(self.manager.db, nota_id)

        resumen_nota = nota_json.get("resumen", {})
        tributos = {t.get("codigo"): t.get("valor", 0) for t in resumen_nota.get("tributos", []) or []}
        venta_data = {
            "sumas": float(resumen_nota.get("subTotalVentas", 0)),
            "descuentos": float(resumen_nota.get("totalDescu", 0)),
            "iva": float(tributos.get("20", 0)),
            "ventas_exentas": float(resumen_nota.get("totalExenta", 0)),
            "ventas_no_sujetas": float(resumen_nota.get("totalNoSuj", 0)),
            "subtotal": float(resumen_nota.get("subTotal", 0)),
            "total": float(resumen_nota.get("montoTotalOperacion", 0)),
            "total_letras": resumen_nota.get("totalLetras", ""),
        }
        if not detalles_pdf:
            detalles_pdf = []
            for d in nota_json.get("cuerpoDocumento", []) or []:
                detalles_pdf.append(
                    {
                        "cantidad": float(d.get("cantidad", 1)),
                        "descripcion": d.get("descripcion", ""),
                        "precio_unitario": float(d.get("precioUni", 0)),
                        "iva": float(iva_item(Decimal(str(d.get("ventaGravada", 0)))) if TRIBUTO_IVA in (d.get("tributos") or []) else 0),
                        "ventas_gravadas": float(d.get("ventaGravada", 0)),
                        "ventas_exentas": float(d.get("ventaExenta", 0)),
                        "ventas_no_sujetas": float(d.get("ventaNoSuj", 0)),
                    }
                )

        cliente = data.get("receptor", {}) or {}
        distribuidor = {}

        conf = {
            "debito": (NOTAS_DEBITO_DIR, "NotaDebito", generar_nota_debito_pdf),
            "credito": (NOTAS_CREDITO_DIR, "NotaCredito", generar_nota_credito_pdf),
            "remision": (NOTAS_REMISION_DIR, "NotaRemision", generar_nota_remision_pdf),
        }
        out_dir, doc_type, pdf_func = conf.get(tipo)
        os.makedirs(out_dir, exist_ok=True)
        pdf_path, json_path = get_dte_document_paths(
            nota_json["identificacion"].get("fecEmi"),
            cliente.get("nombre") or cliente.get("nombreComercial") or "",
            nota_json["identificacion"].get("numeroControl"),
            doc_type,
        )
        identificacion = nota_json.get("identificacion", {}) or {}
        codigo_gen = identificacion.get("codigoGeneracion")
        num_ctrl = identificacion.get("numeroControl")
        fec_emision = identificacion.get("fecEmi") or identificacion.get("fechaEmi")
        def _normalize_sello(value):
            if not value:
                return ""
            text = str(value).strip()
            return text.upper() if text else ""

        respuesta_info = nota_json.get("respuesta")
        if not isinstance(respuesta_info, dict):
            respuesta_info = {}
        sello_recepcion = _normalize_sello(
            nota_json.get("selloRecibido")
            or respuesta_info.get("selloRecibido")
            or respuesta_info.get("selloRecepcion")
            or respuesta_info.get("sello")
        )

        if not sello_recepcion and nota_id:
            try:
                envio_info = self.manager.db.consultar_envio_dte(nota_id) or {}
            except Exception:
                envio_info = {}
            sello_recepcion = _normalize_sello(
                envio_info.get("selloRecibido")
                or envio_info.get("selloRecepcion")
                or envio_info.get("sello")
            )

        def _make_note_renderer(sello_val: str):
            def _render(output_path):
                pdf_func(
                    venta_data,
                    detalles_pdf,
                    cliente or {},
                    distribuidor or {},
                    archivo=str(output_path),
                    codigo_generacion=codigo_gen,
                    numero_control=num_ctrl,
                    fecha_generacion=fec_emision,
                    sello_recepcion=sello_val,
                )

            return _render

        render_note_pdf = _make_note_renderer(sello_recepcion)

        resp = None
        try:
            with loading_dialog(self, "Creando DTE…"):
                pdf_path = write_pdf_atomically(pdf_path, render_note_pdf)
                _, token = sign_and_save(
                    nota_json, str(json_path), return_token=True
                )
                try:
                    persist_client_json(
                        json_path,
                        nota_json,
                        firma=token,
                        sello=sello_recepcion,
                    )
                except Exception:
                    logger.exception(
                        "No se pudo preparar JSON firmado para cliente en %s", json_path
                    )
                modo_eff = self._resolve_modo_transmision()
                resp = dte._enviar_documento(
                    self.manager.db, nota_id, nota_json, modo=modo_eff, jws_token=token
                )
        except dte.DTEValidationError as exc:
            self._show_validation_errors(exc.errors, exc.json_path)
            self.load_invoices()
            return
        except Exception as exc:
            QMessageBox.critical(self, "Nota", str(exc))
            self.load_invoices()
            return

        sello_resp = _normalize_sello(
            (resp or {}).get("sello")
            or (resp or {}).get("selloRecibido")
            or (resp or {}).get("selloRecepcion")
        )
        if not sello_resp and nota_id:
            try:
                envio_info = self.manager.db.consultar_envio_dte(nota_id) or {}
            except Exception:
                envio_info = {}
            sello_resp = _normalize_sello(
                envio_info.get("selloRecibido")
                or envio_info.get("selloRecepcion")
                or envio_info.get("sello")
            )
        if sello_resp and sello_resp != sello_recepcion:
            try:
                render_note_pdf = _make_note_renderer(sello_resp)
                pdf_path = write_pdf_atomically(pdf_path, render_note_pdf)
                sello_recepcion = sello_resp
            except Exception:
                logger.exception("No se pudo regenerar la nota con el sello recibido.")

        sello_final = sello_resp or sello_recepcion
        codigo_generacion_meta = None
        try:
            if codigo_gen:
                codigo_generacion_meta = str(codigo_gen).strip().upper()
        except Exception:
            codigo_generacion_meta = None

        if tipo in {"credito", "debito"} and sello_final and os.path.exists(json_path):
            self._ensure_invoice_json_metadata(
                json_path,
                codigo=codigo_generacion_meta or codigo_gen,
                sello=sello_final,
            )

            if os.path.exists(pdf_path):
                answer = QMessageBox.question(
                    self,
                    "Enviar por correo",
                    "¿Desea enviar por correo?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes,
                )
                if answer == QMessageBox.Yes:
                    self._send_note_email(
                        nota_tipo=tipo,
                        venta_id=venta_id,
                        cliente_info=cliente,
                        pdf_path=pdf_path,
                        json_path=json_path,
                        codigo=codigo_generacion_meta or codigo_gen,
                        sello=sello_final,
                    )

        # Mostrar previsualización del PDF generado
        try:
            self._show_pdf_preview(pdf_path)
        except Exception:
            pass

        estado = str(resp.get("estado", "") if resp else "").lower()
        if estado == "error":
            self._mostrar_respuesta_hacienda(resp, title="Nota")
        else:
            QMessageBox.information(self, "Nota", "Nota registrada y transmitida")
            if resp:
                self._mostrar_respuesta_hacienda(resp, title="Nota")
        self.load_invoices()

    def _get_invoice_paths(self, venta_id, factura=None, entry=None):
        """Obtiene las rutas relacionadas a una factura."""
        pdf_path = None
        ticket_path = None
        dte_json_path = None

        venta = None
        if venta_id:
            try:
                pdf_path = self.manager.db.get_factura_pdf(venta_id)
            except Exception:
                pdf_path = None
            try:
                ticket_path = self.manager.db.get_ticket_pdf(venta_id)
            except Exception:
                ticket_path = None
            try:
                venta = self.manager.db.get_venta_by_id(venta_id)
            except Exception:
                venta = None

        if entry and not ticket_path:
            ticket_path = entry.get("ticket_pdf") or entry.get("ticket_path")

        if factura:
            dte_json_path = factura.get("json")

        if not dte_json_path and entry:
            dte_json_path = entry.get("json") or entry.get("path")

        if not dte_json_path and pdf_path:
            dte_json_path = os.path.splitext(pdf_path)[0] + ".json"

        venta_map = venta if hasattr(venta, "get") else None

        if not dte_json_path and venta_map:
            extra_data = venta_map.get("extra")
            parsed_extra: Mapping[str, Any] | None = None
            if isinstance(extra_data, Mapping):
                parsed_extra = extra_data
            elif isinstance(extra_data, str):
                try:
                    parsed_extra = json.loads(extra_data)
                except Exception:
                    parsed_extra = None
            if parsed_extra:
                for key in (
                    "dteJsonPath",
                    "jsonPath",
                    "json",
                    "path",
                    "dteJson",
                ):
                    candidate = parsed_extra.get(key)
                    if isinstance(candidate, str):
                        candidate = candidate.strip()
                        if candidate and os.path.exists(candidate):
                            dte_json_path = candidate
                            break

        if not dte_json_path and venta_id:
            try:
                resp = self.manager.db.consultar_envio_dte(venta_id)
                dte_json_path = (
                    resp.get("json")
                    or resp.get("path")
                    or resp.get("ruta")
                )
            except Exception:
                dte_json_path = None

        if not dte_json_path and ticket_path:
            dte_json_path = self._guess_ticket_json_path(ticket_path)

        if not dte_json_path and venta_map:
            extra_candidates = (
                venta_map.get("dteJsonPath"),
                venta_map.get("jsonPath"),
                venta_map.get("json"),
            )
            for candidate in extra_candidates:
                if isinstance(candidate, str):
                    candidate = candidate.strip()
                    if candidate and os.path.exists(candidate):
                        dte_json_path = candidate
                        break

        return pdf_path, ticket_path, dte_json_path

    def _guess_ticket_json_path(self, ticket_path: str | None) -> str | None:
        if not ticket_path:
            return None

        try:
            base, _ = os.path.splitext(ticket_path)
        except Exception:
            return None

        candidates: list[str] = []

        def _append_candidate(path_base: str) -> None:
            if not path_base:
                return
            candidates.append(f"{path_base}.json")
            candidates.append(f"{path_base}_consumidorfinal.json")
            candidates.append(f"{path_base}_ConsumidorFinal.json")
            candidates.append(f"{path_base}_creditofiscal.json")
            candidates.append(f"{path_base}_creditoFiscal.json")

        _append_candidate(base)

        suffixes = ["_Ticket", "_ticket", "-Ticket", "-ticket"]
        for suffix in suffixes:
            if base.endswith(suffix):
                trimmed = base[: -len(suffix)]
                _append_candidate(trimmed)
                break

        for candidate in candidates:
            if candidate and os.path.exists(candidate):
                return candidate

        return None

    def _ensure_archive_directory(self, name: str) -> str:
        base_root = DTE_FALLIDOS_DIR
        os.makedirs(base_root, exist_ok=True)
        sanitized = re.sub(r"[^A-Za-z0-9_.-]", "_", name or "rechazo")
        sanitized = sanitized.strip("_") or "rechazo"
        candidate = os.path.join(base_root, sanitized)
        index = 1
        while os.path.exists(candidate):
            candidate = os.path.join(base_root, f"{sanitized}_{index}")
            index += 1
        os.makedirs(candidate)
        return candidate

    def _unique_destination(self, path: str) -> str:
        base, ext = os.path.splitext(path)
        candidate = path
        index = 1
        while os.path.exists(candidate):
            candidate = f"{base}_{index}{ext}"
            index += 1
        return candidate

    def _move_directory_contents(self, src_dir: str, dest_dir: str) -> None:
        if not src_dir or not dest_dir:
            return
        if os.path.abspath(src_dir) == os.path.abspath(dest_dir):
            return
        if not os.path.isdir(src_dir):
            return
        for name in os.listdir(src_dir):
            src_path = os.path.join(src_dir, name)
            dest_path = os.path.join(dest_dir, name)
            dest_path = self._unique_destination(dest_path)
            try:
                shutil.move(src_path, dest_path)
            except Exception:
                logger.exception("No se pudo mover %s a %s", src_path, dest_path)
        try:
            shutil.rmtree(src_dir)
        except OSError:
            pass

    def _normalize_series_component(self, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        # Prefer numeric values when present but keep alphanumeric fallbacks
        filtered = re.sub(r"[^0-9A-Za-z]", "", text)
        if filtered:
            text = filtered
        if len(text) > 3:
            text = text[-3:]
        try:
            return text.zfill(3)
        except Exception:
            return None

    def _infer_dte_series(self, extra_data: Mapping[str, Any] | None) -> dict | None:
        if not isinstance(extra_data, Mapping):
            return None

        correlativo_raw = None
        for key in ("correlativo", "correlativoActual", "correlativo_actual"):
            if key in extra_data:
                correlativo_raw = extra_data.get(key)
                break
        if correlativo_raw in (None, ""):
            return None
        try:
            correlativo = int(str(correlativo_raw).strip())
        except (TypeError, ValueError):
            return None

        tipo_val = extra_data.get("tipoDte") or extra_data.get("tipo_dte") or extra_data.get("tipo")
        try:
            tipo = str(tipo_val).zfill(2) if tipo_val is not None else "01"
        except Exception:
            tipo = "01"

        sucursal = (
            extra_data.get("sucursal")
            or extra_data.get("codEstable")
            or extra_data.get("codEstableMH")
            or extra_data.get("sucursal_id")
        )
        punto = (
            extra_data.get("punto")
            or extra_data.get("codPuntoVenta")
            or extra_data.get("codPuntoVentaMH")
            or extra_data.get("punto_venta")
        )

        try:
            datos_negocio = dte._load_datos_negocio() or {}
        except Exception:
            datos_negocio = {}

        prefijo = None
        if not sucursal or not punto:
            prefijo = (datos_negocio.get("dte_api") or {}).get("prefijo_control")
            if not prefijo:
                prefijo = datos_negocio.get("prefijo_control")
        if prefijo and (not sucursal or not punto):
            m_pref = re.search(r"S([A-Za-z0-9]{3})P([A-Za-z0-9]{3})", str(prefijo))
            if m_pref:
                if not sucursal:
                    sucursal = m_pref.group(1)
                if not punto:
                    punto = m_pref.group(2)

        if not sucursal:
            sucursal = datos_negocio.get("codEstable") or datos_negocio.get("codEstableMH")
        if not punto:
            punto = datos_negocio.get("codPuntoVenta") or datos_negocio.get("codPuntoVentaMH")

        sucursal_norm = self._normalize_series_component(sucursal)
        punto_norm = self._normalize_series_component(punto)
        if not sucursal_norm or not punto_norm:
            return None

        return {
            "tipo": tipo,
            "sucursal": sucursal_norm,
            "punto": punto_norm,
            "correlativo": correlativo,
        }

    def _cleanup_invoice_artifacts(
        self,
        venta_id,
        *,
        pdf_path=None,
        ticket_path=None,
        dte_json_path=None,
        archive_subdir=None,
        extra_data=None,
        prompt_revert=False,
    ):
        reverted_correlativo = False
        archive_dir = None
        if archive_subdir:
            archive_dir = self._ensure_archive_directory(archive_subdir)

        if not isinstance(extra_data, dict):
            extra_data = {}
            if venta_id:
                venta = None
                try:
                    venta = self.manager.db.get_venta_by_id(venta_id)
                except Exception:
                    venta = None
                if venta:
                    raw_extra = venta.get("extra")
                    if isinstance(raw_extra, str) and raw_extra.strip():
                        try:
                            extra_data = json.loads(raw_extra)
                        except Exception:
                            extra_data = {}

        numero_control = None
        serie_info: dict | None = None
        candidate_paths = []
        if dte_json_path:
            candidate_paths.append(dte_json_path)
        for key in ("dteJsonPath", "jsonPath"):
            candidate = extra_data.get(key) if isinstance(extra_data, dict) else None
            if candidate and candidate not in candidate_paths:
                candidate_paths.append(candidate)

        resolved_json_path = None
        for candidate in candidate_paths:
            if not candidate or not os.path.exists(candidate):
                continue
            try:
                with open(candidate, "r", encoding="utf-8") as fh:
                    jdata = json.load(fh)
                ident = jdata.get("identificacion") or jdata.get("identificador") or {}
                numero_control = ident.get("numeroControl")
                if not serie_info:
                    serie_info = self._parse_numero_control(numero_control)
            except Exception:
                numero_control = None
            else:
                resolved_json_path = candidate
                break

        if resolved_json_path:
            dte_json_path = resolved_json_path
            abs_json = os.path.normpath(dte_json_path)
            for root_dir in map(
                os.path.normpath, (DTES_DIR, DTE_FALLIDOS_DIR, DTES_PENDIENTES_DIR)
            ):
                if abs_json.startswith(root_dir + os.sep):
                    if archive_dir:
                        self._move_directory_contents(os.path.dirname(abs_json), archive_dir)
                    else:
                        try:
                            shutil.rmtree(os.path.dirname(abs_json))
                        except OSError:
                            pass
                    break

        if not numero_control and isinstance(extra_data, dict):
            numero_control = extra_data.get("numeroControl")
        if not serie_info and numero_control:
            serie_info = self._parse_numero_control(numero_control)
        if not serie_info:
            serie_info = self._infer_dte_series(extra_data if isinstance(extra_data, Mapping) else None)
            if serie_info and not numero_control:
                numero_control = "DTE-{tipo}-S{sucursal}P{punto}-{correlativo:015d}".format(
                    tipo=serie_info["tipo"],
                    sucursal=serie_info["sucursal"],
                    punto=serie_info["punto"],
                    correlativo=serie_info["correlativo"],
                )

        should_attempt_revert = bool(serie_info)
        if serie_info and prompt_revert:
            prompt_msg = "¿Desea revertir el correlativo asociado al DTE eliminado?"
            if numero_control:
                prompt_msg = (
                    "Se encontró el correlativo para el documento"
                    f" {numero_control}. ¿Desea revertirlo?"
                )
            confirm_revert = QMessageBox.question(
                self,
                "Revertir correlativo",
                prompt_msg,
                QMessageBox.Yes | QMessageBox.No,
            )
            if confirm_revert != QMessageBox.Yes:
                should_attempt_revert = False
                logger.info(
                    "El usuario decidió no revertir el correlativo para el DTE eliminado"
                )

        if serie_info and should_attempt_revert:
            tipo = serie_info["tipo"]
            sucursal = serie_info["sucursal"]
            punto = serie_info["punto"]
            correlativo_val = int(serie_info["correlativo"])
            try:
                reverted, motivo = self.manager.db.revert_dte_correlativo(
                    tipo,
                    sucursal,
                    punto,
                    correlativo_val,
                )
            except Exception:
                logger.exception(
                    "Error al revertir correlativo tipo=%s sucursal=%s punto=%s correlativo=%s",
                    tipo,
                    sucursal,
                    punto,
                    correlativo_val,
                )
            else:
                if reverted:
                    reverted_correlativo = True
                    if numero_control:
                        logger.info(
                            "Se revirtió el correlativo asociado al número de control %s",
                            numero_control,
                        )
                    else:
                        logger.info(
                            "Se revirtió el correlativo tipo=%s sucursal=%s punto=%s correlativo=%s",
                            tipo,
                            sucursal,
                            punto,
                            correlativo_val,
                        )
                elif motivo:
                    logger.warning(
                        "No se pudo revertir el correlativo tipo=%s sucursal=%s punto=%s correlativo=%s: %s",
                        tipo,
                        sucursal,
                        punto,
                        correlativo_val,
                        motivo,
                    )

        targets = [path for path in [pdf_path, ticket_path] if path]
        for base in targets:
            root = os.path.splitext(base)[0]
            for ext in (".pdf", ".json", ".jws"):
                candidate = root + ext
                if not os.path.exists(candidate):
                    continue
                if archive_dir:
                    dest = os.path.join(archive_dir, os.path.basename(candidate))
                    dest = self._unique_destination(dest)
                    try:
                        shutil.move(candidate, dest)
                    except Exception:
                        logger.exception("No se pudo mover %s a %s", candidate, dest)
                else:
                    try:
                        os.remove(candidate)
                    except OSError:
                        pass

        return reverted_correlativo

    def _archive_rejected_invoice(self, entry, factura):
        if not entry:
            return
        venta_id = entry.get("venta_id")
        if not venta_id:
            return

        factura = factura or self._selected_factura()
        pdf_path, ticket_path, dte_json_path = self._get_invoice_paths(
            venta_id, factura=factura, entry=entry
        )

        venta = None
        extra_data = {}
        try:
            venta = self.manager.db.get_venta_by_id(venta_id)
        except Exception:
            venta = None
        if venta:
            raw_extra = venta.get("extra")
            if isinstance(raw_extra, str) and raw_extra.strip():
                try:
                    extra_data = json.loads(raw_extra)
                except Exception:
                    extra_data = {}

        numero_control = None
        if dte_json_path and os.path.exists(dte_json_path):
            try:
                with open(dte_json_path, "r", encoding="utf-8") as fh:
                    jdata = json.load(fh)
                ident = jdata.get("identificacion") or jdata.get("identificador") or {}
                numero_control = ident.get("numeroControl")
            except Exception:
                numero_control = None

        if not numero_control and isinstance(extra_data, dict):
            numero_control = extra_data.get("numeroControl")

        archive_label = numero_control or entry.get("name") or entry.get("control")
        if not archive_label:
            archive_label = f"venta_{venta_id}"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        archive_label = f"{archive_label}_rechazo_{timestamp}"
        archive_label = re.sub(r"[^A-Za-z0-9_.-]", "_", archive_label)

        if not self.manager.db.delete_venta(venta_id):
            QMessageBox.critical(self, "Eliminar", "No se pudo eliminar la venta seleccionada.")
            return
        self.manager.refresh_data()
        main_window = self.window()
        if main_window and hasattr(main_window, "_actualizar_inventario_actual"):
            try:
                main_window._actualizar_inventario_actual()
            except Exception:
                logger.exception(
                    "Error al actualizar inventario actual tras eliminar factura"
                )

        self._cleanup_invoice_artifacts(
            venta_id,
            pdf_path=pdf_path,
            ticket_path=ticket_path,
            dte_json_path=dte_json_path,
            archive_subdir=archive_label,
            extra_data=extra_data,
        )

        self.load_invoices()
        self._clear_preview_files()

    def delete_invoice(self):
        """Elimina una factura junto con archivos y correlativos asociados."""
        data = self._selected_entry()
        if not data or data.get("row_type") not in {"venta", "ticket", "orphan"}:
            QMessageBox.warning(self, "Eliminar", "Seleccione una factura")
            return
        rtype = data.get("row_type")
        venta_id = data.get("venta_id")

        confirm = QMessageBox.question(
            self,
            "Eliminar",
            "¿Eliminar factura y archivos asociados?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        # Handle orphan entries without touching the sales database
        if rtype == "orphan":
            pdf_path = data.get("pdf")
            json_path = data.get("json")
            path = pdf_path or json_path
            base = os.path.splitext(os.path.basename(path))[0] if path else None

            extra_data: dict[str, Any] = {}
            numero_control = data.get("numero_control")
            if numero_control:
                extra_data["numeroControl"] = numero_control
            tipo_codigo = data.get("codigo")
            if tipo_codigo:
                extra_data["tipoDte"] = tipo_codigo

            correlativo_revertido = self._cleanup_invoice_artifacts(
                data.get("venta_id"),
                pdf_path=pdf_path,
                ticket_path=None if pdf_path else json_path,
                dte_json_path=json_path,
                extra_data=extra_data or None,
                prompt_revert=True,
            )

            # Remove database record tied to the orphan file
            if path:
                try:
                    self.manager.db.cursor.execute(
                        "DELETE FROM facturas_pdf WHERE ruta=?", (path,)
                    )
                    self.manager.db.conn.commit()
                except Exception:
                    pass

            if base:
                for folder in INVOICE_DIRS:
                    for ext in (".pdf", ".json", ".jws"):
                        pattern = os.path.join(folder, "**", base + ext)
                        for candidate in glob.glob(pattern, recursive=True):
                            if os.path.exists(candidate):
                                try:
                                    os.remove(candidate)
                                except OSError:
                                    pass

            mensaje = f"{data.get('tipo') or 'Documento'} eliminado"
            if correlativo_revertido:
                mensaje += "\nEl correlativo regresó al valor anterior."

            QMessageBox.information(self, "Eliminar", mensaje)
            self.load_invoices()
            return

        factura = None
        if rtype in {"venta", "ticket"}:
            factura = self._selected_factura()
        pdf_path, ticket_path, dte_json_path = self._get_invoice_paths(
            venta_id, factura=factura, entry=data
        )

        venta = None
        extra_data = {}
        try:
            venta = self.manager.db.get_venta_by_id(venta_id)
        except Exception:
            venta = None
        if venta:
            raw_extra = venta.get("extra")
            if isinstance(raw_extra, str) and raw_extra.strip():
                try:
                    extra_data = json.loads(raw_extra)
                except Exception:
                    extra_data = {}

        if not self.manager.db.delete_venta(venta_id):
            QMessageBox.critical(self, "Eliminar", "No se pudo eliminar la venta seleccionada.")
            return
        self.manager.refresh_data()

        correlativo_revertido = self._cleanup_invoice_artifacts(
            venta_id,
            pdf_path=pdf_path,
            ticket_path=ticket_path,
            dte_json_path=dte_json_path,
            extra_data=extra_data,
            prompt_revert=True,
        )

        mensaje = "Factura eliminada"
        if correlativo_revertido:
            mensaje += "\nEl correlativo regresó al valor anterior."
        QMessageBox.information(self, "Eliminar", mensaje)
        self.load_invoices()

    # ------------------------------------------------------------------
    # Previsualización de facturas
    # ------------------------------------------------------------------
    def show_invoice(self):
        if self.table.currentRow() < 0:
            self.preview_label.setText("Previsualización del PDF")
            self._clear_preview_files()
            return
        data = self._selected_entry()
        if not data:
            self.preview_label.setText("Previsualización del PDF")
            self._clear_preview_files()
            return
        if data.get("row_type") in ("venta", "ticket"):
            self._update_preview(data.get("venta_id"))
        else:
            pdf = data.get("pdf")
            if pdf and os.path.exists(pdf):
                self._show_pdf_preview(pdf)
            else:
                self.preview_label.setText("No hay PDF")
                self._clear_preview_files()

    def _clear_preview_files(self):
        """Remove temporary preview image without deleting stored PDFs."""
        img = getattr(self, "preview_image_file", None)
        if img and os.path.exists(img):
            try:
                os.remove(img)
            except OSError:
                pass
        self.preview_pdf_file = None
        self.preview_image_file = None

    def _is_ticket_sale(self, venta):
        """Return True if the sale should be treated as a ticket."""
        getter_cf = getattr(self.manager.db, "get_venta_credito_fiscal", None)
        if getter_cf:
            try:
                if getter_cf(venta["id"]):
                    return False
            except Exception:
                pass
        cid = venta.get("cliente_id")
        if not cid:
            return True
        cliente = None
        getter = getattr(self.manager.db, "get_cliente", None)
        if getter:
            try:
                cliente = getter(cid)
            except Exception:
                cliente = None
        if not cliente:
            return True
        nit = (cliente.get("nit") or "").strip()
        dui = (cliente.get("dui") or "").strip()
        return not nit and not dui

    def _show_pdf_preview(self, pdf_path):
        self._clear_preview_files()
        prefix = tempfile.mktemp()
        try:
            png_path = prefix + ".png"
            if shutil.which("pdftoppm"):
                subprocess.run([
                    "pdftoppm",
                    "-png",
                    "-singlefile",
                    pdf_path,
                    prefix,
                ], check=True)
            else:
                import fitz

                doc = fitz.open(pdf_path)
                page = doc.load_page(0)
                pix = page.get_pixmap()
                pix.save(png_path)

            self.preview_pdf_file = pdf_path
            self.preview_image_file = png_path
            pixmap = QPixmap(png_path)
            if pixmap.isNull():
                raise RuntimeError("failed to load image")
            scaled = pixmap.scaled(
                600,
                800,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            self.preview_label.setPixmap(scaled)
            self.preview_label.setText("")
        except Exception:
            self.preview_label.setText("No se pudo generar previsualización")
            self._clear_preview_files()

    def _update_preview(self, venta_id):
        venta = next((v for v in self.manager.db.get_ventas() if v["id"] == venta_id), None)
        if not venta:
            self.preview_label.setText("Previsualización del PDF")
            return

        self._clear_preview_files()

        is_ticket = self._is_ticket_sale(venta)
        if is_ticket:
            pdf_path = self.manager.db.get_ticket_pdf(venta_id)
            if not pdf_path or not os.path.exists(pdf_path):
                pdf_path = self._generate_ticket_pdf(venta_id)
        else:
            pdf_path = self.manager.db.get_factura_pdf(venta_id)
            if not pdf_path or not os.path.exists(pdf_path):
                pdf_path = self._generate_invoice_pdf(venta_id)
        if not pdf_path or not os.path.exists(pdf_path):
            self.preview_label.setText("No se pudo generar previsualización")
            return

        self._show_pdf_preview(pdf_path)

    def _generate_invoice_pdf(self, venta_id):
        return generate_invoice_pdf(self.manager, venta_id)

    def _generate_ticket_pdf(self, venta_id):
        """Generate and store the ticket PDF for the given sale."""
        venta = next((v for v in self.manager.db.get_ventas() if v["id"] == venta_id), None)
        if not venta:
            return None

        detalles = self.manager.db.get_detalles_venta(venta_id)
        extra = {}
        raw_extra = venta.get("extra") if venta else None
        if raw_extra:
            try:
                extra = json.loads(raw_extra)
            except Exception:
                extra = {}

        cliente = None
        if venta.get("cliente_id"):
            cliente = next((c for c in self.manager._clientes if c["id"] == venta["cliente_id"]), None)
        cliente_nombre = cliente.get("nombre") if cliente else ""

        filename, json_path = get_document_paths(
            venta.get("fecha"), cliente_nombre, venta_id, "Ticket"
        )

        ticket_json = dte.generar_ticket_json(self.manager.db, venta_id)
        data = dict(extra)
        data["dteJson"] = ticket_json
        generar_ticket_personalizado(venta, detalles, filename, dte_data=data)
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump({"venta": venta, "detalles": detalles}, fh, ensure_ascii=False, indent=2)
        self.manager.db.add_ticket_pdf(venta_id, filename)
        return filename

    def _send_ticket_email(self, venta_id):
        venta = next((v for v in self.manager.db.get_ventas() if v["id"] == venta_id), None)
        if not venta:
            QMessageBox.warning(self, "Enviar ticket", "No se encontró la venta seleccionada.")
            return

        cliente_email = ""
        if venta.get("cliente_id"):
            cli = next((c for c in self.manager._clientes if c["id"] == venta["cliente_id"]), None)
            if cli:
                cliente_email = cli.get("email", "")
        if not cliente_email:
            QMessageBox.warning(self, "Enviar ticket", "El cliente no tiene correo registrado.")
            return

        pdf_path = self.manager.db.get_ticket_pdf(venta_id)
        if not pdf_path or not os.path.exists(pdf_path):
            pdf_path = self._generate_ticket_pdf(venta_id)
        if not pdf_path or not os.path.exists(pdf_path):
            QMessageBox.warning(self, "Enviar ticket", "No se pudo generar el ticket.")
            return
        json_path = os.path.splitext(pdf_path)[0] + ".json"
        if not os.path.exists(json_path):
            pdf_path = self._generate_ticket_pdf(venta_id)
            json_path = os.path.splitext(pdf_path)[0] + ".json"
            if not os.path.exists(json_path):
                QMessageBox.warning(self, "Enviar ticket", "No se encontró el JSON firmado.")
                return

        creds = {}
        if os.path.exists(DATOS_NEGOCIO_PATH):
            try:
                with open(DATOS_NEGOCIO_PATH, "r", encoding="utf-8") as f:
                    creds = json.load(f)
            except Exception:
                creds = {}
        server = creds.get("smtp_server")
        port = creds.get("smtp_port")
        user = creds.get("email_usuario")
        password = os.getenv("INVENTARIO_EMAIL_PASSWORD") or creds.get("email_contrasena")
        if not all([server, port, user, password]):
            QMessageBox.warning(self, "Enviar ticket", "Credenciales SMTP incompletas.")
            return

        subject = "Ticket"
        body = (
            "Adjunto se envía la representación gráfica en PDF y el documento firmado en formato JSON"
        )

        self.btn_enviar.setEnabled(False)
        self.email_thread = EmailSender(
            server,
            port,
            user,
            password,
            cliente_email,
            subject,
            body,
            [pdf_path, json_path],
        )
        self.email_thread.finished.connect(self._on_email_sent)
        self._show_email_loading()
        self.email_thread.start()

