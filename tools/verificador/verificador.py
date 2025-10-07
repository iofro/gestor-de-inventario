"""Aplicación administrativa de verificación de licencias.

Esta primera fase ofrece una interfaz PyQt5 con el backend de carpetas
compartidas como fuente de verdad para las licencias firmadas.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional

from PyQt5.QtCore import (
    QAbstractTableModel,
    QDateTime,
    QModelIndex,
    Qt,
    QSortFilterProxyModel,
    QVariant,
    pyqtSignal,
)
from PyQt5.QtWidgets import (
    QAction,
    QApplication,
    QComboBox,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QDockWidget,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStatusBar,
    QTableView,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from license_backend import AdminConfig, HttpBackend, LicenseRecord, ShareBackend

APP_ROOT = Path(__file__).resolve().parent
CONFIG_PATH = APP_ROOT / "admin_config.json"
LICENSE_STATUSES = ["ACTIVE", "BLOCKED", "EXPIRED", "TRIAL", "GRACE"]


class LicenseTableModel(QAbstractTableModel):
    headers = ["Alias", "Device ID", "Estado", "Expira", "Última sync", "Notas"]

    def __init__(self, records: Optional[List[LicenseRecord]] = None, parent=None) -> None:
        super().__init__(parent)
        self._records: List[LicenseRecord] = records or []

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # type: ignore[override]
        return 0 if parent.isValid() else len(self._records)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # type: ignore[override]
        return 0 if parent.isValid() else len(self.headers)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):  # type: ignore[override]
        if not index.isValid() or not (0 <= index.row() < len(self._records)):
            return QVariant()

        record = self._records[index.row()]

        if role in (Qt.DisplayRole, Qt.EditRole):
            column = index.column()
            if column == 0:
                return record.alias
            if column == 1:
                return record.device_id
            if column == 2:
                return record.status
            if column == 3:
                return record.expires_at or "—"
            if column == 4:
                return record.last_sync or "—"
            if column == 5:
                return record.notes

        if role == Qt.TextAlignmentRole:
            if index.column() in (2, 3, 4):
                return Qt.AlignCenter

        return QVariant()

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):  # type: ignore[override]
        if role != Qt.DisplayRole:
            return QVariant()
        if orientation == Qt.Horizontal and 0 <= section < len(self.headers):
            return self.headers[section]
        return section + 1

    def update_records(self, records: List[LicenseRecord]) -> None:
        self.beginResetModel()
        self._records = records
        self.endResetModel()

    def record_at(self, row: int) -> Optional[LicenseRecord]:
        if 0 <= row < len(self._records):
            return self._records[row]
        return None


class LicenseFilterProxy(QSortFilterProxyModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._filter_text = ""
        self.setFilterCaseSensitivity(Qt.CaseInsensitive)

    def setFilterText(self, text: str) -> None:
        self._filter_text = text.strip().lower()
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:  # type: ignore[override]
        if not self._filter_text:
            return True
        model = self.sourceModel()
        if model is None:
            return True
        record = model.record_at(source_row)  # type: ignore[assignment]
        if record is None:
            return True
        haystack = f"{record.alias} {record.device_id}".lower()
        return self._filter_text in haystack


class DateDialog(QDialog):
    def __init__(self, title: str, label: str, parent=None, *, allow_clear: bool = True) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self._cleared = False
        self.date_edit = QDateTimeEdit(self)
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDateTime(QDateTime.currentDateTime())

        form = QFormLayout()
        form.addRow(label, self.date_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        if allow_clear:
            clear_btn = buttons.addButton("Sin fecha", QDialogButtonBox.ActionRole)
            clear_btn.clicked.connect(self._clear)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _clear(self) -> None:
        self._cleared = True
        self.accept()

    def selected_iso(self) -> Optional[str]:
        if self.result() != QDialog.Accepted:
            return None
        if self._cleared:
            return None
        dt = self.date_edit.dateTime().toPyDateTime()
        return dt.isoformat()


class NotesDialog(QDialog):
    def __init__(self, notes: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Editar notas")
        self.text = QTextEdit(self)
        self.text.setPlainText(notes)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.text)
        layout.addWidget(buttons)

    def value(self) -> str:
        return self.text.toPlainText().strip()


class NewLicenseDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Nuevo sistema")
        self.alias_edit = QLineEdit(self)
        self.device_edit = QLineEdit(self)
        self.status_combo = QComboBox(self)
        self.status_combo.addItems(LICENSE_STATUSES)
        self.status_combo.setCurrentText("ACTIVE")

        form = QFormLayout()
        form.addRow("Alias", self.alias_edit)
        form.addRow("Device ID", self.device_edit)
        form.addRow("Estado inicial", self.status_combo)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        self.buttons.accepted.connect(self._accept)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.buttons)

    def _accept(self) -> None:
        if not self.alias_edit.text().strip():
            QMessageBox.warning(self, "Dato requerido", "Debe ingresar un alias.")
            return
        if not self.device_edit.text().strip():
            QMessageBox.warning(self, "Dato requerido", "Debe ingresar el Device ID.")
            return
        self.accept()

    @property
    def alias(self) -> str:
        return self.alias_edit.text().strip()

    @property
    def device_id(self) -> str:
        return self.device_edit.text().strip()

    @property
    def status(self) -> str:
        return self.status_combo.currentText()


class ConfigDialog(QDialog):
    def __init__(self, config: AdminConfig, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Configuración del verificador")
        self._config = config

        self.mode_combo = QComboBox(self)
        self.mode_combo.addItem("Carpeta compartida", "share")
        self.mode_combo.addItem("HTTP local", "http")
        idx = max(0, self.mode_combo.findData(config.mode))
        self.mode_combo.setCurrentIndex(idx)

        self.share_edit = QLineEdit(config.share_path, self)
        self.licenses_edit = QLineEdit(config.licenses_path, self)
        self.requests_edit = QLineEdit(config.requests_path, self)
        self.pub_key_edit = QLineEdit(config.public_key_path, self)
        self.priv_key_edit = QLineEdit(config.private_key_path, self)

        form = QFormLayout()
        form.addRow("Modo", self.mode_combo)
        form.addRow("Ruta compartida", self.share_edit)
        form.addRow("Licencias", self.licenses_edit)
        form.addRow("Solicitudes", self.requests_edit)
        form.addRow("Clave pública", self.pub_key_edit)
        form.addRow("Clave privada", self.priv_key_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def updated_config(self) -> AdminConfig:
        config = AdminConfig(
            mode=self.mode_combo.currentData(),
            share_path=self.share_edit.text().strip() or self._config.share_path,
            licenses_path=self.licenses_edit.text().strip() or self._config.licenses_path,
            requests_path=self.requests_edit.text().strip() or self._config.requests_path,
            public_key_path=self.pub_key_edit.text().strip() or self._config.public_key_path,
            private_key_path=self.priv_key_edit.text().strip() or self._config.private_key_path,
        )
        return config


class DetailPanel(QWidget):
    activateRequested = pyqtSignal()
    blockRequested = pyqtSignal()
    graceRequested = pyqtSignal()
    expirationRequested = pyqtSignal()
    notesRequested = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._record: Optional[LicenseRecord] = None

        self.alias_label = QLabel("—")
        self.device_label = QLabel("—")
        self.status_label = QLabel("—")
        self.expires_label = QLabel("—")
        self.grace_label = QLabel("—")
        self.issued_label = QLabel("—")
        self.signature_label = QLabel("—")
        self.notes_preview = QLabel("—")
        self.notes_preview.setWordWrap(True)

        form = QFormLayout()
        form.addRow("Alias", self.alias_label)
        form.addRow("Device ID", self.device_label)
        form.addRow("Estado", self.status_label)
        form.addRow("Expira", self.expires_label)
        form.addRow("Grace hasta", self.grace_label)
        form.addRow("Emitida", self.issued_label)
        form.addRow("Firma", self.signature_label)
        form.addRow("Notas", self.notes_preview)

        self.activate_btn = QPushButton("Activar")
        self.block_btn = QPushButton("Bloquear")
        self.grace_btn = QPushButton("Poner en GRACE...")
        self.expire_btn = QPushButton("Establecer expiración...")
        self.notes_btn = QPushButton("Editar notas...")

        self.activate_btn.clicked.connect(self.activateRequested.emit)
        self.block_btn.clicked.connect(self.blockRequested.emit)
        self.grace_btn.clicked.connect(self.graceRequested.emit)
        self.expire_btn.clicked.connect(self.expirationRequested.emit)
        self.notes_btn.clicked.connect(self.notesRequested.emit)

        actions_layout = QVBoxLayout()
        actions_layout.addWidget(self.activate_btn)
        actions_layout.addWidget(self.block_btn)
        actions_layout.addWidget(self.grace_btn)
        actions_layout.addWidget(self.expire_btn)
        actions_layout.addWidget(self.notes_btn)
        actions_layout.addStretch(1)

        wrapper = QVBoxLayout(self)
        wrapper.addLayout(form)
        wrapper.addSpacing(12)
        wrapper.addLayout(actions_layout)
        wrapper.addStretch(1)

    def set_record(self, record: Optional[LicenseRecord]) -> None:
        self._record = record
        if record is None:
            self.alias_label.setText("—")
            self.device_label.setText("—")
            self.status_label.setText("—")
            self.expires_label.setText("—")
            self.grace_label.setText("—")
            self.issued_label.setText("—")
            self.signature_label.setText("—")
            self.notes_preview.setText("—")
            for btn in (self.activate_btn, self.block_btn, self.grace_btn, self.expire_btn, self.notes_btn):
                btn.setEnabled(False)
            return

        self.alias_label.setText(record.alias or "—")
        self.device_label.setText(record.device_id)
        self.status_label.setText(record.status)
        self.expires_label.setText(record.expires_at or "—")
        self.grace_label.setText(record.grace_until or "—")
        self.issued_label.setText(record.issued_at or "—")
        self.signature_label.setText(record.signature or "—")
        self.notes_preview.setText(record.notes or "—")
        for btn in (self.activate_btn, self.block_btn, self.grace_btn, self.expire_btn, self.notes_btn):
            btn.setEnabled(True)


class VerifierMainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Verificador de licencias Vertex")
        self.resize(1100, 700)

        self.backend = ShareBackend(CONFIG_PATH)
        self.records: List[LicenseRecord] = []
        self._current_record: Optional[LicenseRecord] = None

        self._setup_ui()
        self._load_mode_from_config()
        self.refresh()

    # --- UI ---
    def _setup_ui(self) -> None:
        toolbar = QToolBar("Acciones", self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        refresh_action = QAction("Actualizar", self)
        refresh_action.triggered.connect(self.refresh)
        toolbar.addAction(refresh_action)

        new_action = QAction("Nuevo sistema...", self)
        new_action.triggered.connect(self.create_new_license)
        toolbar.addAction(new_action)

        config_action = QAction("Configuración...", self)
        config_action.triggered.connect(self.edit_config)
        toolbar.addAction(config_action)

        gen_keys_action = QAction("Generar claves...", self)
        gen_keys_action.triggered.connect(self.generate_keys)
        toolbar.addAction(gen_keys_action)

        toolbar.addSeparator()

        toolbar.addWidget(QLabel("Buscar:"))
        self.search_edit = QLineEdit(self)
        self.search_edit.setPlaceholderText("Alias o Device ID")
        toolbar.addWidget(self.search_edit)

        toolbar.addSeparator()
        toolbar.addWidget(QLabel("Modo:"))
        self.mode_combo = QComboBox(self)
        self.mode_combo.addItem("Carpeta compartida", "share")
        self.mode_combo.addItem("HTTP local", "http")
        self.mode_combo.currentIndexChanged.connect(self._mode_changed)
        toolbar.addWidget(self.mode_combo)

        self.table_model = LicenseTableModel([])
        self.proxy_model = LicenseFilterProxy(self)
        self.proxy_model.setSourceModel(self.table_model)

        self.table = QTableView(self)
        self.table.setModel(self.proxy_model)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setSelectionMode(QTableView.SingleSelection)
        self.table.doubleClicked.connect(self._row_double_clicked)
        selection_model = self.table.selectionModel()
        if selection_model is not None:
            selection_model.selectionChanged.connect(self._selection_changed)
        self.setCentralWidget(self.table)

        self.detail_panel = DetailPanel(self)
        self.detail_panel.activateRequested.connect(lambda: self._update_status("ACTIVE"))
        self.detail_panel.blockRequested.connect(lambda: self._update_status("BLOCKED"))
        self.detail_panel.graceRequested.connect(self._set_grace)
        self.detail_panel.expirationRequested.connect(self._set_expiration)
        self.detail_panel.notesRequested.connect(self._edit_notes)

        dock = QDockWidget("Detalles", self)
        dock.setWidget(self.detail_panel)
        dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)

        status = QStatusBar(self)
        self.setStatusBar(status)

        self.search_edit.textChanged.connect(self.proxy_model.setFilterText)

    # --- Configuración ---
    def _load_mode_from_config(self) -> None:
        mode = self.backend.config.mode
        idx = self.mode_combo.findData(mode)
        if idx >= 0:
            self.mode_combo.setCurrentIndex(idx)
        else:
            self.mode_combo.setCurrentIndex(0)

    def _mode_changed(self) -> None:
        mode = self.mode_combo.currentData()
        config = self.backend.config
        if config.mode != mode:
            config.mode = mode
            self.backend.save_config(config)
        self._reload_backend()
        self.refresh()

    def _reload_backend(self) -> None:
        try:
            config = AdminConfig.from_path(CONFIG_PATH)
        except Exception as exc:  # pragma: no cover - defensivo
            QMessageBox.critical(self, "Error", f"No se pudo cargar la configuración: {exc}")
            return

        if config.mode == "share":
            self.backend = ShareBackend(CONFIG_PATH)
        else:
            self.backend = HttpBackend(CONFIG_PATH)
        self._update_status_bar()

    def edit_config(self) -> None:
        dialog = ConfigDialog(self.backend.config, self)
        if dialog.exec_() != QDialog.Accepted:
            return

        config = dialog.updated_config()
        try:
            self.backend.save_config(config)
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"No se pudo guardar la configuración: {exc}")
            return

        self._reload_backend()
        idx = self.mode_combo.findData(config.mode)
        if idx >= 0:
            self.mode_combo.setCurrentIndex(idx)
        self.refresh()

    # --- Operaciones ---
    def refresh(self) -> None:
        try:
            if isinstance(self.backend, ShareBackend):
                self.records = self.backend.list_licenses()
            else:
                raise NotImplementedError
        except NotImplementedError:
            self.records = []
            QMessageBox.information(
                self,
                "Modo no disponible",
                "El backend HTTP aún no está implementado.",
            )
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"No se pudo cargar la información: {exc}")
            self.records = []
        finally:
            self.table_model.update_records(self.records)
            self.detail_panel.set_record(None)
            self._current_record = None
            self._update_status_bar()

    def _update_status_bar(self, message: str = "") -> None:
        if isinstance(self.backend, ShareBackend):
            path = self.backend.config.licenses_path
            text = f"Carpeta compartida: {path}"
        else:
            text = "HTTP local (pendiente de implementación)"
        if message:
            text = f"{text} | {message}"
        self.statusBar().showMessage(text)

    def _row_double_clicked(self, index: QModelIndex) -> None:
        self._selection_changed()

    def _selection_changed(self) -> None:
        selection = self.table.selectionModel().selectedRows()
        if not selection:
            self.detail_panel.set_record(None)
            self._current_record = None
            return
        proxy_index = selection[0]
        source_index = self.proxy_model.mapToSource(proxy_index)
        record = self.table_model.record_at(source_index.row())
        self._current_record = record
        self.detail_panel.set_record(record)

    def create_new_license(self) -> None:
        dialog = NewLicenseDialog(self)
        if dialog.exec_() != QDialog.Accepted:
            return

        if not isinstance(self.backend, ShareBackend):
            QMessageBox.warning(self, "Modo no disponible", "Solo puede crear licencias en modo carpeta compartida.")
            return

        try:
            record = self.backend.create_license(
                alias=dialog.alias,
                device_id=dialog.device_id,
                status=dialog.status,
            )
            self._update_status_bar(f"Licencia emitida para {record.device_id}")
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"No se pudo crear la licencia: {exc}")
        finally:
            self.refresh()

    def generate_keys(self) -> None:
        if not isinstance(self.backend, ShareBackend):
            QMessageBox.warning(self, "Modo no disponible", "La generación de claves solo está disponible en modo carpeta compartida.")
            return
        try:
            self.backend.generate_keys()
            self._update_status_bar("Claves generadas correctamente")
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"No se pudieron generar las claves: {exc}")

    def _update_status(self, status: str) -> None:
        if not isinstance(self.backend, ShareBackend):
            QMessageBox.warning(self, "Modo no disponible", "El backend actual no permite modificar licencias.")
            return
        if not self._current_record:
            return
        try:
            self.backend.update_status(self._current_record, status)
            self._update_status_bar(f"Estado actualizado a {status}")
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"No se pudo actualizar la licencia: {exc}")
        finally:
            self.refresh()

    def _set_expiration(self) -> None:
        if not isinstance(self.backend, ShareBackend) or not self._current_record:
            return
        dialog = DateDialog("Expiración", "Fecha y hora de expiración", self)
        if dialog.exec_() != QDialog.Accepted:
            return
        expires = dialog.selected_iso()
        try:
            self.backend.set_expiration(self._current_record, expires)
            message = "Expiración eliminada" if expires is None else "Expiración actualizada"
            self._update_status_bar(message)
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"No se pudo actualizar la expiración: {exc}")
        finally:
            self.refresh()

    def _set_grace(self) -> None:
        if not isinstance(self.backend, ShareBackend) or not self._current_record:
            return
        dialog = DateDialog("Período de gracia", "Fin de GRACE", self)
        if dialog.exec_() != QDialog.Accepted:
            return
        grace = dialog.selected_iso()
        try:
            self.backend.set_grace_until(self._current_record, grace)
            if grace:
                self.backend.update_status(self._current_record, "GRACE")
                message = "Período de gracia actualizado"
            else:
                message = "Período de gracia eliminado"
            self._update_status_bar(message)
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"No se pudo actualizar la licencia: {exc}")
        finally:
            self.refresh()

    def _edit_notes(self) -> None:
        if not isinstance(self.backend, ShareBackend) or not self._current_record:
            return
        dialog = NotesDialog(self._current_record.notes, self)
        if dialog.exec_() != QDialog.Accepted:
            return
        self._current_record.notes = dialog.value()
        try:
            self.backend.save_license(self._current_record)
            self._update_status_bar("Notas guardadas")
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"No se pudieron guardar las notas: {exc}")
        finally:
            self.refresh()


def main() -> None:
    app = QApplication(sys.argv)
    window = VerifierMainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
