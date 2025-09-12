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
from PyQt5.QtCore import QTimer, Qt, QEvent
import dte

DOC_TYPES = [
    ("NIT", "36"),
    ("DUI", "13"),
    ("Carnet de residente", "02"),
    ("Pasaporte", "03"),
    ("Otro", "37"),
]

class AnularFacturaDialog(QDialog):
    """Formulario para capturar datos de anulación."""

    def __init__(self, parent=None, responsable: dict | None = None, solicitante: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle("Anular factura")
        layout = QVBoxLayout(self)

        # Tipo de anulación
        row = QHBoxLayout()
        row.addWidget(QLabel("Tipo de anulación:"))
        self.tipo_cb = QComboBox()
        for text, val in [
            ("1", 1),
            ("2", 2),
            ("3", 3),
        ]:
            self.tipo_cb.addItem(text, val)
        row.addWidget(self.tipo_cb)
        layout.addLayout(row)

        # Motivo
        row = QHBoxLayout()
        row.addWidget(QLabel("Motivo:"))
        self.motivo_edit = QLineEdit()
        row.addWidget(self.motivo_edit)
        layout.addLayout(row)

        # Responsable
        layout.addWidget(QLabel("Responsable"))
        self.emp_search = QLineEdit()
        self.emp_search.setPlaceholderText(
            "Buscar empleado por nombre, DUI o NIT…"
        )
        layout.addWidget(self.emp_search)
        self.emp_results = QListWidget()
        self.emp_results.addItem("Escribe para buscar…")
        self.emp_results.item(0).setFlags(Qt.NoItemFlags)
        layout.addWidget(self.emp_results)

        row = QHBoxLayout()
        row.addWidget(QLabel("Nombre:"))
        self.nom_resp = QLineEdit()
        row.addWidget(self.nom_resp)
        layout.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("Tipo doc:"))
        self.tdoc_resp = QComboBox()
        for text, val in DOC_TYPES:
            self.tdoc_resp.addItem(text, val)
        row.addWidget(self.tdoc_resp)
        row.addWidget(QLabel("Número:"))
        self.ndoc_resp = QLineEdit()
        row.addWidget(self.ndoc_resp)
        layout.addLayout(row)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.negocio_btn = QPushButton("Usar datos del negocio")
        self.negocio_btn.clicked.connect(self._usar_datos_negocio)
        btn_row.addWidget(self.negocio_btn)
        layout.addLayout(btn_row)

        # Solicitante
        layout.addWidget(QLabel("Solicitante"))
        row = QHBoxLayout()
        row.addWidget(QLabel("Nombre:"))
        self.nom_sol = QLineEdit()
        row.addWidget(self.nom_sol)
        layout.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("Tipo doc:"))
        self.tdoc_sol = QComboBox()
        for text, val in DOC_TYPES:
            self.tdoc_sol.addItem(text, val)
        row.addWidget(self.tdoc_sol)
        row.addWidget(QLabel("Número:"))
        self.ndoc_sol = QLineEdit()
        row.addWidget(self.ndoc_sol)
        layout.addLayout(row)

        self.emp_timer = QTimer(self)
        self.emp_timer.setSingleShot(True)
        self.emp_timer.setInterval(250)
        self.emp_search.textChanged.connect(self.emp_timer.start)
        self.emp_timer.timeout.connect(self._buscar_empleado)
        self.emp_results.itemActivated.connect(self._seleccionar_empleado)
        self.emp_results.itemClicked.connect(self._seleccionar_empleado)
        for w in [self.emp_search, self.emp_results]:
            w.installEventFilter(self)

        self._prefill(responsable, self.nom_resp, self.tdoc_resp, self.ndoc_resp)
        self._prefill(solicitante, self.nom_sol, self.tdoc_sol, self.ndoc_sol)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_accept(self):
        if not self._validate():
            return
        self.accept()

    def _prefill(
        self,
        data: dict | None,
        name_edit: QLineEdit,
        combo: QComboBox,
        doc_edit: QLineEdit,
    ) -> None:
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

    def _get_db(self):
        parent = self.parent()
        while parent is not None:
            db = getattr(getattr(parent, "manager", None), "db", None)
            if db:
                return db
            parent = parent.parent()
        return None

    def _populate_results(self, items):
        self.emp_results.clear()
        if not items:
            self.emp_results.addItem("Sin resultados. Puedes escribir manualmente.")
            self.emp_results.item(0).setFlags(Qt.NoItemFlags)
            return
        for emp in items:
            text = f"{emp.get('nombre', '')} - {emp.get('dui') or emp.get('nit') or ''}"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, emp)
            self.emp_results.addItem(item)
        self.emp_results.setCurrentRow(0)

    def _buscar_empleado(self):
        text = self.emp_search.text().strip()
        if not text:
            self.emp_results.clear()
            self.emp_results.addItem("Escribe para buscar…")
            self.emp_results.item(0).setFlags(Qt.NoItemFlags)
            return
        db = self._get_db()
        try:
            empleados = db.get_trabajadores(search=text) if db else []
        except Exception:
            empleados = []
        self._populate_results(empleados)

    def _seleccionar_empleado(self, item):
        data = item.data(Qt.UserRole) if item else None
        if isinstance(data, dict):
            self.nom_resp.setText(data.get("nombre", ""))
            doc = data.get("dui") or data.get("nit") or ""
            if data.get("dui"):
                doc_type = "13"
            elif data.get("nit"):
                doc_type = "36"
            else:
                doc_type = None
            if doc_type:
                idx = self.tdoc_resp.findData(doc_type)
                if idx >= 0:
                    self.tdoc_resp.setCurrentIndex(idx)
            self.ndoc_resp.setText(doc)

    def _usar_datos_negocio(self):
        negocio = dte._load_datos_negocio()
        self._prefill(negocio, self.nom_resp, self.tdoc_resp, self.ndoc_resp)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.KeyPress:
            if obj is self.emp_search and event.key() in (Qt.Key_Down, Qt.Key_Up):
                if self.emp_results.count():
                    self.emp_results.setFocus()
                    self.emp_results.setCurrentRow(0)
                    return True
            if obj is self.emp_results and event.key() in (
                Qt.Key_Return,
                Qt.Key_Enter,
            ):
                current = self.emp_results.currentItem()
                if current:
                    self.emp_results.itemActivated.emit(current)
                    return True
        return super().eventFilter(obj, event)

    def _validate(self) -> bool:
        motivo = self.motivo_edit.text().strip()
        if len(motivo) < 5 or len(motivo) > 250:
            QMessageBox.warning(self, "Anulación", "Motivo inválido")
            return False
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

    def get_data(self) -> dict:
        return {
            "tipoAnulacion": self.tipo_cb.currentData(),
            "motivoAnulacion": self.motivo_edit.text().strip(),
            "nombreResponsable": self.nom_resp.text().strip(),
            "tipDocResponsable": self.tdoc_resp.currentData(),
            "numDocResponsable": self.ndoc_resp.text().strip(),
            "nombreSolicita": self.nom_sol.text().strip(),
            "tipDocSolicita": self.tdoc_sol.currentData(),
            "numDocSolicita": self.ndoc_sol.text().strip(),
        }
