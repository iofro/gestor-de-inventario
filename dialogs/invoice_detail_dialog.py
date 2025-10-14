from typing import Callable, Dict, List
import logging
import os
import re
import shutil
from collections.abc import Mapping, Sequence
from decimal import Decimal

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
    QComboBox,
    QFormLayout,
    QPushButton,
    QTabWidget,
    QWidget,
    QTreeWidget,
    QTreeWidgetItem,
)
from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtGui import QDesktopServices

from utils.catalogos import TRIBUTO_IVA
from utils.docs import get_document_paths, get_dte_document_paths
from paths import resolve_user_visible_path
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

_FIELD_LABEL_OVERRIDES = {
    "identificacion": "Identificación",
    "emisor": "Emisor",
    "receptor": "Receptor",
    "resumen": "Resumen",
    "cuerpoDocumento": "Cuerpo del documento",
    "documentoRelacionado": "Documentos relacionados",
    "apendice": "Apéndice",
    "apéndice": "Apéndice",
    "otrosDocumentos": "Otros documentos",
    "extension": "Extensión",
    "fletes": "Fletes",
    "descuentos": "Descuentos",
    "tributos": "Tributos",
    "tipoDte": "Tipo DTE",
    "numeroControl": "Número de control",
    "codigoGeneracion": "Código de generación",
    "montoTotalOperacion": "Monto total de la operación",
    "selloRecibido": "Sello recibido",
    "nombreComercial": "Nombre comercial",
    "nombre_comercial": "Nombre comercial",
    "montoTotalPagar": "Monto total a pagar",
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
        envio_state: str | None = None,
        envio_options: List[str] | None = None,
        on_envio_change: Callable[[str], str] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.venta_id = venta_id
        self.numero_control = numero_control
        self.factura = factura or {}
        self._json_path = json_path
        self._pdf_path = pdf_path
        self._source_json_path = json_path
        self._source_pdf_path = pdf_path
        self.anulacion_result = None
        self._open_button = None
        self.envio_updated = False
        self._envio_combo: QComboBox | None = None
        self._envio_label: QLabel | None = None
        self._save_state_button: QPushButton | None = None
        self._current_envio_value = (envio_state or "").strip()
        self._on_envio_change = on_envio_change
        self.setWindowTitle("Detalle de factura")
        self.setMinimumSize(900, 600)
        self.resize(1000, 700)
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

        info_widget = self._build_metadata_tab()
        if info_widget is None:
            layout.addWidget(self.table)
            layout.addLayout(totals_layout)
        else:
            tabs = QTabWidget(self)
            items_container = QWidget(self)
            items_layout = QVBoxLayout(items_container)
            items_layout.setContentsMargins(0, 0, 0, 0)
            items_layout.setSpacing(8)
            items_layout.addWidget(self.table)
            items_layout.addLayout(totals_layout)
            tabs.addTab(items_container, "Productos")
            tabs.addTab(info_widget, "Información")
            layout.addWidget(tabs)

        envio_layout = QFormLayout()
        envio_layout.setLabelAlignment(Qt.AlignLeft)
        envio_layout.setFormAlignment(Qt.AlignLeft)
        current_envio_display = self._current_envio_value or "Pendiente de envío"
        self._envio_label = QLabel(current_envio_display, self)
        envio_layout.addRow("Estado de envío actual:", self._envio_label)
        if envio_options:
            combo = QComboBox(self)
            seen = set()
            for option in envio_options:
                text = str(option or "").strip()
                if not text:
                    continue
                lowered = text.lower()
                if lowered in seen:
                    continue
                combo.addItem(text)
                seen.add(lowered)
            if self._current_envio_value:
                idx = combo.findText(self._current_envio_value)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
                else:
                    combo.addItem(self._current_envio_value)
                    combo.setCurrentText(self._current_envio_value)
            combo.currentTextChanged.connect(self._on_envio_combo_changed)
            self._envio_combo = combo
            envio_layout.addRow("Actualizar estado:", combo)
        layout.addLayout(envio_layout)

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
        if self._envio_combo is not None and callable(self._on_envio_change):
            self._save_state_button = buttons.addButton(
                "Guardar estado de envío", QDialogButtonBox.ActionRole
            )
            self._save_state_button.setEnabled(False)
            self._save_state_button.clicked.connect(self._save_envio_state)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    def _build_metadata_tab(self) -> QWidget | None:
        tipo_codigo = self._resolve_document_code()
        if tipo_codigo not in {"01", "03", "04", "05", "06"}:
            return None
        factura = self.factura or {}
        if not isinstance(factura, Mapping):
            return None

        tree = QTreeWidget(self)
        tree.setColumnCount(2)
        tree.setHeaderLabels(["Campo", "Valor"])
        header_fn = getattr(tree, "header", None)
        if callable(header_fn):
            header = header_fn()
            if header is not None:
                resize_fn = getattr(header, "setSectionResizeMode", None)
                if callable(resize_fn):
                    try:
                        resize_fn(0, QHeaderView.ResizeToContents)
                        resize_fn(1, QHeaderView.Stretch)
                    except Exception:
                        pass
        alt_colors = getattr(tree, "setAlternatingRowColors", None)
        if callable(alt_colors):
            alt_colors(True)
        uniform_rows = getattr(tree, "setUniformRowHeights", None)
        if callable(uniform_rows):
            uniform_rows(True)
        selection_mode = getattr(tree, "setSelectionMode", None)
        if callable(selection_mode):
            selection_mode(QAbstractItemView.NoSelection)
        edit_triggers = getattr(tree, "setEditTriggers", None)
        if callable(edit_triggers):
            edit_triggers(QAbstractItemView.NoEditTriggers)
        focus_policy = getattr(tree, "setFocusPolicy", None)
        if callable(focus_policy):
            try:
                focus_policy(Qt.NoFocus)
            except Exception:
                pass

        root = None
        root_fn = getattr(tree, "invisibleRootItem", None)
        if callable(root_fn):
            root = root_fn()
        if root is None:
            return None

        for key, value in factura.items():
            if self._is_empty_value(value):
                continue
            label = self._format_field_label(key)
            self._add_tree_entry(root, label, value)

        top_level_count = getattr(tree, "topLevelItemCount", None)
        if callable(top_level_count) and top_level_count() == 0:
            return None

        expand_fn = getattr(tree, "expandToDepth", None)
        if callable(expand_fn):
            try:
                expand_fn(1)
            except Exception:
                pass

        container = QWidget(self)
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.addWidget(tree)
        return container

    def _resolve_document_code(self) -> str | None:
        factura = self.factura or {}
        ident = factura.get("identificacion") or {}
        candidates = [
            ident.get("tipoDte"),
            factura.get("tipoDte"),
            factura.get("tipo_documento"),
            factura.get("tipoDocumento"),
        ]
        for raw_tipo in candidates:
            if raw_tipo is None:
                continue
            if isinstance(raw_tipo, str):
                stripped = raw_tipo.strip()
                if not stripped:
                    continue
                if stripped in _DOC_TYPE_BY_CODE:
                    return stripped
                lowered = stripped.lower()
                if lowered in _DOC_CODE_BY_DESC:
                    return _DOC_CODE_BY_DESC[lowered]
                if stripped.isdigit():
                    normalized = f"{int(stripped):02d}"
                    if normalized in _DOC_TYPE_BY_CODE:
                        return normalized
            else:
                try:
                    numeric = int(raw_tipo)
                except (TypeError, ValueError):
                    continue
                normalized = f"{numeric:02d}"
                if normalized in _DOC_TYPE_BY_CODE:
                    return normalized
        return None

    def _format_field_label(self, key) -> str:
        if not isinstance(key, str):
            return str(key)
        stripped = key.strip()
        if not stripped:
            return str(key)
        override = _FIELD_LABEL_OVERRIDES.get(stripped)
        if override:
            return override
        normalized = re.sub(r"(?<!^)(?=[A-Z])", " ", stripped)
        normalized = normalized.replace("_", " ")
        normalized = re.sub(r"\s+", " ", normalized).strip()
        upper_tokens = {"nit", "nrc", "dui", "iva"}
        if normalized.lower() in upper_tokens:
            return normalized.upper()
        if not normalized:
            return stripped
        if normalized.isupper():
            return normalized
        return normalized[:1].upper() + normalized[1:]

    def _format_value(self, value) -> str:
        if isinstance(value, bool):
            return "Sí" if value else "No"
        if isinstance(value, Decimal):
            txt = format(value, "f")
            return txt.rstrip("0").rstrip(".") if "." in txt else txt
        return str(value)

    def _is_empty_value(self, value) -> bool:
        if value is None:
            return True
        if isinstance(value, str):
            return not value.strip()
        if isinstance(value, Mapping):
            for subvalue in value.values():
                if not self._is_empty_value(subvalue):
                    return False
            return True
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            for item in value:
                if not self._is_empty_value(item):
                    return False
            return True
        return False

    def _add_tree_entry(self, parent: QTreeWidgetItem, label: str, value) -> None:
        if self._is_empty_value(value):
            return
        if isinstance(value, Mapping):
            item = QTreeWidgetItem([label, ""])
            for subkey, subvalue in sorted(value.items(), key=lambda kv: str(kv[0])):
                sublabel = self._format_field_label(subkey)
                self._add_tree_entry(item, sublabel, subvalue)
            if item.childCount() > 0:
                parent.addChild(item)
            return
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            item = QTreeWidgetItem([label, ""])
            for idx, element in enumerate(value, start=1):
                entry_label = f"Elemento {idx}"
                if isinstance(element, Mapping):
                    child = QTreeWidgetItem([entry_label, ""])
                    for subkey, subvalue in sorted(element.items(), key=lambda kv: str(kv[0])):
                        sublabel = self._format_field_label(subkey)
                        self._add_tree_entry(child, sublabel, subvalue)
                    if child.childCount() > 0:
                        item.addChild(child)
                elif isinstance(element, Sequence) and not isinstance(
                    element, (str, bytes, bytearray)
                ):
                    self._add_tree_entry(item, entry_label, element)
                elif not self._is_empty_value(element):
                    item.addChild(QTreeWidgetItem([entry_label, self._format_value(element)]))
            if item.childCount() > 0:
                parent.addChild(item)
            return
        parent.addChild(QTreeWidgetItem([label, self._format_value(value)]))

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

    def _on_envio_combo_changed(self, value: str) -> None:
        if not self._save_state_button:
            return
        value_norm = (value or "").strip()
        current_norm = (self._current_envio_value or "").strip()
        enabled = bool(value_norm) and value_norm != current_norm and callable(
            self._on_envio_change
        )
        self._save_state_button.setEnabled(enabled)

    def _save_envio_state(self) -> None:
        if not self._envio_combo or not callable(self._on_envio_change):
            return
        selection = self._envio_combo.currentText().strip()
        if not selection:
            QMessageBox.warning(self, "Estado de envío", "Seleccione un estado válido")
            return
        try:
            new_display = self._on_envio_change(selection)
        except Exception as exc:  # pragma: no cover - UI feedback
            QMessageBox.warning(self, "Estado de envío", str(exc))
            return
        display_text = str(new_display or "").strip()
        if not display_text:
            QMessageBox.warning(
                self, "Estado de envío", "No se pudo actualizar el estado seleccionado"
            )
            return
        self.envio_updated = True
        self._current_envio_value = display_text
        if self._envio_label is not None:
            self._envio_label.setText(display_text)
        if self._envio_combo.findText(display_text) < 0:
            self._envio_combo.addItem(display_text)
        self._envio_combo.setCurrentText(display_text)
        if self._save_state_button is not None:
            self._save_state_button.setEnabled(False)
        QMessageBox.information(
            self, "Estado de envío", "Estado actualizado correctamente"
        )

    def _determine_file_path(self) -> str | None:
        """Return the most relevant file path for the current invoice."""

        seen = set()
        for path in (
            getattr(self, "_source_pdf_path", None),
            getattr(self, "_source_json_path", None),
            self._pdf_path,
            self._json_path,
        ):
            if path is None:
                continue
            try:
                candidate = os.fspath(path)
            except TypeError:
                continue
            try:
                marker = os.path.abspath(candidate)
            except (TypeError, ValueError, OSError):
                marker = candidate
            if marker in seen:
                continue
            seen.add(marker)
            if os.path.exists(candidate):
                return candidate
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
        visible_directory = resolve_user_visible_path(directory)
        QDesktopServices.openUrl(QUrl.fromLocalFile(visible_directory))

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
                    self._source_pdf_path = pdf_path
                    json_candidate = os.path.splitext(pdf_path)[0] + ".json"
                    if os.path.exists(json_candidate):
                        self._json_path = json_candidate
                        self._source_json_path = json_candidate
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
                self._source_pdf_path = pdf_path
                json_candidate = os.path.splitext(pdf_path)[0] + ".json"
                if os.path.exists(json_candidate):
                    self._json_path = json_candidate
                    self._source_json_path = json_candidate

                self._sync_standard_paths()
                refreshed = self._determine_file_path()
                if refreshed:
                    self._update_open_button_state()
                return refreshed
        return None

    def _sync_standard_paths(self) -> None:
        try:
            original_pdf = (
                os.fspath(self._pdf_path) if self._pdf_path is not None else None
            )
        except TypeError:
            original_pdf = None

        pdf_path, json_path = self._ensure_standard_location(
            self._pdf_path, self._json_path
        )
        self._pdf_path = pdf_path
        self._json_path = json_path

        if (
            self.venta_id
            and original_pdf
            and pdf_path
            and os.path.abspath(original_pdf) != os.path.abspath(pdf_path)
        ):
            parent_fn = getattr(self, "parent", None)
            parent = parent_fn() if callable(parent_fn) else None
            manager = getattr(parent, "manager", None) if parent else None
            db = getattr(manager, "db", None) if manager else None
            updater = getattr(db, "update_factura_pdf_path", None) if db else None
            if callable(updater):
                try:
                    updater(self.venta_id, pdf_path)
                except Exception:
                    logger.warning(
                        "No se pudo actualizar la ruta canónica de la factura",
                        exc_info=True,
                    )

    def _ensure_standard_location(
        self, pdf_path: os.PathLike | str | None, json_path: os.PathLike | str | None
    ) -> tuple[str | None, str | None]:
        try:
            pdf_path = os.fspath(pdf_path) if pdf_path is not None else None
        except TypeError:
            pdf_path = None
        try:
            json_path = os.fspath(json_path) if json_path is not None else None
        except TypeError:
            json_path = None

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

        return (
            os.fspath(pdf_path) if pdf_path is not None else None,
            os.fspath(json_path) if json_path is not None else None,
        )

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

