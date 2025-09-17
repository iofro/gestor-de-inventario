from PyQt5.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QComboBox,
    QLineEdit,
    QDialogButtonBox,
    QMessageBox,
    QListWidget,
    QListWidgetItem,
    QPushButton,
)
from PyQt5.QtCore import Qt, QTimer, QEvent
import dte
import anulacion
from db import DB
from utils.catalogos import TIPO_INVALIDACION, TIPO_DOC_REC
from .seleccionar_dte_dialog import SeleccionarDteDialog

class AnularFacturaDialog(QDialog):
    """Formulario para capturar datos de anulación."""

    def __init__(
        self,
        parent=None,
        responsable: dict | None = None,
        solicitante: dict | None = None,
        db: DB | None = None,
        factura: dict | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Anular factura")
        self.db = db
        self._factura = factura or {}
        ident = self._factura.get("identificacion") or {}
        tipo_val = ident.get("tipoDte")
        self._original_tipo = str(tipo_val).zfill(2) if tipo_val is not None else None
        codigo_val = ident.get("codigoGeneracion")
        self._original_uuid = str(codigo_val or "").strip().upper() or None
        self._original_ambiente = anulacion.normalize_ambiente(ident.get("ambiente"))
        fecha_val = ident.get("fecEmi") or ident.get("fechaEmision") or ident.get("fecha")
        self._original_fecha = str(fecha_val)[:10] if fecha_val else None
        self._receptor_docs: set[str] = set()
        receptor_data = (factura or {}).get("receptor") or {}
        for key in ("numDocumento", "nit", "dui"):
            val = receptor_data.get(key)
            if val:
                self._receptor_docs.add(str(val))
        self._emisor_doc = None
        emisor_data = (factura or {}).get("emisor") or {}
        for key in ("nit", "numDocumento", "nrc", "dui"):
            val = emisor_data.get(key)
            if val:
                self._emisor_doc = str(val)
                break
        if solicitante:
            for key in ("numDoc", "numDocumento", "nit", "dui"):
                val = solicitante.get(key)
                if val:
                    self._receptor_docs.add(str(val))
        layout = QVBoxLayout(self)

        # Tipo de anulación
        row = QHBoxLayout()
        row.addWidget(QLabel("Tipo de anulación:"))
        self.tipo_cb = QComboBox()
        for code, desc in sorted(TIPO_INVALIDACION.items()):
            self.tipo_cb.addItem(f"{code} - {desc}", str(code))
        row.addWidget(self.tipo_cb)
        layout.addLayout(row)

        # Motivo
        row = QHBoxLayout()
        row.addWidget(QLabel("Motivo:"))
        self.motivo_edit = QLineEdit()
        row.addWidget(self.motivo_edit)
        layout.addLayout(row)

        row = QHBoxLayout()
        self.codigo_label = QLabel("Documento que reemplaza:")
        row.addWidget(self.codigo_label)
        self.codigo_edit = QLineEdit()
        self.codigo_edit.setReadOnly(True)
        self.codigo_edit.setPlaceholderText("Selecciona con el botón…")
        row.addWidget(self.codigo_edit)
        self.codigo_status = QLabel("")
        self.codigo_status.setFixedWidth(18)
        self.codigo_status.setAlignment(Qt.AlignCenter)
        row.addWidget(self.codigo_status)
        self.buscar_btn = QPushButton("Buscar…")
        row.addWidget(self.buscar_btn)
        layout.addLayout(row)
        self.codigo_hint = QLabel(
            "Para tipo 1/3, selecciona el DTE corregido (mismo tipo) recepcionado por MH. "
            "En tipo 2 deja vacío."
        )
        self.codigo_hint.setWordWrap(True)
        self.codigo_hint.setStyleSheet("color: #555555; font-size: 11px;")
        layout.addWidget(self.codigo_hint)

        # Responsable
        layout.addWidget(QLabel("Responsable"))
        self.emp_search = QLineEdit()
        self.emp_search.setPlaceholderText(
            "Buscar trabajador por nombre, DUI o NIT"
        )
        layout.addWidget(self.emp_search)
        self.emp_results = QListWidget()
        self.emp_results.addItem("Escribe para buscar…")
        self.emp_results.item(0).setFlags(Qt.NoItemFlags)
        layout.addWidget(self.emp_results)
        self.negocio_btn = QPushButton("Usar datos del negocio")
        layout.addWidget(self.negocio_btn)
        row = QHBoxLayout()
        row.addWidget(QLabel("Nombre:"))
        self.nom_resp = QLineEdit()
        row.addWidget(self.nom_resp)
        layout.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("Tipo doc:"))
        self.tdoc_resp = QComboBox()
        for code, desc in sorted(TIPO_DOC_REC.items()):
            self.tdoc_resp.addItem(f"{code} - {desc}", str(code))
        row.addWidget(self.tdoc_resp)
        row.addWidget(QLabel("Número:"))
        self.ndoc_resp = QLineEdit()
        row.addWidget(self.ndoc_resp)
        layout.addLayout(row)

        # Solicitante
        layout.addWidget(QLabel("Solicitante"))
        self.cli_search = QLineEdit()
        self.cli_search.setPlaceholderText(
            "Buscar cliente por nombre, DUI o NIT"
        )
        layout.addWidget(self.cli_search)
        self.cli_results = QListWidget()
        self.cli_results.addItem("Escribe para buscar…")
        self.cli_results.item(0).setFlags(Qt.NoItemFlags)
        layout.addWidget(self.cli_results)
        row = QHBoxLayout()
        row.addWidget(QLabel("Nombre:"))
        self.nom_sol = QLineEdit()
        row.addWidget(self.nom_sol)
        layout.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("Tipo doc:"))
        self.tdoc_sol = QComboBox()
        for code, desc in sorted(TIPO_DOC_REC.items()):
            self.tdoc_sol.addItem(f"{code} - {desc}", str(code))
        row.addWidget(self.tdoc_sol)
        row.addWidget(QLabel("Número:"))
        self.ndoc_sol = QLineEdit()
        row.addWidget(self.ndoc_sol)
        layout.addLayout(row)

        # Timer and search connections
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

        self.negocio_btn.clicked.connect(self._usar_datos_negocio)
        self.tipo_cb.currentIndexChanged.connect(self._on_tipo_changed)
        self.codigo_edit.textChanged.connect(self._update_codigo_status)
        self.codigo_edit.editingFinished.connect(self._normalize_codigo)
        self.buscar_btn.clicked.connect(self._abrir_selector)
        self.buscar_btn.setEnabled(self.db is not None)

        def _prefill(data: dict | None, name_edit: QLineEdit, combo: QComboBox, doc_edit: QLineEdit):
            if not data:
                return
            name_edit.setText(data.get("nombre", ""))
            doc = data.get("dui")
            doc_type = "13" if doc else None
            if not doc:
                doc = data.get("nit")
                doc_type = "36" if doc else doc_type
            if doc_type:
                idx = combo.findData(doc_type)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
            if doc:
                doc_edit.setText(doc)

        _prefill(responsable, self.nom_resp, self.tdoc_resp, self.ndoc_resp)
        _prefill(solicitante, self.nom_sol, self.tdoc_sol, self.ndoc_sol)

        self._on_tipo_changed(self.tipo_cb.currentIndex())

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_accept(self):
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

        codigo = self.codigo_edit.text().strip()
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
            if self.codigo_edit.text() != codigo_upper:
                self.codigo_edit.setText(codigo_upper)

        for name, line in [
            ("Responsable", self.nom_resp),
            ("Solicitante", self.nom_sol),
        ]:
            val = line.text().strip()
            if len(val) < 5 or len(val) > 100:
                QMessageBox.warning(self, "Anulación", f"Nombre de {name} inválido")
                return False
        for name, line in [
            ("Documento responsable", self.ndoc_resp),
            ("Documento solicitante", self.ndoc_sol),
        ]:
            val = line.text().strip()
            if len(val) < 3 or len(val) > 20:
                QMessageBox.warning(self, "Anulación", f"Número de {name} inválido")
                return False
        return True

    def _on_tipo_changed(self, index: int):
        tipo = self.tipo_cb.itemData(index)
        requiere = tipo in {"1", "3"}
        self.codigo_label.setVisible(requiere)
        self.codigo_edit.setVisible(requiere)
        self.codigo_status.setVisible(requiere)
        self.codigo_hint.setVisible(requiere)
        self.buscar_btn.setVisible(requiere)
        self.buscar_btn.setEnabled(requiere and self.db is not None)
        if not requiere:
            self.codigo_edit.clear()
        self._update_codigo_status()

    def _normalize_codigo(self):
        codigo = self.codigo_edit.text().strip().upper()
        if codigo and self.codigo_edit.text() != codigo:
            self.codigo_edit.blockSignals(True)
            self.codigo_edit.setText(codigo)
            self.codigo_edit.blockSignals(False)
        self._update_codigo_status()

    def _update_codigo_status(self):
        if not self.codigo_edit.isVisible():
            self.codigo_status.clear()
            return
        codigo = self.codigo_edit.text().strip().upper()
        if not codigo:
            self.codigo_status.setText("")
            self.codigo_status.setStyleSheet("")
            return
        if self._original_uuid and codigo == self._original_uuid:
            self.codigo_status.setText("!")
            self.codigo_status.setStyleSheet("color: #d93025; font-weight: bold;")
            return
        if anulacion.UUID36_RE.fullmatch(codigo):
            self.codigo_status.setText("✓")
            self.codigo_status.setStyleSheet("color: #1e8e3e; font-weight: bold;")
        else:
            self.codigo_status.setText("•")
            self.codigo_status.setStyleSheet("color: #999999; font-weight: bold;")

    def _abrir_selector(self):
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
            self.codigo_edit.setText(dlg.selected_uuid.upper())
            self._update_codigo_status()

    # --- Empleado search helpers -----------------------------------------------

    def _populate_emp_results(self, items):
        self.emp_results.clear()
        if not items:
            self.emp_results.addItem("Sin resultados. Puedes escribir manualmente.")
            self.emp_results.item(0).setFlags(Qt.NoItemFlags)
            return
        for e in items:
            doc = e.get("dui") or e.get("nit") or ""
            item = QListWidgetItem(f"{e.get('nombre', '')} - {doc}")
            item.setData(Qt.UserRole, e)
            self.emp_results.addItem(item)
        self.emp_results.setCurrentRow(0)

    def _buscar_empleado(self):
        text = self.emp_search.text().strip()
        if not text:
            self.emp_results.clear()
            self.emp_results.addItem("Escribe para buscar…")
            self.emp_results.item(0).setFlags(Qt.NoItemFlags)
            return
        try:
            db = self.db or DB()
            empleados = db.get_trabajadores(search=text)
            if self.db is None:
                db.conn.close()
        except Exception:
            empleados = []
        self._populate_emp_results(empleados)

    def _seleccionar_empleado(self, item):
        data = item.data(Qt.UserRole) if item else None
        if isinstance(data, dict):
            self.nom_resp.setText(data.get("nombre", ""))
            doc = data.get("dui") or data.get("nit") or ""
            self.ndoc_resp.setText(doc)
            doc_type = "13" if data.get("dui") else "36" if data.get("nit") else None
            if doc_type:
                idx = self.tdoc_resp.findData(doc_type)
                if idx >= 0:
                    self.tdoc_resp.setCurrentIndex(idx)

    def _usar_datos_negocio(self):
        datos = dte._load_datos_negocio()
        self.nom_resp.setText(datos.get("nombre", ""))
        doc = datos.get("dui") or datos.get("nit") or ""
        self.ndoc_resp.setText(doc)
        doc_type = "13" if datos.get("dui") else "36" if datos.get("nit") else None
        if doc_type:
            idx = self.tdoc_resp.findData(doc_type)
            if idx >= 0:
                self.tdoc_resp.setCurrentIndex(idx)

    # --- Cliente search helpers -------------------------------------------------

    def _populate_results(self, items):
        self.cli_results.clear()
        if not items:
            self.cli_results.addItem("Sin resultados. Puedes escribir manualmente.")
            self.cli_results.item(0).setFlags(Qt.NoItemFlags)
            return
        for c in items:
            doc = c.get("dui") or c.get("nit") or c.get("nrc") or ""
            item = QListWidgetItem(f"{c.get('nombre', '')} - {doc}")
            item.setData(Qt.UserRole, c)
            self.cli_results.addItem(item)
        self.cli_results.setCurrentRow(0)

    def _buscar_cliente(self):
        text = self.cli_search.text().strip()
        if not text:
            self.cli_results.clear()
            self.cli_results.addItem("Escribe para buscar…")
            self.cli_results.item(0).setFlags(Qt.NoItemFlags)
            return
        try:
            db = self.db or DB()
            clientes = db.get_clientes(search=text)
            if self.db is None:
                db.conn.close()
        except Exception:
            clientes = []
        self._populate_results(clientes)

    def _seleccionar_cliente(self, item):
        data = item.data(Qt.UserRole) if item else None
        if isinstance(data, dict):
            self.nom_sol.setText(data.get("nombre", ""))
            doc = data.get("dui") or data.get("nit") or data.get("nrc") or ""
            self.ndoc_sol.setText(doc)
            doc_type = "13" if data.get("dui") else "36" if data.get("nit") or data.get("nrc") else None
            if doc_type:
                idx = self.tdoc_sol.findData(doc_type)
                if idx >= 0:
                    self.tdoc_sol.setCurrentIndex(idx)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.KeyPress:
            if obj is self.emp_search and event.key() in (Qt.Key_Down, Qt.Key_Up):
                if self.emp_results.count():
                    self.emp_results.setFocus()
                    self.emp_results.setCurrentRow(0)
                    return True
            if obj is self.emp_results and event.key() in (Qt.Key_Return, Qt.Key_Enter):
                current = self.emp_results.currentItem()
                if current:
                    self.emp_results.itemActivated.emit(current)
                    return True
            if obj is self.cli_search and event.key() in (Qt.Key_Down, Qt.Key_Up):
                if self.cli_results.count():
                    self.cli_results.setFocus()
                    self.cli_results.setCurrentRow(0)
                    return True
            if obj is self.cli_results and event.key() in (Qt.Key_Return, Qt.Key_Enter):
                current = self.cli_results.currentItem()
                if current:
                    self.cli_results.itemActivated.emit(current)
                    return True
        return super().eventFilter(obj, event)

    def get_data(self) -> dict:
        tipo = self.tipo_cb.currentData()
        codigo = self.codigo_edit.text().strip().upper()
        if tipo not in {"1", "3"}:
            codigo = None
        return {
            "tipoAnulacion": self.tipo_cb.currentData(),
            "motivoAnulacion": self.motivo_edit.text().strip(),
            "nombreResponsable": self.nom_resp.text().strip(),
            "tipDocResponsable": self.tdoc_resp.currentData(),
            "numDocResponsable": self.ndoc_resp.text().strip(),
            "nombreSolicita": self.nom_sol.text().strip(),
            "tipDocSolicita": self.tdoc_sol.currentData(),
            "numDocSolicita": self.ndoc_sol.text().strip(),
            "codigoGeneracionR": codigo if codigo else None,
        }
