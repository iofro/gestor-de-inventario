from __future__ import annotations

from datetime import datetime
import logging
import sqlite3
from typing import Iterable

from PyQt5.QtCore import QDate, QTimer, Qt
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

import anulacion
from db import DB


logger = logging.getLogger(__name__)


class SeleccionarDteDialog(QDialog):
    """Modal dialog to browse DTE candidates received by the tax authority."""

    HEADERS = [
        "Fecha emisión",
        "Tipo",
        "Número de control",
        "Código generación (UUID)",
        "Receptor",
        "Total",
        "Estado",
        "Con sello",
    ]

    def __init__(
        self,
        db: DB | None,
        *,
        tipo_dte: str | None,
        ambiente: str | None,
        receptor_documentos: Iterable[str] | None = None,
        exclude_uuid: str | None = None,
        emisor_documento: str | None = None,
        fecha_emision_original: str | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.db = db
        self.tipo_dte = str(tipo_dte).zfill(2) if tipo_dte else None
        self.ambiente = anulacion.normalize_ambiente(ambiente)
        docs = receptor_documentos or []
        normalizados: list[str] = []
        for raw in docs:
            norm = anulacion._normalize_documento_id(raw)
            if norm and norm not in normalizados:
                normalizados.append(norm)
        self.receptor_documentos = normalizados
        self.exclude_uuid = (exclude_uuid or "").strip().upper()
        self.candidates: list[dict] = []
        self.selected_uuid: str | None = None
        self.emisor_documento_norm = anulacion._normalize_documento_id(emisor_documento)
        self.original_fecha = (
            str(fecha_emision_original)[:10]
            if fecha_emision_original
            else None
        )

        self.setWindowTitle("Seleccionar DTE corregido")
        layout = QVBoxLayout(self)

        info_parts = []
        if self.tipo_dte:
            info_parts.append(f"Tipo: {self.tipo_dte}")
        if self.ambiente:
            info_parts.append(f"Ambiente: {self.ambiente}")
        if info_parts:
            info_label = QLabel(" · ".join(info_parts))
            info_label.setStyleSheet("color: #555555; font-size: 11px;")
            layout.addWidget(info_label)

        search_layout = QHBoxLayout()
        search_label = QLabel("Buscar:")
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(
            "Código de generación, número de control, receptor o monto"
        )
        search_layout.addWidget(search_label)
        search_layout.addWidget(self.search_edit)
        layout.addLayout(search_layout)

        filters_layout = QHBoxLayout()
        self.recepcionado_cb = QCheckBox("Solo DTE recepcionados por MH")
        self.recepcionado_cb.setChecked(False)
        filters_layout.addWidget(self.recepcionado_cb)

        self.mismo_receptor_cb = QCheckBox("Mismo receptor")
        tiene_docs = bool(self.receptor_documentos)
        self.mismo_receptor_cb.setChecked(False)
        self.mismo_receptor_cb.setEnabled(tiene_docs)
        if tiene_docs:
            self.mismo_receptor_cb.setToolTip(
                "Restringe los resultados al receptor del documento original."
            )
        else:
            self.mismo_receptor_cb.setToolTip(
                "No hay identificadores de receptor para filtrar."
            )
        filters_layout.addWidget(self.mismo_receptor_cb)

        self.mismo_tipo_cb = QCheckBox("Solo mismo tipo")
        self.mismo_tipo_cb.setChecked(False)
        self.mismo_tipo_cb.setEnabled(self.tipo_dte is not None)
        if self.tipo_dte is None:
            self.mismo_tipo_cb.setToolTip(
                "No hay tipo de DTE para filtrar automáticamente."
            )
        else:
            self.mismo_tipo_cb.setToolTip(
                "Restringe los resultados al mismo tipo de DTE que el documento original."
            )
        filters_layout.addWidget(self.mismo_tipo_cb)

        self.mismo_ambiente_cb = QCheckBox("Solo mismo ambiente")
        self.mismo_ambiente_cb.setChecked(False)
        self.mismo_ambiente_cb.setEnabled(self.ambiente is not None)
        if self.ambiente is None:
            self.mismo_ambiente_cb.setToolTip(
                "No hay ambiente registrado para aplicar este filtro."
            )
        else:
            self.mismo_ambiente_cb.setToolTip(
                "Restringe los resultados al mismo ambiente que el documento original."
            )
        filters_layout.addWidget(self.mismo_ambiente_cb)

        self.filtrar_fecha_cb = QCheckBox("Filtrar por fecha")
        self.filtrar_fecha_cb.setChecked(False)
        filters_layout.addWidget(self.filtrar_fecha_cb)
        filters_layout.addStretch(1)

        filters_layout.addWidget(QLabel("Desde:"))
        self.fecha_inicio = QDateEdit()
        self.fecha_inicio.setCalendarPopup(True)
        self.fecha_inicio.setDisplayFormat("yyyy-MM-dd")
        self.fecha_inicio.setSpecialValueText("")
        self.fecha_inicio.setMinimumDate(QDate(1900, 1, 1))
        self.fecha_inicio.setDate(self.fecha_inicio.minimumDate())
        filters_layout.addWidget(self.fecha_inicio)

        filters_layout.addWidget(QLabel("Hasta:"))
        self.fecha_fin = QDateEdit()
        self.fecha_fin.setCalendarPopup(True)
        self.fecha_fin.setDisplayFormat("yyyy-MM-dd")
        self.fecha_fin.setSpecialValueText("")
        self.fecha_fin.setMinimumDate(QDate(1900, 1, 1))
        self.fecha_fin.setDate(self.fecha_fin.minimumDate())
        filters_layout.addWidget(self.fecha_fin)
        layout.addLayout(filters_layout)

        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        header = self.table.horizontalHeader()
        header.setStretchLastSection(True)
        for idx in range(len(self.HEADERS)):
            header.setSectionResizeMode(idx, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.table)

        self.result_label = QLabel("")
        self.result_label.setStyleSheet("color: #555555; font-size: 11px;")
        layout.addWidget(self.result_label)

        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.select_btn = self.button_box.button(QDialogButtonBox.Ok)
        self.select_btn.setText("Seleccionar")
        self.button_box.accepted.connect(self._select_current)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        self.table.itemDoubleClicked.connect(lambda *_: self._select_current())
        self.table.itemSelectionChanged.connect(self._update_button_state)

        self.search_timer = QTimer(self)
        self.search_timer.setInterval(250)
        self.search_timer.setSingleShot(True)
        self.search_edit.textChanged.connect(self.search_timer.start)
        self.search_timer.timeout.connect(self._refresh)

        self._retry_timer = QTimer(self)
        self._retry_timer.setSingleShot(True)
        self._retry_timer.setInterval(250)
        self._retry_timer.timeout.connect(self._refresh)

        self.recepcionado_cb.toggled.connect(self._refresh)
        self.mismo_receptor_cb.toggled.connect(self._refresh)
        self.mismo_tipo_cb.toggled.connect(self._refresh)
        self.mismo_ambiente_cb.toggled.connect(self._refresh)
        self.filtrar_fecha_cb.toggled.connect(self._on_toggle_fecha_filter)
        self.fecha_inicio.dateChanged.connect(lambda *_: self._refresh())
        self.fecha_fin.dateChanged.connect(lambda *_: self._refresh())

        self._fecha_filtro_configurado = False
        self._on_toggle_fecha_filter(self.filtrar_fecha_cb.isChecked(), refresh=False)

        if self.db is None:
            for widget in (
                self.search_edit,
                self.recepcionado_cb,
                self.mismo_receptor_cb,
                self.mismo_tipo_cb,
                self.mismo_ambiente_cb,
                self.filtrar_fecha_cb,
                self.fecha_inicio,
                self.fecha_fin,
            ):
                widget.setEnabled(False)

        self._refresh()

    def _on_toggle_fecha_filter(self, enabled: bool, *, refresh: bool = True) -> None:
        self.fecha_inicio.setEnabled(enabled)
        self.fecha_fin.setEnabled(enabled)
        if enabled:
            if not self._fecha_filtro_configurado:
                self._fecha_filtro_configurado = True
                inicio = QDate.currentDate().addDays(-60)
                fin = QDate.currentDate()
                self.fecha_inicio.blockSignals(True)
                self.fecha_fin.blockSignals(True)
                self.fecha_inicio.setDate(inicio)
                self.fecha_fin.setDate(fin)
                self.fecha_inicio.blockSignals(False)
                self.fecha_fin.blockSignals(False)
        else:
            self._fecha_filtro_configurado = False
            self.fecha_inicio.blockSignals(True)
            self.fecha_fin.blockSignals(True)
            self.fecha_inicio.setDate(self.fecha_inicio.minimumDate())
            self.fecha_fin.setDate(self.fecha_fin.minimumDate())
            self.fecha_inicio.blockSignals(False)
            self.fecha_fin.blockSignals(False)
        if refresh:
            self._refresh()

    def _current_candidate(self) -> dict | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if item is None:
            return None
        data = item.data(Qt.UserRole)
        return data if isinstance(data, dict) else None

    def _update_button_state(self) -> None:
        self.select_btn.setEnabled(self._current_candidate() is not None)

    def _refresh(self) -> None:
        if self.db is None:
            self.candidates = []
            self._populate_table()
            return

        if (
            self.filtrar_fecha_cb.isChecked()
            and self.fecha_inicio.date() > self.fecha_fin.date()
        ):
            self.fecha_fin.setDate(self.fecha_inicio.date())

        filtros = {
            "exclude_uuid": self.exclude_uuid,
            "recepcionado": self.recepcionado_cb.isChecked(),
            "mismo_receptor": self.mismo_receptor_cb.isChecked(),
            "receptor_documentos": self.receptor_documentos,
            "search": self.search_edit.text(),
            "permitir_tipo_mismatch": True,
            "permitir_ambiente_mismatch": True,
        }
        if self.tipo_dte and self.mismo_tipo_cb.isChecked():
            filtros["tipo_dte"] = self.tipo_dte
        if self.ambiente and self.mismo_ambiente_cb.isChecked():
            filtros["ambiente"] = self.ambiente
        if self.filtrar_fecha_cb.isChecked():
            filtros.update(
                {
                    "fecha_inicio": self.fecha_inicio.date().toString("yyyy-MM-dd"),
                    "fecha_fin": self.fecha_fin.date().toString("yyyy-MM-dd"),
                }
            )
        if self._retry_timer.isActive():
            self._retry_timer.stop()

        try:
            candidates = anulacion.buscar_candidatos_reemplazo(self.db, filtros)
        except sqlite3.OperationalError as exc:
            if "locked" in str(exc).lower():
                logger.info("Base de datos ocupada al buscar DTE, reintentando…")
                if not self._retry_timer.isActive():
                    self._retry_timer.start()
                return
            logger.exception("Error SQLite al buscar candidatos de DTE")
            candidates = []
        except Exception:
            logger.exception("No se pudieron cargar los candidatos de DTE")
            candidates = []

        self.candidates = candidates
        self._populate_table()

    def _populate_table(self) -> None:
        self.table.setRowCount(0)
        preselect_row = -1
        for idx, cand in enumerate(self.candidates):
            self.table.insertRow(idx)
            fecha = cand.get("fecha_emision") or ""
            tipo = cand.get("tipo_dte") or "?"
            numero_control = cand.get("numero_control") or ""
            codigo = cand.get("codigo_generacion") or ""
            receptor_nombre = cand.get("receptor_nombre") or ""
            receptor_doc = cand.get("receptor_documento") or ""
            if receptor_doc:
                if receptor_nombre:
                    receptor = f"{receptor_nombre}\n{receptor_doc}"
                else:
                    receptor = receptor_doc
            else:
                receptor = receptor_nombre
            total = cand.get("total")
            total_txt = f"{total:.2f}" if isinstance(total, (int, float)) else ""
            estado = cand.get("estado") or ""
            con_sello = "Sí" if cand.get("con_sello") else "No"

            values = [
                fecha,
                tipo,
                numero_control,
                codigo,
                receptor,
                total_txt,
                estado.capitalize() if estado else "",
                con_sello,
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col == 0:
                    item.setData(Qt.UserRole, cand)
                item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                self.table.setItem(idx, col, item)

            if not cand.get("seleccionable", False):
                for col in range(len(self.HEADERS)):
                    cell = self.table.item(idx, col)
                    if cell is not None:
                        cell.setForeground(Qt.gray)

            if cand.get("preselect") and preselect_row == -1:
                preselect_row = idx

        if self.candidates:
            if preselect_row >= 0:
                self.table.selectRow(preselect_row)
            else:
                self.table.selectRow(0)
        self._update_button_state()
        self.result_label.setText(f"{len(self.candidates)} resultado(s)")

    def _select_current(self) -> None:
        cand = self._current_candidate()
        if not cand:
            return
        error = self._validate_candidate(cand)
        if error:
            QMessageBox.warning(self, "Seleccionar DTE", error)
            return
        self.selected_uuid = cand.get("codigo_generacion")
        if self.selected_uuid:
            self.selected_uuid = self.selected_uuid.upper()
        self.accept()

    def _validate_candidate(self, cand: dict) -> str | None:
        codigo = (cand.get("codigo_generacion") or "").upper()
        if self.exclude_uuid and codigo == self.exclude_uuid:
            return anulacion.ERROR_REEMPLAZO_DISTINTO
        if cand.get("tipo_indeterminado"):
            return anulacion.ERROR_REEMPLAZO_TIPO_INDETERMINADO
        if self.tipo_dte and cand.get("tipo_dte") != self.tipo_dte:
            return anulacion.ERROR_REEMPLAZO_TIPO
        if cand.get("estado_canonico") not in anulacion.ACCEPTED_EVENT_STATES or not cand.get(
            "con_sello"
        ):
            return anulacion.ERROR_REEMPLAZO_NO_RECEPCION
        if self.ambiente and cand.get("ambiente") and cand.get("ambiente") != self.ambiente:
            return "El DTE seleccionado pertenece a un ambiente diferente."
        if self.emisor_documento_norm:
            cand_emisor = anulacion._normalize_documento_id(
                cand.get("emisor_documento")
            )
            if not cand_emisor or cand_emisor != self.emisor_documento_norm:
                return anulacion.ERROR_REEMPLAZO_EMISOR
        if self.original_fecha and cand.get("fecha_emision"):
            try:
                cand_dt = datetime.strptime(str(cand.get("fecha_emision"))[:10], "%Y-%m-%d")
                orig_dt = datetime.strptime(self.original_fecha[:10], "%Y-%m-%d")
            except Exception:
                cand_dt = None
                orig_dt = None
            if cand_dt is not None and orig_dt is not None and cand_dt < orig_dt:
                return anulacion.ERROR_REEMPLAZO_FECHA
        return None
