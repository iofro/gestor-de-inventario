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
        self._resp_docs: dict[str, str] = {}
        self._sol_docs: dict[str, str] = {}
        self._negocio_docs: dict[str, str] = {}
        ident = self._factura.get("identificacion") or {}
        tipo_val = ident.get("tipoDte")
        self._original_tipo = str(tipo_val).zfill(2) if tipo_val is not None else None
        self._is_fse = self._original_tipo == "14"
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
        self.resp_label = QLabel("Responsable")
        layout.addWidget(self.resp_label)
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
        self.nom_resp_label = QLabel("Nombre:")
        row.addWidget(self.nom_resp_label)
        self.nom_resp = QLineEdit()
        row.addWidget(self.nom_resp)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.tdoc_resp_label = QLabel("Tipo doc:")
        row.addWidget(self.tdoc_resp_label)
        self.tdoc_resp = QComboBox()
        for code, desc in sorted(TIPO_DOC_REC.items()):
            self.tdoc_resp.addItem(f"{code} - {desc}", str(code))
        row.addWidget(self.tdoc_resp)
        self.ndoc_resp_label = QLabel("Número:")
        row.addWidget(self.ndoc_resp_label)
        self.ndoc_resp = QLineEdit()
        row.addWidget(self.ndoc_resp)
        layout.addLayout(row)

        # Solicitante
        self.sol_label = QLabel("Solicitante")
        layout.addWidget(self.sol_label)
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
        self.nom_sol_label = QLabel("Nombre:")
        row.addWidget(self.nom_sol_label)
        self.nom_sol = QLineEdit()
        row.addWidget(self.nom_sol)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.tdoc_sol_label = QLabel("Tipo doc:")
        row.addWidget(self.tdoc_sol_label)
        self.tdoc_sol = QComboBox()
        for code, desc in sorted(TIPO_DOC_REC.items()):
            self.tdoc_sol.addItem(f"{code} - {desc}", str(code))
        row.addWidget(self.tdoc_sol)
        self.ndoc_sol_label = QLabel("Número:")
        row.addWidget(self.ndoc_sol_label)
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
        self.tdoc_resp.currentIndexChanged.connect(self._on_resp_doc_type_changed)
        self.tdoc_sol.currentIndexChanged.connect(self._on_sol_doc_type_changed)

        def _prefill(
            data: dict | None,
            name_edit: QLineEdit,
            combo: QComboBox,
            doc_edit: QLineEdit,
            doc_store: dict[str, str],
        ):
            if not data:
                return
            name_edit.setText(data.get("nombre", ""))
            dui = data.get("dui")
            nit = data.get("nit")
            tip_doc = data.get("tipDoc")
            num_doc = data.get("numDoc")
            if num_doc:
                doc_edit.setText(str(num_doc))
            else:
                doc = dui or nit or ""
                if doc:
                    doc_edit.setText(doc)
            self._update_doc_store(doc_store, dui=dui, nit=nit)
            doc_type = tip_doc or ("13" if dui else "36" if nit else None)
            if doc_type:
                idx = combo.findData(str(doc_type))
                if idx >= 0:
                    combo.blockSignals(True)
                    combo.setCurrentIndex(idx)
                    combo.blockSignals(False)

        auto_resp = self._build_auto_responsable()
        auto_sol = self._build_auto_solicitante()
        _prefill(auto_resp or responsable, self.nom_resp, self.tdoc_resp, self.ndoc_resp, self._resp_docs)
        _prefill(auto_sol or solicitante, self.nom_sol, self.tdoc_sol, self.ndoc_sol, self._sol_docs)

        if self._is_fse:
            self._configure_fse_ui()
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
        if self._is_fse:
            if tipo not in {"1", "2", "3"}:
                QMessageBox.warning(self, "Anulación", "Seleccione un tipo de anulación")
                return False
            if not (5 <= len(motivo) <= 300):
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
            for name, line in [("Responsable", self.nom_resp)]:
                val = line.text().strip()
                if len(val) < 5 or len(val) > 100:
                    QMessageBox.warning(self, "Anulación", f"Nombre de {name} inválido")
                    return False
            doc_type = self.tdoc_resp.currentData()
            if not doc_type or doc_type not in TIPO_DOC_REC:
                QMessageBox.warning(self, "Anulación", "Tipo de documento de responsable inválido")
                return False
            doc_num = self.ndoc_resp.text().strip()
            if not (3 <= len(doc_num) <= 20):
                QMessageBox.warning(self, "Anulación", "Número de documento de responsable inválido")
                return False
            # No se valida receptor en FSE; se usa el del DTE original.
            for name, line in [("Solicitante", self.nom_sol)]:
                val = line.text().strip()
                if len(val) < 5 or len(val) > 100:
                    QMessageBox.warning(self, "Anulación", f"Nombre de {name} inválido")
                    return False
            doc_type_sol = self.tdoc_sol.currentData()
            if not doc_type_sol or doc_type_sol not in TIPO_DOC_REC:
                QMessageBox.warning(self, "Anulación", "Tipo de documento de solicitante inválido")
                return False
            doc_num_sol = self.ndoc_sol.text().strip()
            if not (3 <= len(doc_num_sol) <= 20):
                QMessageBox.warning(self, "Anulación", "Número de documento de solicitante inválido")
                return False
            return True
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
            if val and (len(val) < 3 or len(val) > 20):
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
            dui = data.get("dui")
            nit = data.get("nit")
            self._update_doc_store(self._resp_docs, dui=dui, nit=nit)
            doc = dui or nit or ""
            self.ndoc_resp.setText(doc)
            doc_type = "13" if dui else "36" if nit else None
            if doc_type:
                idx = self.tdoc_resp.findData(doc_type)
                if idx >= 0:
                    self.tdoc_resp.blockSignals(True)
                    self.tdoc_resp.setCurrentIndex(idx)
                    self.tdoc_resp.blockSignals(False)

    def _usar_datos_negocio(self):
        datos = dte._load_datos_negocio()
        self.nom_resp.setText(datos.get("nombre", ""))
        dui = datos.get("dui")
        nit = datos.get("nit")
        self._update_doc_store(self._negocio_docs, dui=dui, nit=nit)
        self._update_doc_store(self._resp_docs, dui=dui, nit=nit)
        doc = dui or nit or ""
        self.ndoc_resp.setText(doc)
        doc_type = "13" if dui else "36" if nit else None
        if doc_type:
            idx = self.tdoc_resp.findData(doc_type)
            if idx >= 0:
                self.tdoc_resp.blockSignals(True)
                self.tdoc_resp.setCurrentIndex(idx)
                self.tdoc_resp.blockSignals(False)

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
        if self._is_fse:
            try:
                db = self.db or DB()
                vendedores = db.get_vendedores()
                if self.db is None:
                    db.conn.close()
            except Exception:
                vendedores = []
            solo_excluidos = [v for v in vendedores if v.get("is_subject_excluded")]
            if text:
                term = text.lower()
                solo_excluidos = [
                    v
                    for v in solo_excluidos
                    if term in (v.get("nombre") or "").lower()
                    or term in (v.get("codigo") or "").lower()
                    or term in str(v.get("dui") or "").lower()
                    or term in str(v.get("nit") or "").lower()
                ]
            results = []
            for v in solo_excluidos:
                doc = v.get("dui") or v.get("nit") or v.get("codigo") or ""
                results.append(
                    {
                        "nombre": v.get("nombre", ""),
                        "dui": v.get("dui", ""),
                        "nit": v.get("nit", ""),
                        "doc": doc,
                    }
                )
            self._populate_results(
                [
                    {"nombre": r["nombre"], "dui": r["dui"], "nit": r["nit"], "doc": r["doc"]}
                    for r in results
                ]
            )
            return
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
            dui = data.get("dui")
            nit = data.get("nit") or data.get("nrc")
            self._update_doc_store(self._sol_docs, dui=dui, nit=nit)
            doc = dui or nit or ""
            self.ndoc_sol.setText(doc)
            doc_type = "13" if dui else "36" if nit else None
            if doc_type:
                idx = self.tdoc_sol.findData(doc_type)
                if idx >= 0:
                    self.tdoc_sol.blockSignals(True)
                    self.tdoc_sol.setCurrentIndex(idx)
                    self.tdoc_sol.blockSignals(False)

    def _update_doc_store(
        self,
        store: dict[str, str],
        *,
        dui: str | None = None,
        nit: str | None = None,
    ) -> None:
        if dui:
            store["13"] = str(dui)
        else:
            store.pop("13", None)
        if nit:
            store["36"] = str(nit)
        else:
            store.pop("36", None)

    def _on_resp_doc_type_changed(self, index: int) -> None:
        code = self.tdoc_resp.itemData(index)
        if code in {"13", "36"}:
            doc = self._resp_docs.get(code)
            if doc and self.ndoc_resp.text() != doc:
                self.ndoc_resp.blockSignals(True)
                self.ndoc_resp.setText(doc)
                self.ndoc_resp.blockSignals(False)

    def _on_sol_doc_type_changed(self, index: int) -> None:
        code = self.tdoc_sol.itemData(index)
        if code in {"13", "36"}:
            doc = self._sol_docs.get(code)
            if doc and self.ndoc_sol.text() != doc:
                self.ndoc_sol.blockSignals(True)
                self.ndoc_sol.setText(doc)
                self.ndoc_sol.blockSignals(False)

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
        data = {
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
        if self._is_fse:
            return data
        return data

    def _configure_fse_ui(self) -> None:
        """Reduce la UI a los campos permitidos para anulación de FSE."""
        hide_widgets = [
            self.codigo_label,
            self.codigo_edit,
            self.codigo_status,
            self.codigo_hint,
            self.buscar_btn,
            self.emp_search,
            self.emp_results,
        ]
        for widget in hide_widgets:
            widget.setVisible(False)
            widget.setEnabled(False)

    def _build_auto_responsable(self) -> dict | None:
        try:
            datos = anulacion._build_emisor_for_anulacion()
        except Exception:
            return None
        nombre = datos.get("nombre")
        nit = datos.get("nit")
        dui = datos.get("dui")
        tip_doc = "36" if nit else "13" if dui else None
        num_doc = nit or dui
        return {"nombre": nombre, "nit": nit, "dui": dui, "tipDoc": tip_doc, "numDoc": num_doc}

    def _build_auto_solicitante(self) -> dict | None:
        factura = self._factura or {}
        if self._is_fse:
            solicitante = factura.get("sujetoExcluido") or {}
        else:
            solicitante = factura.get("receptor") or {}
        if not isinstance(solicitante, dict):
            return None
        nombre = solicitante.get("nombre") or solicitante.get("nombreComercial")
        tip_doc_raw = solicitante.get("tipoDocumento") or solicitante.get("tipoDocumentoIdentidad")
        tip_doc = str(tip_doc_raw).zfill(2) if tip_doc_raw not in (None, "") else None
        num_doc = solicitante.get("numDocumento") or solicitante.get("nit") or solicitante.get("dui")
        return {
            "nombre": nombre,
            "nit": solicitante.get("nit"),
            "dui": solicitante.get("dui"),
            "tipDoc": tip_doc,
            "numDoc": num_doc,
        }
