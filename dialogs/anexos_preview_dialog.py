from __future__ import annotations

import calendar
from datetime import date
from typing import Iterable

from PyQt5.QtCore import QDate, Qt
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QHeaderView,
)

from declaracion.dte_provider import (
    AnexoPreviewData,
    DeclaracionPreview,
    EXCLUSION_MOTIVOS,
    PreviewExclusionEntry,
    PreviewRow,
)
from utils.facturacion_records import short_tipo_label


def _periodo_bounds(periodo: str) -> tuple[date, date]:
    anio = int(periodo[:4])
    mes = int(periodo[4:])
    inicio = date(anio, mes, 1)
    ultimo_dia = calendar.monthrange(anio, mes)[1]
    fin = date(anio, mes, ultimo_dia)
    return inicio, fin


class _ExclusionSection(QWidget):
    def __init__(self, motivo: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.motivo = motivo
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.toggle = QToolButton(self)
        self.toggle.setText(motivo)
        self.toggle.setCheckable(True)
        self.toggle.setChecked(False)
        self.toggle.setArrowType(Qt.RightArrow)
        layout.addWidget(self.toggle)

        self.list_widget = QListWidget(self)
        self.list_widget.setVisible(False)
        layout.addWidget(self.list_widget)

        self.toggle.toggled.connect(self._handle_toggle)

    def _handle_toggle(self, checked: bool) -> None:
        self.toggle.setArrowType(Qt.DownArrow if checked else Qt.RightArrow)
        self.list_widget.setVisible(checked)

    def update_entries(self, entries: Iterable[PreviewExclusionEntry]) -> None:
        items = list(entries)
        self.toggle.setText(f"{self.motivo} ({len(items)})")
        self.list_widget.clear()
        for entry in items[:10]:
            texto = entry.to_display() or entry.describe() or "—"
            QListWidgetItem(texto, self.list_widget)


class AnexoPreviewTab(QWidget):
    def __init__(self, titulo: str, *, incluye_debito: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName(f"anexo_preview_{titulo.lower().replace(' ', '_')}")
        self._incluye_debito = incluye_debito
        self._data: AnexoPreviewData | None = None
        self._rows: list[PreviewRow] = []
        self._filtered_rows: list[PreviewRow] = []
        self._periodo: tuple[date, date] = (date.today(), date.today())

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        resumen_layout = QHBoxLayout()
        resumen_layout.setSpacing(16)
        self.candidatos_label = QLabel("Candidatos leídos: 0", self)
        self.incluidos_label = QLabel("Incluidos (aptos): 0", self)
        self.excluidos_label = QLabel("Excluidos: 0", self)
        for widget in (self.candidatos_label, self.incluidos_label, self.excluidos_label):
            widget.setObjectName("preview_counter")
            resumen_layout.addWidget(widget)
        resumen_layout.addStretch(1)
        layout.addLayout(resumen_layout)

        self.type_pills_layout = QHBoxLayout()
        self.type_pills_layout.setSpacing(8)
        layout.addLayout(self.type_pills_layout)

        filtros_layout = QHBoxLayout()
        filtros_layout.setSpacing(12)

        self.codigo_filter = QLineEdit(self)
        self.codigo_filter.setPlaceholderText("Buscar código de generación…")
        filtros_layout.addWidget(QLabel("Código:", self))
        filtros_layout.addWidget(self.codigo_filter)

        self.fecha_inicio = QDateEdit(self)
        self.fecha_inicio.setCalendarPopup(True)
        self.fecha_fin = QDateEdit(self)
        self.fecha_fin.setCalendarPopup(True)
        filtros_layout.addWidget(QLabel("Fecha de emisión:", self))
        filtros_layout.addWidget(self.fecha_inicio)
        filtros_layout.addWidget(QLabel("→", self))
        filtros_layout.addWidget(self.fecha_fin)

        self.tipo_filter = QComboBox(self)
        filtros_layout.addWidget(QLabel("Tipo:", self))
        filtros_layout.addWidget(self.tipo_filter)

        self.estado_filter = QComboBox(self)
        filtros_layout.addWidget(QLabel("Estado:", self))
        filtros_layout.addWidget(self.estado_filter)

        self.resultados_label = QLabel("Mostrando 0 de 0", self)
        filtros_layout.addWidget(self.resultados_label)
        filtros_layout.addStretch(1)

        layout.addLayout(filtros_layout)

        self.table = QTableWidget(self)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table)

        self.exclusiones_layout = QVBoxLayout()
        self.exclusiones_layout.setSpacing(6)
        self.exclusiones_layout.setContentsMargins(0, 0, 0, 0)
        self.exclusion_sections: dict[str, _ExclusionSection] = {}
        for motivo in EXCLUSION_MOTIVOS:
            section = _ExclusionSection(motivo, self)
            self.exclusion_sections[motivo] = section
            self.exclusiones_layout.addWidget(section)
        layout.addLayout(self.exclusiones_layout)

        self.codigo_filter.textChanged.connect(self._apply_filters)
        self.fecha_inicio.dateChanged.connect(self._apply_filters)
        self.fecha_fin.dateChanged.connect(self._apply_filters)
        self.tipo_filter.currentIndexChanged.connect(self._apply_filters)
        self.estado_filter.currentIndexChanged.connect(self._apply_filters)

        self._configure_table()

    def _configure_table(self) -> None:
        if self._incluye_debito:
            headers = [
                "Fecha",
                "Tipo",
                "Código generación",
                "Número control",
                "Estado base",
                "Estado manual",
                "Fuente estado",
                "Cliente",
                "Identificación",
                "Exentas",
                "No sujetas",
                "Gravadas",
                "Débito",
                "Total",
                "Sello recepción",
            ]
        else:
            headers = [
                "Fecha",
                "Tipo",
                "Código generación",
                "Número control",
                "Estado base",
                "Estado manual",
                "Fuente estado",
                "Cliente",
                "Identificación",
                "Exentas",
                "No sujetas",
                "Gravadas",
                "Total",
                "Sello recepción",
            ]
        self._columns = headers
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        header = self.table.horizontalHeader()
        header.setStretchLastSection(True)
        for idx in range(len(headers)):
            if idx <= 3:
                mode = QHeaderView.ResizeToContents
            else:
                mode = QHeaderView.Stretch
            header.setSectionResizeMode(idx, mode)

    def set_data(self, data: AnexoPreviewData, periodo: tuple[date, date]) -> None:
        self._data = data
        self._rows = list(data.incluidos)
        self._periodo = periodo
        self._populate_filters()
        self._update_summary()
        self._update_exclusions()
        self._apply_filters()

    def _populate_filters(self) -> None:
        inicio, fin = self._periodo
        self.fecha_inicio.blockSignals(True)
        self.fecha_fin.blockSignals(True)
        self.fecha_inicio.setDate(QDate(inicio.year, inicio.month, inicio.day))
        self.fecha_fin.setDate(QDate(fin.year, fin.month, fin.day))
        self.fecha_inicio.blockSignals(False)
        self.fecha_fin.blockSignals(False)

        tipos = sorted({row.tipo for row in self._rows if row.tipo})
        estados = sorted({estado for row in self._rows for estado in (row.estado_base, row.estado_manual) if estado})

        self.tipo_filter.blockSignals(True)
        self.tipo_filter.clear()
        self.tipo_filter.addItem("Todos", None)
        for tipo in tipos:
            self.tipo_filter.addItem(str(tipo), tipo)
        self.tipo_filter.blockSignals(False)

        self.estado_filter.blockSignals(True)
        self.estado_filter.clear()
        self.estado_filter.addItem("Todos", None)
        for estado in estados:
            self.estado_filter.addItem(str(estado), estado)
        self.estado_filter.blockSignals(False)

    def _update_summary(self) -> None:
        if not self._data:
            return
        self.candidatos_label.setText(f"Candidatos leídos: {self._data.candidatos}")
        self.incluidos_label.setText(f"Incluidos (aptos): {self._data.total_incluidos}")
        self.excluidos_label.setText(f"Excluidos: {self._data.total_excluidos}")

        # Limpiar pills existentes
        while self.type_pills_layout.count():
            item = self.type_pills_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        for tipo, conteo in self._data.conteos_por_tipo.items():
            tipo_display = short_tipo_label(tipo) or tipo
            texto = f"{tipo_display}: {conteo.get('incluidos', 0)} incluidos / {conteo.get('excluidos', 0)} excluidos"
            etiqueta = QLabel(texto, self)
            etiqueta.setStyleSheet(
                "border: 1px solid #ccc; border-radius: 12px; padding: 4px 8px; background: #f5f5f5;"
            )
            self.type_pills_layout.addWidget(etiqueta)
        self.type_pills_layout.addStretch(1)

    def _update_exclusions(self) -> None:
        if not self._data:
            return
        for motivo, section in self.exclusion_sections.items():
            section.update_entries(self._data.excluidos.get(motivo, []))

    def _apply_filters(self) -> None:
        if self._data is None:
            return
        codigo = self.codigo_filter.text().strip().lower()
        tipo = self.tipo_filter.currentData()
        estado = self.estado_filter.currentData()
        inicio = self.fecha_inicio.date().toPyDate()
        fin = self.fecha_fin.date().toPyDate()

        filtrados: list[PreviewRow] = []
        for row in self._rows:
            if codigo and codigo not in row.codigo_generacion.lower():
                continue
            if tipo and row.tipo != tipo:
                continue
            if estado and estado not in {row.estado_base, row.estado_manual}:
                continue
            fecha_obj = row.fecha_obj
            if fecha_obj:
                fecha_date = fecha_obj.date()
                if fecha_date < inicio or fecha_date > fin:
                    continue
            filtrados.append(row)

        self._filtered_rows = filtrados
        self.resultados_label.setText(f"Mostrando {len(filtrados)} de {len(self._rows)}")
        self._populate_table()

    def _populate_table(self) -> None:
        self.table.setRowCount(len(self._filtered_rows))
        numeric_headers = {"Exentas", "No sujetas", "Gravadas", "Débito", "Total"}
        for fila, row in enumerate(self._filtered_rows):
            datos = [
                row.fecha,
                row.tipo,
                row.codigo_generacion,
                row.numero_control or "",
                row.estado_base or "—",
                self._estado_manual_text(row),
                row.estado_fuente or "",
                row.cliente,
                row.identificacion or "",
                row.totales.get("exentas", "0.00"),
                row.totales.get("no_sujetas", "0.00"),
                row.totales.get("gravadas", "0.00"),
            ]
            if self._incluye_debito:
                datos.append(row.totales.get("debito", "0.00"))
            datos.append(row.totales.get("total", "0.00"))
            datos.append(row.sello_recepcion or "")
            for col, texto in enumerate(datos):
                item = QTableWidgetItem(str(texto))
                header = self._columns[col]
                if header in numeric_headers:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if col == 5 and row.estado_override:
                    item.setBackground(QColor("#FFF4CE"))
                self.table.setItem(fila, col, item)

        self.table.resizeRowsToContents()

    @staticmethod
    def _estado_manual_text(row: PreviewRow) -> str:
        if not row.estado_manual:
            return "—"
        texto = row.estado_manual
        if row.estado_override:
            texto = f"{texto} (override)"
        return texto


class AnexosPreviewDialog(QDialog):
    def __init__(self, preview: DeclaracionPreview, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Previsualización de anexos DTE")
        self.preview = preview
        self.resize(1100, 720)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        header_layout = QHBoxLayout()
        periodo_texto = f"Período: {preview.periodo[:4]}-{preview.periodo[4:]}"
        header_layout.addWidget(QLabel(periodo_texto, self))
        header_layout.addStretch(1)
        self.export_button = QPushButton("Exportar diagnóstico", self)
        header_layout.addWidget(self.export_button)
        layout.addLayout(header_layout)

        self.tabs = QTabWidget(self)
        self.tab_i = AnexoPreviewTab("Anexo I", incluye_debito=True, parent=self)
        self.tab_ii = AnexoPreviewTab("Anexo II", incluye_debito=False, parent=self)
        self.tabs.addTab(self.tab_i, "Anexo I (Contribuyentes)")
        self.tabs.addTab(self.tab_ii, "Anexo II (Consumidor final)")
        layout.addWidget(self.tabs)

        botones = QDialogButtonBox(QDialogButtonBox.Close, parent=self)
        botones.rejected.connect(self.reject)
        layout.addWidget(botones)

        periodo = _periodo_bounds(preview.periodo)
        self.tab_i.set_data(preview.anexo_i, periodo)
        self.tab_ii.set_data(preview.anexo_ii, periodo)

        self.export_button.clicked.connect(self._exportar_diagnostico)

    def _exportar_diagnostico(self) -> None:
        texto = self._build_diagnostic_text()
        QApplication.clipboard().setText(texto)
        QMessageBox.information(self, "Diagnóstico", "Resumen copiado al portapapeles.")

    def _build_diagnostic_text(self) -> str:
        secciones: list[str] = []
        secciones.append(self._format_section("Anexo I", self.preview.anexo_i))
        secciones.append(self._format_section("Anexo II", self.preview.anexo_ii))
        return "\n\n".join(secciones)

    @staticmethod
    def _format_section(nombre: str, data: AnexoPreviewData) -> str:
        lineas = [
            nombre,
            f"Candidatos leídos: {data.candidatos}",
            f"Incluidos (aptos): {data.total_incluidos}",
            f"Excluidos: {data.total_excluidos}",
            "Por tipo:",
        ]
        for tipo, conteo in data.conteos_por_tipo.items():
            tipo_display = short_tipo_label(tipo) or tipo
            lineas.append(
                f"  {tipo_display}: {conteo.get('incluidos', 0)} incluidos / {conteo.get('excluidos', 0)} excluidos"
            )
        lineas.append("Motivos:")
        for motivo in EXCLUSION_MOTIVOS:
            entradas = data.excluidos.get(motivo, [])
            lineas.append(f"  {motivo}: {len(entradas)}")
            for entry in entradas[:3]:
                texto = entry.to_display() or entry.describe() or "—"
                lineas.append(f"    - {texto}")
        return "\n".join(lineas)


__all__ = ["AnexosPreviewDialog"]
