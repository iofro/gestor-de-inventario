"""Diálogo PyQt (UI-only) para generar Comprobante de Retención (CR-07)."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Dict, List, Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .retencion_constants import RET_MH, TIPOS_DOC_REF, TIPOS_DTE_REL
from .retencion_models import CRDetalle, CRDraft
from .retencion_store import RetencionStore, get_retencion_store
from .retencion_utils import (
    build_resumen,
    draft_to_dict,
    ensure_detalle_defaults,
    is_valid_uuid,
    quantize_money,
)


class RetencionCRDialog(QDialog):
    """QDialog para capturar un borrador UI de CR-07."""

    def __init__(
        self,
        parent=None,
        *,
        defaults: Optional[dict] = None,
        store: Optional[RetencionStore] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Generar Comprobante de Retención (CR-07)")
        self.setModal(True)

        self.store = store or get_retencion_store()
        self.draft = CRDraft()
        self.data: Optional[dict] = None
        self._draft_key = ""
        self._row_widgets: List[Dict[str, QWidget]] = []

        self._setup_ui()
        self._load_defaults(defaults or {})
        self._update_summary()

    # --------------------------------------------------------------------- UI
    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        self.tabs = QTabWidget(self)
        layout.addWidget(self.tabs)

        self.header_tab = QWidget()
        self.detail_tab = QWidget()
        self.summary_tab = QWidget()
        self.preview_tab = QWidget()

        self.tabs.addTab(self.header_tab, "Encabezado")
        self.tabs.addTab(self.detail_tab, "Detalle")
        self.tabs.addTab(self.summary_tab, "Resumen")
        self.tabs.addTab(self.preview_tab, "Notas")

        self._setup_header_tab()
        self._setup_detail_tab()
        self._setup_summary_tab()
        self._setup_preview_tab()

        buttons = QDialogButtonBox(self)
        self.preview_btn = QPushButton("Previsualizar")
        self.save_draft_btn = QPushButton("Guardar borrador")
        buttons.addButton(self.preview_btn, QDialogButtonBox.ActionRole)
        buttons.addButton(self.save_draft_btn, QDialogButtonBox.ActionRole)
        buttons.addButton("Cancelar", QDialogButtonBox.RejectRole)
        buttons.addButton("Aceptar", QDialogButtonBox.AcceptRole)
        layout.addWidget(buttons)

        # Connections
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        self.preview_btn.clicked.connect(self._on_preview_clicked)
        self.save_draft_btn.clicked.connect(self._on_save_draft_clicked)

    def _setup_header_tab(self) -> None:
        layout = QFormLayout(self.header_tab)
        layout.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        self.meta_identificacion = QTextEdit()
        self.meta_identificacion.setReadOnly(True)
        self.meta_identificacion.setMinimumHeight(80)

        self.meta_emisor = QTextEdit()
        self.meta_emisor.setReadOnly(True)
        self.meta_emisor.setMinimumHeight(80)

        self.meta_receptor = QTextEdit()
        self.meta_receptor.setReadOnly(True)
        self.meta_receptor.setMinimumHeight(80)

        layout.addRow(QLabel("Identificación (solo lectura)"), self.meta_identificacion)
        layout.addRow(QLabel("Emisor"), self.meta_emisor)
        layout.addRow(QLabel("Receptor"), self.meta_receptor)

    def _setup_detail_tab(self) -> None:
        wrapper = QVBoxLayout(self.detail_tab)

        self.detail_table = QTableWidget(0, 8, self.detail_tab)
        self.detail_table.setHorizontalHeaderLabels(
            [
                "Tipo DTE",
                "Tipo Ref",
                "N° doc / Código",
                "Fecha emisión",
                "Monto sujeto",
                "Código retención",
                "IVA retenido",
                "Descripción",
            ]
        )
        self.detail_table.horizontalHeader().setStretchLastSection(True)
        self.detail_table.verticalHeader().setVisible(False)

        wrapper.addWidget(self.detail_table)

        button_row = QHBoxLayout()
        self.btn_add_row = QPushButton("Agregar fila")
        self.btn_remove_row = QPushButton("Eliminar fila")
        button_row.addWidget(self.btn_add_row)
        button_row.addWidget(self.btn_remove_row)
        button_row.addStretch(1)
        wrapper.addLayout(button_row)

        self.btn_add_row.clicked.connect(self._add_empty_row)
        self.btn_remove_row.clicked.connect(self._remove_selected_row)
        self.detail_table.itemChanged.connect(lambda *_: self._update_summary())

    def _setup_summary_tab(self) -> None:
        layout = QFormLayout(self.summary_tab)
        layout.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        self.total_sujeto_label = QLabel("0.00")
        self.total_iva_label = QLabel("0.00")
        self.total_letras_text = QTextEdit()
        self.total_letras_text.setReadOnly(True)
        self.total_letras_text.setMaximumHeight(80)

        layout.addRow("Total sujeto a retención", self.total_sujeto_label)
        layout.addRow("IVA retenido", self.total_iva_label)
        layout.addRow("IVA retenido (letras)", self.total_letras_text)

    def _setup_preview_tab(self) -> None:
        layout = QVBoxLayout(self.preview_tab)
        self.notes_text = QTextEdit()
        self.notes_text.setReadOnly(True)
        self.notes_text.setPlainText(
            "El flujo CR-07 es solo UI. No se realiza firma ni transmisión real.\n"
            "Use “Guardar borrador” para conservar la información localmente."
        )
        layout.addWidget(self.notes_text)

    # ---------------------------------------------------------------- Defaults
    def _load_defaults(self, defaults: dict) -> None:
        meta = defaults.get("meta") or {}

        self._draft_key = str(meta.get("key") or meta.get("codigoGeneracion") or meta.get("numeroControl") or "")
        self.draft.meta = meta

        # Rellenar bloques de texto
        ident_text = json.dumps(meta.get("identificacion", {}), indent=2, ensure_ascii=False)
        emisor_text = json.dumps(meta.get("emisor", {}), indent=2, ensure_ascii=False)
        receptor_text = json.dumps(meta.get("receptor", {}), indent=2, ensure_ascii=False)
        self.meta_identificacion.setPlainText(ident_text)
        self.meta_emisor.setPlainText(emisor_text)
        self.meta_receptor.setPlainText(receptor_text)

        detalles_data = defaults.get("detalles") or []
        if not detalles_data and self.store and self._draft_key:
            stored = self.store.get_draft(self._draft_key)
            if stored:
                detalles_data = [
                    {
                        "tipoDte": det.tipoDte,
                        "tipoDoc": det.tipoDoc,
                        "numDocumento": det.numDocumento,
                        "codGeneracion": det.codGeneracion,
                        "fechaEmision": det.fechaEmision,
                        "montoSujetoGrav": det.montoSujetoGrav,
                        "codigoRetencionMH": det.codigoRetencionMH,
                        "ivaRetenido": det.ivaRetenido,
                        "descripcion": det.descripcion,
                    }
                    for det in stored.detalles
                ]

        if not detalles_data:
            detalles_data = [{}]

        for detalle in detalles_data:
            self._add_empty_row(initial=detalle)

        self._update_summary()

    # ---------------------------------------------------------------- Helpers
    def _add_empty_row(self, *_ , initial: Optional[dict] = None) -> None:
        row = self.detail_table.rowCount()
        self.detail_table.insertRow(row)

        defaults = initial or {}
        widgets: Dict[str, QWidget] = {}

        combo_tipo = QComboBox()
        for codigo, label in TIPOS_DTE_REL:
            combo_tipo.addItem(label, codigo)
        if defaults.get("tipoDte"):
            idx = combo_tipo.findData(defaults.get("tipoDte"))
            if idx >= 0:
                combo_tipo.setCurrentIndex(idx)
        combo_tipo.currentIndexChanged.connect(lambda *_: self._update_summary())
        self.detail_table.setCellWidget(row, 0, combo_tipo)
        widgets["tipoDte"] = combo_tipo

        combo_doc = QComboBox()
        for codigo, label in TIPOS_DOC_REF:
            combo_doc.addItem(label, codigo)
        if defaults.get("tipoDoc"):
            idx = combo_doc.findData(defaults.get("tipoDoc"))
            if idx >= 0:
                combo_doc.setCurrentIndex(idx)
        combo_doc.currentIndexChanged.connect(lambda *_: self._update_summary())
        self.detail_table.setCellWidget(row, 1, combo_doc)
        widgets["tipoDoc"] = combo_doc

        valor_edit = QLineEdit()
        valor = defaults.get("numDocumento") or defaults.get("codGeneracion") or ""
        valor_edit.setText(str(valor))
        valor_edit.textChanged.connect(lambda *_: self._update_summary())
        self.detail_table.setCellWidget(row, 2, valor_edit)
        widgets["valor"] = valor_edit

        fecha_edit = QLineEdit()
        fecha_edit.setPlaceholderText("YYYY-MM-DD")
        if defaults.get("fechaEmision"):
            fecha_edit.setText(str(defaults.get("fechaEmision")))
        fecha_edit.textChanged.connect(lambda *_: self._update_summary())
        self.detail_table.setCellWidget(row, 3, fecha_edit)
        widgets["fecha"] = fecha_edit

        monto_spin = QDoubleSpinBox()
        monto_spin.setRange(0, 10_000_000_000)
        monto_spin.setDecimals(2)
        monto_spin.setValue(float(defaults.get("montoSujetoGrav") or 0))
        monto_spin.valueChanged.connect(lambda *_: self._update_summary())
        self.detail_table.setCellWidget(row, 4, monto_spin)
        widgets["monto"] = monto_spin

        combo_ret = QComboBox()
        for option in RET_MH:
            combo_ret.addItem(option["label"], option["codigo"])
        if defaults.get("codigoRetencionMH"):
            idx = combo_ret.findData(defaults.get("codigoRetencionMH"))
            if idx >= 0:
                combo_ret.setCurrentIndex(idx)
        combo_ret.currentIndexChanged.connect(lambda *_: self._update_summary())
        self.detail_table.setCellWidget(row, 5, combo_ret)
        widgets["codigo"] = combo_ret

        iva_spin = QDoubleSpinBox()
        iva_spin.setRange(0, 10_000_000_000)
        iva_spin.setDecimals(2)
        iva_spin.setValue(float(defaults.get("ivaRetenido") or 0))
        iva_spin.valueChanged.connect(lambda *_: self._update_summary())
        self.detail_table.setCellWidget(row, 6, iva_spin)
        widgets["iva"] = iva_spin

        desc_edit = QLineEdit()
        desc_edit.setText(str(defaults.get("descripcion") or ""))
        desc_edit.textChanged.connect(lambda *_: self._update_summary())
        self.detail_table.setCellWidget(row, 7, desc_edit)
        widgets["descripcion"] = desc_edit

        self._row_widgets.append(widgets)

    def _remove_selected_row(self) -> None:
        row = self.detail_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Detalle", "Seleccione una fila para eliminar.")
            return
        if self.detail_table.rowCount() == 1:
            QMessageBox.warning(self, "Detalle", "Debe existir al menos una fila.")
            return
        self.detail_table.removeRow(row)
        del self._row_widgets[row]
        self._update_summary()

    def _collect_details(self) -> List[CRDetalle]:
        detalles: List[CRDetalle] = []
        for widgets in self._row_widgets:
            tipo_dte = widgets["tipoDte"].currentData()
            tipo_doc = widgets["tipoDoc"].currentData()
            valor_ref = widgets["valor"].text().strip()
            fecha = widgets["fecha"].text().strip()
            monto = widgets["monto"].value()
            codigo_ret = widgets["codigo"].currentData()
            iva_ret = widgets["iva"].value()
            descripcion = widgets["descripcion"].text().strip()

            detalle = CRDetalle(
                tipoDte=str(tipo_dte or ""),
                tipoDoc=str(tipo_doc or ""),
                fechaEmision=fecha,
                montoSujetoGrav=float(monto),
                codigoRetencionMH=str(codigo_ret or "22"),
                ivaRetenido=float(iva_ret),
                descripcion=descripcion,
            )
            if detalle.tipoDoc == "2":
                detalle.codGeneracion = valor_ref or ""
                detalle.numDocumento = None
            else:
                detalle.numDocumento = valor_ref or ""
                detalle.codGeneracion = None
            detalles.append(ensure_detalle_defaults(detalle))
        return detalles

    def _update_summary(self) -> None:
        detalles = self._collect_details()
        self.draft.detalles = detalles
        self.draft.resumen = build_resumen(detalles)

        self.total_sujeto_label.setText(f"${self.draft.resumen.totalSujetoRetencion:,.2f}")
        self.total_iva_label.setText(f"${self.draft.resumen.totalIVAretenido:,.2f}")
        self.total_letras_text.setPlainText(self.draft.resumen.totalIVAretenidoLetras)

    # ---------------------------------------------------------------- Actions
    def _on_preview_clicked(self) -> None:
        detalles = self._collect_details()
        if not detalles:
            QMessageBox.warning(self, "Previsualizar", "Agregue al menos un detalle.")
            return
        payload = draft_to_dict(
            CRDraft(detalles=detalles, resumen=build_resumen(detalles), meta=self.draft.meta)
        )
        QMessageBox.information(
            self,
            "Previsualización CR-07 (JSON)",
            json.dumps(payload, indent=2, ensure_ascii=False),
        )

    def _on_save_draft_clicked(self) -> None:
        if not self._draft_key:
            QMessageBox.warning(
                self,
                "Borrador",
                "No fue posible determinar una clave para el borrador (falta metadata).",
            )
            return
        self._update_summary()
        self.store.save_draft(self._draft_key, self.draft)
        QMessageBox.information(self, "Borrador", "CR-07 guardado localmente.")

    def _validate(self) -> bool:
        detalles = self._collect_details()
        if not detalles:
            QMessageBox.warning(self, "Validación", "Debe ingresar al menos un detalle.")
            return False
        for idx, detalle in enumerate(detalles, start=1):
            if detalle.tipoDoc == "2":
                if not is_valid_uuid(detalle.codGeneracion):
                    QMessageBox.warning(
                        self,
                        "Validación",
                        f"Fila {idx}: ingrese un Código de generación válido (UUID).",
                    )
                    return False
            else:
                if not detalle.numDocumento:
                    QMessageBox.warning(
                        self,
                        "Validación",
                        f"Fila {idx}: ingrese el número de documento relacionado.",
                    )
                    return False
        self.draft.detalles = detalles
        self.draft.resumen = build_resumen(detalles)
        return True

    def _on_accept(self) -> None:
        if not self._validate():
            return
        payload = draft_to_dict(self.draft)
        payload["meta"] = self.draft.meta
        self.data = payload
        self.accept()
