from PyQt5.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QComboBox,
    QLineEdit,
    QDialogButtonBox,
    QMessageBox,
    QPushButton,
)
from dialogs import ClienteSelectorDialog

DOC_TYPES = [
    ("NIT", "36"),
    ("DUI", "13"),
    ("Carnet de residente", "02"),
    ("Pasaporte", "03"),
    ("Otro", "37"),
]

class AnularFacturaDialog(QDialog):
    """Formulario para capturar datos de anulación."""

    def __init__(
        self,
        parent=None,
        responsable: dict | None = None,
        solicitante: dict | None = None,
        db=None,
    ):
        super().__init__(parent)
        self.db = db
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

        # Solicitante
        layout.addWidget(QLabel("Solicitante"))
        row = QHBoxLayout()
        row.addWidget(QLabel("Nombre:"))
        self.nom_sol = QLineEdit()
        row.addWidget(self.nom_sol)
        self.sel_sol_btn = QPushButton("Seleccionar")
        self.sel_sol_btn.clicked.connect(self._select_solicitante)
        row.addWidget(self.sel_sol_btn)
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

        self._prefill(responsable, self.nom_resp, self.tdoc_resp, self.ndoc_resp, prefer_nit=True)
        self._prefill(solicitante, self.nom_sol, self.tdoc_sol, self.ndoc_sol)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _prefill(
        self,
        data: dict | None,
        name_edit: QLineEdit,
        combo: QComboBox,
        doc_edit: QLineEdit,
        *,
        prefer_nit: bool = False,
    ) -> None:
        if not data:
            return
        name_edit.setText(data.get("nombre", ""))
        doc = None
        doc_type = None
        if prefer_nit and data.get("nit"):
            doc = data.get("nit")
            doc_type = "36"
        elif data.get("dui"):
            doc = data.get("dui")
            doc_type = "13"
        elif data.get("nit"):
            doc = data.get("nit")
            doc_type = "36"
        if doc_type is not None:
            idx = combo.findData(doc_type)
            if idx >= 0:
                combo.setCurrentIndex(idx)
        if doc:
            doc_edit.setText(doc)

    def _select_solicitante(self) -> None:
        if not self.db:
            QMessageBox.warning(self, "Anulación", "Base de datos no disponible")
            return
        dlg = ClienteSelectorDialog(self.db, self)
        if dlg.exec_() != QDialog.Accepted:
            return
        cli = dlg.get_selected_cliente()
        if not cli:
            return
        self._prefill(cli, self.nom_sol, self.tdoc_sol, self.ndoc_sol)

    def _on_accept(self):
        if not self._validate():
            return
        self.accept()

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
