from __future__ import annotations

from decimal import Decimal, getcontext, ROUND_HALF_UP, InvalidOperation
from pathlib import Path
import json
import logging
import base64
import shutil
import requests
from datetime import date, timedelta, datetime
from typing import Any, Mapping, MutableMapping, Optional

logger = logging.getLogger(__name__)
from PyQt5.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QSpinBox,
    QDoubleSpinBox, QPushButton, QListWidget, QListWidgetItem, QMessageBox, QCheckBox, QRadioButton, QComboBox,
    QDateEdit, QTableWidget, QTableWidgetItem, QGroupBox, QFormLayout, QButtonGroup,
    QAbstractItemView, QTextEdit, QStackedLayout, QWidget, QHeaderView, QSizePolicy,
    QFileDialog, QDialogButtonBox, QListView, QFrame, QCompleter, QGridLayout, QScrollArea, QPlainTextEdit,
    QStyledItemDelegate, QStyleOptionViewItem, QLayout
)
from PyQt5.QtCore import (
    Qt,
    QObject,
    QDate,
    QUrl,
    QRegularExpression,
    QSignalBlocker,
    QEvent,
    QSize,
    QTimer,
    QRectF,
    pyqtSignal,
)
from PyQt5.QtGui import (
    QDesktopServices,
    QIntValidator,
    QRegularExpressionValidator,
    QPixmap,
    QPainter,
    QColor,
    QPainterPath,
)

import os
import re

from db import DB

from utils import jws
from utils.certificates import copy_certificate_to_signer_dir, resolve_signer_cert_dir
from utils.catalogos import CONTINGENCIA
from utils.sanitize import solo_digitos
from utils.fiscal_extra import normalize_retencion_payload
from svfe.config import CAT012_DEPARTAMENTOS, CAT013_MUNICIPIOS
from dte import peek_next_correlativo
from utils.party_resolver import Catalogs, normalize_identifier, resolve_party_names
from utils.loading import loading_dialog
from retenciones.service import RetencionCRService
from paths import (
    FACTURAS_CONSUMIDOR_FINAL_DIR,
    FACTURAS_CREDITO_FISCAL_DIR,
    FACTURAS_ARCHIVE_CF_DIR,
    FACTURAS_ARCHIVE_CREDITO_DIR,
    TICKETS_OUTPUT_DIR,
    NOTAS_DEBITO_DIR,
    NOTAS_CREDITO_DIR,
    NOTAS_REMISION_DIR,
    DTES_DIR,
    DTE_FALLIDOS_DIR,
    DTE_FIRMADO_DIR,
    DTES_PENDIENTES_DIR,
    RETENCIONES_DIR,
    ensure_user_dir,
)
getcontext().prec = 28
getcontext().rounding = ROUND_HALF_UP
IVA_RATE = Decimal("0.13")
IVA_FACTOR = Decimal("1") + IVA_RATE

CREDIT_TERM_BACKEND_ROLE = Qt.UserRole + 1

TIPO_CONTRIBUYENTE_OPCIONES = ["Persona Natural", "Persona Jurídica"]


def _normalize_tipo_contribuyente(value: str | None) -> str:
    if not value:
        return TIPO_CONTRIBUYENTE_OPCIONES[0]
    normalized = value.strip().lower()
    mapping = {
        "pn": "persona natural",
        "persona natural": "persona natural",
        "persona jurídica": "persona jurídica",
        "persona juridica": "persona jurídica",
        "pj": "persona jurídica",
    }
    normalized = mapping.get(normalized, normalized)
    for option in TIPO_CONTRIBUYENTE_OPCIONES:
        if option.lower() == normalized:
            return option
    return TIPO_CONTRIBUYENTE_OPCIONES[0]


class _NoWheelFilter(QObject):
    """Evita que la rueda del ratón cambie valores de inputs."""

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Wheel:
            event.ignore()
            return True
        return super().eventFilter(obj, event)


class LoginDialog(QDialog):
    def __init__(self, *args, **kwargs):
        raise RuntimeError("NO DEBERÍA USARSE")

    def exec_(self):
        raise RuntimeError("NO DEBERÍA USARSE")


def get_field(obj, key, default=0):
    if isinstance(obj, dict):
        return obj.get(key, default)
    elif hasattr(obj, "keys"):
        return obj[key] if key in obj.keys() else default
    return default

def validar_nit(nit):
    """Valida que el NIT contenga 9 o 14 dígitos numéricos.

    Una cadena vacía se considera válida para permitir que el campo sea opcional.
    """
    import re
    if nit == "":
        return True
    if not nit:
        return False
    nit_pattern = r"^(?:\d{9}|\d{14})$"
    return bool(re.match(nit_pattern, nit))

def validar_dui(dui):
    """Valida que el DUI contenga exactamente 9 dígitos."""
    import re
    if not dui:
        return False
    dui_pattern = r"^\d{9}$"
    return bool(re.match(dui_pattern, dui))

def validar_email(email):
    """Valida un formato básico de correo electrónico.

    Una cadena vacía se considera válida para permitir que el campo sea opcional.
    """
    import re
    if email == "":
        return True
    if not email:
        return False
    return bool(re.match(r"^[^@]+@[^@]+\.[^@]+$", email))

def validar_nrc(nrc):
    """Valida el formato del NRC salvadoreño (solo dígitos, sin guiones)."""
    import re
    return bool(re.fullmatch(r"\d{1,8}", nrc))

def validar_telefono(telefono):
    """Valida números de teléfono salvadoreños con o sin código de país."""
    import re
    digits = re.sub(r"\D", "", telefono)
    return len(digits) == 8 or (len(digits) == 11 and digits.startswith("503"))

DEPARTAMENTOS = [
    {"codigo": "00", "nombre": "Otro (Para extranjeros)"},
    {"codigo": "01", "nombre": "Ahuachapán"},
    {"codigo": "02", "nombre": "Santa Ana"},
    {"codigo": "03", "nombre": "Sonsonate"},
    {"codigo": "04", "nombre": "Chalatenango"},
    {"codigo": "05", "nombre": "La Libertad"},
    {"codigo": "06", "nombre": "San Salvador"},
    {"codigo": "07", "nombre": "Cuscatlán"},
    {"codigo": "08", "nombre": "La Paz"},
    {"codigo": "09", "nombre": "Cabañas"},
    {"codigo": "10", "nombre": "San Vicente"},
    {"codigo": "11", "nombre": "Usulután"},
    {"codigo": "12", "nombre": "San Miguel"},
    {"codigo": "13", "nombre": "Morazán"},
    {"codigo": "14", "nombre": "La Unión"},
]

MUNICIPIOS = [
    {"codigo": "00", "nombre": "Otro (Para extranjeros)"},
    {"codigo": "13", "nombre": "AHUACHAPAN NORTE"},
    {"codigo": "14", "nombre": "AHUACHAPAN CENTRO"},
    {"codigo": "15", "nombre": "AHUACHAPAN SUR"},
    {"codigo": "14", "nombre": "SANTA ANA NORTE"},
    {"codigo": "15", "nombre": "SANTA ANA CENTRO"},
    {"codigo": "16", "nombre": "SANTA ANA ESTE"},
    {"codigo": "17", "nombre": "SANTA ANA OESTE"},
    {"codigo": "17", "nombre": "SONSONATE NORTE"},
    {"codigo": "18", "nombre": "SONSONATE CENTRO"},
    {"codigo": "19", "nombre": "SONSONATE ESTE"},
    {"codigo": "20", "nombre": "SONSONATE OESTE"},
    {"codigo": "34", "nombre": "CHALATENANGO NORTE"},
    {"codigo": "35", "nombre": "CHALATENANGO CENTRO"},
    {"codigo": "36", "nombre": "CHALATENANGO SUR"},
    {"codigo": "23", "nombre": "LA LIBERTAD NORTE"},
    {"codigo": "24", "nombre": "LA LIBERTAD CENTRO"},
    {"codigo": "25", "nombre": "LA LIBERTAD OESTE"},
    {"codigo": "26", "nombre": "LA LIBERTAD ESTE"},
    {"codigo": "27", "nombre": "LA LIBERTAD COSTA"},
    {"codigo": "28", "nombre": "LA LIBERTAD SUR"},
    {"codigo": "20", "nombre": "SAN SALVADOR NORTE"},
    {"codigo": "21", "nombre": "SAN SALVADOR OESTE"},
    {"codigo": "22", "nombre": "SAN SALVADOR ESTE"},
    {"codigo": "23", "nombre": "SAN SALVADOR CENTRO"},
    {"codigo": "24", "nombre": "SAN SALVADOR SUR"},
    {"codigo": "17", "nombre": "CUSCATLAN NORTE"},
    {"codigo": "18", "nombre": "CUSCATLAN SUR"},
    {"codigo": "23", "nombre": "LA PAZ OESTE"},
    {"codigo": "24", "nombre": "LA PAZ CENTRO"},
    {"codigo": "25", "nombre": "LA PAZ ESTE"},
    {"codigo": "10", "nombre": "CABANAS OESTE"},
    {"codigo": "11", "nombre": "CABANAS ESTE"},
    {"codigo": "14", "nombre": "SAN VICENTE NORTE"},
    {"codigo": "15", "nombre": "SAN VICENTE SUR"},
    {"codigo": "24", "nombre": "USULUTAN NORTE"},
    {"codigo": "25", "nombre": "USULUTAN ESTE"},
    {"codigo": "26", "nombre": "USULUTAN OESTE"},
    {"codigo": "21", "nombre": "SAN MIGUEL NORTE"},
    {"codigo": "22", "nombre": "SAN MIGUEL CENTRO"},
    {"codigo": "23", "nombre": "SAN MIGUEL OESTE"},
    {"codigo": "27", "nombre": "MORAZAN NORTE"},
    {"codigo": "28", "nombre": "MORAZAN SUR"},
    {"codigo": "19", "nombre": "LA UNION NORTE"},
    {"codigo": "20", "nombre": "LA UNION SUR"},
]

DEPARTAMENTOS_SET = {d["codigo"] for d in DEPARTAMENTOS}
MUNICIPIOS_SET = {m["codigo"] for m in MUNICIPIOS}


def _populate_combo(combo, items):
    combo.clear()
    combo.addItem("Seleccione...", "")
    for item in items:
        combo.addItem(f"{item['codigo']} — {item['nombre']}", item["codigo"])
    combo.setEditable(False)
    combo.setMaxVisibleItems(8)
    combo.view().setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)


def _set_combo_value(combo, items, value):
    if not value:
        combo.setCurrentIndex(0)
        return
    idx = combo.findData(value)
    if idx == -1:
        for item in items:
            if item["nombre"] == value:
                idx = combo.findData(item["codigo"])
                break
    if idx >= 0:
        combo.setCurrentIndex(idx)


class ClienteSelectorDialog(QDialog):
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("Seleccionar Cliente")
        layout = QVBoxLayout()
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Buscar cliente por nombre, NIT, NRC, etc.")
        layout.addWidget(self.search_bar)

        self.lista_clientes = QTableWidget(0, 4)
        self.lista_clientes.setHorizontalHeaderLabels(["Código", "Nombre", "NIT", "DUI"])
        self.lista_clientes.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.lista_clientes.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.lista_clientes.setSelectionMode(QAbstractItemView.SingleSelection)
        self.lista_clientes.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.lista_clientes.verticalHeader().setVisible(False)
        self.lista_clientes.setAlternatingRowColors(True)
        self.lista_clientes.setStyleSheet(
            """
            QTableWidget {
                gridline-color: #d0d7e2;
            }
            QTableWidget::item {
                padding: 8px;
            }
            QTableWidget::item:selected {
                background: #d6eaff;
                color: #0a3a60;
            }
            QHeaderView::section {
                background: #f1f5f9;
                font-weight: 600;
                padding: 8px 6px;
            }
            """
        )
        layout.addWidget(self.lista_clientes)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.btn_ok = QPushButton("Seleccionar")
        self.btn_ok.setCursor(Qt.PointingHandCursor)
        self.btn_ok.setStyleSheet(
            """
            QPushButton {
                background-color: #0d6efd;
                color: white;
                padding: 8px 16px;
                border-radius: 6px;
                font-weight: 600;
            }
            QPushButton:hover { background-color: #0b5ed7; }
            QPushButton:pressed { background-color: #0a58ca; }
            """
        )
        self.btn_ok.clicked.connect(self._handle_accept)
        btn_row.addWidget(self.btn_ok)
        layout.addLayout(btn_row)

        self.setLayout(layout)
        self._mostrar_clientes(self.db.get_clientes(""))
        self.search_bar.textChanged.connect(self._filtrar_clientes)
        self.selected_cliente = None
        self.lista_clientes.itemSelectionChanged.connect(self._seleccionar_cliente)
        self.lista_clientes.itemDoubleClicked.connect(self._handle_accept)
        self.resize(900, 600)

    def _mostrar_clientes(self, clientes):
        self.lista_clientes.setRowCount(len(clientes))
        self.clientes_mostrados = clientes[:]  # <-- Actualiza la lista de mostrados
        for row, cli in enumerate(clientes):
            codigo = get_field(cli, "codigo", "")
            nombre = get_field(cli, "nombre", "")
            nit = get_field(cli, "nit", "")
            dui = get_field(cli, "dui", "")
            self.lista_clientes.setItem(row, 0, QTableWidgetItem(str(codigo)))
            self.lista_clientes.setItem(row, 1, QTableWidgetItem(str(nombre)))
            self.lista_clientes.setItem(row, 2, QTableWidgetItem(str(nit)))
            self.lista_clientes.setItem(row, 3, QTableWidgetItem(str(dui)))
        if clientes:
            self.lista_clientes.selectRow(0)

    def _filtrar_clientes(self, texto):
        filtrados = self.db.get_clientes(texto)
        self._mostrar_clientes(filtrados)

    def _seleccionar_cliente(self, item=None):
        idx = self.lista_clientes.currentRow()
        if idx >= 0:
            self.selected_cliente = self.clientes_mostrados[idx]  # <-- Usa la lista de mostrados

    def _handle_accept(self, *args):
        idx = self.lista_clientes.currentRow()
        if idx >= 0:
            self.selected_cliente = self.clientes_mostrados[idx]
        self.accept()

    def get_selected_cliente(self):
        return self.selected_cliente


class EstadoCuentaDialog(QDialog):
    """Ventana para configurar la generación de estados de cuenta."""

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("Generar estado de cuenta")

        layout = QVBoxLayout()

        # Modo de generación
        self.modo_combo = QComboBox()
        self.modo_combo.addItems(["Por cliente", "Por vendedor", "Todos los vendedores"])
        layout.addWidget(self.modo_combo)

        # --- Widgets dinámicos ---
        self.stack = QStackedLayout()

        # Por cliente
        cli_widget = QWidget()
        cli_layout = QVBoxLayout(cli_widget)
        self.cliente_search = QLineEdit()
        self.cliente_search.setPlaceholderText(
            "Buscar cliente por código o nombre..."
        )
        cli_layout.addWidget(self.cliente_search)
        self.cliente_table = QTableWidget(0, 2)
        self.cliente_table.setHorizontalHeaderLabels(["Código", "Nombre"])
        self.cliente_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.cliente_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.cliente_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.cliente_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.clientes = self.db.get_clientes()
        self.clientes_mostrados = list(self.clientes)
        self._mostrar_clientes(self.clientes)
        cli_layout.addWidget(self.cliente_table)
        self.solo_saldo_cliente = QCheckBox("Incluir solo saldos pendientes")
        cli_layout.addWidget(self.solo_saldo_cliente)
        self.stack.addWidget(cli_widget)

        # Por vendedor
        vend_widget = QWidget()
        vend_layout = QVBoxLayout(vend_widget)
        self.vendedor_search = QLineEdit()
        self.vendedor_search.setPlaceholderText(
            "Buscar vendedor por código o nombre..."
        )
        vend_layout.addWidget(self.vendedor_search)
        self.vendedor_table = QTableWidget(0, 2)
        self.vendedor_table.setHorizontalHeaderLabels(["Código", "Nombre"])
        self.vendedor_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.vendedor_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.vendedor_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.vendedor_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # Use trabajadores marked as vendedores when listing available sellers
        self.vendedores = self.db.get_trabajadores(solo_vendedores=True)
        self.vendedores_mostrados = list(self.vendedores)
        self._mostrar_vendedores(self.vendedores)
        vend_layout.addWidget(self.vendedor_table)
        self.solo_saldo_vend = QCheckBox("Incluir solo clientes con saldo")
        vend_layout.addWidget(self.solo_saldo_vend)
        self.stack.addWidget(vend_widget)

        # Todos los vendedores (tabla sin búsqueda)
        todos_widget = QWidget()
        todos_layout = QVBoxLayout(todos_widget)
        self.vendedor_table_all = QTableWidget(0, 2)
        self.vendedor_table_all.setHorizontalHeaderLabels(["Código", "Nombre"])
        self.vendedor_table_all.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.vendedor_table_all.setSelectionBehavior(QTableWidget.SelectRows)
        self.vendedor_table_all.setSelectionMode(QAbstractItemView.NoSelection)
        self.vendedor_table_all.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.vendedor_table_all.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._mostrar_vendedores_all(self.vendedores)
        todos_layout.addWidget(self.vendedor_table_all)
        self.stack.addWidget(todos_widget)

        layout.addLayout(self.stack)

        # Filtros comunes
        filtros = QHBoxLayout()
        self.filtrar_fechas_chk = QCheckBox("Filtrar por fechas")
        self.quick_range = QComboBox()
        self.quick_range.addItems([
            "Personalizado",
            "Hoy",
            "Esta semana",
            "Este mes",
            "Este año",
        ])
        filtros.addWidget(self.filtrar_fechas_chk)
        filtros.addWidget(self.quick_range)
        filtros.addWidget(QLabel("Desde"))
        self.fecha_inicio = QDateEdit(QDate.currentDate())
        self.fecha_inicio.setCalendarPopup(True)
        filtros.addWidget(self.fecha_inicio)
        filtros.addWidget(QLabel("Hasta"))
        self.fecha_fin = QDateEdit(QDate.currentDate())
        self.fecha_fin.setCalendarPopup(True)
        filtros.addWidget(self.fecha_fin)
        layout.addLayout(filtros)

        self.quick_range.setEnabled(False)
        self.fecha_inicio.setEnabled(False)
        self.fecha_fin.setEnabled(False)

        self.incluir_pagos = QCheckBox("Incluir abonos/pagos realizados")
        self.agrupar_factura = QCheckBox("Agrupar por factura")
        self.incluir_detalles = QCheckBox("Incluir detalles de productos")
        layout.addWidget(self.incluir_pagos)
        layout.addWidget(self.agrupar_factura)
        layout.addWidget(self.incluir_detalles)

        # Botones
        btns = QHBoxLayout()
        self.btn_generar = QPushButton("Generar PDF")
        self.btn_imprimir = QPushButton("Generar e imprimir PDF")
        btns.addWidget(self.btn_generar)
        btns.addWidget(self.btn_imprimir)
        layout.addLayout(btns)

        self.setLayout(layout)

        self.modo_combo.currentIndexChanged.connect(self.stack.setCurrentIndex)
        self.filtrar_fechas_chk.toggled.connect(self._toggle_filtro_fechas)
        self.quick_range.currentIndexChanged.connect(self._apply_quick_range)
        self.filtrar_fechas_chk.toggled.connect(self._apply_quick_range)
        self.fecha_inicio.dateChanged.connect(
            lambda *_: self._collect_params(require_selection=False)
        )
        self.fecha_fin.dateChanged.connect(
            lambda *_: self._collect_params(require_selection=False)
        )
        self.cliente_search.textChanged.connect(self._filtrar_clientes)
        self.vendedor_search.textChanged.connect(self._filtrar_vendedores)
        self.cliente_table.itemSelectionChanged.connect(self._seleccionar_cliente)
        self.vendedor_table.itemSelectionChanged.connect(self._seleccionar_vendedor)

        self.btn_generar.clicked.connect(self._generar_pdf)
        self.btn_imprimir.clicked.connect(self._generar_e_imprimir_pdf)

        self._toggle_filtro_fechas(False)

    def _toggle_filtro_fechas(self, checked):
        self.quick_range.setEnabled(checked)
        custom = self.quick_range.currentIndex() == 0
        self.fecha_inicio.setEnabled(checked and custom)
        self.fecha_fin.setEnabled(checked and custom)
        if checked:
            self._apply_quick_range()
        else:
            self._collect_params(require_selection=False)

    def _apply_quick_range(self):
        if not self.filtrar_fechas_chk.isChecked():
            self._collect_params(require_selection=False)
            return
        option = self.quick_range.currentText()
        today = date.today()
        if option == "Hoy":
            start = end = today
            self.fecha_inicio.setDate(QDate(start))
            self.fecha_fin.setDate(QDate(end))
            self.fecha_inicio.setEnabled(False)
            self.fecha_fin.setEnabled(False)
        elif option == "Esta semana":
            start = today - timedelta(days=today.weekday())
            end = start + timedelta(days=6)
            self.fecha_inicio.setDate(QDate(start))
            self.fecha_fin.setDate(QDate(end))
            self.fecha_inicio.setEnabled(False)
            self.fecha_fin.setEnabled(False)
        elif option == "Este mes":
            start = today.replace(day=1)
            if today.month == 12:
                end = date(today.year, 12, 31)
            else:
                end = date(today.year, today.month + 1, 1) - timedelta(days=1)
            self.fecha_inicio.setDate(QDate(start))
            self.fecha_fin.setDate(QDate(end))
            self.fecha_inicio.setEnabled(False)
            self.fecha_fin.setEnabled(False)
        elif option == "Este año":
            start = date(today.year, 1, 1)
            end = date(today.year, 12, 31)
            self.fecha_inicio.setDate(QDate(start))
            self.fecha_fin.setDate(QDate(end))
            self.fecha_inicio.setEnabled(False)
            self.fecha_fin.setEnabled(False)
        else:
            self.fecha_inicio.setEnabled(True)
            self.fecha_fin.setEnabled(True)
        self._collect_params(require_selection=False)

    def _mostrar_clientes(self, clientes):
        self.cliente_table.setRowCount(len(clientes))
        for row, c in enumerate(clientes):
            self.cliente_table.setItem(row, 0, QTableWidgetItem(c.get("codigo", "")))
            self.cliente_table.setItem(row, 1, QTableWidgetItem(c.get("nombre", "")))
        self.clientes_mostrados = list(clientes)

    def _filtrar_clientes(self, texto: str):
        texto = texto.lower()
        filtrados = [
            c
            for c in self.clientes
            if texto in (c.get("codigo", "") or "").lower()
            or texto in (c.get("nombre", "") or "").lower()
        ]
        self._mostrar_clientes(filtrados)

    def _seleccionar_cliente(self):
        idx = self.cliente_table.currentRow()
        if 0 <= idx < len(self.clientes_mostrados):
            self.selected_cliente = self.clientes_mostrados[idx]

    def _mostrar_vendedores(self, vendedores):
        self.vendedor_table.setRowCount(len(vendedores))
        for row, v in enumerate(vendedores):
            self.vendedor_table.setItem(row, 0, QTableWidgetItem(v.get("codigo", "")))
            self.vendedor_table.setItem(row, 1, QTableWidgetItem(v.get("nombre", "")))
        self.vendedores_mostrados = list(vendedores)

    def _mostrar_vendedores_all(self, vendedores):
        self.vendedor_table_all.setRowCount(len(vendedores))
        for row, v in enumerate(vendedores):
            self.vendedor_table_all.setItem(row, 0, QTableWidgetItem(v.get("codigo", "")))
            self.vendedor_table_all.setItem(row, 1, QTableWidgetItem(v.get("nombre", "")))

    def _filtrar_vendedores(self, texto: str):
        texto = texto.lower()
        filtrados = [
            v
            for v in self.vendedores
            if texto in (v.get("codigo", "") or "").lower()
            or texto in (v.get("nombre", "") or "").lower()
        ]
        self._mostrar_vendedores(filtrados)

    def _seleccionar_vendedor(self):
        idx = self.vendedor_table.currentRow()
        if 0 <= idx < len(self.vendedores_mostrados):
            self.selected_vendedor = self.vendedores_mostrados[idx]

    # ---- Generación de PDF -----
    def _collect_params(self, require_selection: bool = True):
        modo_idx = self.modo_combo.currentIndex()
        modo = "cliente" if modo_idx == 0 else "vendedor" if modo_idx == 1 else "todos"
        params = {
            "modo": modo,
            "fecha_inicio": self.fecha_inicio.date().toString("yyyy-MM-dd")
            if self.filtrar_fechas_chk.isChecked()
            else "",
            "fecha_fin": self.fecha_fin.date().toString("yyyy-MM-dd")
            if self.filtrar_fechas_chk.isChecked()
            else "",
            "incluir_pagos": self.incluir_pagos.isChecked(),
            "agrupar_factura": self.agrupar_factura.isChecked(),
            "incluir_detalles": self.incluir_detalles.isChecked(),
        }
        if modo == "cliente":
            idx = self.cliente_table.currentRow()
            if idx < 0 or idx >= len(self.clientes_mostrados):
                if require_selection:
                    QMessageBox.warning(
                        self, "Validación", "No se ha seleccionado ningún cliente."
                    )
                return None
            params["cliente_id"] = self.clientes_mostrados[idx].get("id")
        if modo == "vendedor":
            idx = self.vendedor_table.currentRow()
            if idx < 0 or idx >= len(self.vendedores_mostrados):
                if require_selection:
                    QMessageBox.warning(
                        self, "Validación", "No se ha seleccionado ningún vendedor."
                    )
                return None
            params["vendedor_id"] = self.vendedores_mostrados[idx].get("id")
        return params

    def _generar_pdf(self):
        params = self._collect_params()
        if params is None:
            return
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Guardar PDF",
            "estado_cuenta.pdf",
            "PDF Files (*.pdf)"
        )
        if not filename:
            return
        from estado_cuenta_pdf import generar_estado_cuenta_pdf
        try:
            generar_estado_cuenta_pdf(self.db, archivo=filename, **params)
            QMessageBox.information(self, "Estado de cuenta", f"Archivo generado en {filename}")
        except Exception as e:
            QMessageBox.warning(self, "Estado de cuenta", f"Error: {e}")

    def _generar_e_imprimir_pdf(self):
        params = self._collect_params()
        if params is None:
            return
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Guardar PDF",
            "estado_cuenta.pdf",
            "PDF Files (*.pdf)"
        )
        if not filename:
            return
        from estado_cuenta_pdf import generar_estado_cuenta_pdf
        try:
            generar_estado_cuenta_pdf(self.db, archivo=filename, **params)
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath(filename)))
        except Exception as e:
            QMessageBox.warning(self, "Estado de cuenta", f"Error: {e}")


class ProductDialogBase:
    """Mixin with shared helper methods for product selection dialogs."""

    def _resolve_manager_db(self):
        """Busca manager y db navegando padres, útil si el widget fue re-parentado."""
        manager = getattr(self, "manager", None)
        db = getattr(self, "db", None)
        parent = self.parent() if hasattr(self, "parent") else None
        chain = []
        while parent is not None and (manager is None or db is None):
            chain.append(type(parent).__name__)
            manager = manager or getattr(parent, "manager", None)
            db = db or getattr(parent, "db", None)
            if manager and hasattr(manager, "db") and db is None:
                db = manager.db
            parent = parent.parent() if hasattr(parent, "parent") else None
        logger.info(
            "Resolver manager/db: manager=%s db=%s chain=%s self.db=%s",
            bool(manager),
            bool(db),
            "->".join(chain) if chain else "(self)",
            bool(getattr(self, "db", None)),
        )
        return manager, db

    def _mostrar_productos(self, productos):
        self.product_list.clear()
        for p in productos:
            codigo_lote = p.get("codigo_lote")
            lote_segment = f" | Lote: {codigo_lote}" if codigo_lote else ""
            texto = (
                f"{p.get('nombre', '')} | Código: {p.get('codigo', '')} | Stock: {p.get('stock', 0)}"
                f"{lote_segment} | Vence: {p.get('fecha_vencimiento', '')}"
            )
            item = QListWidgetItem(texto)
            stock = p.get("stock", 0)
            if stock < 5:
                item.setBackground(QColor("red"))
            elif stock < 10:
                item.setBackground(QColor("orange"))
            elif stock < 25:
                item.setBackground(QColor("yellow"))
            else:
                item.setBackground(QColor("lightgreen"))
            self.product_list.addItem(item)
        self.productos = productos

    def _filtrar_productos(self, texto):
        texto = texto.lower()
        filtrados = [
            p for p in self._productos_original
            if texto in p.get("nombre", "").lower()
            or texto in p.get("codigo", "").lower()
            or texto in (
                f"{p.get('nombre', '')} | Código: {p.get('codigo', '')} | Stock: {p.get('stock', 0)}"
                f"{' | Lote: ' + p.get('codigo_lote', '') if p.get('codigo_lote') else ''} | "
                f"Vence: {p.get('fecha_vencimiento', '')}"
            ).lower()
            or texto in (p.get("codigo_lote", "") or "").lower()
        ]
        self._mostrar_productos(filtrados)
        if hasattr(self, "_actualizar_presentacion_combo"):
            try:
                self._actualizar_presentacion_combo()
            except Exception:
                logger.debug("No se pudo refrescar presentaciones tras filtrar productos", exc_info=True)

    def _fill_presentaciones_combo(self, combo: QComboBox, producto: Mapping[str, Any] | None) -> None:
        """Llena un combo con la unidad base y las presentaciones del producto."""
        with QSignalBlocker(combo):
            combo.clear()
            combo.addItem("Unidad Base (x1)", 1)
            if not producto:
                combo.setCurrentIndex(0)
                return
            presentaciones = producto.get("presentaciones") or []
            if isinstance(presentaciones, list):
                for pres in presentaciones:
                    try:
                        factor = float(pres.get("factor") or 0)
                    except Exception:
                        continue
                    if factor <= 0:
                        continue
                    nombre_raw = str(pres.get("nombre") or "").strip()
                    label = f"{nombre_raw} (x{factor:g})" if nombre_raw else f"Presentación x{factor:g}"
                    combo.addItem(label, factor)
                    combo.setItemData(combo.count() - 1, pres, Qt.UserRole + 1)
            combo.setCurrentIndex(0)

    def _presentacion_factor_from_combo(self, combo: QComboBox) -> float:
        """Devuelve el factor de conversión seleccionado (>=1)."""
        data = combo.currentData()
        try:
            factor = float(data)
        except Exception:
            factor = 1.0
        if factor <= 0:
            factor = 1.0
        return factor

    def _presentacion_data_from_combo(self, combo: QComboBox) -> Mapping[str, Any]:
        idx = combo.currentIndex()
        data = combo.itemData(idx, Qt.UserRole + 1)
        return data if isinstance(data, Mapping) else {}

    def _toggle_comision_inputs(self, state):
        enabled = self.comision_chk.isChecked()
        self.comision_pct_spin.setEnabled(enabled)
        self.comision_tipo_combo.setEnabled(enabled)
        if not enabled:
            self.comision_pct_spin.setValue(0)
        if hasattr(self, "_recalcular_totales"):
            self._recalcular_totales()

    def _apply_card_styles(self):
        """Estilo base de tarjetas moderno para diálogos POS."""
        self.setObjectName("DialogRoot")
        self.setStyleSheet(
            """
#DialogRoot {
    background-color: #f5f6f8;
}
QFrame#Card, QFrame#PosCardTop, QFrame#PosCardBottom {
    background: #ffffff;
    border: 1px solid #e0e0e0;
    border-radius: 10px;
}
QLabel#CardTitle {
    font-size: 15px;
    font-weight: 700;
    color: #0f172a;
    margin: 0;
    padding: 0 0 2px 0;
}
QLabel#TotalHighlight {
    font-size: 18px;
    font-weight: 800;
    color: #0f172a;
}
QPushButton[variant="primary"] {
    background: #2563eb;
    color: #ffffff;
    border: none;
    border-radius: 6px;
    padding: 10px 14px;
    font-weight: 600;
}
QPushButton[variant="primary"]:hover {
    background: #1e4fd9;
}
QPushButton[variant="secondary"] {
    background: #0ea5e9;
    color: #ffffff;
    border: none;
    border-radius: 6px;
    padding: 8px 12px;
    font-weight: 600;
}
QPushButton[variant="clientAdd"] {
    background: #1f3f78;
    color: #ffffff;
    border: none;
    border-radius: 8px;
    padding: 9px 14px;
    font-weight: 600;
}
QPushButton[variant="clientAdd"]:hover {
    background: #274a8a;
}
QPushButton {
    padding: 8px 12px;
    border-radius: 6px;
}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit {
    padding: 6px 8px;
    border: 1px solid #d0d5dd;
    border-radius: 6px;
    background: #ffffff;
}
QTableWidget {
    border: 1px solid #e0e0e0;
    gridline-color: transparent;
    alternate-background-color: #fafafa;
    selection-background-color: #dbeafe;
    selection-color: #0f172a;
}
QHeaderView::section {
    background: #f1f3f5;
    padding: 8px 6px;
    border: none;
    border-right: 1px solid #e0e0e0;
    font-weight: 600;
}
"""
        )

    def _install_no_wheel_filter(self):
        """Bloquea cambios con la rueda en combos y spin para permitir solo scroll."""
        blocker = getattr(self, "_wheel_event_filter", None)
        if blocker is None:
            blocker = _NoWheelFilter(self)
            self._wheel_event_filter = blocker
        for cls in (QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit):
            for widget in self.findChildren(cls):
                widget.installEventFilter(blocker)

    def _actualizar_Distribuidor_por_producto(self):
        idx = self.product_list.currentRow()
        if idx < 0 or idx >= len(self.productos):
            return
        lote = self.productos[idx]
        target_name = None
        if hasattr(self, "_producto_Distribuidor_map") and isinstance(lote, Mapping):
            prod_name = get_field(lote, "nombre", "")
            target_name = self._producto_Distribuidor_map.get(prod_name)
        distribuidor_id = None
        if isinstance(lote, Mapping):
            distribuidor_id = lote.get("Distribuidor_id")
        Distribuidores = getattr(self, "Distribuidores", None)
        if Distribuidores is None and hasattr(self, "parent") and self.parent() and hasattr(self.parent(), "manager"):
            Distribuidores = getattr(self.parent().manager, "_Distribuidores", None)
        if Distribuidores:
            for i, dist in enumerate(Distribuidores):
                if isinstance(dist, Mapping) and dist.get("id") == distribuidor_id:
                    if hasattr(self, "Distribuidor_combo"):
                        self.Distribuidor_combo.setCurrentIndex(i)
                    break
                if target_name and isinstance(dist, str) and dist.strip() == target_name:
                    if hasattr(self, "Distribuidor_combo"):
                        self.Distribuidor_combo.setCurrentIndex(i)
                    break

    def _restrict_retencion_to_one_percent(self) -> None:
        """Limita la UI de retención a 1% y oculta configuraciones avanzadas."""
        if not hasattr(self, "retencion_tasa_spin"):
            return
        try:
            self.retencion_tasa_spin.blockSignals(True)
            self.retencion_tasa_spin.setRange(1.0, 1.0)
            self.retencion_tasa_spin.setValue(1.0)
            self.retencion_tasa_spin.setButtonSymbols(QDoubleSpinBox.NoButtons)
        finally:
            self.retencion_tasa_spin.blockSignals(False)
        combo = getattr(self, "retencion_codigo_combo", None)
        if combo is not None:
            if combo.count() == 0:
                combo.addItem("1% (código 22)", "22")
            idx = combo.findData("22")
            if idx == -1 and combo.count() > 0:
                idx = 0
            if idx >= 0:
                combo.setCurrentIndex(idx)
            combo.setEnabled(False)
            combo.setVisible(False)
        for geo_combo in (
            getattr(self, "retencion_geo_emisor_combo", None),
            getattr(self, "retencion_geo_receptor_combo", None),
        ):
            if geo_combo is not None:
                geo_combo.setEnabled(False)
                geo_combo.setVisible(False)
        form = getattr(self, "_retencion_form_layout", None)
        if isinstance(form, QFormLayout):
            for row in range(form.rowCount()):
                for role in (QFormLayout.LabelRole, QFormLayout.FieldRole):
                    item = form.itemAt(row, role)
                    if item is not None and item.widget() is not None:
                        item.widget().setVisible(False)
    def _abrir_selector_cliente(self):
        selector = ClienteSelectorDialog(self.db, self)
        if selector.exec_():
            self._set_cliente_actual(selector.get_selected_cliente())

    def _abrir_crear_cliente(self):
        # Busca manager y db de forma robusta y loguea el flujo
        parent = self.parent()
        manager, db = self._resolve_manager_db()
        if manager and not getattr(self, "manager", None):
            self.manager = manager
        if db and not getattr(self, "db", None):
            self.db = db
        if manager is None or db is None:
            logger.warning(
                "No se pudo abrir formulario de cliente: manager=%s db=%s parent=%s",
                manager,
                db,
                type(parent).__name__ if parent else None,
            )
            QMessageBox.warning(self, "Cliente", "No se pudo abrir el formulario de cliente.")
            return
        try:
            codigo_sugerido = db.get_next_cliente_codigo()
        except Exception:
            codigo_sugerido = ""
            logger.exception("No se pudo obtener codigo_sugerido de cliente, se usará vacío")
        dialog = ClienteDialog(parent, codigo_sugerido=codigo_sugerido)
        if dialog.exec_():
            data = dialog.get_data()
            try:
                manager.add_cliente(
                    data["nombre"],
                    data["nrc"],
                    data["nit"],
                    data["dui"],
                    data["giro"],
                    data["codActividad"],
                    data["telefono"],
                    data["email"],
                    data["direccion"],
                    data["departamento"],
                    data["municipio"],
                    data["codigo"],
                    nombreComercial=data["nombreComercial"],
                    tipoContribuyente=data["tipoContribuyente"],
                    razonSocial=data["razonSocial"],
                )
            except Exception as exc:
                logger.exception("Error al agregar cliente desde dialogo de venta", exc_info=exc)
                QMessageBox.warning(self, "Cliente", str(exc))
                return
            nuevo_cli = self._buscar_cliente_creado(manager, data)
            logger.info("Cliente creado desde venta: encontrado=%s codigo=%s nit=%s nrc=%s",
                        bool(nuevo_cli), data.get("codigo"), data.get("nit"), data.get("nrc"))
            if nuevo_cli is None:
                QMessageBox.information(
                    self,
                    "Cliente",
                    "Cliente guardado, pero no se pudo seleccionar automáticamente. "
                    "Por favor selecciónelo manualmente.",
                )
            else:
                self._set_cliente_actual(nuevo_cli)
        else:
            logger.info("Formulario de cliente cancelado o cerrado sin guardar")

    def _buscar_cliente_creado(self, manager, data):
        clientes = getattr(manager, "_clientes", None) or []
        codigo = data.get("codigo")
        nit = data.get("nit")
        nrc = data.get("nrc")
        for cli in clientes:
            if codigo and cli.get("codigo") == codigo:
                return cli
            if nit and cli.get("nit") == nit:
                return cli
            if nrc and cli.get("nrc") == nrc:
                return cli
        # Fallback a DB por si la cache no se actualizó aún
        db = getattr(manager, "db", None)
        if db is not None:
            try:
                for cli in db.get_clientes():
                    if codigo and cli.get("codigo") == codigo:
                        return cli
                    if nit and cli.get("nit") == nit:
                        return cli
                    if nrc and cli.get("nrc") == nrc:
                        return cli
            except Exception as exc:
                logger.warning("No se pudo leer clientes tras crear uno nuevo: %s", exc, exc_info=True)
        return None

    def _set_cliente_actual(self, cli):
        if not cli:
            return
        nombre = get_field(cli, "nombre", "") or get_field(cli, "codigo", "")
        nit = get_field(cli, "nit", "") or ""
        dui = get_field(cli, "dui", "") or ""
        nrc = get_field(cli, "nrc", "") or ""
        prioridad_doc = nit or dui or nrc
        doc_label = "NIT" if nit else "DUI" if dui else "NRC" if nrc else "NIT"
        self.selected_cliente = cli
        doc_fragment = f"{doc_label}: {prioridad_doc}" if prioridad_doc else "Sin documento"
        self.cliente_label.setText(f"{nombre} | {doc_fragment}")

        if hasattr(self, "nrc_edit") and self.nrc_edit is not None:
            self.nrc_edit.setText(prioridad_doc)
        if hasattr(self, "nit_edit") and self.nit_edit is not None:
            self.nit_edit.setText(nrc)
        for attr, key in [
            ("giro_edit", "giro"),
            ("email_edit", "email"),
        ]:
            widget = getattr(self, attr, None)
            if widget is not None:
                widget.setText(get_field(cli, key, ""))
        updater = getattr(self, "_update_retencion_group_state", None)
        if callable(updater):
            updater()

    def _sync_credit_term_payload(self):
        """Mantiene los códigos de plazo y periodo en el formato requerido."""

        if not hasattr(self, "_backend_pago_plazo"):
            self._backend_pago_plazo = ""
        if not hasattr(self, "_backend_pago_periodo"):
            self._backend_pago_periodo = ""

        condicion_combo = getattr(self, "condicion_pago_combo", None)
        if condicion_combo is None or condicion_combo.currentData() != 2:
            self._backend_pago_plazo = ""
            self._backend_pago_periodo = ""
            return

        plazo_combo = getattr(self, "plazo_combo", None)
        if plazo_combo is not None:
            backend_code_raw = plazo_combo.itemData(
                plazo_combo.currentIndex(), CREDIT_TERM_BACKEND_ROLE
            )
            backend_code = "" if backend_code_raw is None else str(backend_code_raw).strip()
            if backend_code not in {"01", "02", "03"}:
                backend_code = ""
            self._backend_pago_plazo = backend_code

        plazo_spin = getattr(self, "plazo_spin", None)
        if plazo_spin is not None:
            periodo_value = int(plazo_spin.value())
            self._backend_pago_periodo = str(periodo_value) if periodo_value > 0 else ""


class RegisterSaleDialog(QDialog, ProductDialogBase):
    venta_validada = pyqtSignal(dict)

    def __init__(
        self,
        productos,
        Distribuidores,
        vendedores_trabajadores,
        parent=None,
        db=None,
        venta_extra=None,
    ):
        super().__init__(parent)
        self.manager = getattr(parent, "manager", None)
        self.db = db or (self.manager.db if self.manager and hasattr(self.manager, "db") else None)
        self.setWindowTitle("Registrar Venta")
        self.setMinimumSize(0, 0)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._apply_card_styles()

        content_widget = QWidget()
        main_layout = QVBoxLayout(content_widget)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(16)

        self.productos = productos
        self.Distribuidores = Distribuidores
        self.vendedores_trabajadores = vendedores_trabajadores
        self.venta_items = []


        left_layout = QVBoxLayout()
        left_layout.setSpacing(12)
        left_layout.setContentsMargins(0, 0, 0, 0)

        def _card(title: str):
            frame = QFrame()
            frame.setObjectName("Card")
            layout = QVBoxLayout(frame)
            layout.setContentsMargins(16, 14, 16, 14)
            layout.setSpacing(10)
            if title:
                header = QLabel(title)
                header.setObjectName("CardTitle")
                header.setStyleSheet("border: none; margin: 0; padding: 0 0 2px 0; font-weight: 700;")
                header.setContentsMargins(0, 0, 0, 0)
                header.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
                header.setFixedHeight(22)
                layout.addWidget(header)
            return frame, layout

        productos_card, productos_layout = _card("Búsqueda y productos")
        productos_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        productos_layout.setContentsMargins(12, 6, 12, 10)
        productos_layout.setSpacing(6)

        # Distribuidor y búsqueda (lado de productos)
        top_row = QHBoxLayout()
        top_row.setSpacing(6)
        top_row.addWidget(QLabel("Distribuidor:"))
        self.Distribuidor_combo = QComboBox()
        if Distribuidores:
            if isinstance(Distribuidores[0], dict):
                self.Distribuidor_combo.addItems([d.get("nombre", "") for d in Distribuidores])
            else:
                self.Distribuidor_combo.addItems(Distribuidores)
        top_row.addWidget(self.Distribuidor_combo, 1)
        productos_layout.addLayout(top_row)

        self.product_search = QLineEdit()
        self.product_search.setPlaceholderText("Buscar producto por nombre o código...")
        productos_layout.addWidget(self.product_search)

        self.product_list = QListWidget()
        self._productos_original = list(productos)
        self._mostrar_productos(productos)
        self.product_list.setMinimumHeight(180)
        self.product_list.setMaximumHeight(240)
        self.product_list.setSpacing(2)
        self.product_list.setStyleSheet(
            "QListWidget { border: 1px solid #d4d4d8; border-radius: 6px; }"
            "QListWidget::item { padding: 6px 8px; margin: 2px 4px; border-radius: 4px; }"
            "QListWidget::item:selected { background: #e5f1ff; color: #0f172a; }"
        )
        productos_layout.addWidget(self.product_list)

        # Grid compacto de captura
        grid = QGridLayout()
        grid.setVerticalSpacing(4)
        grid.setHorizontalSpacing(8)
        grid.addWidget(QLabel("Cant."), 0, 0)
        grid.addWidget(QLabel("Unidad/Pres."), 0, 1)
        grid.addWidget(QLabel("P. Unitario"), 0, 2)
        grid.addWidget(QLabel("P. Total"), 0, 3)

        self.cantidad_spin = QSpinBox()
        self.cantidad_spin.setMinimum(1)
        self.cantidad_spin.setMaximum(100000)
        grid.addWidget(self.cantidad_spin, 1, 0)

        self.presentacion_combo = QComboBox()
        grid.addWidget(self.presentacion_combo, 1, 1)

        self.precio_spin = QDoubleSpinBox()
        self.precio_spin.setMinimum(0)
        self.precio_spin.setMaximum(1000000)
        self.precio_spin.setDecimals(2)
        self.precio_spin.setPrefix("$")
        grid.addWidget(self.precio_spin, 1, 2)

        self.precio_total_spin = QDoubleSpinBox()
        self.precio_total_spin.setMinimum(0)
        self.precio_total_spin.setMaximum(100000000)
        self.precio_total_spin.setDecimals(2)
        self.precio_total_spin.setPrefix("$")
        grid.addWidget(self.precio_total_spin, 1, 3)

        self.descuento_spin = QDoubleSpinBox()
        self.descuento_spin.setMinimum(0)
        self.descuento_spin.setMaximum(1000000)
        self.descuento_spin.setDecimals(2)
        self.descuento_spin.setValue(0)
        self.descuento_tipo_combo = QComboBox()
        self.descuento_tipo_combo.addItems(["%", "$"])
        self.descuento_tipo_combo.setCurrentText("$")
        desc_tipo_container = QWidget()
        desc_tipo_container.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        desc_tipo_layout = QHBoxLayout(desc_tipo_container)
        desc_tipo_layout.setContentsMargins(0, 0, 0, 0)
        desc_tipo_layout.setSpacing(6)
        desc_tipo_layout.addWidget(QLabel("Desc."))
        desc_tipo_layout.addWidget(self.descuento_spin)
        desc_tipo_layout.addWidget(self.descuento_tipo_combo)
        desc_tipo_layout.addSpacing(10)
        desc_tipo_layout.addWidget(QLabel("Tipo"))
        self.tipo_fiscal_combo = QComboBox()
        self.tipo_fiscal_combo.addItems(["Venta gravada", "Venta exenta", "Venta no sujeta"])
        desc_tipo_layout.addWidget(self.tipo_fiscal_combo)
        grid.addWidget(desc_tipo_container, 2, 0, 1, 5, alignment=Qt.AlignLeft)
        productos_layout.addLayout(grid)

        # Resumen compacto sin cajas
        self.item_sumas_label = QLabel("Sumas: $0.00")
        self.item_total_sin_desc_label = QLabel("IVA inc.: $0.00")
        self.item_descuento_label = QLabel("Desc.: -$0.00")
        self.item_subtotal_label = QLabel("Subtotal: $0.00")
        for lbl in (
            self.item_sumas_label,
            self.item_total_sin_desc_label,
            self.item_descuento_label,
        ):
            lbl.setStyleSheet("font-weight: 600; color: #0f172a; padding: 0; margin: 0;")
        self.item_subtotal_label.setStyleSheet("font-weight: 700; color: #1d4ed8; padding: 0; margin: 0;")

        summary_layout = QHBoxLayout()
        summary_layout.setSpacing(8)
        summary_layout.setContentsMargins(0, 0, 0, 0)
        summary_layout.addWidget(self.item_sumas_label)
        summary_layout.addWidget(self.item_total_sin_desc_label)
        summary_layout.addWidget(self.item_descuento_label)
        summary_layout.addWidget(self.item_subtotal_label)
        summary_layout.addStretch(1)

        summary_frame = QFrame()
        summary_frame.setStyleSheet("background-color: #f1f5f9; border-radius: 6px; padding: 4px;")
        summary_frame.setLayout(summary_layout)
        productos_layout.addWidget(summary_frame)

        self.descuento_spin.valueChanged.connect(self._recalcular_totales)
        self.descuento_tipo_combo.currentIndexChanged.connect(self._on_descuento_tipo_changed)

        # Botón agregar a venta
        self.btn_agregar = QPushButton("Agregar a venta")
        self.btn_agregar.setProperty("variant", "primary")
        productos_layout.addWidget(self.btn_agregar)

        carrito_card, carrito_layout = _card("Carrito")
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([
            "Producto", "Cantidad", "Precio U.", "Descuento", "Tipo fiscal", "Eliminar"
        ])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        header_cf = self.table.horizontalHeader()
        header_cf.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header_cf.setSectionResizeMode(0, QHeaderView.Interactive)  # Producto
        self.table.setColumnWidth(0, 190)
        for col, width in [(1, 60), (2, 80), (3, 80), (4, 100)]:
            header_cf.setSectionResizeMode(col, QHeaderView.ResizeToContents)
            self.table.setColumnWidth(col, width)
        self.table.setColumnWidth(5, 140)
        header_cf.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.table.setMinimumHeight(320)
        self.table.setMaximumHeight(440)
        carrito_layout.addWidget(self.table)
        self.btn_agregar.clicked.connect(self._agregar_a_venta)
        self.table.cellClicked.connect(self._eliminar_fila)

        # Resumen (sin IVA para consumidor final) y retención en el carrito
        self.precio_label = QLabel("Precio U.: $0.00")
        self.sumas_label = QLabel("Sumas: $0.00")
        self.subtotal_label = QLabel("Subtotal: $0.00")
        self.total_label = QLabel("Venta total: $0.00")
        self.total_label.setObjectName("TotalHighlight")
        for lbl in (self.precio_label, self.sumas_label, self.subtotal_label):
            lbl.setStyleSheet("padding: 0; margin: 0;")
        carrito_layout.addWidget(self.precio_label)
        carrito_layout.addWidget(self.sumas_label)
        carrito_layout.addWidget(self.subtotal_label)

        self.retencion_group = QGroupBox("Retención de IVA")
        retencion_layout = QVBoxLayout(self.retencion_group)
        retencion_layout.setContentsMargins(9, 9, 9, 9)
        self.retencion_checkbox = QCheckBox("Aplicar retención de IVA")
        self._retencion_catalog_ok = False

        self.retencion_codigo_combo = QComboBox()
        self.retencion_tasa_spin = QDoubleSpinBox()
        self.retencion_tasa_spin.setRange(0, 100)
        self.retencion_tasa_spin.setDecimals(3)
        self.retencion_tasa_spin.setSingleStep(0.1)
        self.retencion_tasa_spin.setValue(1.0)
        self.retencion_geo_emisor_combo = QComboBox()
        self.retencion_geo_receptor_combo = QComboBox()
        for code in [f"{i:02d}" for i in range(1, 23)]:
            self.retencion_geo_emisor_combo.addItem(code, code)
            self.retencion_geo_receptor_combo.addItem(code, code)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        form.addRow("Código MH (CAT-006)", self.retencion_codigo_combo)
        form.addRow("Tasa (%)", self.retencion_tasa_spin)
        form.addRow("Geo emisor (01-22)", self.retencion_geo_emisor_combo)
        form.addRow("Geo receptor (01-22)", self.retencion_geo_receptor_combo)
        retencion_layout.addLayout(form)

        self.retencion_base_label = QLabel("Base sujeta: $0.00")
        self.retencion_iva_label = QLabel("IVA retenido (1%): $0.00")
        ret_header = QHBoxLayout()
        ret_header.setSpacing(10)
        ret_header.addWidget(self.retencion_checkbox)
        ret_header.addSpacing(12)
        ret_header.addWidget(self.retencion_base_label)
        ret_header.addSpacing(12)
        ret_header.addWidget(self.retencion_iva_label)
        ret_header.addStretch(1)
        retencion_layout.insertLayout(0, ret_header)
        self._restrict_retencion_to_one_percent()
        carrito_layout.addWidget(self.retencion_group)
        self.retencion_checkbox.toggled.connect(self._update_retencion_summary)
        self.retencion_tasa_spin.valueChanged.connect(self._update_retencion_summary)
        self.retencion_codigo_combo.currentIndexChanged.connect(self._update_retencion_summary)
        self.retencion_geo_emisor_combo.currentIndexChanged.connect(self._update_retencion_summary)
        self.retencion_geo_receptor_combo.currentIndexChanged.connect(self._update_retencion_summary)

        carrito_layout.addWidget(self.total_label)

        # Botón para registrar la venta (debajo del total)
        self.btn_ok = QPushButton("Registrar")
        self.btn_ok.setProperty("variant", "primary")
        carrito_layout.addWidget(self.btn_ok)
        self.btn_ok.clicked.connect(self._validar_y_accept)

        left_layout.addWidget(productos_card)
        left_layout.addWidget(carrito_card)

        right_layout = QVBoxLayout()
        right_layout.setSpacing(12)
        right_layout.setContentsMargins(0, 0, 0, 0)

        datos_card, datos_layout = _card("Cliente y vendedor")
        # Combo de vendedor trabajador
        datos_layout.addWidget(QLabel("Vendedor (trabajador):"))
        self.vendedor_combo = QComboBox()
        self.vendedor_combo.addItem("Sin vendedor")
        for v in vendedores_trabajadores:
            self.vendedor_combo.addItem(v["nombre"])
        datos_layout.addWidget(self.vendedor_combo)

        # Comisión para el vendedor
        com_layout = QHBoxLayout()
        com_layout.setContentsMargins(0, 0, 0, 0)
        com_layout.setSpacing(8)
        self.comision_chk = QCheckBox("Aplicar comisión")
        com_layout.addWidget(self.comision_chk)
        com_layout.addWidget(QLabel("%"))
        self.comision_pct_spin = QDoubleSpinBox()
        self.comision_pct_spin.setRange(0, 100)
        self.comision_pct_spin.setDecimals(2)
        self.comision_pct_spin.setEnabled(False)
        self.comision_pct_spin.setMaximumWidth(90)
        com_layout.addWidget(self.comision_pct_spin)
        self.comision_tipo_combo = QComboBox()
        self.comision_tipo_combo.addItems(["Incluida en el precio"])
        self.comision_tipo_combo.setEnabled(False)
        self.comision_tipo_combo.setMinimumWidth(160)
        com_layout.addWidget(self.comision_tipo_combo)
        com_layout.addStretch(1)
        self.comision_label = QLabel("Comisión: $0.00")
        com_layout.addWidget(self.comision_label)
        datos_layout.addLayout(com_layout)
        self.comision_chk.stateChanged.connect(self._toggle_comision_inputs)
        self.comision_pct_spin.valueChanged.connect(self._recalcular_totales)
        self.comision_tipo_combo.currentIndexChanged.connect(self._recalcular_totales)

        # Cliente selector
        datos_layout.addWidget(QLabel("Cliente:"))
        self.cliente_btn = QPushButton("Seleccionar Cliente")
        self.cliente_btn.setProperty("variant", "secondary")
        datos_layout.addWidget(self.cliente_btn)
        self.cliente_label = QLabel("(Ningún cliente seleccionado)")
        datos_layout.addWidget(self.cliente_label)
        self.selected_cliente = None

        # Campos "Venta a cuenta de" y "DUI/NIT" en la misma fila
        venta_tercero_layout = QGridLayout()
        venta_tercero_layout.setContentsMargins(0, 0, 0, 0)
        venta_tercero_layout.setHorizontalSpacing(8)
        venta_tercero_layout.setVerticalSpacing(4)
        venta_tercero_layout.addWidget(QLabel("Venta a cuenta de:"), 0, 0)
        venta_tercero_layout.addWidget(QLabel("DUI/NIT:"), 0, 1)
        self.venta_a_cuenta_de_edit = QLineEdit()
        self.venta_a_cuenta_de_edit.setPlaceholderText("Nombre")
        venta_tercero_layout.addWidget(self.venta_a_cuenta_de_edit, 1, 0)
        self.venta_documento_edit = QLineEdit()
        self.venta_documento_edit.setPlaceholderText("Documento")
        venta_tercero_layout.addWidget(self.venta_documento_edit, 1, 1)
        venta_tercero_layout.setColumnStretch(0, 1)
        venta_tercero_layout.setColumnStretch(1, 1)
        datos_layout.addLayout(venta_tercero_layout)

        pago_card, pago_layout = _card("Pago y totales")

        # Condición de pago y estado en la misma fila
        pago_estado_layout = QGridLayout()
        pago_estado_layout.setContentsMargins(0, 0, 0, 0)
        pago_estado_layout.setHorizontalSpacing(8)
        pago_estado_layout.addWidget(QLabel("Condición de pago:"), 0, 0)
        self.condicion_pago_combo = QComboBox()
        self.condicion_pago_combo.addItem("Contado", 1)
        self.condicion_pago_combo.addItem("Crédito", 2)
        self.condicion_pago_combo.addItem("Otros", 3)
        pago_estado_layout.addWidget(self.condicion_pago_combo, 0, 1)
        pago_estado_layout.addWidget(QLabel("Estado:"), 0, 2)
        self.estado_combo = QComboBox()
        self.estado_combo.addItems(["Pagada", "Pendiente"])
        pago_estado_layout.addWidget(self.estado_combo, 0, 3)
        pago_estado_layout.setColumnStretch(1, 1)
        pago_estado_layout.setColumnStretch(3, 1)
        pago_layout.addLayout(pago_estado_layout)

        self.condicion_pago_combo.currentIndexChanged.connect(
            self._update_condicion_pago_fields
        )

        self.credit_fields_widget = QWidget()
        credit_layout = QFormLayout(self.credit_fields_widget)
        credit_layout.setContentsMargins(0, 0, 0, 0)

        self.plazo_combo = QComboBox()
        self.plazo_combo.addItem("Seleccionar", "")
        self.plazo_combo.setItemData(0, "", CREDIT_TERM_BACKEND_ROLE)
        self.plazo_combo.addItem("Días (01)", "D")
        self.plazo_combo.setItemData(self.plazo_combo.count() - 1, "01", CREDIT_TERM_BACKEND_ROLE)
        self.plazo_combo.addItem("Meses (02)", "M")
        self.plazo_combo.setItemData(self.plazo_combo.count() - 1, "02", CREDIT_TERM_BACKEND_ROLE)
        self.plazo_combo.addItem("Años (03)", "A")
        self.plazo_combo.setItemData(self.plazo_combo.count() - 1, "03", CREDIT_TERM_BACKEND_ROLE)
        credit_layout.addRow("Plazo:", self.plazo_combo)

        self.plazo_spin = QSpinBox()
        self.plazo_spin.setMinimum(1)
        self.plazo_spin.setValue(1)
        credit_layout.addRow("Cantidad:", self.plazo_spin)

        self._backend_pago_plazo = ""
        self._backend_pago_periodo = ""

        self.plazo_combo.currentIndexChanged.connect(self._sync_credit_term_payload)
        self.plazo_spin.valueChanged.connect(self._sync_credit_term_payload)
        self._sync_credit_term_payload()

        self.referencia_edit = QLineEdit()
        self.referencia_edit.setPlaceholderText("Referencia (opcional)")
        credit_layout.addRow("Referencia:", self.referencia_edit)

        pago_layout.addWidget(self.credit_fields_widget)

        pago_layout.addStretch(1)

        right_layout.addWidget(datos_card)
        right_layout.addWidget(pago_card)

        # --- AGREGA LOS DOS LAYOUTS COMO TARJETAS ---
        card_top = QFrame()
        card_top.setObjectName("PosCardTop")
        card_top.setFrameShape(QFrame.StyledPanel)
        card_top_layout = QVBoxLayout(card_top)
        card_top_layout.setContentsMargins(16, 16, 16, 16)
        card_top_layout.setSpacing(10)
        card_top_layout.addWidget(QLabel("Nueva Venta / Carrito"))
        card_top_layout.addLayout(left_layout)

        card_bottom = QFrame()
        card_bottom.setObjectName("PosCardBottom")
        card_bottom.setFrameShape(QFrame.StyledPanel)
        card_bottom_layout = QVBoxLayout(card_bottom)
        card_bottom_layout.setContentsMargins(16, 16, 16, 16)
        card_bottom_layout.setSpacing(6)
        card_bottom_layout.addWidget(QLabel("Cliente y Pago"))
        card_bottom_layout.addLayout(right_layout)

        # Cliente y pago arriba, carrito abajo (igual a crédito fiscal)
        main_layout.addWidget(card_bottom)
        main_layout.addWidget(card_top)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setWidget(content_widget)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.addWidget(scroll)
        self.setLayout(root_layout)

        # Creamos un diccionario que mapea nombre de producto a nombre de Distribuidor
        self._producto_Distribuidor_map = {}
        # Construimos un diccionario id->nombre para Distribuidores
        Distribuidores_dict = {}
        if parent and hasattr(parent, "manager") and hasattr(parent.manager, "_Distribuidores"):
            for v in parent.manager._Distribuidores:
                Distribuidores_dict[v["id"]] = v["nombre"]
        # Llena el mapa producto->Distribuidor
        for p in productos:
            nombre_prod = get_field(p, "nombre", "")
            Distribuidor_nombre = ""
            Distribuidor_id = None
            # Acceso seguro a Distribuidor_id
            if isinstance(p, dict):
                Distribuidor_id = p.get("Distribuidor_id")
            elif hasattr(p, "keys") and "Distribuidor_id" in p.keys():
                Distribuidor_id = p["Distribuidor_id"]
            if Distribuidor_id and Distribuidor_id in Distribuidores_dict:
                Distribuidor_nombre = Distribuidores_dict[Distribuidor_id]
            self._producto_Distribuidor_map[nombre_prod] = Distribuidor_nombre

        # Estado
        self.productos_data = productos

        # Conexiones
        self.cliente_btn.clicked.connect(self._abrir_selector_cliente)
        self.product_list.currentRowChanged.connect(self._actualizar_precio_defecto)
        self.product_list.currentRowChanged.connect(self._actualizar_presentacion_combo)
        self.cantidad_spin.valueChanged.connect(self._recalcular_totales)
        self.precio_spin.valueChanged.connect(self._recalcular_totales)
        self.precio_total_spin.valueChanged.connect(self._recalcular_totales)
        self.presentacion_combo.currentIndexChanged.connect(self._on_presentacion_changed)
        self.product_search.textChanged.connect(self._filtrar_productos)

        # --- INICIO BLOQUE NUEVO: Actualizar combo de Distribuidor en tiempo real según producto seleccionado ---
        self.product_list.currentRowChanged.connect(self._actualizar_Distribuidor_por_producto)
        # --- FIN BLOQUE NUEVO ---

        # Ajusta el máximo del descuento según el tipo seleccionado
        self._on_descuento_tipo_changed()
        self._update_condicion_pago_fields()
        self._retencion_allowed_flag = False  # Solo aplica para CCF (03)
        self._retencion_warning_shown = False
        self._apply_retencion_visibility()
        self._load_retencion_catalog()
        self.load_payment_data(venta_extra)
        self._update_retencion_group_state()
        self._install_no_wheel_filter()
        self._actualizar_presentacion_combo()
        self._actualizar_presentacion_combo()

    def set_productos_data(self, productos_data):
        self.productos_data = productos_data or []
        self._productos_original = list(self.productos_data)
        self.productos = list(self.productos_data)
        self.product_list.clear()
        self._mostrar_productos(self.productos_data)
        if hasattr(self, "_actualizar_presentacion_combo"):
            self._actualizar_presentacion_combo()

    def clear_carrito(self):
        """Limpia carrito y totales para iniciar una venta desde cero."""
        self.venta_items = []
        self.table.setRowCount(0)
        self.item_sumas_label.setText("Sumas: $0.00")
        self.item_total_sin_desc_label.setText("IVA inc.: $0.00")
        self.item_descuento_label.setText("Desc.: -$0.00")
        self.item_subtotal_label.setText("Subtotal: $0.00")
        self.precio_label.setText("Precio U.: $0.00")
        self.sumas_label.setText("Sumas: $0.00")
        self.subtotal_label.setText("Subtotal: $0.00")
        self.total_label.setText("Venta total: $0.00")
        self.cantidad_spin.setValue(1)
        self.precio_spin.setValue(0)
        self.precio_total_spin.setValue(0)
        self.descuento_spin.setValue(0)
        self.tipo_fiscal_combo.setCurrentIndex(0)
        self.product_list.clearSelection()
        if hasattr(self, "presentacion_combo") and self.presentacion_combo.count() > 0:
            self.presentacion_combo.setCurrentIndex(0)
        self.venta_a_cuenta_de_edit.clear()
        self.venta_documento_edit.clear()

    def _actualizar_precio_defecto(self):
        idx = self.product_list.currentRow()
        if idx < 0:
            self.precio_spin.setValue(0)
            self.precio_total_spin.setValue(0)
            self._recalcular_totales()
            return
        nombre = self.product_list.currentItem().text()
        prod = None
        if 0 <= idx < len(self.productos):
            prod = self.productos[idx]
        elif self.productos_data:
            for p in self.productos_data:
                nombre_prod = get_field(p, "nombre", "")
                if nombre.startswith(nombre_prod):
                    prod = p
                    break
        factor = self._presentacion_factor_from_combo(self.presentacion_combo)
        pres_data = self._presentacion_data_from_combo(self.presentacion_combo)
        precio = 0
        if prod:
            base = get_field(prod, "precio_venta_minorista", 0)
            pres_price = pres_data.get("precio_venta", None)
            if pres_price not in (None, ""):
                try:
                    precio = float(pres_price) / factor if factor else float(pres_price)
                except Exception:
                    precio = base
            else:
                precio = base
        self.precio_spin.blockSignals(True)
        self.precio_total_spin.blockSignals(True)
        self.precio_spin.setValue(float(precio))
        self.precio_total_spin.setValue(float(precio) * self.cantidad_spin.value())
        self.precio_spin.blockSignals(False)
        self.precio_total_spin.blockSignals(False)
        self._recalcular_totales()

    def _actualizar_presentacion_combo(self):
        prod = None
        idx = self.product_list.currentRow()
        if 0 <= idx < len(self.productos):
            prod = self.productos[idx]
        self._fill_presentaciones_combo(self.presentacion_combo, prod)
        self._on_presentacion_changed()

    def _on_presentacion_changed(self):
        factor = self._presentacion_factor_from_combo(self.presentacion_combo)
        try:
            self.cantidad_spin.blockSignals(True)
            self.cantidad_spin.setValue(int(factor) if factor > 0 else 1)
        finally:
            self.cantidad_spin.blockSignals(False)
        self._actualizar_precio_defecto()

    def _actualizar_presentacion_combo(self):
        prod = None
        idx = self.product_list.currentRow()
        if 0 <= idx < len(self.productos):
            prod = self.productos[idx]
        self._fill_presentaciones_combo(self.presentacion_combo, prod)
        self._on_presentacion_changed()

    def _on_presentacion_changed(self):
        self._actualizar_precio_defecto()

    def _toggle_precio_edicion(self):
        # Ambos precios editables; se sincronizan en _recalcular_totales
        self.precio_spin.setEnabled(True)
        self.precio_total_spin.setEnabled(True)
        self._recalcular_totales()



    def _on_descuento_tipo_changed(self):
        tipo = self.descuento_tipo_combo.currentText()
        if tipo == "%":
            self.descuento_spin.setMaximum(100)
        else:
            self.descuento_spin.setMaximum(1000000)
        self._recalcular_totales()


    def _recalcular_totales(self):
        cantidad = self.cantidad_spin.value()
        cantidad = 1 if cantidad <= 0 else cantidad

        sender = self.sender()
        precio_unitario = self.precio_spin.value()
        precio_total = self.precio_total_spin.value()

        if sender is self.precio_total_spin:
            precio_unitario = round(precio_total / cantidad, 6) if cantidad > 0 else 0
            self.precio_spin.blockSignals(True)
            self.precio_spin.setValue(precio_unitario)
            self.precio_spin.blockSignals(False)
        else:
            precio_total = precio_unitario * cantidad
            self.precio_total_spin.blockSignals(True)
            self.precio_total_spin.setValue(precio_total)
            self.precio_total_spin.blockSignals(False)

        descuento_valor = self.descuento_spin.value()
        descuento_tipo = self.descuento_tipo_combo.currentText()
        subtotal = precio_total

        # Cálculo del descuento
        if descuento_tipo == "%":
            descuento_monto = subtotal * (descuento_valor / 100)
        else:
            descuento_monto = descuento_valor

        subtotal_con_descuento = max(subtotal - descuento_monto, 0)

        # Comisión de vendedor
        comision_pct = self.comision_pct_spin.value() if self.comision_chk.isChecked() else 0
        comision_tipo = self.comision_tipo_combo.currentText()
        if comision_tipo == "Añadida al total":
            comision_monto = subtotal_con_descuento * (comision_pct / 100)
        elif comision_tipo == "Desglosada (incluida en el precio)":
            comision_monto = subtotal_con_descuento * (comision_pct / (100 + comision_pct)) if comision_pct > 0 else 0
        else:
            comision_monto = 0

        base_iva = subtotal_con_descuento
        if comision_tipo == "Desglosada (incluida en el precio)":
            base_iva = subtotal_con_descuento - comision_monto

        # IVA (si aplica)
        iva = 0
        if hasattr(self, "iva_checkbox") and self.iva_checkbox.isChecked():
            if self.iva_agregado_radio.isChecked():
                iva = base_iva * 0.13
                total = subtotal_con_descuento + iva
            elif self.iva_desglosado_radio.isChecked():
                iva = base_iva * 13 / 113
                total = subtotal_con_descuento
                subtotal = base_iva - iva
            else:
                total = subtotal_con_descuento
        else:
            total = subtotal_con_descuento

        if comision_tipo == "Añadida al total":
            total_final = total + comision_monto
        else:
            total_final = total

        iva_incl = max(total - subtotal_con_descuento, 0)
        self.item_sumas_label.setText(f"Sumas: ${subtotal:.2f}")
        self.item_total_sin_desc_label.setText(f"IVA inc.: ${iva_incl:.2f}")
        self.item_descuento_label.setText(f"Desc.: -${descuento_monto:.2f}")
        self.item_subtotal_label.setText(f"Subtotal: ${total_final:.2f}")
        self.precio_label.setText(f"Precio U.: ${precio_unitario:.2f}")
        self.comision_label.setText(f"Comisión: ${comision_monto:.2f}")


    def get_data(self):
        vendedor_idx = self.vendedor_combo.currentIndex()
        vendedor_id = None
        if vendedor_idx > 0:
            vendedor_id = self.vendedores_trabajadores[vendedor_idx - 1]["id"]

        sumas = 0
        descuentos = 0
        ventas_exentas = 0
        ventas_no_sujetas = 0
        total = 0
        iva = 0

        for item in self.venta_items:
            tipo_fiscal = item.get("tipo_fiscal", "").lower()
            if tipo_fiscal == "venta gravada":
                sumas += item["subtotal"]
                descuentos += item.get("descuento_monto", 0)
                iva += item.get("iva", 0)  # <-- Suma el IVA real de cada producto gravado
            elif tipo_fiscal == "venta exenta":
                ventas_exentas += item["subtotal_con_descuento"]
            elif tipo_fiscal == "venta no sujeta":
                ventas_no_sujetas += item["subtotal_con_descuento"]
            total += item.get("total", 0) 

        condicion_operacion = self.condicion_pago_combo.currentData()
        if condicion_operacion == 2:
            # TODO(back): mapear los nuevos controles de cantidad/unidad al payload cuando el backend esté listo
            _ = self.plazo_spin.value()
            _ = self.plazo_combo.currentData()
            plazo_codigo = self._backend_pago_plazo
            periodo_codigo = self._backend_pago_periodo
        else:
            self._backend_pago_plazo = ""
            self._backend_pago_periodo = ""
            plazo_codigo = ""
            periodo_codigo = ""
        referencia = (
            self.referencia_edit.text().strip() if condicion_operacion == 2 else ""
        )

        data = {
            "cliente": self.selected_cliente if self.selected_cliente else {},
            "items": self.venta_items,
            "tipo_venta": "Manual",
            "precio_total_manual": float(self.precio_total_spin.value()),
            "iva_agregado": self.iva_agregado_radio.isChecked() if hasattr(self, "iva_agregado_radio") else False,
            "venta_a_cuenta_de": self.venta_a_cuenta_de_edit.text(),
            "documento_venta_a_cuenta": self.venta_documento_edit.text(),
            "sumas": sumas,
            "descuentos": descuentos,
            "iva": iva,
            "ventas_exentas": ventas_exentas,
            "ventas_no_sujetas": ventas_no_sujetas,
            "subtotal": (sumas - descuentos) + iva,
            # Usar el total acumulado para reflejar comisiones u otros cargos
            "total": total,
            "fecha": QDate.currentDate().toString("yyyy-MM-dd"),
            "Distribuidor_id": (
                self.Distribuidor_combo.currentIndex()
                if self.Distribuidor_combo.currentIndex() >= 0 else None
            ),
            "vendedor_id": vendedor_id,
            "estado": self.estado_combo.currentText(),
            "condicion_operacion": condicion_operacion,
            "pago_plazo": plazo_codigo,
            "pago_periodo": periodo_codigo,
            "pago_referencia": referencia,
            "condicion_pago": self.condicion_pago_combo.currentText(),
        }
        ret_allowed = self._retencion_permitida_para_tipo()
        if ret_allowed:
            base, iva_retenido = self._compute_retencion_values()
            geo_emisor = self.retencion_geo_emisor_combo.currentData() if hasattr(self, "retencion_geo_emisor_combo") else None
            geo_receptor = self.retencion_geo_receptor_combo.currentData() if hasattr(self, "retencion_geo_receptor_combo") else None
            data["_ui_retencion"] = normalize_retencion_payload(
                {
                    "enabled": self.retencion_checkbox.isChecked(),
                    "base": float(base),
                    "montoRetenido": float(iva_retenido),
                    "codigoRetencionMH": self._retencion_codigo_value(),
                    "tasa": float(self._retencion_rate_pct()),
                    "geoEmisor": geo_emisor,
                    "geoReceptor": geo_receptor,
                }
            )
        elif self.retencion_checkbox.isChecked():
            self._warn_retencion_solo_ccf()
        return data

    def _update_condicion_pago_fields(self):
        is_credit = self.condicion_pago_combo.currentData() == 2
        self.credit_fields_widget.setVisible(is_credit)
        if not is_credit:
            self.plazo_combo.setCurrentIndex(0)
            self.plazo_spin.setValue(1)
            self.referencia_edit.clear()
            self._backend_pago_plazo = ""
            self._backend_pago_periodo = ""
        self._sync_credit_term_payload()

    def load_payment_data(self, extra):
        if not extra:
            return
        data = {}
        if isinstance(extra, str):
            try:
                data = json.loads(extra)
            except (TypeError, ValueError):
                return
        elif isinstance(extra, dict):
            data = extra
        else:
            return

        self._backend_pago_plazo = ""
        self._backend_pago_periodo = ""

        condicion = data.get("condicion_operacion")
        if condicion not in {1, 2, 3}:
            condicion = data.get("condicionOperacion")
        if condicion in {1, 2, 3}:
            idx = self.condicion_pago_combo.findData(condicion)
            if idx >= 0:
                self.condicion_pago_combo.setCurrentIndex(idx)
        pagos = data.get("pagos") or []
        if pagos:
            pago = pagos[0]
            plazo_valor = pago.get("plazo")
            self._backend_pago_plazo = str(plazo_valor) if plazo_valor not in (None, "") else ""
            if plazo_valor in {"D", "M", "A"}:
                plazo_valor = {"D": "01", "M": "02", "A": "03"}.get(plazo_valor, plazo_valor)
            if plazo_valor is not None:
                for idx in range(self.plazo_combo.count()):
                    if (
                        self.plazo_combo.itemData(idx, CREDIT_TERM_BACKEND_ROLE)
                        == plazo_valor
                    ):
                        self.plazo_combo.setCurrentIndex(idx)
                        break
            periodo_valor = pago.get("periodo")
            self._backend_pago_periodo = str(periodo_valor) if periodo_valor not in (None, "") else ""
            if periodo_valor not in (None, ""):
                try:
                    self.plazo_spin.setValue(int(periodo_valor))
                except (TypeError, ValueError):
                    self.plazo_spin.setValue(1)
            referencia = pago.get("referencia")
            if referencia:
                self.referencia_edit.setText(str(referencia))
        self._update_condicion_pago_fields()
        self._load_retencion_state(data)

    def _load_retencion_state(self, extra: Mapping[str, Any]) -> None:
        if not hasattr(self, "retencion_checkbox"):
            return
        ret_block = None
        if isinstance(extra, Mapping):
            ret_block = extra.get("_ui_retencion") or extra.get("retencion_iva")
        elif isinstance(extra, str):
            try:
                parsed = json.loads(extra)
            except (TypeError, ValueError):
                parsed = {}
            if isinstance(parsed, Mapping):
                ret_block = parsed.get("_ui_retencion") or parsed.get("retencion_iva")
        normalized = normalize_retencion_payload(ret_block) if ret_block else None
        if not self._retencion_permitida_para_tipo():
            if normalized and normalized.get("enabled"):
                self._warn_retencion_solo_ccf()
            with QSignalBlocker(self.retencion_checkbox):
                self.retencion_checkbox.setChecked(False)
            self._apply_retencion_visibility()
            return
        with QSignalBlocker(self.retencion_checkbox):
            self.retencion_checkbox.setChecked(bool(normalized and normalized.get("enabled")))
        if normalized:
            base = normalized.get("base") or normalized.get("baseSujeta") or 0.0
            reten = normalized.get("montoRetenido") or normalized.get("ivaRetenido") or 0.0
            tasa = normalized.get("tasa")
            if tasa not in (None, ""):
                try:
                    self.retencion_tasa_spin.setValue(float(tasa))
                except Exception:
                    pass
            codigo = normalized.get("codigoRetencionMH")
            if codigo:
                idx = self.retencion_codigo_combo.findData(str(codigo))
                if idx >= 0:
                    self.retencion_codigo_combo.setCurrentIndex(idx)
            geo_emisor = normalized.get("geoEmisor")
            geo_receptor = normalized.get("geoReceptor")
            if geo_emisor:
                idx = self.retencion_geo_emisor_combo.findData(str(geo_emisor))
                if idx >= 0:
                    self.retencion_geo_emisor_combo.setCurrentIndex(idx)
            if geo_receptor:
                idx = self.retencion_geo_receptor_combo.findData(str(geo_receptor))
                if idx >= 0:
                    self.retencion_geo_receptor_combo.setCurrentIndex(idx)
            self.retencion_base_label.setText(f"Base sujeta: ${float(base):.2f}")
            self.retencion_iva_label.setText(
                f"IVA retenido ({float(self._retencion_rate_pct()):.3f}%): ${float(reten):.2f}"
            )
        else:
            self.retencion_base_label.setText("Base sujeta: $0.00")
            self.retencion_iva_label.setText(
                f"IVA retenido ({float(self._retencion_rate_pct()):.3f}%): $0.00"
            )

    def _agregar_a_venta(self):
        idx = self.product_list.currentRow()
        if idx < 0:
            QMessageBox.warning(self, "Validación", "Seleccione un producto del inventario actual.")
            return
        lote = self.productos[idx]
        cantidad_bultos = self.cantidad_spin.value()

        # Precios siempre editables y sincronizados
        self._recalcular_totales()
        precio_unit_base = self.precio_spin.value()
        factor = self._presentacion_factor_from_combo(self.presentacion_combo) or 1
        if factor <= 0:
            factor = 1
        precio_presentacion = precio_unit_base * max(factor, 1)
        precio_total = precio_presentacion * cantidad_bultos

        pres_nombre = (self.presentacion_combo.currentText() or "").strip()
        cantidad_base = cantidad_bultos * factor
        precio_base = precio_presentacion / factor if factor else precio_presentacion

        descuento_valor = self.descuento_spin.value()
        descuento_tipo = self.descuento_tipo_combo.currentText()
        subtotal = precio_total

        iva = 0
        iva_tipo = "ninguno"
        if hasattr(self, "iva_checkbox") and self.iva_checkbox.isChecked() and self.iva_desglosado_radio.isChecked():
            iva_tipo = "desglosado"
            # Mantener precio unitario y subtotal brutos; el DTE calculará base e IVA

        if descuento_tipo == "%":
            descuento_monto = subtotal * (descuento_valor / 100)
        else:
            descuento_monto = descuento_valor

        subtotal_con_descuento = max(subtotal - descuento_monto, 0)

        # Comisión
        comision_pct = self.comision_pct_spin.value() if self.comision_chk.isChecked() else 0
        comision_tipo = self.comision_tipo_combo.currentText()
        if comision_tipo == "Añadida al total":
            comision_monto = subtotal_con_descuento * (comision_pct / 100)
        elif comision_tipo == "Desglosada (incluida en el precio)":
            comision_monto = subtotal_con_descuento * (comision_pct / (100 + comision_pct)) if comision_pct > 0 else 0
        else:
            comision_monto = 0

        base_iva = subtotal_con_descuento
        if comision_tipo == "Desglosada (incluida en el precio)":
            base_iva = subtotal_con_descuento - comision_monto

        if hasattr(self, "iva_checkbox") and self.iva_checkbox.isChecked():
            if self.iva_agregado_radio.isChecked():
                iva = round(base_iva * 0.13, 2)
                iva_tipo = "agregado"
            elif self.iva_desglosado_radio.isChecked():
                iva = round(base_iva * 0.13, 2)
            total = subtotal_con_descuento + iva
        else:
            total = subtotal_con_descuento

        if comision_tipo == "Añadida al total":
            total_final = total + comision_monto
        else:
            total_final = total
        tipo_fiscal = self.tipo_fiscal_combo.currentText()

        producto_display = lote.get("nombre", "")
        if pres_nombre and not pres_nombre.lower().startswith("unidad base"):
            producto_display = f"{producto_display} [{pres_nombre}]"

        self.venta_items.append({
            "lote_id": lote["lote_id"],
            "producto_id": lote["producto_id"],
            "producto": lote["nombre"],
            "producto_display": producto_display,
            "codigo": lote.get("codigo", ""),
            "sku": lote.get("sku", ""),

            "cantidad": cantidad_base,
            "cantidad_bultos": cantidad_bultos,
            "presentacion_factor": factor,
            "presentacion_nombre": pres_nombre or "Unidad Base (x1)",
            "precio": precio_base,  # Precio unitario con IVA en unidad base
            "precio_presentacion": precio_presentacion,
            "descuento": descuento_valor,
            "descuento_tipo": descuento_tipo,
            "descuento_monto": descuento_monto,
            "subtotal": subtotal,
            "subtotal_con_descuento": subtotal_con_descuento,
            "iva": iva,
            "iva_tipo": iva_tipo,
            "comision_monto": comision_monto,
            "total": total_final,
            "tipo_fiscal": tipo_fiscal,
            "vendedor_id": lote.get("vendedor_id"),
            "Distribuidor_id": lote["Distribuidor_id"],
            "fecha_vencimiento": lote.get("fecha_vencimiento", ""),
            "codigo_lote": lote.get("codigo_lote", ""),
            "registro_sanitario": lote.get("registro_sanitario", ""),
            "extra": {
                "lote_id": lote.get("lote_id"),
                "producto_id": lote.get("producto_id"),
                "cantidad": float(cantidad_base),
                "cantidad_presentacion": float(cantidad_bultos),
                "codigo_lote": lote.get("codigo_lote"),
                "registro_sanitario": lote.get("registro_sanitario"),
            },
        })
        self._actualizar_tabla()
        self._recalcular_totales()
        self._actualizar_resumen()

    def _actualizar_tabla(self):
        self.table.setRowCount(len(self.venta_items))
        for i, item in enumerate(self.venta_items):
            producto_texto = item.get("producto_display", item.get("producto", ""))
            self.table.setItem(i, 0, QTableWidgetItem(producto_texto))

            cant_bultos = item.get("cantidad_bultos", item.get("cantidad", 0))
            pres_nombre = item.get("presentacion_nombre", "")
            cantidad_base = item.get("cantidad", cant_bultos)
            cantidad_texto = f"{int(cantidad_base) if float(cantidad_base).is_integer() else cantidad_base} unidades"
            cantidad_item = QTableWidgetItem(cantidad_texto)
            cantidad_item.setData(Qt.UserRole, cantidad_base)
            self.table.setItem(i, 1, cantidad_item)

            precio_pres = item.get("precio_presentacion")
            if precio_pres is None:
                factor = item.get("presentacion_factor", 1) or 1
                precio_pres = (item.get("precio", 0) or 0) * factor
            self.table.setItem(i, 2, QTableWidgetItem(f"${float(precio_pres):.2f}"))
            self.table.setItem(i, 3, QTableWidgetItem(f"{item['descuento']}{item['descuento_tipo']}"))
            self.table.setItem(i, 4, QTableWidgetItem(item.get("tipo_fiscal", "")))
            btn = QPushButton("Eliminar")
            btn.setStyleSheet(
                "background-color: #b71c1c; color: #fff; border-radius: 6px; font-size:9px;"
                "min-width:70px; max-width:100px; min-height:14px; max-height:22px;"
            )
            btn.clicked.connect(lambda _, row=i: self._eliminar_item(row))
            cell = QWidget()
            cell_layout = QHBoxLayout(cell)
            cell_layout.setContentsMargins(0, 0, 0, 0)
            cell_layout.setAlignment(Qt.AlignCenter)
            cell_layout.addWidget(btn)
            self.table.setCellWidget(i, 5, cell)

    def _actualizar_resumen(self):
        sumas = sum(i["subtotal"] for i in self.venta_items)
        descuentos = sum(i.get("descuento_monto", 0) for i in self.venta_items)
        subtotal = sumas - descuentos
        total = sum(i.get("total", 0) for i in self.venta_items)

        self.item_sumas_label.setText(f"Sumas: ${sumas:.2f}")
        self.item_total_sin_desc_label.setText(f"Subtotal: ${subtotal:.2f}")
        self.item_descuento_label.setText(f"Desc.: -${descuentos:.2f}")
        self.item_subtotal_label.setText(f"Total con IVA: ${total:.2f}")
        self.sumas_label.setText(f"Sumas: ${sumas:.2f}")
        self.subtotal_label.setText(f"Subtotal: ${subtotal:.2f}")
        self.total_label.setText(f"Venta total: ${total:.2f}")
        base_ret, iva_ret = self._compute_retencion_values()
        if self.retencion_checkbox.isChecked() and iva_ret > 0:
            tasa = float(self._retencion_rate_pct())
            self.item_subtotal_label.setText(
                f"Total con IVA: ${total:.2f}  Retención {tasa:.3f}%: ${iva_ret:.2f}"
            )
        self._update_retencion_summary()

    def _retencion_rate_pct(self) -> Decimal:
        if hasattr(self, "retencion_tasa_spin"):
            try:
                return Decimal(str(self.retencion_tasa_spin.value()))
            except Exception:
                return Decimal("0")
        return Decimal("0")

    def _retencion_codigo_value(self) -> str:
        if hasattr(self, "retencion_codigo_combo"):
            data = self.retencion_codigo_combo.currentData()
            if data not in (None, ""):
                return str(data)
        return "22"

    def _valid_geo_code(self, value: str | None) -> bool:
        if not value:
            return False
        digits = "".join(ch for ch in str(value) if ch.isdigit())
        if not digits:
            return False
        try:
            numero = int(digits)
        except ValueError:
            return False
        return 1 <= numero <= 22

    def _load_retencion_catalog(self) -> None:
        self._retencion_catalog_ok = False
        if not self._retencion_permitida_para_tipo():
            self._apply_retencion_visibility()
            return
        try:
            from retenciones.catalogos_retencion import CatalogosRetencion

            catalogos = CatalogosRetencion()
            entries = catalogos.entries("CAT-006")
            self.retencion_codigo_combo.clear()
            for entry in entries:
                label = f"{entry.code} – {entry.label}" if entry.label else entry.code
                self.retencion_codigo_combo.addItem(label, entry.code)
            idx = self.retencion_codigo_combo.findData("22")
            if idx >= 0:
                self.retencion_codigo_combo.setCurrentIndex(idx)
            self._retencion_catalog_ok = True
            self.retencion_group.setEnabled(True)
        except Exception as exc:
            logger.warning("No se pudo cargar catálogo CAT-006: %s", exc, exc_info=True)
            self.retencion_codigo_combo.clear()
            self.retencion_codigo_combo.addItem("Catálogo no disponible", "")
            self.retencion_checkbox.setChecked(False)
            self.retencion_group.setEnabled(False)
            QMessageBox.warning(
                self,
                "Catálogo de retención",
                "No se pudo cargar el catálogo CAT-006. "
                "La retención de IVA se desactivará para esta venta.\n\n"
                f"Detalle: {exc}",
            )
        self._restrict_retencion_to_one_percent()
        self._apply_retencion_visibility()

    def _compute_retencion_values(self) -> tuple[Decimal, Decimal]:
        """Return the taxable base and retained VAT for gravada items."""

        sumas = Decimal("0")
        descuentos = Decimal("0")
        for item in self.venta_items:
            tipo_fiscal = (item.get("tipo_fiscal") or "").lower()
            if tipo_fiscal != "venta gravada":
                continue
            sumas += Decimal(str(item.get("subtotal", 0)))
            descuentos += Decimal(str(item.get("descuento_monto", 0)))

        base = sumas - descuentos
        if base < 0:
            base = Decimal("0")
        base = base.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        tasa_pct = self._retencion_rate_pct()
        tasa = tasa_pct / Decimal("100")
        iva_retenido = (base * tasa).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return base, iva_retenido

    def _update_retencion_summary(self) -> None:
        if not hasattr(self, "retencion_base_label"):
            return
        base, iva_retenido = self._compute_retencion_values()
        self.retencion_base_label.setText(f"Base sujeta: ${base:.2f}")
        self.retencion_iva_label.setText(
            f"IVA retenido ({float(self._retencion_rate_pct()):.3f}%): ${iva_retenido:.2f}"
        )

    def _retencion_permitida_para_tipo(self) -> bool:
        return bool(getattr(self, "_retencion_allowed_flag", True))

    def _apply_retencion_visibility(self) -> None:
        if not hasattr(self, "retencion_group"):
            return
        allowed = self._retencion_permitida_para_tipo()
        self.retencion_group.setVisible(allowed)
        self.retencion_group.setEnabled(allowed and getattr(self, "_retencion_catalog_ok", True))
        with QSignalBlocker(self.retencion_checkbox):
            if not allowed:
                self.retencion_checkbox.setChecked(False)
        self._update_retencion_summary()

    def _warn_retencion_solo_ccf(self) -> None:
        if getattr(self, "_retencion_warning_shown", False):
            return
        QMessageBox.information(self, "Retención de IVA", "La retención de IVA solo aplica a CCF (03)")
        self._retencion_warning_shown = True

    def _update_retencion_group_state(self) -> None:
        if not hasattr(self, "retencion_checkbox"):
            return
        if not self._retencion_permitida_para_tipo():
            self._apply_retencion_visibility()
            return
        if not getattr(self, "_retencion_catalog_ok", True):
            self.retencion_checkbox.setEnabled(False)
            self.retencion_checkbox.setChecked(False)
            self._update_retencion_summary()
            return
        cliente = self.selected_cliente or {}
        nit_cliente = solo_digitos(str(get_field(cliente, "nit", "") or ""))
        nrc_cliente = solo_digitos(str(get_field(cliente, "nrc", "") or ""))
        tipo_contribuyente = (
            str(get_field(cliente, "tipoContribuyente", "") or "")
            or str(get_field(cliente, "tipo_contribuyente", "") or "")
        )
        should_enable = bool(nit_cliente or nrc_cliente or tipo_contribuyente)
        self.retencion_checkbox.setEnabled(should_enable)
        if not should_enable:
            self.retencion_checkbox.setChecked(False)
        self._update_retencion_summary()

    def _eliminar_fila(self, row, col):
        if col == 5:
            self._eliminar_item(row)

    def _eliminar_item(self, row):
        if 0 <= row < len(self.venta_items):
            del self.venta_items[row]
            self._actualizar_tabla()
            self._recalcular_totales()
            self._actualizar_resumen()

    def _validar_y_accept(self):
        if not self.venta_items:
            QMessageBox.warning(self, "Validación", "Agregue al menos un producto al carrito.")
            return
        condicion_operacion = self.condicion_pago_combo.currentData()
        tercero_nombre = self.venta_a_cuenta_de_edit.text().strip()
        tercero_documento = self.venta_documento_edit.text().strip()
        if tercero_nombre or tercero_documento:
            nit_digits = solo_digitos(tercero_documento)
            if tercero_documento and len(nit_digits) not in (9, 14):
                respuesta = QMessageBox.question(
                    self,
                    "Venta a tercero inválida",
                    (
                        "El documento ingresado para 'Venta a cuenta de' debe contener "
                        "9 o 14 dígitos luego de quitar guiones y espacios.\n\n"
                        "Si continúas, la sección 'venta a tercero' del DTE quedará vacía.\n\n"
                        "¿Deseas continuar sin esos datos?"
                    ),
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if respuesta != QMessageBox.Yes:
                    return

        if self.retencion_checkbox.isChecked():
            if not self._retencion_permitida_para_tipo():
                self._warn_retencion_solo_ccf()
                self.retencion_checkbox.setChecked(False)
            else:
                if not getattr(self, "_retencion_catalog_ok", False):
                    QMessageBox.warning(
                        self,
                        "Retención",
                        "No se pudo cargar el catálogo de retenciones (CAT-006).",
                    )
                    return
                base, reten = self._compute_retencion_values()
                tasa = self._retencion_rate_pct()
                if tasa <= 0:
                    QMessageBox.warning(self, "Retención", "La tasa de retención debe ser mayor a 0%.")
                    return
                if base <= 0 or reten <= 0:
                    QMessageBox.warning(
                        self,
                        "Retención",
                        "Para aplicar retención, la base sujeta y el monto retenido deben ser mayores a 0.",
                    )
                    return
                codigo = self._retencion_codigo_value().strip()
                if not codigo:
                    QMessageBox.warning(self, "Retención", "Seleccione un código de retención válido (CAT-006).")
                    return
                geo_emisor = self.retencion_geo_emisor_combo.currentData()
                geo_receptor = self.retencion_geo_receptor_combo.currentData()
                if not (self._valid_geo_code(geo_emisor) and self._valid_geo_code(geo_receptor)):
                    QMessageBox.warning(
                        self,
                        "Retención",
                        "Debe definir geocódigos emisor y receptor en el rango 01–22.",
                    )
                    return

        # Emitir datos al padre (modo incrustado) y cerrar
        try:
            self.venta_validada.emit(self.get_data())
        except Exception:
            # Si algo falla al preparar datos, impedir el cierre silencioso
            logger.exception("No se pudo emitir datos de venta")
            QMessageBox.critical(self, "Error", "No se pudo preparar los datos de la venta.")
            return
        self.accept()

class ProductDialog(QDialog):
    def __init__(self, vendedores, Distribuidores, parent=None, producto=None):
        super().__init__(parent)
        self.setWindowTitle("Editar Producto" if producto else "Crear Nuevo Producto")
        self.resize(960, 720)
        self.presentaciones: list[dict[str, Any]] = []
        if producto:
            try:
                raw_pres = producto.get("presentaciones")
                if isinstance(raw_pres, list):
                    self.presentaciones = [dict(p) for p in raw_pres if isinstance(p, Mapping)]
            except Exception:
                self.presentaciones = []

        # Datos básicos del producto
        self.codigo_edit = QLineEdit()
        self.codigo_edit.installEventFilter(self)
        self.sku_edit = QLineEdit()
        self.nombre_edit = QLineEdit()
        self.precio_compra_spin = QDoubleSpinBox()
        self.precio_compra_spin.setMaximum(1000000)
        self.precio_compra_spin.setDecimals(8)
        self.precio_compra_spin.setSingleStep(1)
        self.precio_venta_minorista_spin = QDoubleSpinBox()
        self.precio_venta_minorista_spin.setMaximum(1000000)
        self.precio_venta_minorista_spin.setDecimals(2)
        self.precio_venta_mayorista_spin = QDoubleSpinBox()
        self.precio_venta_mayorista_spin.setMaximum(1000000)
        self.precio_venta_mayorista_spin.setDecimals(2)

        self.setStyleSheet(
            """
            QWidget { font-family: 'Inter', 'Segoe UI', sans-serif; color: #1f2937; font-size: 13px; }
            QLabel#DialogTitle { font-size: 20px; font-weight: 700; color: #0f172a; }
            QLabel[class="sectionHeader"] {
                background: #e8f3ff;
                border: 1px solid #d0e4ff;
                border-radius: 6px;
                padding: 10px 12px;
                font-weight: 700;
                color: #0a3a60;
            }
            QLabel[class="fieldLabel"] { font-weight: 600; margin-bottom: 2px; }
            QLineEdit, QDoubleSpinBox {
                border: 1px solid #d1d5db;
                border-radius: 6px;
                padding: 8px 10px;
                background: white;
            }
            QLineEdit:focus, QDoubleSpinBox:focus {
                border: 1px solid #0d6efd;
                outline: none;
            }
            QTableWidget {
                border: 1px solid #d1d5db;
                border-radius: 8px;
                gridline-color: #e5e7eb;
                alternate-background-color: #f9fafb;
            }
            QHeaderView::section {
                background: #f3f4f6;
                font-weight: 700;
                padding: 10px 6px;
                border: none;
                border-right: 1px solid #e5e7eb;
            }
            QTableWidget::item { padding: 10px 6px; }
            QToolButton {
                border: none;
                padding: 4px 6px;
                border-radius: 4px;
            }
            QPushButton[class="primary"] {
                background: #0d6efd;
                color: white;
                padding: 10px 18px;
                border-radius: 8px;
                border: none;
                font-weight: 600;
            }
            QPushButton[class="secondary"] {
                background: #f9fafb;
                color: #111827;
                padding: 10px 18px;
                border-radius: 8px;
                border: 1px solid #d1d5db;
                font-weight: 600;
            }
            QPushButton[class="ghost"] {
                background: #f8fbff;
                color: #0d6efd;
                border: 1px solid #cfe2ff;
                padding: 10px 16px;
                border-radius: 8px;
                font-weight: 600;
            }
            """
        )

        layout = QVBoxLayout()
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(16)

        title = QLabel("Crear Nuevo Producto" if not producto else "Editar Producto")
        title.setObjectName("DialogTitle")
        layout.addWidget(title)

        # Sección 1: Información básica
        header1 = QLabel("1. Información Básica y Precios Unitarios")
        header1.setProperty("class", "sectionHeader")
        layout.addWidget(header1)

        form_card = QFrame()
        form_layout = QGridLayout(form_card)
        form_layout.setHorizontalSpacing(14)
        form_layout.setVerticalSpacing(12)
        form_layout.setContentsMargins(6, 6, 6, 6)

        def add_field(row, col, label_text, widget, colspan=1):
            lbl = QLabel(label_text)
            lbl.setProperty("class", "fieldLabel")
            form_layout.addWidget(lbl, row * 2, col, 1, colspan)
            widget.setMinimumHeight(34)
            form_layout.addWidget(widget, row * 2 + 1, col, 1, colspan)

        add_field(0, 0, "Código", self.codigo_edit)
        add_field(0, 1, "SKU Principal", self.sku_edit)
        add_field(1, 0, "Nombre del Producto", self.nombre_edit, colspan=2)
        add_field(2, 0, "Precio de Compra Unitario", self.precio_compra_spin)
        add_field(2, 1, "Precio de Venta Unitario", self.precio_venta_minorista_spin)
        add_field(3, 0, "Precio de Venta Mayorista (opcional)", self.precio_venta_mayorista_spin, colspan=2)
        form_layout.setColumnStretch(0, 1)
        form_layout.setColumnStretch(1, 1)
        layout.addWidget(form_card)

        # Sección 2: Presentaciones adicionales (UI estática)
        header2 = QLabel("2. Presentaciones Adicionales y Precios")
        header2.setProperty("class", "sectionHeader")
        layout.addWidget(header2)

        self.presentaciones_table = QTableWidget(0, 5)
        self.presentaciones_table.setHorizontalHeaderLabels([
            "Nombre Presentación",
            "Factor (Unidades Base)",
            "Precio Compra Presentación",
            "Precio Venta Presentación",
            "Acciones",
        ])
        self.presentaciones_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.presentaciones_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.presentaciones_table.verticalHeader().setVisible(False)
        self.presentaciones_table.setAlternatingRowColors(True)
        self.presentaciones_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.presentaciones_table.setSelectionMode(QTableWidget.NoSelection)

        layout.addWidget(self.presentaciones_table)

        add_row = QHBoxLayout()
        add_row.addStretch(1)
        self.btn_add_presentacion = QPushButton("+ Agregar Presentación")
        self.btn_add_presentacion.setProperty("class", "ghost")
        add_row.addWidget(self.btn_add_presentacion)
        add_row.addStretch(1)
        layout.addLayout(add_row)

        # Footer
        footer = QHBoxLayout()
        footer.addStretch(1)
        self.btn_cancel = QPushButton("Cancelar")
        self.btn_cancel.setProperty("class", "secondary")
        self.btn_ok = QPushButton("Guardar")
        self.btn_ok.setProperty("class", "primary")
        footer.addWidget(self.btn_cancel)
        footer.addWidget(self.btn_ok)
        layout.addLayout(footer)

        self.setLayout(layout)

        self.btn_ok.clicked.connect(self.accept)
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_add_presentacion.clicked.connect(self._agregar_presentacion)
        self._refrescar_presentaciones_table()

        if producto:
            self.nombre_edit.setText(producto.get("nombre", ""))
            self.codigo_edit.setText(producto.get("codigo", ""))
            self.sku_edit.setText(producto.get("sku") or "")
            self.precio_compra_spin.setValue(producto.get("precio_compra", 0))
            self.precio_venta_minorista_spin.setValue(producto.get("precio_venta_minorista", 0))
            self.precio_venta_mayorista_spin.setValue(producto.get("precio_venta_mayorista", 0))
            self._refrescar_presentaciones_table()

    def _handle_scanned_code(self):
        codigo = self.codigo_edit.text().strip()
        if not codigo:
            return
        self.sku_edit.setText(codigo)
        self.codigo_edit.clear()
        self.sku_edit.setFocus()
        self.sku_edit.selectAll()

    def eventFilter(self, obj, event):
        if obj is self.codigo_edit and event.type() == QEvent.KeyPress:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                self._handle_scanned_code()
                return True
        return super().eventFilter(obj, event)

    def _refrescar_presentaciones_table(self):
        rows = self.presentaciones or []
        self.presentaciones_table.setRowCount(len(rows))
        for r, item in enumerate(rows):
            nombre = item.get("nombre", "")
            factor = item.get("factor", "")
            pc = item.get("precio_compra", 0)
            pv = item.get("precio_venta", 0)
            self.presentaciones_table.setItem(r, 0, QTableWidgetItem(str(nombre)))
            self.presentaciones_table.setItem(r, 1, QTableWidgetItem(str(factor)))
            self.presentaciones_table.setItem(r, 2, QTableWidgetItem(f"${float(pc):.2f}"))
            self.presentaciones_table.setItem(r, 3, QTableWidgetItem(f"${float(pv):.2f}"))
            actions = QWidget()
            layout = QHBoxLayout(actions)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(6)
            btn_edit = QPushButton("Editar")
            btn_delete = QPushButton("Eliminar")
            btn_edit.clicked.connect(lambda _=None, idx=r: self._editar_presentacion(idx))
            btn_delete.clicked.connect(lambda _=None, idx=r: self._eliminar_presentacion(idx))
            layout.addWidget(btn_edit)
            layout.addWidget(btn_delete)
            layout.addStretch(1)
            self.presentaciones_table.setCellWidget(r, 4, actions)

    def _agregar_presentacion(self):
        dialog = PresentacionDialog(self)
        if dialog.exec_():
            data = dialog.get_data()
            self.presentaciones.append(data)
            self._refrescar_presentaciones_table()

    def _editar_presentacion(self, idx: int):
        if idx < 0 or idx >= len(self.presentaciones):
            return
        dialog = PresentacionDialog(self, data=self.presentaciones[idx])
        if dialog.exec_():
            self.presentaciones[idx] = dialog.get_data()
            self._refrescar_presentaciones_table()

    def _eliminar_presentacion(self, idx: int):
        if idx < 0 or idx >= len(self.presentaciones):
            return
        del self.presentaciones[idx]
        self._refrescar_presentaciones_table()

    def get_data(self):
        codigo = (self.codigo_edit.text() or "").strip()
        sku_text = (self.sku_edit.text() or "").strip()
        sku = sku_text or None
        return {
            "nombre": self.nombre_edit.text(),
            "codigo": codigo,
            "sku": sku,
            "precio_compra": self.precio_compra_spin.value(),
            "precio_venta_minorista": self.precio_venta_minorista_spin.value(),
            "precio_venta_mayorista": self.precio_venta_mayorista_spin.value(),
            "presentaciones": [dict(p) for p in self.presentaciones],
        }


class PresentacionDialog(QDialog):
    """Diálogo simple para agregar/editar una presentación de producto."""

    def __init__(self, parent=None, data=None):
        super().__init__(parent)
        self.setWindowTitle("Editar Presentación" if data else "Agregar Presentación")
        layout = QVBoxLayout()
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        self.nombre_edit = QLineEdit()
        self.factor_spin = QDoubleSpinBox()
        self.factor_spin.setRange(0.0001, 1_000_000)
        self.factor_spin.setDecimals(4)
        self.factor_spin.setSingleStep(1)
        self.factor_spin.setValue(1.0)
        self.precio_compra_spin = QDoubleSpinBox()
        self.precio_compra_spin.setRange(0, 1_000_000)
        self.precio_compra_spin.setDecimals(4)
        self.precio_venta_spin = QDoubleSpinBox()
        self.precio_venta_spin.setRange(0, 1_000_000)
        self.precio_venta_spin.setDecimals(4)

        form = QGridLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        form.addWidget(QLabel("Nombre Presentación"), 0, 0)
        form.addWidget(self.nombre_edit, 1, 0, 1, 2)
        form.addWidget(QLabel("Factor (Unidades Base)"), 2, 0)
        form.addWidget(self.factor_spin, 3, 0)
        form.addWidget(QLabel("Precio Compra Presentación"), 4, 0)
        form.addWidget(self.precio_compra_spin, 5, 0)
        form.addWidget(QLabel("Precio Venta Presentación"), 4, 1)
        form.addWidget(self.precio_venta_spin, 5, 1)
        layout.addLayout(form)

        btns = QHBoxLayout()
        btns.addStretch(1)
        btn_cancel = QPushButton("Cancelar")
        btn_save = QPushButton("Guardar")
        btn_save.setProperty("class", "primary")
        btns.addWidget(btn_cancel)
        btns.addWidget(btn_save)
        layout.addLayout(btns)
        self.setLayout(layout)

        btn_cancel.clicked.connect(self.reject)
        btn_save.clicked.connect(self.accept)

        if data:
            self.nombre_edit.setText(str(data.get("nombre", "")))
            try:
                self.factor_spin.setValue(float(data.get("factor", 0)))
            except Exception:
                pass
            try:
                self.precio_compra_spin.setValue(float(data.get("precio_compra", 0)))
            except Exception:
                pass
            try:
                self.precio_venta_spin.setValue(float(data.get("precio_venta", 0)))
            except Exception:
                pass

    def get_data(self):
        return {
            "nombre": self.nombre_edit.text().strip(),
            "factor": self.factor_spin.value(),
            "precio_compra": self.precio_compra_spin.value(),
            "precio_venta": self.precio_venta_spin.value(),
        }


class RegisterPurchaseDialog(QDialog):

    def __init__(
        self,
        productos,
        Distribuidores,
        Vendedores,
        parent=None,
        compra=None,
        detalles=None,
    ):
        super().__init__(parent)
        self.productos = productos
        self._filtered_productos = list(self.productos)
        self.Distribuidores = Distribuidores
        self.Vendedores = Vendedores
        self._vendedores_map = {v["id"]: v for v in self.Vendedores}
        self.compra_items = []
        self._productos_por_nombre = {p.get("nombre"): p for p in self.productos}
        self._productos_por_id = {p.get("id"): p for p in self.productos}
        self._distribuidores_map = {d.get("id"): d for d in self.Distribuidores}
        self._editing_row = None
        self._compra_data = compra if isinstance(compra, dict) else {}
        self._existing_fecha = self._compra_data.get("fecha") if self._compra_data else None
        self._compra_id = self._compra_data.get("id") if self._compra_data else None
        self.edit_mode = self._compra_id is not None
        self.is_subject_excluded_purchase = bool(self._compra_data.get("is_subject_excluded_purchase"))
        self._user_selected_vendor = False
        self._suppress_vendor_signal = False
        self.setWindowTitle("Editar Compra" if self.edit_mode else "Registrar Compra")
        self.resize(1200, 780)

        layout = QVBoxLayout()

        self._summary_group = None
        if self.edit_mode:
            self._init_summary_section(layout)

        # Banner sujeto excluido (solo UI)
        self.subject_excluded_banner = QLabel(
            "El vendedor es un sujeto excluido: se generará comprobante de sujeto excluido (DTE 14) y el IVA queda deshabilitado."
        )
        self.subject_excluded_banner.setStyleSheet("font-weight: bold; background-color: #fff3cd; padding: 6px; border: 1px solid #ffeeba;")
        self.subject_excluded_banner.setVisible(False)
        layout.addWidget(self.subject_excluded_banner)

        # Mapeo producto -> vendedor y vendedor -> Distribuidor
        self._producto_vendedor_map = {}
        self._vendedor_Distribuidor_map = {}
        for v in self.Vendedores:
            self._vendedor_Distribuidor_map[v["id"]] = v.get("Distribuidor_id")
        for p in self.productos:
            self._producto_vendedor_map[p["nombre"]] = p.get("vendedor_id")

        # Crear widgets sin agregarlos aún
        self.vendedor_combo = QComboBox()
        self.vendedor_combo.setEditable(True)
        self.vendedor_combo.setInsertPolicy(QComboBox.NoInsert)
        line_edit = self.vendedor_combo.lineEdit()
        if line_edit is not None:
            line_edit.setPlaceholderText("Buscar por nombre o código")
        self.vendedor_combo.addItem("Seleccionar proveedor", None)
        for v in self.Vendedores:
            vendedor_codigo = v.get("codigo", "") or ""
            display_text = f"{v['nombre']} — {vendedor_codigo}" if vendedor_codigo else v["nombre"]
            self.vendedor_combo.addItem(display_text, v["id"])
        completer = QCompleter(self.vendedor_combo.model(), self.vendedor_combo)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        if line_edit is not None:
            line_edit.setCompleter(completer)

            def _on_completer_activated(text):
                idx = self.vendedor_combo.findText(text, Qt.MatchExactly)
                if idx != -1:
                    self.vendedor_combo.setCurrentIndex(idx)

            completer.activated[str].connect(_on_completer_activated)
        self.Distribuidor_combo = QComboBox()
        self.Distribuidor_combo.setEnabled(False)
        self.product_search_edit = QLineEdit()
        self.product_search_edit.setPlaceholderText("Buscar producto por nombre, código o SKU...")
        self.product_list = QListWidget()
        self._refrescar_lista_productos()

        self.cantidad_spin = QSpinBox()
        self.cantidad_spin.setMinimum(1)
        self.cantidad_spin.setMaximum(100000)
        self.combo_presentacion = QComboBox()
        self.precio_unitario_spin = QDoubleSpinBox()
        self.precio_unitario_spin.setMinimum(0)
        self.precio_unitario_spin.setMaximum(1000000)
        self.precio_unitario_spin.setDecimals(8)
        self.precio_unitario_spin.setSingleStep(1)
        self.precio_total_spin = QDoubleSpinBox()
        self.precio_total_spin.setMinimum(0)
        self.precio_total_spin.setMaximum(100000000)
        self.precio_total_spin.setDecimals(8)
        self.precio_total_spin.setSingleStep(1)
        self.fecha_vencimiento_edit = QDateEdit(QDate.currentDate())
        self.fecha_vencimiento_edit.setCalendarPopup(True)
        self.codigo_lote_edit = QLineEdit()
        self.codigo_lote_edit.setPlaceholderText("Identificador del lote (opcional)")
        self.registro_sanitario_edit = QLineEdit()
        self.registro_sanitario_edit.setPlaceholderText("Registro sanitario (opcional)")
        self.descuento_spin = QDoubleSpinBox()
        self.descuento_spin.setMinimum(0)
        self.descuento_spin.setMaximum(1000000)
        self.descuento_spin.setDecimals(2)
        self.descuento_spin.setValue(0)
        self.descuento_tipo_combo = QComboBox()
        self.descuento_tipo_combo.addItems(["%", "$"])
        self.descuento_tipo_combo.setCurrentText("$")
        self.iva_checkbox = QCheckBox("Aplicar IVA")
        self.iva_checkbox.setChecked(False)
        self.iva_desglosado_radio = QRadioButton("IVA desglosado (restar del precio)")
        self.iva_desglosado_radio.setChecked(False)
        self.iva_desglosado_radio.setEnabled(False)
        self.iva_añadido_radio = QRadioButton("IVA añadido (sumar al precio)")
        self.iva_añadido_radio.setChecked(False)
        self.iva_añadido_radio.setEnabled(False)

        # Agrupa IVA en su propio grupo
        self.iva_group = QButtonGroup(self)
        self.iva_group.setExclusive(True)
        self.iva_group.addButton(self.iva_desglosado_radio)
        self.iva_group.addButton(self.iva_añadido_radio)

        # Resumen
        self.subtotal_label = QLabel(f"Subtotal: {self._format_currency(0)}")
        self.iva_label = QLabel(f"IVA: {self._format_currency(0)}")
        self.comision_label_resumen = QLabel(f"Comisión: {self._format_currency(0)}")
        self.total_label = QLabel(f"TOTAL: {self._format_currency(0)}")

        # Conexiones para IVA
        self.iva_checkbox.stateChanged.connect(self._toggle_iva_radios)
        self.iva_desglosado_radio.toggled.connect(self._actualizar_total_general)

        # Comisión (ahora del vendedor)
        self.comision_pct_spin = QDoubleSpinBox()
        self.comision_pct_spin.setRange(0, 100)
        self.comision_pct_spin.setDecimals(2)
        self.comision_pct_spin.setValue(0)
        self.comision_tipo_combo = QComboBox()
        self.comision_tipo_combo.addItems(["Incluida en el precio"])
        self.btn_agregar = QPushButton("Agregar a compra")

        # --- Nuevo layout tipo dashboard ---
        top_split = QHBoxLayout()
        top_split.setSpacing(16)

        # Tarjeta izquierda
        left_card = QFrame()
        left_card.setObjectName("CardFrame")
        left_card_layout = QVBoxLayout(left_card)
        left_card_layout.setContentsMargins(16, 16, 16, 16)
        left_card_layout.setSpacing(12)
        left_title = QLabel("Proveedor y Costos")
        left_title.setStyleSheet("font-size: 16px; font-weight: 700; color: #111827;")
        left_card_layout.addWidget(left_title)

        proveedor_form = QVBoxLayout()

        def _stack_field(label_text, widget):
            container = QWidget()
            vbox = QVBoxLayout(container)
            vbox.setContentsMargins(0, 0, 0, 0)
            vbox.setSpacing(4)
            lbl = QLabel(label_text)
            lbl.setStyleSheet("color: #4b5563; font-weight: 600;")
            vbox.addWidget(lbl)
            vbox.addWidget(widget)
            return container

        proveedor_form.addWidget(_stack_field("Vendedor", self.vendedor_combo))
        proveedor_form.addWidget(_stack_field("Distribuidor", self.Distribuidor_combo))

        comision_row = QWidget()
        comision_row_layout = QHBoxLayout(comision_row)
        comision_row_layout.setContentsMargins(0, 0, 0, 0)
        comision_row_layout.setSpacing(8)
        comision_row_layout.addWidget(QLabel("Comisión (%)"))
        comision_row_layout.addWidget(self.comision_pct_spin, 1)
        comision_row_layout.addWidget(QLabel("Tipo"))
        comision_row_layout.addWidget(self.comision_tipo_combo, 1)
        proveedor_form.addWidget(comision_row)

        left_card_layout.addLayout(proveedor_form)

        resumen_box = QFrame()
        resumen_box.setObjectName("SubCardFrame")
        resumen_layout = QVBoxLayout(resumen_box)
        resumen_layout.setContentsMargins(12, 12, 12, 12)
        resumen_layout.setSpacing(6)
        resumen_title = QLabel("Resumen")
        resumen_title.setStyleSheet("font-weight: 700; color: #111827;")
        resumen_layout.addWidget(resumen_title)
        for lbl in (
            self.subtotal_label,
            self.iva_label,
            self.comision_label_resumen,
            self.total_label,
        ):
            lbl.setStyleSheet("font-size: 13px; color: #0f172a;")
            resumen_layout.addWidget(lbl)
        left_card_layout.addWidget(resumen_box)

        self.btn_agregar.setObjectName("PrimaryAction")
        self.btn_agregar.setMinimumHeight(44)
        left_card_layout.addWidget(self.btn_agregar)
        left_card_layout.addStretch(1)

        # Tarjeta derecha
        right_card = QFrame()
        right_card.setObjectName("CardFrame")
        right_layout = QVBoxLayout(right_card)
        right_layout.setContentsMargins(16, 16, 16, 16)
        right_layout.setSpacing(12)
        right_title = QLabel("Búsqueda y Productos")
        right_title.setStyleSheet("font-size: 16px; font-weight: 700; color: #111827;")
        right_layout.addWidget(right_title)

        right_layout.addWidget(_stack_field("Buscar producto", self.product_search_edit))
        right_layout.addWidget(self.product_list, 1)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)

        def _grid_stack(label_text, widget):
            container = QWidget()
            vbox = QVBoxLayout(container)
            vbox.setContentsMargins(0, 0, 0, 0)
            vbox.setSpacing(4)
            lbl = QLabel(label_text)
            lbl.setStyleSheet("color: #4b5563; font-weight: 600;")
            vbox.addWidget(lbl)
            vbox.addWidget(widget)
            return container

        grid.addWidget(_grid_stack("Cantidad", self.cantidad_spin), 0, 0)
        grid.addWidget(_grid_stack("Unidad/Presentación", self.combo_presentacion), 0, 1)
        grid.addWidget(_grid_stack("Precio unitario", self.precio_unitario_spin), 0, 2)
        grid.addWidget(_grid_stack("Precio total", self.precio_total_spin), 0, 3)
        grid.addWidget(_grid_stack("Vencimiento", self.fecha_vencimiento_edit), 0, 4)

        grid.addWidget(_grid_stack("Código de lote", self.codigo_lote_edit), 1, 0, 1, 2)
        grid.addWidget(_grid_stack("Registro sanitario", self.registro_sanitario_edit), 1, 2, 1, 2)

        descuento_container = QWidget()
        desc_layout = QHBoxLayout(descuento_container)
        desc_layout.setContentsMargins(0, 0, 0, 0)
        desc_layout.setSpacing(6)
        desc_layout.addWidget(self.descuento_spin)
        desc_layout.addWidget(self.descuento_tipo_combo)
        grid.addWidget(_grid_stack("Descuento", descuento_container), 2, 0)

        iva_opts = QWidget()
        iva_opts_layout = QVBoxLayout(iva_opts)
        iva_opts_layout.setContentsMargins(0, 0, 0, 0)
        iva_opts_layout.setSpacing(4)
        iva_opts_layout.addWidget(self.iva_checkbox)
        iva_radios = QHBoxLayout()
        iva_radios.setContentsMargins(0, 0, 0, 0)
        iva_radios.setSpacing(6)
        iva_radios.addWidget(self.iva_desglosado_radio)
        iva_radios.addWidget(self.iva_añadido_radio)
        iva_opts_layout.addLayout(iva_radios)
        grid.addWidget(_grid_stack("IVA", iva_opts), 2, 1, 1, 3)

        right_layout.addLayout(grid)

        # Intercambia posiciones: búsqueda a la izquierda, proveedor a la derecha
        top_split.addWidget(right_card, 65)
        top_split.addWidget(left_card, 35)
        layout.addLayout(top_split)

        # Tarjeta inferior: carrito
        cart_card = QFrame()
        cart_card.setObjectName("CardFrame")
        cart_layout = QVBoxLayout(cart_card)
        cart_layout.setContentsMargins(16, 16, 16, 16)
        cart_layout.setSpacing(10)
        cart_title = QLabel("Carrito de Compra")
        cart_title.setStyleSheet("font-size: 16px; font-weight: 700; color: #111827;")
        cart_layout.addWidget(cart_title)

        # En el __init__ de RegisterPurchaseDialog, donde creas la tabla:
        self.table = QTableWidget(0, 12)
        self.table.setHorizontalHeaderLabels([
            "Producto",
            "Cantidad",
            "Precio U.",
            "Subtotal",
            "IVA",
            "Comisión",
            "Total",
            "Código lote",
            "Registro sanitario",
            "Vencimiento",
            "Editar",
            "Eliminar",
        ])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # Oculta columna de registro sanitario solo en UI (se sigue guardando)
        self.table.setColumnHidden(8, True)
        cart_layout.addWidget(self.table)
        self._edit_column = 10
        self._delete_column = 11

        # Total general de la compra
        layout.addWidget(cart_card)

        # Botón registrar compra
        self.total_general_label = QLabel(f"Total compra: {self._format_currency(0)}")
        self.btn_registrar = QPushButton(
            "Guardar cambios" if self.edit_mode else "Registrar Compra"
        )
        self.btn_cancelar = QPushButton("Cancelar")
        botones_layout = QHBoxLayout()
        botones_layout.addWidget(self.total_general_label)
        botones_layout.addStretch(1)
        botones_layout.addWidget(self.btn_registrar)
        botones_layout.addWidget(self.btn_cancelar)
        layout.addLayout(botones_layout)

        self.setLayout(layout)

        # Estilos
        self.setStyleSheet(
            """
            QDialog {
                background-color: #f0f2f5;
            }
            QFrame#CardFrame {
                background-color: white;
                border: 1px solid #e5e7eb;
                border-radius: 8px;
            }
            QFrame#SubCardFrame {
                background-color: #f9fafb;
                border: 1px solid #e5e7eb;
                border-radius: 6px;
            }
            QPushButton#PrimaryAction {
                background-color: #2563eb;
                color: white;
                border: none;
                border-radius: 6px;
                font-weight: 700;
            }
            QPushButton#PrimaryAction:hover {
                background-color: #1d4ed8;
            }
            QListWidget::item:selected {
                background-color: #e0f2fe;
                color: #0f172a;
            }
            QListWidget::item:selected:!active {
                background-color: #e0f2fe;
                color: #0f172a;
            }
            """
        )

        # --- CONEXIONES ---
        self.btn_cancelar.clicked.connect(self.reject)
        self.btn_registrar.clicked.connect(self._registrar_compra)
        self.btn_agregar.clicked.connect(self._agregar_a_compra)
        self.table.cellClicked.connect(self._eliminar_fila)
        self.product_search_edit.textChanged.connect(self._filtrar_lista_productos)
        self.product_list.currentRowChanged.connect(self._actualizar_vendedor_y_Distribuidor)
        self.product_list.currentRowChanged.connect(self._actualizar_presentacion_combo)
        self.combo_presentacion.currentIndexChanged.connect(self._actualizar_precio_unitario_por_producto)
        self.vendedor_combo.currentIndexChanged.connect(self._mark_vendor_user_selected)
        self.vendedor_combo.currentIndexChanged.connect(self._actualizar_Distribuidor)
        self.vendedor_combo.currentIndexChanged.connect(self._update_summary_vendor_info)
        self.vendedor_combo.currentIndexChanged.connect(self._on_proveedor_changed)
        self.Distribuidor_combo.currentIndexChanged.connect(self._update_summary_vendor_info)
        self.comision_pct_spin.valueChanged.connect(self._actualizar_total_general)
        self.product_list.currentRowChanged.connect(self._actualizar_precio_unitario_por_producto)
        self._actualizar_precio_unitario_por_producto()
        self._actualizar_presentacion_combo()

        # Inicializa combos
        if productos:
            self.product_list.setCurrentRow(0)
            self._actualizar_vendedor_y_Distribuidor()
        self._actualizar_total_general()
        self._reset_edit_mode()

        if self.edit_mode:
            self._cargar_compra_existente(detalles)
        # Aplica estado inicial de sujeto excluido si aplica
        self._apply_subject_excluded_ui_state(self.is_subject_excluded_purchase)
        # Solo marcar como elección del usuario cuando intervenga manualmente
        self._user_selected_vendor = False

        # Conexiones para cálculo en tiempo real
        self.cantidad_spin.valueChanged.connect(self._calcular_preview_item)
        self.precio_unitario_spin.valueChanged.connect(self._calcular_preview_item)
        self.precio_total_spin.valueChanged.connect(self._calcular_preview_item)
        self.comision_pct_spin.valueChanged.connect(self._calcular_preview_item)
        self.iva_checkbox.stateChanged.connect(self._toggle_iva_radios)
        self.iva_desglosado_radio.toggled.connect(self._calcular_preview_item)
        self.iva_añadido_radio.toggled.connect(self._calcular_preview_item)
        self.product_list.currentRowChanged.connect(self._calcular_preview_item)
        self._calcular_preview_item()

    def _format_currency(self, value):
        dec_value = Decimal(str(value))
        quantized = dec_value.quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)
        formatted = format(quantized.normalize(), "f")
        if "." in formatted:
            formatted = formatted.rstrip("0").rstrip(".")
        if formatted in ("-0", "-0.0"):
            formatted = "0"
        return f"${formatted}"

    def _quantize_money(self, value, exp: str = "0.01") -> Decimal:
        try:
            dec_value = Decimal(str(value if value is not None else 0))
        except (InvalidOperation, ValueError, TypeError):
            dec_value = Decimal("0")
        return dec_value.quantize(Decimal(exp), rounding=ROUND_HALF_UP)

    def _init_summary_section(self, parent_layout):
        self._summary_group = QGroupBox("Información de la compra")
        form_layout = QFormLayout()

        self._summary_id_label = QLabel("-")
        self._summary_fecha_label = QLabel("-")
        self._summary_vendedor_label = QLabel("-")
        self._summary_distribuidor_label = QLabel("-")
        self._summary_items_label = QLabel("0")
        self._summary_total_label = QLabel(self._format_currency(0))

        for lbl in (
            self._summary_id_label,
            self._summary_fecha_label,
            self._summary_vendedor_label,
            self._summary_distribuidor_label,
            self._summary_items_label,
            self._summary_total_label,
        ):
            lbl.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)

        form_layout.addRow("ID de compra:", self._summary_id_label)
        form_layout.addRow("Fecha registrada:", self._summary_fecha_label)
        form_layout.addRow("Vendedor:", self._summary_vendedor_label)
        form_layout.addRow("Distribuidor:", self._summary_distribuidor_label)
        form_layout.addRow("Productos cargados:", self._summary_items_label)
        form_layout.addRow("Total registrado:", self._summary_total_label)

        self._summary_group.setLayout(form_layout)
        parent_layout.addWidget(self._summary_group)

    def _format_fecha(self, value):
        if not value:
            return "-"
        if isinstance(value, datetime):
            return value.strftime("%d/%m/%Y %H:%M:%S")
        if isinstance(value, date):
            return value.strftime("%d/%m/%Y")
        if isinstance(value, str):
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                try:
                    parsed = datetime.strptime(value, fmt)
                    if "%H" in fmt:
                        return parsed.strftime("%d/%m/%Y %H:%M:%S")
                    return parsed.strftime("%d/%m/%Y")
                except ValueError:
                    continue
            return value
        return str(value)

    def _populate_compra_summary(self):
        if not self.edit_mode or not hasattr(self, "_summary_id_label"):
            return
        self._summary_id_label.setText(str(self._compra_id) if self._compra_id is not None else "-")
        fecha_val = self._compra_data.get("fecha") if self._compra_data else None
        self._summary_fecha_label.setText(self._format_fecha(fecha_val))
        self._summary_items_label.setText(str(len(self.compra_items)))

        total_registrado = self._compra_data.get("total") if self._compra_data else None
        if total_registrado is None:
            total_registrado = sum(item.get("total", 0) for item in self.compra_items)
        self._summary_total_label.setText(self._format_currency(total_registrado))

        self._update_summary_vendor_info()

    def _update_summary_vendor_info(self):
        if not self.edit_mode or not hasattr(self, "_summary_vendedor_label"):
            return

        vendedor_texto = "Sin vendedor"
        vendedor_id = self.vendedor_combo.currentData() if hasattr(self, "vendedor_combo") else None
        if vendedor_id is not None:
            vendedor = self._vendedores_map.get(vendedor_id)
            if vendedor:
                vendedor_texto = vendedor.get("nombre") or vendedor.get("codigo") or vendedor_texto
            else:
                texto_combo = self.vendedor_combo.currentText().strip()
                if texto_combo:
                    vendedor_texto = texto_combo

        distribuidor_texto = "-"
        if self.Distribuidor_combo.count() > 0:
            distribuidor_texto = self.Distribuidor_combo.currentText().strip() or "-"
        elif self.edit_mode and self._compra_data.get("Distribuidor_id"):
            distribuidor = self._distribuidores_map.get(self._compra_data.get("Distribuidor_id"))
            if distribuidor:
                distribuidor_texto = distribuidor.get("nombre", distribuidor_texto)

        self._summary_vendedor_label.setText(vendedor_texto or "Sin vendedor")
        self._summary_distribuidor_label.setText(distribuidor_texto or "-")

    def _get_producto_por_indice(self, idx):
        if 0 <= idx < len(self._filtered_productos):
            return self._filtered_productos[idx]
        return None

    def _get_current_producto(self):
        return self._get_producto_por_indice(self.product_list.currentRow())

    def _refrescar_lista_productos(self, selected_id=None):
        if selected_id is None:
            current_producto = self._get_current_producto()
            if current_producto:
                selected_id = current_producto.get("id")

        with QSignalBlocker(self.product_list):
            self.product_list.clear()
            for producto in self._filtered_productos:
                self.product_list.addItem(producto.get("nombre", ""))

        if not self._filtered_productos:
            self.product_list.setCurrentRow(-1)
            return

        row_to_select = 0
        if selected_id is not None:
            for idx, producto in enumerate(self._filtered_productos):
                if producto.get("id") == selected_id:
                    row_to_select = idx
                    break
            else:
                row_to_select = 0

        self.product_list.setCurrentRow(row_to_select)

    def _filtrar_lista_productos(self, texto):
        texto_normalizado = (texto or "").strip().lower()
        current_producto = self._get_current_producto()
        selected_id = current_producto.get("id") if current_producto else None

        if not texto_normalizado:
            filtrados = list(self.productos)
        else:
            filtrados = [
                producto
                for producto in self.productos
                if texto_normalizado in str(producto.get("nombre", "")).lower()
                or texto_normalizado in str(producto.get("codigo", "")).lower()
                or texto_normalizado in str(producto.get("sku", "")).lower()
            ]

        self._filtered_productos = filtrados
        self._refrescar_lista_productos(selected_id)

    def _actualizar_presentacion_combo(self):
        prod = self._get_current_producto()
        with QSignalBlocker(self.combo_presentacion):
            self.combo_presentacion.clear()
            self.combo_presentacion.addItem("Unidad Base (x1)", 1)
            if prod:
                presentaciones = prod.get("presentaciones") or []
                if isinstance(presentaciones, list):
                    for pres in presentaciones:
                        try:
                            factor = float(pres.get("factor") or 0)
                        except Exception:
                            continue
                        if factor <= 0:
                            continue
                        nombre_raw = str(pres.get("nombre") or "").strip()
                        opcion_texto = (
                            f"{nombre_raw} (x{factor:g})" if nombre_raw else f"Presentación x{factor:g}"
                        )
                        self.combo_presentacion.addItem(opcion_texto, factor)
                        self.combo_presentacion.setItemData(self.combo_presentacion.count() - 1, pres, Qt.UserRole + 1)
            self.combo_presentacion.setCurrentIndex(0)
        self._actualizar_precio_unitario_por_producto()

    # --- NUEVO MÉTODO ---
    def _actualizar_precio_unitario_por_producto(self):
        idx = self.product_list.currentRow()
        prod = self._get_producto_por_indice(idx)
        if not prod:
            self.precio_unitario_spin.setValue(0)
            return
        pres_data = self.combo_presentacion.itemData(self.combo_presentacion.currentIndex(), Qt.UserRole + 1)
        factor_raw = self.combo_presentacion.currentData()
        try:
            factor = float(factor_raw)
        except Exception:
            factor = 1.0
        if factor <= 0:
            factor = 1.0
        precio = None
        if isinstance(pres_data, Mapping):
            precio = pres_data.get("precio_compra")
        precio_base = prod.get("precio_compra", 0) or 0
        try:
            precio_base_val = float(precio_base)
        except Exception:
            precio_base_val = 0.0
        if precio in (None, ""):
            try:
                precio = float(precio_base_val) * factor
            except Exception:
                precio = 0
        try:
            precio_val = float(precio)
        except Exception:
            precio_val = 0.0
        if precio_val <= 0 and precio_base_val > 0:
            precio_val = precio_base_val * factor
        try:
            precio_val = float(precio_val)
        except Exception:
            precio_val = 0.0
        self.precio_unitario_spin.blockSignals(True)
        self.precio_unitario_spin.setValue(precio_val)
        self.precio_unitario_spin.blockSignals(False)
        self._calcular_preview_item()

    def _calcular_preview_item(self):
        cantidad = self.cantidad_spin.value()

        precio_unit = self.precio_unitario_spin.value()
        precio_total = self.precio_total_spin.value()

        # Si el total es editable y el usuario lo modificó, ajusta el precio unitario
        if self.precio_total_spin.isEnabled() and self.precio_total_spin.hasFocus():
            precio_unit = round(precio_total / cantidad, 8) if cantidad > 0 else 0
            self.precio_unitario_spin.blockSignals(True)
            self.precio_unitario_spin.setValue(precio_unit)
            self.precio_unitario_spin.blockSignals(False)
        else:
            precio_total = cantidad * precio_unit
            self.precio_total_spin.blockSignals(True)
            self.precio_total_spin.setValue(precio_total)
            self.precio_total_spin.blockSignals(False)

        subtotal = cantidad * precio_unit

        # Descuento
        descuento_valor = self.descuento_spin.value()
        descuento_tipo = self.descuento_tipo_combo.currentText()
        if descuento_tipo == "%":
            descuento_monto = subtotal * (descuento_valor / 100)
        else:
            descuento_monto = min(descuento_valor, subtotal)
        subtotal_con_descuento = max(subtotal - descuento_monto, 0)

        # Comisión (se calcula antes del IVA para determinar la base)
        comision_pct = self.comision_pct_spin.value()
        comision_tipo = self.comision_tipo_combo.currentText()
        if comision_tipo == "Añadida al total":
            comision_monto = subtotal_con_descuento * (comision_pct / 100)
        elif comision_tipo == "Desglosada (incluida en el precio)":
            # La comisión ya está incluida en el precio, se calcula cuánto representa
            comision_monto = subtotal_con_descuento * (comision_pct / (100 + comision_pct)) if comision_pct > 0 else 0
        else:
            comision_monto = 0

        # Base para calcular IVA
        base_iva = subtotal_con_descuento
        if comision_tipo == "Desglosada (incluida en el precio)":
            base_iva = subtotal_con_descuento - comision_monto

        # IVA
        iva = 0
        total = subtotal_con_descuento
        if not self.is_subject_excluded_purchase and self.iva_checkbox.isChecked():
            if self.iva_desglosado_radio.isChecked():
                iva = base_iva * 13 / 113
                total = subtotal_con_descuento
            elif self.iva_añadido_radio.isChecked():
                iva = base_iva * 0.13
                total = subtotal_con_descuento + iva

        # Total final considerando comisión
        if comision_tipo == "Añadida al total":
            total_final = total + comision_monto
        else:
            total_final = total  # Comisión ya incluida o inexistente

        self.subtotal_label.setText(f"Subtotal: {self._format_currency(subtotal)}")
        self.iva_label.setText(f"IVA: {self._format_currency(iva)}")
        self.comision_label_resumen.setText(f"Comisión: {self._format_currency(comision_monto)}")
        self.total_label.setText(f"TOTAL: {self._format_currency(total_final)}")

    def _toggle_iva_radios(self, state):
        checked = self.iva_checkbox.isChecked()
        self.iva_desglosado_radio.setEnabled(checked)
        self.iva_añadido_radio.setEnabled(checked)
        if checked and not (self.iva_desglosado_radio.isChecked() or self.iva_añadido_radio.isChecked()):
            self.iva_desglosado_radio.setChecked(True)
        if not checked:
            self.iva_group.setExclusive(False)
            self.iva_desglosado_radio.setChecked(False)
            self.iva_añadido_radio.setChecked(False)
            self.iva_group.setExclusive(True)
        self._calcular_preview_item()

    def _actualizar_total_general(self):
        subtotal_general = sum(
            (self._quantize_money(item.get("subtotal", item["cantidad"] * item["precio"])) for item in self.compra_items),
            Decimal("0.00"),
        )
        iva_general = sum(
            (self._quantize_money(item.get("iva", 0)) for item in self.compra_items),
            Decimal("0.00"),
        )
        comision_general = sum(
            (self._quantize_money(item.get("comision_monto", 0)) for item in self.compra_items),
            Decimal("0.00"),
        )
        total_general = sum(
            (self._quantize_money(item.get("total", 0)) for item in self.compra_items),
            Decimal("0.00"),
        )

        self.subtotal_label.setText(f"Subtotal: {self._format_currency(subtotal_general)}")
        self.iva_label.setText(f"IVA: {self._format_currency(iva_general)}")
        self.comision_label_resumen.setText(f"Comisión: {self._format_currency(comision_general)}")
        self.total_label.setText(f"TOTAL: {self._format_currency(total_general)}")
        self.total_general_label.setText(f"Total compra: {self._format_currency(total_general)}")
        if self.edit_mode and hasattr(self, "_summary_items_label"):
            self._summary_items_label.setText(str(len(self.compra_items)))
            self._summary_total_label.setText(self._format_currency(total_general))

    def _fetch_db_record(self, table, record_id):
        parent = self.parent()
        if not record_id or not parent or not hasattr(parent, "manager"):
            return None
        db = getattr(parent.manager, "db", None)
        if db is None or not hasattr(db, "cursor"):
            return None
        try:
            db.cursor.execute(f"SELECT * FROM {table} WHERE id=?", (record_id,))
            row = db.cursor.fetchone()
            return dict(row) if row else None
        except Exception:
            logger.exception("No fue posible cargar el registro %s de %s", record_id, table)
            return None

    def _ensure_vendor_available(self, vendedor_id):
        if vendedor_id is None:
            return None
        vendedor = self._vendedores_map.get(vendedor_id)
        if vendedor is None:
            vendedor = self._fetch_db_record("vendedores", vendedor_id)
            if vendedor is None:
                vendedor = {
                    "id": vendedor_id,
                    "nombre": f"Proveedor {vendedor_id}",
                    "codigo": "",
                    "Distribuidor_id": self._compra_data.get("Distribuidor_id"),
                }
            self._vendedores_map[vendedor_id] = vendedor

        distribuidor_id = vendedor.get("Distribuidor_id")
        if distribuidor_id is None and self._compra_data.get("Distribuidor_id") is not None:
            distribuidor_id = self._compra_data.get("Distribuidor_id")
            vendedor = dict(vendedor)
            vendedor["Distribuidor_id"] = distribuidor_id
            self._vendedores_map[vendedor_id] = vendedor
        self._vendedor_Distribuidor_map[vendedor_id] = distribuidor_id

        if self.vendedor_combo.findData(vendedor_id) < 0:
            codigo = vendedor.get("codigo") or ""
            nombre = vendedor.get("nombre") or f"Proveedor {vendedor_id}"
            display_text = f"{nombre} — {codigo}" if codigo else nombre
            with QSignalBlocker(self.vendedor_combo):
                self.vendedor_combo.addItem(display_text, vendedor_id)
        return vendedor

    def _ensure_distribuidor_available(self, distribuidor_id):
        if distribuidor_id is None:
            return None
        distribuidor = self._distribuidores_map.get(distribuidor_id)
        if distribuidor is None:
            distribuidor = self._fetch_db_record("Distribuidores", distribuidor_id)
            if distribuidor is None:
                distribuidor = {
                    "id": distribuidor_id,
                    "nombre": f"Distribuidor {distribuidor_id}",
                }
            self._distribuidores_map[distribuidor_id] = distribuidor
            if not any(d.get("id") == distribuidor_id for d in self.Distribuidores):
                self.Distribuidores.append(distribuidor)
        return distribuidor

    def _cargar_compra_existente(self, detalles):
        vendedor_id = self._compra_data.get("vendedor_id") if self._compra_data else None
        if vendedor_id is not None:
            self._ensure_vendor_available(vendedor_id)
            idx = self.vendedor_combo.findData(vendedor_id)
            if idx >= 0:
                self.vendedor_combo.setCurrentIndex(idx)
        self._actualizar_Distribuidor()
        distribuidor_id = self._compra_data.get("Distribuidor_id") if self._compra_data else None
        if distribuidor_id is not None:
            self._ensure_distribuidor_available(distribuidor_id)
            idx = self.Distribuidor_combo.findData(distribuidor_id)
            if idx >= 0:
                self.Distribuidor_combo.setCurrentIndex(idx)

        if detalles is None:
            detalles = []
            if self.parent() and hasattr(self.parent(), "manager") and getattr(self.parent().manager, "db", None) and self._compra_id is not None:
                try:
                    detalles = self.parent().manager.db.get_detalles_compra(self._compra_id)
                except Exception:
                    logger.exception("No fue posible cargar los detalles de la compra %s", self._compra_id)
                    detalles = []

        self.compra_items = []
        for detalle in detalles:
            producto_id = detalle.get("producto_id")
            producto_info = self._productos_por_id.get(producto_id, {})
            nombre_producto = producto_info.get("nombre") or f"Producto {producto_id}" if producto_id is not None else ""
            factor_raw = detalle.get("presentacion_factor")
            try:
                factor_val = float(factor_raw)
            except Exception:
                factor_val = 1.0
            if factor_val <= 0:
                factor_val = 1.0
            cantidad_base = detalle.get("cantidad", 0) or 0
            cantidad_pres = detalle.get("cantidad_presentacion")
            if cantidad_pres is None and factor_val:
                try:
                    cantidad_pres = float(cantidad_base) / factor_val
                except Exception:
                    cantidad_pres = None
            cantidad = cantidad_pres if cantidad_pres is not None else cantidad_base
            precio_base = detalle.get("precio_unitario", 0) or 0
            precio_pres = detalle.get("precio_presentacion")
            if precio_pres is None and factor_val:
                try:
                    precio_pres = float(precio_base) * factor_val
                except Exception:
                    precio_pres = precio_base
            precio = precio_pres if precio_pres is not None else precio_base
            subtotal = detalle.get("subtotal")
            if subtotal is None:
                subtotal = cantidad * precio
            descuento_monto = detalle.get("descuento", 0) or 0
            descuento_tipo = detalle.get("descuento_tipo", "%") or "%"
            if descuento_tipo == "%":
                descuento_valor = (descuento_monto / subtotal * 100) if subtotal else 0
            else:
                descuento_valor = descuento_monto
            subtotal_con_descuento = max(subtotal - descuento_monto, 0)
            iva = detalle.get("iva", 0) or 0
            iva_tipo = detalle.get("iva_tipo") or "ninguno"
            comision_pct = detalle.get("comision_pct", 0) or 0
            comision_monto = detalle.get("comision_monto", 0) or 0
            comision_tipo = detalle.get("comision_tipo") or "Añadida al total"
            total = detalle.get("total")
            if total is None:
                total_base = subtotal_con_descuento
                if iva_tipo == "añadido":
                    total_base = subtotal_con_descuento + iva
                total = total_base + comision_monto if comision_tipo == "Añadida al total" else total_base
            self.compra_items.append(
                {
                    "producto": nombre_producto,
                    "producto_display": nombre_producto,
                    "producto_id": producto_id,
                    "cantidad": cantidad,
                    "cantidad_base": cantidad_base,
                    "cantidad_presentacion": cantidad,
                    "presentacion_factor": factor_val,
                    "presentacion_nombre": detalle.get("presentacion_nombre", "Unidad Base (x1)"),
                    "precio": precio,
                    "precio_presentacion": precio,
                    "precio_unitario_base": precio_base,
                    "subtotal": subtotal,
                    "descuento_valor": descuento_valor,
                    "descuento_pct": (descuento_monto / subtotal * 100) if subtotal else 0,
                    "descuento_monto": descuento_monto,
                    "descuento_tipo": descuento_tipo,
                    "iva": iva,
                    "iva_tipo": iva_tipo,
                    "comision_pct": comision_pct,
                    "comision_monto": comision_monto,
                    "comision_tipo": comision_tipo,
                    "total": total,
                    "fecha_vencimiento": detalle.get("fecha_vencimiento", "") or "",
                    "codigo_lote": detalle.get("codigo_lote", "") or "",
                    "registro_sanitario": detalle.get("registro_sanitario", "") or "",
                }
            )

        self._populate_compra_summary()
        self._actualizar_tabla()
        self._actualizar_total_general()

    def _actualizar_vendedor_y_Distribuidor(self):
        idx = self.product_list.currentRow()
        producto = self._get_producto_por_indice(idx)
        if not producto:
            return
        vendedor_id = producto.get("vendedor_id")
        # Solo auto-seleccionar si el usuario no ha elegido manualmente o no hay selección válida
        if self._user_selected_vendor and self.vendedor_combo.currentData() is not None:
            return
        combo_idx = self.vendedor_combo.findData(vendedor_id)
        self._suppress_vendor_signal = True
        self.vendedor_combo.blockSignals(True)
        if combo_idx >= 0:
            self.vendedor_combo.setCurrentIndex(combo_idx)
        elif not self._user_selected_vendor:
            self.vendedor_combo.setCurrentIndex(0)
        self.vendedor_combo.blockSignals(False)
        self._suppress_vendor_signal = False
        self._actualizar_Distribuidor()

    def _actualizar_Distribuidor(self):
        vendedor_id = self.vendedor_combo.currentData()
        self.Distribuidor_combo.clear()
        if vendedor_id is None:
            self.comision_label_resumen.setText("Comisión vendedor: 0%")
            self.comision_pct_spin.setValue(0)
            if self.edit_mode and self._compra_data.get("Distribuidor_id"):
                distribuidor_id = self._compra_data.get("Distribuidor_id")
                distribuidor = self._ensure_distribuidor_available(distribuidor_id)
                if distribuidor:
                    self.Distribuidor_combo.addItem(distribuidor.get("nombre", ""), distribuidor_id)
            self._update_summary_vendor_info()
            return
        vendedor = self._ensure_vendor_available(vendedor_id)
        if not vendedor:
            self.comision_label_resumen.setText("Comisión vendedor: 0%")
            self.comision_pct_spin.setValue(0)
            self._update_summary_vendor_info()
            return
        Distribuidor_id = self._vendedor_Distribuidor_map.get(vendedor_id)
        if Distribuidor_id is None:
            Distribuidor_id = vendedor.get("Distribuidor_id") or self._compra_data.get("Distribuidor_id")
        distribuidor = self._ensure_distribuidor_available(Distribuidor_id)
        if distribuidor:
            self.Distribuidor_combo.addItem(distribuidor.get("nombre", ""), Distribuidor_id)
        # Actualiza comisión base del vendedor
        comision = vendedor.get("comision_base", 0)
        try:
            comision_val = float(comision) if comision is not None else 0.0
        except Exception:
            comision_val = 0.0
        self.comision_label_resumen.setText(f"Comisión vendedor: {comision_val}%")
        self.comision_pct_spin.setValue(comision_val)
        self._update_summary_vendor_info()

    def _on_proveedor_changed(self):
        """Solo UI: muestra/oculta banner y aplica modo sujeto excluido."""

        if self._suppress_vendor_signal:
            return
        vendor_id = self.vendedor_combo.currentData()
        vendor = self._vendedores_map.get(vendor_id) if vendor_id is not None else None
        enabled = bool(vendor.get("is_subject_excluded")) if vendor else False
        self.is_subject_excluded_purchase = enabled
        self.subject_excluded_banner.setVisible(enabled)
        self._apply_subject_excluded_ui_state(enabled)
        self._user_selected_vendor = True

    def _mark_vendor_user_selected(self, *args, **kwargs):
        """Marca que el usuario cambió el vendedor manualmente."""

        if self._suppress_vendor_signal:
            return
        self._user_selected_vendor = True

    def _apply_subject_excluded_ui_state(self, enabled: bool) -> None:
        """Solo UI: deshabilita/rehabilita IVA cuando la compra es a sujeto excluido."""

        if enabled:
            self.iva_checkbox.blockSignals(True)
            self.iva_checkbox.setChecked(False)
            self.iva_checkbox.blockSignals(False)
            self.iva_desglosado_radio.setChecked(False)
            self.iva_añadido_radio.setChecked(False)
            self.descuento_spin.blockSignals(True)
            self.iva_desglosado_radio.setEnabled(False)
            self.iva_añadido_radio.setEnabled(False)
            self.iva_checkbox.setEnabled(False)
            self.descuento_spin.blockSignals(False)
            # Normaliza IVA de ítems existentes solo para la vista
            if self.compra_items:
                updated = False
                for item in self.compra_items:
                    if item.get("iva", 0) or item.get("iva_tipo") not in (None, "", "ninguno"):
                        item["iva"] = 0
                        item["iva_tipo"] = "ninguno"
                        updated = True
                if updated:
                    self._actualizar_tabla()
                    self._actualizar_total_general()
        else:
            self.iva_checkbox.setEnabled(True)
            self.iva_desglosado_radio.setEnabled(True)
            self.iva_añadido_radio.setEnabled(True)

    def _agregar_a_compra(self):
        producto_info = self._get_current_producto()
        producto = producto_info.get("nombre", "") if producto_info else ""
        cantidad = self.cantidad_spin.value()
        precio = self.precio_unitario_spin.value()
        if not producto_info or not producto or cantidad <= 0 or precio <= 0:
            QMessageBox.warning(self, "Validación", "Seleccione producto, cantidad y precio válidos.")
            return

        factor_raw = self.combo_presentacion.currentData()
        try:
            factor = float(factor_raw)
        except Exception:
            factor = 1.0
        if factor <= 0:
            factor = 1.0
        presentacion_nombre = (self.combo_presentacion.currentText() or "Unidad Base (x1)").strip()
        cantidad_base = cantidad * factor
        precio_unitario_base = precio / factor if factor else precio
        producto_display = producto
        if presentacion_nombre and not presentacion_nombre.lower().startswith("unidad base"):
            producto_display = f"{producto} [{presentacion_nombre}]"

        producto_id = producto_info.get("id")
        subtotal = cantidad * precio
        descuento_valor = self.descuento_spin.value()
        descuento_tipo = self.descuento_tipo_combo.currentText()
        if descuento_tipo == "%":
            descuento_monto = subtotal * (descuento_valor / 100)
            descuento_pct = descuento_valor
        else:
            descuento_monto = min(descuento_valor, subtotal)
            descuento_pct = (descuento_monto / subtotal * 100) if subtotal else 0
        subtotal_con_descuento = max(subtotal - descuento_monto, 0)

        comision_pct = self.comision_pct_spin.value()
        comision_tipo = self.comision_tipo_combo.currentText()
        if comision_tipo == "Añadida al total":
            comision_monto = subtotal_con_descuento * (comision_pct / 100)
        elif comision_tipo == "Desglosada (incluida en el precio)":
            comision_monto = subtotal_con_descuento * (comision_pct / (100 + comision_pct)) if comision_pct > 0 else 0
        else:
            comision_monto = 0

        base_iva = subtotal_con_descuento
        if comision_tipo == "Desglosada (incluida en el precio)":
            base_iva = subtotal_con_descuento - comision_monto

        iva = 0
        iva_tipo = "ninguno"
        total = subtotal_con_descuento
        if self.is_subject_excluded_purchase:
            iva = 0
            iva_tipo = "ninguno"
            total = subtotal_con_descuento
        elif self.iva_checkbox.isChecked():
            if self.iva_desglosado_radio.isChecked():
                iva = base_iva * 13 / 113
                iva_tipo = "desglosado"
            elif self.iva_añadido_radio.isChecked():
                iva = base_iva * 0.13
                iva_tipo = "añadido"
                total = subtotal_con_descuento + iva
            else:
                iva = 0
                iva_tipo = "ninguno"
        else:
            iva = 0
            iva_tipo = "ninguno"

        if not self.iva_checkbox.isChecked() or self.iva_desglosado_radio.isChecked():
            total = subtotal_con_descuento

        if comision_tipo == "Añadida al total":
            total_con_comision = total + comision_monto
        else:
            total_con_comision = total

        fecha_vencimiento = self.fecha_vencimiento_edit.date().toString("yyyy-MM-dd")

        item_data = {
            "producto": producto,
            "producto_display": producto_display,
            "producto_id": producto_id,
            "cantidad": cantidad,
            "cantidad_presentacion": cantidad,
            "cantidad_base": cantidad_base,
            "presentacion_factor": factor,
            "presentacion_nombre": presentacion_nombre,
            "precio": precio,
            "precio_presentacion": precio,
            "precio_unitario_base": precio_unitario_base,
            "subtotal": subtotal,
            "descuento_valor": descuento_valor,
            "descuento_pct": descuento_pct,
            "descuento_monto": descuento_monto,
            "descuento_tipo": descuento_tipo,
            "iva": iva,
            "iva_tipo": iva_tipo,
            "comision_pct": comision_pct,
            "comision_monto": comision_monto,
            "comision_tipo": comision_tipo,
            "total": total_con_comision,
            "fecha_vencimiento": fecha_vencimiento,
            "codigo_lote": self.codigo_lote_edit.text().strip(),
            "registro_sanitario": self.registro_sanitario_edit.text().strip(),
        }

        if self._editing_row is not None and 0 <= self._editing_row < len(self.compra_items):
            self.compra_items[self._editing_row] = item_data
        else:
            self.compra_items.append(item_data)

        self._reset_edit_mode()
        self._actualizar_tabla()
        self._actualizar_total_general()

    def _actualizar_tabla(self):
        self.table.setRowCount(len(self.compra_items))
        for i, item in enumerate(self.compra_items):
            producto_texto = item.get("producto_display", item.get("producto", ""))
            self.table.setItem(i, 0, QTableWidgetItem(producto_texto))

            cantidad_texto = str(item.get("cantidad", 0))
            presentacion_nombre = item.get("presentacion_nombre", "")
            if presentacion_nombre:
                cantidad_texto = f"{cantidad_texto} {presentacion_nombre}"
            cantidad_item = QTableWidgetItem(cantidad_texto)
            cantidad_item.setData(Qt.UserRole, item.get("cantidad_base", item.get("cantidad", 0)))
            self.table.setItem(i, 1, cantidad_item)
            self.table.setItem(i, 2, QTableWidgetItem(self._format_currency(item["precio"])))
            self.table.setItem(i, 3, QTableWidgetItem(self._format_currency(item.get("subtotal", 0))))
            self.table.setItem(i, 4, QTableWidgetItem(self._format_currency(item.get("iva", 0))))
            # Comisión (monto y porcentaje)
            comision_text = f"{self._format_currency(item.get('comision_monto', 0))} ({item.get('comision_pct', 0):.2f}%)"
            self.table.setItem(i, 5, QTableWidgetItem(comision_text))
            self.table.setItem(i, 6, QTableWidgetItem(self._format_currency(item.get("total", 0))))
            self.table.setItem(i, 7, QTableWidgetItem(item.get("codigo_lote", "")))
            self.table.setItem(i, 8, QTableWidgetItem(item.get("registro_sanitario", "")))
            self.table.setItem(i, 9, QTableWidgetItem(item.get("fecha_vencimiento", "")))

            size_style = (
                "font-size:9px; min-width:70px; max-width:100px; "
                "min-height:10px; max-height:15px;"
            )

            edit_btn = QPushButton("Editar")
            edit_btn.setStyleSheet(size_style)
            edit_btn.clicked.connect(lambda _, row=i: self._start_edit_item(row))
            self.table.setCellWidget(i, self._edit_column, edit_btn)

            delete_btn = QPushButton("Eliminar")
            delete_btn.setStyleSheet(
                "background-color: #b71c1c; color: #fff; border-radius: 6px; "
                f"{size_style}"
            )
            delete_btn.clicked.connect(lambda _, row=i: self._eliminar_item(row))
            self.table.setCellWidget(i, self._delete_column, delete_btn)

    def _reset_edit_mode(self):
        self._editing_row = None
        self.btn_agregar.setText("Agregar a compra")
        self.table.clearSelection()
        self.codigo_lote_edit.clear()
        self.registro_sanitario_edit.clear()
        if self.combo_presentacion.count() > 0:
            self.combo_presentacion.setCurrentIndex(0)

    def _start_edit_item(self, row):
        if not (0 <= row < len(self.compra_items)):
            return
        item = self.compra_items[row]
        self._editing_row = row
        self.btn_agregar.setText("Actualizar producto")

        if hasattr(self, "product_search_edit"):
            with QSignalBlocker(self.product_search_edit):
                self.product_search_edit.clear()
            self._filtrar_lista_productos("")

        matching_items = self.product_list.findItems(item.get("producto", ""), Qt.MatchExactly)
        if matching_items:
            self.product_list.setCurrentItem(matching_items[0])

        factor = item.get("presentacion_factor", 1)
        with QSignalBlocker(self.combo_presentacion):
            idx = self.combo_presentacion.findData(factor)
            self.combo_presentacion.setCurrentIndex(idx if idx >= 0 else 0)

        self.cantidad_spin.setValue(int(item.get("cantidad", 0)))
        self.precio_unitario_spin.setValue(float(item.get("precio", 0)))
        self.precio_total_spin.setValue(float(item.get("cantidad", 0)) * float(item.get("precio", 0)))
        self.codigo_lote_edit.setText(item.get("codigo_lote", ""))
        self.registro_sanitario_edit.setText(item.get("registro_sanitario", ""))

        descuento_tipo = item.get("descuento_tipo", "%")
        idx = self.descuento_tipo_combo.findText(descuento_tipo)
        if idx >= 0:
            self.descuento_tipo_combo.setCurrentIndex(idx)
        descuento_valor = item.get("descuento_valor")
        if descuento_valor is None and descuento_tipo == "%":
            descuento_valor = item.get("descuento_pct", 0)
        if descuento_valor is None:
            descuento_valor = 0
        self.descuento_spin.setValue(float(descuento_valor))

        iva_tipo = item.get("iva_tipo", "ninguno")
        if iva_tipo in ("desglosado", "añadido"):
            self.iva_checkbox.setChecked(True)
            if iva_tipo == "desglosado":
                self.iva_desglosado_radio.setChecked(True)
            else:
                self.iva_añadido_radio.setChecked(True)
        else:
            self.iva_checkbox.setChecked(False)

        self.comision_pct_spin.setValue(float(item.get("comision_pct", 0)))
        tipo_idx = 0
        self.comision_tipo_combo.setCurrentIndex(tipo_idx)

        fecha_texto = item.get("fecha_vencimiento")
        if fecha_texto:
            fecha_qt = QDate.fromString(fecha_texto, "yyyy-MM-dd")
            if fecha_qt.isValid():
                self.fecha_vencimiento_edit.setDate(fecha_qt)

        self._calcular_preview_item()


    def _eliminar_fila(self, row, col):
        if col == self._delete_column:
            self._eliminar_item(row)
        elif col == self._edit_column:
            self._start_edit_item(row)

    def _eliminar_item(self, row):
        if 0 <= row < len(self.compra_items):
            if self._editing_row is not None:
                if row == self._editing_row:
                    self._reset_edit_mode()
                elif row < self._editing_row:
                    self._editing_row -= 1
            del self.compra_items[row]
            self._actualizar_tabla()
            self._actualizar_total_general()

    def _registrar_compra(self):
        if not self.compra_items:
            QMessageBox.warning(self, "Validación", "Debe agregar al menos un producto a la compra.")
            return

        productos_dict = {p.get("nombre"): p.get("id") for p in self.productos}
        for item in self.compra_items:
            producto_id = item.get("producto_id")
            if producto_id is None:
                producto_id = productos_dict.get(item.get("producto"))
            if producto_id is None:
                QMessageBox.warning(
                    self,
                    "Producto no válido",
                    f"El producto '{item.get('producto', '')}' no existe. Registro cancelado."
                )
                return
            item["producto_id"] = producto_id

        if not self.edit_mode or not self._existing_fecha:
            fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        else:
            fecha = self._existing_fecha
        total_general = sum(
            (self._quantize_money(item.get("total", 0)) for item in self.compra_items),
            Decimal("0.00"),
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        vendedor_id = self.vendedor_combo.currentData()
        Distribuidor_id = (
            self.Distribuidor_combo.currentData()
            if self.Distribuidor_combo.count() > 0
            else None
        )

        if vendedor_id is None and self.edit_mode:
            vendedor_id = self._compra_data.get("vendedor_id")
        if Distribuidor_id is None and self.edit_mode:
            Distribuidor_id = self._compra_data.get("Distribuidor_id")

        if vendedor_id is None or Distribuidor_id is None:
            respuesta = QMessageBox.question(
                self,
                "Confirmación",
                "esta a punto de agregar una compra sin vendedor, esto puede causar errores en el sistema, esta seguro de continuar?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if respuesta != QMessageBox.Yes:
                return

        comision_total = sum(
            (self._quantize_money(item.get("comision_monto", 0)) for item in self.compra_items),
            Decimal("0.00"),
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        total_general_value = float(total_general)
        comision_total_value = float(comision_total)
        vendor_info = self._vendedores_map.get(vendedor_id) if vendedor_id is not None else {}
        is_subject_excluded_purchase = bool(
            self.is_subject_excluded_purchase or (vendor_info.get("is_subject_excluded") if vendor_info else False)
        )
        prev_dte_status = self._compra_data.get("subject_excluded_dte_status") if self.edit_mode else None
        if is_subject_excluded_purchase:
            dte_status = prev_dte_status or "PENDIENTE"
        else:
            dte_status = "NO_APLICA"

        def _cantidad_y_precio_base(item):
            factor_raw = item.get("presentacion_factor", 1)
            try:
                factor_val = float(factor_raw)
            except Exception:
                factor_val = 1.0
            if factor_val <= 0:
                factor_val = 1.0
            cantidad_pres = item.get("cantidad_presentacion", item.get("cantidad", 0))
            cantidad_base = item.get("cantidad_base")
            if cantidad_base is None:
                cantidad_base = (cantidad_pres or 0) * factor_val
            precio_presentacion = item.get("precio_presentacion", item.get("precio", 0))
            precio_base = item.get("precio_unitario_base")
            if precio_base is None:
                precio_base = precio_presentacion / factor_val if factor_val else precio_presentacion
            return float(cantidad_base), float(precio_base)

        if self.edit_mode and self._compra_id is not None:
            detalles_para_guardar = []
            for item in self.compra_items:
                cantidad_base, precio_base = _cantidad_y_precio_base(item)
                detalle = dict(item)
                detalle["cantidad"] = cantidad_base
                detalle["cantidad_base"] = cantidad_base
                detalle["cantidad_presentacion"] = item.get("cantidad_presentacion", item.get("cantidad"))
                detalle["precio"] = precio_base
                detalle["precio_unitario_base"] = precio_base
                detalle.setdefault("precio_presentacion", item.get("precio_presentacion", item.get("precio")))
                detalles_para_guardar.append(detalle)
            self.parent().manager.db.update_compra_detallada(
                self._compra_id,
                {
                    "fecha": fecha,
                    "producto_id": None,
                    "cantidad": 0,
                    "precio_unitario": 0,
                    "total": total_general_value,
                    "Distribuidor_id": Distribuidor_id,
                    "comision_pct": 0,
                    "comision_monto": comision_total_value,
                    "vendedor_id": vendedor_id,
                    "is_subject_excluded_purchase": is_subject_excluded_purchase,
                    "subject_excluded_dte_status": dte_status,
                },
                detalles_para_guardar,
            )
            self.accept()
            return

        compra_id = self.parent().manager.db.add_compra_detallada({
            "fecha": fecha,
            "producto_id": None,
            "cantidad": 0,
            "precio_unitario": 0,
            "total": total_general_value,
            "Distribuidor_id": Distribuidor_id,
            "comision_pct": 0,
            "comision_monto": comision_total_value,
            "vendedor_id": vendedor_id,
            "is_subject_excluded_purchase": is_subject_excluded_purchase,
            "subject_excluded_dte_status": dte_status,
        })

        for item in self.compra_items:
            producto_id = item["producto_id"]
            cantidad_base, precio_base = _cantidad_y_precio_base(item)
            self.parent().manager.db.add_detalle_compra(
                compra_id,
                producto_id,
                cantidad_base,
                precio_base,
                item.get("fecha_vencimiento", ""),
                item.get("descuento_monto", 0),
                item.get("descuento_tipo", "%"),
                item.get("iva", 0),
                item.get("iva_tipo", ""),
                item.get("comision_pct", 0),
                item.get("comision_monto", 0),
                item.get("comision_tipo", ""),
                codigo_lote=item.get("codigo_lote", ""),
                registro_sanitario=item.get("registro_sanitario", ""),
                cantidad_presentacion=item.get("cantidad_presentacion", item.get("cantidad")),
                presentacion_factor=item.get("presentacion_factor"),
                presentacion_nombre=item.get("presentacion_nombre"),
                precio_presentacion=item.get("precio_presentacion", item.get("precio")),
            )
            self.parent().manager.aumentar_stock(producto_id, cantidad_base)

        self.accept()

    def get_data(self):
        total_general = sum(item["total"] for item in self.compra_items)
        vendedor_id = self.vendedor_combo.currentData()
        Distribuidor_id = (
            self.Distribuidor_combo.currentData()
            if self.Distribuidor_combo.count() > 0
            else None
        )
        return {
            "fecha": QDate.currentDate().toString("yyyy-MM-dd"),
            "vendedor_id": vendedor_id,
            "Distribuidor_id": Distribuidor_id,
            "items": self.compra_items,
            "total": total_general,
            "comision_pct": self.comision_pct_spin.value(),
            "comision_tipo": self.comision_tipo_combo.currentText()
        }
    
class RegisterCreditoFiscalDialog(QDialog, ProductDialogBase):
    venta_validada = pyqtSignal(dict)

    def __init__(
        self,
        productos,
        Distribuidores,
        vendedores_trabajadores,
        parent=None,
        db=None,
        venta_extra=None,
    ):
        super().__init__(parent)
        self.db = db or (parent.manager.db if parent and hasattr(parent, "manager") else None)
        self.setWindowTitle("Registrar Venta a Crédito Fiscal")
        self.setMinimumSize(0, 0)
        self.resize(0, 0)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._apply_card_styles()
        content_widget = QWidget()
        main_layout = QVBoxLayout(content_widget)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(8)
        main_layout.setSizeConstraint(QLayout.SetMinimumSize)

        # --- LADO IZQUIERDO ---
        left_layout = QVBoxLayout()
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)
        self.productos = productos
        self.venta_items = []
        self.Distribuidores = Distribuidores
        self.vendedores_trabajadores = vendedores_trabajadores

        def _card(title: str):
            frame = QFrame()
            frame.setObjectName("Card")
            layout = QVBoxLayout(frame)
            layout.setContentsMargins(16, 14, 16, 14)
            layout.setSpacing(10)
            if title:
                header = QLabel(title)
                header.setObjectName("CardTitle")
                header.setStyleSheet("border: none; margin: 0; padding: 0 0 2px 0; font-weight: 700;")
                header.setContentsMargins(0, 0, 0, 0)
                header.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
                header.setFixedHeight(22)
                layout.addWidget(header)
            return frame, layout

        productos_card, productos_layout = _card("Búsqueda y productos")
        productos_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        productos_layout.setContentsMargins(12, 6, 12, 10)
        productos_layout.setSpacing(6)

        # Distribuidor y búsqueda
        top_row = QHBoxLayout()
        top_row.setSpacing(6)
        top_row.addWidget(QLabel("Distribuidor:"))
        self.Distribuidor_combo = QComboBox()
        if Distribuidores:
            if isinstance(Distribuidores[0], dict):
                self.Distribuidor_combo.addItems([d.get("nombre", "") for d in Distribuidores])
            else:
                self.Distribuidor_combo.addItems(Distribuidores)
        top_row.addWidget(self.Distribuidor_combo, 1)
        productos_layout.addLayout(top_row)

        self.product_search = QLineEdit()
        self.product_search.setPlaceholderText("Buscar producto por nombre o código...")
        productos_layout.addWidget(self.product_search)

        self.product_list = QListWidget()
        self._productos_original = list(productos)
        self._mostrar_productos(productos)
        self.product_list.setMinimumHeight(100)
        self.product_list.setMaximumHeight(130)
        self.product_list.setSpacing(2)
        self.product_list.setStyleSheet(
            "QListWidget { border: 1px solid #d4d4d8; border-radius: 6px; }"
            "QListWidget::item { padding: 6px 8px; margin: 2px 4px; border-radius: 4px; }"
            "QListWidget::item:selected { background: #e5f1ff; color: #0f172a; }"
        )
        productos_layout.addWidget(self.product_list)

        # Grid compacto de captura (igual que consumidor final)
        grid = QGridLayout()
        grid.setVerticalSpacing(4)
        grid.setHorizontalSpacing(8)
        grid.addWidget(QLabel("Cant."), 0, 0)
        grid.addWidget(QLabel("Unidad/Pres."), 0, 1)
        grid.addWidget(QLabel("P. Unitario"), 0, 2)
        grid.addWidget(QLabel("P. Total"), 0, 3)

        self.cantidad_spin = QSpinBox()
        self.cantidad_spin.setMinimum(1)
        self.cantidad_spin.setMaximum(100000)
        grid.addWidget(self.cantidad_spin, 1, 0)

        self.presentacion_combo = QComboBox()
        grid.addWidget(self.presentacion_combo, 1, 1)

        self.precio_spin = QDoubleSpinBox()
        self.precio_spin.setMinimum(0)
        self.precio_spin.setMaximum(1000000)
        self.precio_spin.setDecimals(2)
        self.precio_spin.setPrefix("$")
        grid.addWidget(self.precio_spin, 1, 2)

        self.precio_total_spin = QDoubleSpinBox()
        self.precio_total_spin.setMinimum(0)
        self.precio_total_spin.setMaximum(100000000)
        self.precio_total_spin.setDecimals(2)
        self.precio_total_spin.setPrefix("$")
        grid.addWidget(self.precio_total_spin, 1, 3)

        self.descuento_spin = QDoubleSpinBox()
        self.descuento_spin.setMinimum(0)
        self.descuento_spin.setMaximum(1000000)
        self.descuento_spin.setDecimals(2)
        self.descuento_spin.setValue(0)
        self.descuento_tipo_combo = QComboBox()
        self.descuento_tipo_combo.addItems(["%", "$"])
        self.descuento_tipo_combo.setCurrentText("$")
        desc_tipo_container = QWidget()
        desc_tipo_container.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        desc_tipo_layout = QHBoxLayout(desc_tipo_container)
        desc_tipo_layout.setContentsMargins(0, 0, 0, 0)
        desc_tipo_layout.setSpacing(6)
        desc_tipo_layout.addWidget(QLabel("Desc."))
        desc_tipo_layout.addWidget(self.descuento_spin)
        desc_tipo_layout.addWidget(self.descuento_tipo_combo)
        desc_tipo_layout.addSpacing(10)
        desc_tipo_layout.addWidget(QLabel("Tipo"))
        self.tipo_fiscal_combo = QComboBox()
        self.tipo_fiscal_combo.addItems(["Venta gravada", "Venta exenta", "Venta no sujeta"])
        desc_tipo_layout.addWidget(self.tipo_fiscal_combo)
        grid.addWidget(desc_tipo_container, 2, 0, 1, 5, alignment=Qt.AlignLeft)
        productos_layout.addLayout(grid)

        # Resumen compacto sin cajas
        self.item_sumas_label = QLabel("Sumas: $0.00")
        self.item_total_sin_desc_label = QLabel("Subtotal: $0.00")
        self.item_descuento_label = QLabel("Desc.: -$0.00")
        self.item_subtotal_label = QLabel("Total con IVA: $0.00")
        for lbl in (
            self.item_sumas_label,
            self.item_total_sin_desc_label,
            self.item_descuento_label,
        ):
            lbl.setStyleSheet("font-weight: 600; color: #0f172a; padding: 0; margin: 0;")
        self.item_subtotal_label.setStyleSheet("font-weight: 700; color: #1d4ed8; padding: 0; margin: 0;")

        summary_layout = QHBoxLayout()
        summary_layout.setSpacing(8)
        summary_layout.setContentsMargins(0, 0, 0, 0)
        summary_layout.addWidget(self.item_sumas_label)
        summary_layout.addWidget(self.item_total_sin_desc_label)
        summary_layout.addWidget(self.item_descuento_label)
        summary_layout.addWidget(self.item_subtotal_label)
        summary_layout.addStretch(1)

        summary_frame = QFrame()
        summary_frame.setStyleSheet("background-color: #f1f5f9; border-radius: 6px; padding: 4px;")
        summary_frame.setLayout(summary_layout)
        productos_layout.addWidget(summary_frame)

        self.descuento_spin.valueChanged.connect(self._recalcular_totales)
        self.descuento_tipo_combo.currentIndexChanged.connect(self._on_descuento_tipo_changed)

        # Botón agregar a venta
        self.btn_agregar = QPushButton("Agregar a venta")
        self.btn_agregar.setProperty("variant", "primary")
        productos_layout.addWidget(self.btn_agregar)
        self.btn_agregar.clicked.connect(self._agregar_a_venta)

        carrito_card, carrito_layout = _card("Carrito")
        # Tabla de productos agregados
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels([
            "Cantidad", "Producto", "Descuento", "Total", "Eliminar"
        ])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        header_cf = self.table.horizontalHeader()
        header_cf.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header_cf.setStretchLastSection(False)
        header_cf.setSectionResizeMode(1, QHeaderView.Interactive)  # Producto
        self.table.setColumnWidth(1, 170)
        for col, width in [(0, 60), (2, 80)]:
            header_cf.setSectionResizeMode(col, QHeaderView.ResizeToContents)
            self.table.setColumnWidth(col, width)
        # Total un poco más ancho y fijo para evitar recortes
        self.table.setColumnWidth(3, 100)
        header_cf.setSectionResizeMode(3, QHeaderView.Fixed)
        # Dar más espacio a eliminar para que no se corte
        self.table.setColumnWidth(4, 89)
        header_cf.setSectionResizeMode(4, QHeaderView.Fixed)
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.table.setMinimumHeight(170)
        self.table.setMaximumHeight(230)
        carrito_layout.addWidget(self.table)
        self.table.cellClicked.connect(self._eliminar_fila)

        # Retención antes del total
        self.retencion_group = QGroupBox("Retención de IVA (solo 1%)")
        retencion_layout = QVBoxLayout(self.retencion_group)
        retencion_layout.setContentsMargins(9, 9, 9, 9)
        self.retencion_checkbox = QCheckBox("Aplicar retención 1%")
        self._retencion_catalog_ok = False

        self.retencion_codigo_combo = QComboBox()
        self.retencion_tasa_spin = QDoubleSpinBox()
        self.retencion_tasa_spin.setRange(0, 100)
        self.retencion_tasa_spin.setDecimals(3)
        self.retencion_tasa_spin.setSingleStep(0.1)
        self.retencion_tasa_spin.setValue(1.0)
        self.retencion_geo_emisor_combo = QComboBox()
        self.retencion_geo_receptor_combo = QComboBox()
        for code in [f"{i:02d}" for i in range(1, 23)]:
            self.retencion_geo_emisor_combo.addItem(code, code)
            self.retencion_geo_receptor_combo.addItem(code, code)

        ret_form = QFormLayout()
        ret_form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        ret_form.addRow("Código MH (CAT-006)", self.retencion_codigo_combo)
        ret_form.addRow("Tasa (%)", self.retencion_tasa_spin)
        ret_form.addRow("Geo emisor (01-22)", self.retencion_geo_emisor_combo)
        ret_form.addRow("Geo receptor (01-22)", self.retencion_geo_receptor_combo)
        self._retencion_form_layout = ret_form
        retencion_layout.addLayout(ret_form)

        self.retencion_base_label = QLabel("Base sujeta: $0.00")
        self.retencion_iva_label = QLabel("IVA retenido (1%): $0.00")
        ret_header = QHBoxLayout()
        ret_header.setSpacing(10)
        ret_header.addWidget(self.retencion_checkbox)
        ret_header.addSpacing(12)
        ret_header.addWidget(self.retencion_base_label)
        ret_header.addSpacing(12)
        ret_header.addWidget(self.retencion_iva_label)
        ret_header.addStretch(1)
        retencion_layout.insertLayout(0, ret_header)
        self._restrict_retencion_to_one_percent()
        self.retencion_checkbox.toggled.connect(self._update_retencion_summary)
        self.retencion_tasa_spin.valueChanged.connect(self._update_retencion_summary)
        self.retencion_codigo_combo.currentIndexChanged.connect(self._update_retencion_summary)
        self.retencion_geo_emisor_combo.currentIndexChanged.connect(self._update_retencion_summary)
        self.retencion_geo_receptor_combo.currentIndexChanged.connect(self._update_retencion_summary)
        carrito_layout.addWidget(self.retencion_group)

        # Resumen de la venta
        self.total_label = QLabel("Total venta (con IVA): $0.00")
        self.total_label.setObjectName("TotalHighlight")
        carrito_layout.addWidget(self.total_label)

        # Botón para registrar la venta (debajo del total)
        self.btn_ok = QPushButton("Registrar")
        self.btn_ok.setProperty("variant", "primary")
        self.btn_ok.clicked.connect(self._validar_y_accept)
        carrito_layout.addWidget(self.btn_ok)

        left_layout.addWidget(productos_card)
        left_layout.addWidget(carrito_card)

        # --- LADO DERECHO: datos del cliente ---
        right_layout = QVBoxLayout()
        right_layout.setSpacing(12)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSizeConstraint(QLayout.SetMinimumSize)

        cliente_card, cliente_layout = _card("Cliente y vendedor")

        self.vendedores_trabajadores = vendedores_trabajadores
        self.vendedor_combo = QComboBox()
        self.vendedor_combo.addItem("Sin vendedor")
        for v in vendedores_trabajadores:
            self.vendedor_combo.addItem(v["nombre"])
        cliente_layout.addWidget(QLabel("Vendedor (trabajador):"))
        cliente_layout.addWidget(self.vendedor_combo)

        self.comision_chk = QCheckBox("Aplicar comisión")
        cliente_layout.addWidget(self.comision_chk)
        com_layout = QHBoxLayout()
        com_layout.addWidget(QLabel("%:"))
        self.comision_pct_spin = QDoubleSpinBox()
        self.comision_pct_spin.setRange(0, 100)
        self.comision_pct_spin.setDecimals(2)
        self.comision_pct_spin.setEnabled(False)
        com_layout.addWidget(self.comision_pct_spin)
        self.comision_tipo_combo = QComboBox()
        self.comision_tipo_combo.addItems(["Incluida en el precio"])
        self.comision_tipo_combo.setEnabled(False)
        com_layout.addWidget(self.comision_tipo_combo)
        cliente_layout.addLayout(com_layout)
        self.comision_label = QLabel("Comisión: $0.00")
        cliente_layout.addWidget(self.comision_label)
        self.comision_chk.stateChanged.connect(self._toggle_comision_inputs)
        self.comision_pct_spin.valueChanged.connect(self._recalcular_totales)
        self.comision_tipo_combo.currentIndexChanged.connect(self._recalcular_totales)

        cliente_layout.addWidget(QLabel("Cliente:"))
        cliente_buttons = QHBoxLayout()
        cliente_buttons.setContentsMargins(0, 0, 0, 0)
        cliente_buttons.setSpacing(8)
        self.cliente_btn = QPushButton("Seleccionar Cliente")
        self.cliente_btn.setProperty("variant", "secondary")
        cliente_buttons.addWidget(self.cliente_btn)
        self.nuevo_cliente_btn = QPushButton("Agregar nuevo cliente")
        self.nuevo_cliente_btn.setProperty("variant", "clientAdd")
        cliente_buttons.addWidget(self.nuevo_cliente_btn)
        cliente_buttons.addStretch(1)
        cliente_layout.addLayout(cliente_buttons)
        self.cliente_label = QLabel("(Ningún cliente seleccionado)")
        self.cliente_label.setWordWrap(True)
        cliente_layout.addWidget(self.cliente_label)
        self.selected_cliente = None

        datos_cliente_layout = QGridLayout()
        datos_cliente_layout.setContentsMargins(0, 0, 0, 0)
        datos_cliente_layout.setHorizontalSpacing(8)
        datos_cliente_layout.setVerticalSpacing(6)

        def _make_static_field():
            label = QLabel()
            label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
            label.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
            label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            return label

        datos_cliente_layout.addWidget(QLabel("NIT/DUI:"), 0, 0)
        self.nrc_edit = _make_static_field()
        datos_cliente_layout.addWidget(self.nrc_edit, 0, 1)

        datos_cliente_layout.addWidget(QLabel("NRC:"), 0, 2)
        self.nit_edit = _make_static_field()
        datos_cliente_layout.addWidget(self.nit_edit, 0, 3)

        datos_cliente_layout.addWidget(QLabel("Giro:"), 1, 0)
        self.giro_edit = _make_static_field()
        datos_cliente_layout.addWidget(self.giro_edit, 1, 1)

        datos_cliente_layout.addWidget(QLabel("Correo electrónico:"), 1, 2)
        self.email_edit = _make_static_field()
        datos_cliente_layout.addWidget(self.email_edit, 1, 3)

        datos_cliente_layout.setColumnStretch(1, 1)
        datos_cliente_layout.setColumnStretch(3, 1)
        cliente_layout.addLayout(datos_cliente_layout)

        pago_card, pago_layout = _card("Datos fiscales y pago")

        # Condición de pago y estado en la misma fila
        pago_estado_layout = QGridLayout()
        pago_estado_layout.setContentsMargins(0, 0, 0, 0)
        pago_estado_layout.setHorizontalSpacing(8)
        pago_estado_layout.addWidget(QLabel("Condición de pago:"), 0, 0)
        self.condicion_pago_combo = QComboBox()
        self.condicion_pago_combo.addItem("Contado", 1)
        self.condicion_pago_combo.addItem("Crédito", 2)
        self.condicion_pago_combo.addItem("Otros", 3)
        pago_estado_layout.addWidget(self.condicion_pago_combo, 0, 1)
        pago_estado_layout.addWidget(QLabel("Estado:"), 0, 2)
        self.estado_combo = QComboBox()
        self.estado_combo.addItems(["Pagada", "Pendiente"])
        pago_estado_layout.addWidget(self.estado_combo, 0, 3)
        pago_estado_layout.setColumnStretch(1, 1)
        pago_estado_layout.setColumnStretch(3, 1)
        pago_layout.addLayout(pago_estado_layout)

        self.condicion_pago_combo.currentIndexChanged.connect(
            self._update_condicion_pago_fields
        )

        self.credit_fields_widget = QWidget()
        credit_layout = QFormLayout(self.credit_fields_widget)
        credit_layout.setContentsMargins(0, 0, 0, 0)
        credit_layout.setSpacing(8)

        self.plazo_combo = QComboBox()
        self.plazo_combo.addItem("Seleccionar", "")
        self.plazo_combo.setItemData(0, "", CREDIT_TERM_BACKEND_ROLE)
        self.plazo_combo.addItem("Días (01)", "D")
        self.plazo_combo.setItemData(self.plazo_combo.count() - 1, "01", CREDIT_TERM_BACKEND_ROLE)
        self.plazo_combo.addItem("Meses (02)", "M")
        self.plazo_combo.setItemData(self.plazo_combo.count() - 1, "02", CREDIT_TERM_BACKEND_ROLE)
        self.plazo_combo.addItem("Años (03)", "A")
        self.plazo_combo.setItemData(self.plazo_combo.count() - 1, "03", CREDIT_TERM_BACKEND_ROLE)
        credit_layout.addRow("Plazo:", self.plazo_combo)

        self.plazo_spin = QSpinBox()
        self.plazo_spin.setMinimum(1)
        self.plazo_spin.setValue(1)
        credit_layout.addRow("Cantidad:", self.plazo_spin)

        self._backend_pago_plazo = ""
        self._backend_pago_periodo = ""

        self.plazo_combo.currentIndexChanged.connect(self._sync_credit_term_payload)
        self.plazo_spin.valueChanged.connect(self._sync_credit_term_payload)
        self._sync_credit_term_payload()

        self.referencia_edit = QLineEdit()
        self.referencia_edit.setPlaceholderText("Referencia (opcional)")
        credit_layout.addRow("Referencia:", self.referencia_edit)

        pago_layout.addWidget(self.credit_fields_widget)

        # No. de remisión y Orden No. en la misma fila
        remision_layout = QGridLayout()
        remision_layout.setContentsMargins(0, 0, 0, 0)
        remision_layout.setHorizontalSpacing(8)
        remision_layout.addWidget(QLabel("No. Remisión:"), 0, 0)
        self.no_remision_edit = QLineEdit()
        self.no_remision_edit.setPlaceholderText("Número de remisión")
        remision_layout.addWidget(self.no_remision_edit, 0, 1)
        remision_layout.addWidget(QLabel("Orden No."), 0, 2)
        self.orden_no_edit = QLineEdit()
        self.orden_no_edit.setPlaceholderText("Número de orden")
        remision_layout.addWidget(self.orden_no_edit, 0, 3)
        remision_layout.setColumnStretch(1, 1)
        remision_layout.setColumnStretch(3, 1)
        pago_layout.addLayout(remision_layout)

        # Venta a cuenta de y documento en la misma fila
        venta_tercero_layout = QGridLayout()
        venta_tercero_layout.setContentsMargins(0, 0, 0, 0)
        venta_tercero_layout.setHorizontalSpacing(8)
        venta_tercero_layout.addWidget(QLabel("Venta a cuenta de:"), 0, 0)
        self.venta_a_cuenta_de_edit = QLineEdit()
        self.venta_a_cuenta_de_edit.setPlaceholderText("Venta a cuenta de")
        venta_tercero_layout.addWidget(self.venta_a_cuenta_de_edit, 0, 1)
        venta_tercero_layout.addWidget(QLabel("DUI/NIT:"), 0, 2)
        self.venta_documento_edit = QLineEdit()
        self.venta_documento_edit.setPlaceholderText("Documento")
        venta_tercero_layout.addWidget(self.venta_documento_edit, 0, 3)
        venta_tercero_layout.setColumnStretch(1, 1)
        venta_tercero_layout.setColumnStretch(3, 1)
        pago_layout.addLayout(venta_tercero_layout)

        # Fechas de remisión en una misma fila
        fechas_layout = QGridLayout()
        fechas_layout.setContentsMargins(0, 0, 0, 0)
        fechas_layout.setHorizontalSpacing(8)
        fechas_layout.addWidget(QLabel("Fecha nota de remisión anterior:"), 0, 0)
        self.fecha_remision_anterior = QDateEdit(QDate.currentDate())
        self.fecha_remision_anterior.setCalendarPopup(True)
        fechas_layout.addWidget(self.fecha_remision_anterior, 0, 1)
        fechas_layout.addWidget(QLabel("Fecha de remisión:"), 0, 2)
        self.fecha_remision = QDateEdit(QDate.currentDate())
        self.fecha_remision.setCalendarPopup(True)
        fechas_layout.addWidget(self.fecha_remision, 0, 3)
        fechas_layout.setColumnStretch(1, 1)
        fechas_layout.setColumnStretch(3, 1)
        pago_layout.addLayout(fechas_layout)

        right_layout.addWidget(cliente_card)
        right_layout.addWidget(pago_card)

        # --- Agrega ambos layouts al principal como tarjetas ---
        card_top = QFrame()
        card_top.setObjectName("PosCardTop")
        card_top.setFrameShape(QFrame.StyledPanel)
        card_top.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        card_top_layout = QVBoxLayout(card_top)
        card_top_layout.setContentsMargins(12, 12, 12, 12)
        card_top_layout.setSpacing(8)
        card_top_layout.setSizeConstraint(QLayout.SetMinimumSize)
        card_top_layout.addWidget(QLabel("Nueva Venta / Carrito"))
        card_top_layout.addLayout(left_layout)

        card_bottom = QFrame()
        card_bottom.setObjectName("PosCardBottom")
        card_bottom.setFrameShape(QFrame.StyledPanel)
        card_bottom.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        card_bottom_layout = QVBoxLayout(card_bottom)
        card_bottom_layout.setContentsMargins(12, 12, 12, 12)
        card_bottom_layout.setSpacing(6)
        card_bottom_layout.setSizeConstraint(QLayout.SetMinimumSize)
        card_bottom_layout.addWidget(QLabel("Cliente y Pago"))
        card_bottom_layout.addLayout(right_layout)

        # Carrito arriba, cliente/pago abajo con botón de registrar dentro del último card
        # Clientes/pago arriba, carrito abajo
        main_layout.addWidget(card_bottom)
        main_layout.addWidget(card_top)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setWidget(content_widget)
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.addWidget(scroll)
        self.setLayout(root_layout)

        # Estado
        self.productos_data = productos

        # Conexiones adicionales
        self.cliente_btn.clicked.connect(self._abrir_selector_cliente)
        self.nuevo_cliente_btn.clicked.connect(self._abrir_crear_cliente)
        self.product_list.currentRowChanged.connect(self._actualizar_precio_defecto)
        self.product_list.currentRowChanged.connect(self._actualizar_presentacion_combo)
        self.cantidad_spin.valueChanged.connect(self._recalcular_totales)
        self.precio_spin.valueChanged.connect(self._recalcular_totales)
        self.precio_total_spin.valueChanged.connect(self._recalcular_totales)
        self.presentacion_combo.currentIndexChanged.connect(self._on_presentacion_changed)
        self.product_search.textChanged.connect(self._filtrar_productos)
        self.product_list.currentRowChanged.connect(self._actualizar_Distribuidor_por_producto)

        if productos:
            self.product_list.setCurrentRow(0)
            self._actualizar_presentacion_combo()
            self._actualizar_precio_defecto()
        self._actualizar_resumen()
        self._on_descuento_tipo_changed()
        self._update_condicion_pago_fields()
        self._load_retencion_catalog()
        self.load_payment_data(venta_extra)
        self._autofill_remision_fields(venta_extra)
        self._update_retencion_summary()
        self._install_no_wheel_filter()

    def set_productos_data(self, productos_data):
        self.productos_data = productos_data or []
        self._productos_original = list(self.productos_data)
        self.productos = list(self.productos_data)
        self.product_list.clear()
        self._mostrar_productos(self.productos_data)

    def clear_carrito(self):
        """Limpia carrito y totales para iniciar una venta desde cero."""
        self.venta_items = []
        self.table.setRowCount(0)
        self.item_sumas_label.setText("Sumas: $0.00")
        self.item_total_sin_desc_label.setText("Subtotal: $0.00")
        self.item_descuento_label.setText("Desc.: -$0.00")
        self.item_subtotal_label.setText("Total con IVA: $0.00")
        self.total_label.setText("Total venta (con IVA): $0.00")
        self.cantidad_spin.setValue(1)
        self.precio_spin.setValue(0)
        self.precio_total_spin.setValue(0)
        self.descuento_spin.setValue(0)
        self.tipo_fiscal_combo.setCurrentIndex(0)
        self.product_list.clearSelection()
        if hasattr(self, "presentacion_combo") and self.presentacion_combo.count() > 0:
            self.presentacion_combo.setCurrentIndex(0)
        self.venta_a_cuenta_de_edit.clear()
        self.venta_documento_edit.clear()

    def _actualizar_precio_defecto(self):
        idx = self.product_list.currentRow()
        if idx < 0:
            self.precio_spin.setValue(0)
            self.precio_total_spin.setValue(0)
            self._recalcular_totales()
            return
        nombre = self.product_list.currentItem().text()
        prod = None
        if 0 <= idx < len(self.productos):
            prod = self.productos[idx]
        elif self.productos_data:
            for p in self.productos_data:
                nombre_prod = get_field(p, "nombre", "")
                if nombre.startswith(nombre_prod):
                    prod = p
                    break
        factor = self._presentacion_factor_from_combo(self.presentacion_combo)
        pres_data = self._presentacion_data_from_combo(self.presentacion_combo)
        precio = 0
        if prod:
            base = get_field(prod, "precio_venta_minorista", 0)
            precio = pres_data.get("precio_venta", None)
            if precio in (None, ""):
                precio = base * factor
        self.precio_spin.blockSignals(True)
        self.precio_total_spin.blockSignals(True)
        self.precio_spin.setValue(float(precio))
        self.precio_total_spin.setValue(float(precio) * self.cantidad_spin.value())
        self.precio_spin.blockSignals(False)
        self.precio_total_spin.blockSignals(False)
        self._recalcular_totales()

    def _actualizar_presentacion_combo(self):
        prod = None
        idx = self.product_list.currentRow()
        if 0 <= idx < len(self.productos):
            prod = self.productos[idx]
        self._fill_presentaciones_combo(self.presentacion_combo, prod)
        self._on_presentacion_changed()

    def _on_presentacion_changed(self):
        self._actualizar_precio_defecto()

    def _toggle_precio_edicion(self):
        self.precio_spin.setEnabled(True)
        self.precio_total_spin.setEnabled(True)
        self._recalcular_totales()


    def _on_descuento_tipo_changed(self):
        tipo = self.descuento_tipo_combo.currentText()
        if tipo == "%":
            self.descuento_spin.setMaximum(100)
        else:
            self.descuento_spin.setMaximum(1000000)
        self._recalcular_totales()

    def _recalcular_totales(self):
        cantidad = Decimal(self.cantidad_spin.value() or 0)
        if cantidad <= 0:
            cantidad = Decimal("1")

        sender = self.sender()
        precio_unitario_con_iva = Decimal(str(self.precio_spin.value()))
        precio_total_con_iva = Decimal(str(self.precio_total_spin.value()))

        if sender is self.precio_total_spin:
            precio_unitario_con_iva = precio_total_con_iva / cantidad if cantidad > 0 else Decimal("0")
            self.precio_spin.blockSignals(True)
            self.precio_spin.setValue(float(precio_unitario_con_iva))
            self.precio_spin.blockSignals(False)
        else:
            precio_total_con_iva = precio_unitario_con_iva * cantidad
            self.precio_total_spin.blockSignals(True)
            self.precio_total_spin.setValue(float(precio_total_con_iva))
            self.precio_total_spin.blockSignals(False)

        descuento_valor = Decimal(str(self.descuento_spin.value()))
        descuento_tipo = self.descuento_tipo_combo.currentText()
        if descuento_tipo == "%":
            descuento_monto = precio_total_con_iva * descuento_valor / Decimal("100")
        else:
            descuento_monto = min(descuento_valor, precio_total_con_iva)
        total_con_descuento = precio_total_con_iva - descuento_monto
        if total_con_descuento < 0:
            total_con_descuento = Decimal("0")

        comision_pct = Decimal(str(self.comision_pct_spin.value())) if self.comision_chk.isChecked() else Decimal("0")
        comision_tipo = self.comision_tipo_combo.currentText()
        if comision_tipo == "Añadida al total":
            # La comisión se considera un cargo no gravado; no altera la base del IVA
            comision_monto = total_con_descuento * comision_pct / Decimal("100")
            importe_con_iva_para_desglose = total_con_descuento
            total_final = total_con_descuento + comision_monto
        elif comision_tipo == "Desglosada (incluida en el precio)":
            comision_monto = total_con_descuento * comision_pct / (Decimal("100") + comision_pct) if comision_pct > 0 else Decimal("0")
            importe_con_iva_para_desglose = total_con_descuento - comision_monto
            total_final = total_con_descuento
        else:
            comision_monto = Decimal("0")
            importe_con_iva_para_desglose = total_con_descuento
            total_final = total_con_descuento

        tipo_fiscal = self.tipo_fiscal_combo.currentText()
        if tipo_fiscal == "Venta gravada":
            precio_unitario_sin_iva = precio_unitario_con_iva / IVA_FACTOR
            subtotal_con_descuento_sin_iva = importe_con_iva_para_desglose / IVA_FACTOR
        else:
            precio_unitario_sin_iva = precio_unitario_con_iva
            subtotal_con_descuento_sin_iva = importe_con_iva_para_desglose

        sumas = precio_unitario_sin_iva * cantidad

        precio_unitario_sin_iva_disp = precio_unitario_sin_iva.quantize(Decimal("0.01"))
        # Sumas visuales basadas en el precio unitario mostrado para coincidir con la percepción del usuario
        sumas_disp = (precio_unitario_sin_iva_disp * cantidad).quantize(Decimal("0.01"))
        total_sin_desc_disp = precio_total_con_iva.quantize(Decimal("0.01"))
        descuento_disp = descuento_monto.quantize(Decimal("0.01"))
        subtotal_final_disp = total_final.quantize(Decimal("0.01"))
        comision_disp = comision_monto.quantize(Decimal("0.01"))

        self.item_sumas_label.setText(f"Sumas: ${sumas_disp:.2f}")
        self.item_total_sin_desc_label.setText(f"Subtotal: ${total_sin_desc_disp:.2f}")
        self.item_descuento_label.setText(f"Desc.: -${descuento_disp:.2f}")
        self.item_subtotal_label.setText(f"Total con IVA: ${subtotal_final_disp:.2f}")
        self.comision_label.setText(f"Comisión: ${comision_disp:.2f}")

    def _agregar_a_venta(self):
        idx = self.product_list.currentRow()
        if idx < 0:
            QMessageBox.warning(self, "Validación", "Seleccione un producto del inventario actual.")
            return
        lote = self.productos[idx]
        cantidad_bultos = Decimal(self.cantidad_spin.value() or 0)
        if cantidad_bultos <= 0:
            cantidad_bultos = Decimal("1")

        # Precios siempre editables y sincronizados
        self._recalcular_totales()
        precio_total_con_iva = Decimal(str(self.precio_total_spin.value()))
        precio_unitario_con_iva_bulto = Decimal(str(self.precio_spin.value()))

        factor = Decimal(str(self._presentacion_factor_from_combo(self.presentacion_combo)))
        pres_nombre = (self.presentacion_combo.currentText() or "").strip()
        cantidad_base = (cantidad_bultos * factor).quantize(Decimal("0.00000001"))
        if factor <= 0:
            factor = Decimal("1")
        precio_unitario_base_con_iva = (precio_unitario_con_iva_bulto / factor) if factor else precio_unitario_con_iva_bulto

        descuento_valor = Decimal(str(self.descuento_spin.value()))
        descuento_tipo = self.descuento_tipo_combo.currentText()
        if descuento_tipo == "%":
            descuento_monto = precio_total_con_iva * descuento_valor / Decimal("100")
        else:
            descuento_monto = min(descuento_valor, precio_total_con_iva)
        total_con_descuento = precio_total_con_iva - descuento_monto
        if total_con_descuento < 0:
            total_con_descuento = Decimal("0")

        comision_pct = Decimal(str(self.comision_pct_spin.value())) if self.comision_chk.isChecked() else Decimal("0")
        comision_tipo = self.comision_tipo_combo.currentText()
        if comision_tipo == "Añadida al total":
            # Comisión tratada como cargo no gravado
            comision_monto = total_con_descuento * comision_pct / Decimal("100")
            importe_con_iva_para_desglose = total_con_descuento
            total_final = total_con_descuento + comision_monto
        elif comision_tipo == "Desglosada (incluida en el precio)":
            comision_monto = total_con_descuento * comision_pct / (Decimal("100") + comision_pct) if comision_pct > 0 else Decimal("0")
            importe_con_iva_para_desglose = total_con_descuento - comision_monto
            total_final = total_con_descuento
        else:
            comision_monto = Decimal("0")
            importe_con_iva_para_desglose = total_con_descuento
            total_final = total_con_descuento

        tipo_fiscal = self.tipo_fiscal_combo.currentText()
        if tipo_fiscal == "Venta gravada":
            precio_unitario_sin_iva = precio_unitario_base_con_iva / IVA_FACTOR
            subtotal_sin_iva = precio_unitario_sin_iva * cantidad_base
            subtotal_con_descuento_sin_iva = importe_con_iva_para_desglose / IVA_FACTOR
            iva = importe_con_iva_para_desglose - subtotal_con_descuento_sin_iva
        else:
            precio_unitario_sin_iva = precio_unitario_base_con_iva
            subtotal_sin_iva = precio_unitario_sin_iva * cantidad_base
            subtotal_con_descuento_sin_iva = importe_con_iva_para_desglose
            iva = Decimal("0")

        producto_display = lote.get("nombre", "")
        if pres_nombre and not pres_nombre.lower().startswith("unidad base"):
            producto_display = f"{producto_display} [{pres_nombre}]"

        q8 = Decimal("0.00000001")
        self.venta_items.append({
            "lote_id": lote["lote_id"],
            "producto_id": lote["producto_id"],
            "producto": lote["nombre"],
            "producto_display": producto_display,
            "codigo": lote.get("codigo", ""),
            "sku": lote.get("sku", ""),
            "cantidad": float(cantidad_base),
            "cantidad_bultos": float(cantidad_bultos),
            "presentacion_factor": float(factor),
            "presentacion_nombre": pres_nombre or "Unidad Base (x1)",
            "precio": float(precio_unitario_sin_iva.quantize(q8)),
            "precio_con_iva": float(precio_unitario_base_con_iva.quantize(q8)),
            "precio_presentacion": float(precio_unitario_con_iva_bulto.quantize(q8)),
            "descuento": float(descuento_valor),
            "descuento_tipo": descuento_tipo,
            "descuento_monto": float(descuento_monto.quantize(q8)),
            "subtotal": float(subtotal_sin_iva.quantize(q8)),
            "subtotal_con_descuento": float(subtotal_con_descuento_sin_iva.quantize(q8)),
            "iva": float(iva.quantize(q8)),
            "iva_tipo": "incluido",
            "comision_monto": float(comision_monto.quantize(q8)),
            "total": float(total_final.quantize(q8)),
            "tipo_fiscal": tipo_fiscal,
            "vendedor_id": lote.get("vendedor_id"),
            "Distribuidor_id": lote["Distribuidor_id"],
            "fecha_vencimiento": lote.get("fecha_vencimiento", ""),
            "codigo_lote": lote.get("codigo_lote", ""),
            "extra": {
                "lote_id": lote.get("lote_id"),
                "producto_id": lote.get("producto_id"),
                "cantidad": float(cantidad_base),
                "cantidad_presentacion": float(cantidad_bultos),
                "codigo_lote": lote.get("codigo_lote"),
            },
        })

        self._actualizar_tabla()
        self._recalcular_totales()
        self._actualizar_resumen()


    def _actualizar_tabla(self):
        self.table.setRowCount(len(self.venta_items))
        for i, item in enumerate(self.venta_items):
            cant_bultos = item.get("cantidad_bultos", item.get("cantidad", 0))
            pres_nombre = item.get("presentacion_nombre", "")
            cant_texto = f"{cant_bultos} {pres_nombre}".strip()
            cant_item = QTableWidgetItem(str(cant_texto))
            cant_item.setData(Qt.UserRole, item.get("cantidad", cant_bultos))
            self.table.setItem(i, 0, cant_item)

            producto_texto = item.get("producto_display", item.get("producto", ""))
            self.table.setItem(i, 1, QTableWidgetItem(producto_texto))
            self.table.setItem(i, 2, QTableWidgetItem(f"{item['descuento']}{item['descuento_tipo']}"))
            self.table.setItem(i, 3, QTableWidgetItem(f"${item['total']:.2f}"))
            btn = QPushButton("Eliminar")
            btn.setStyleSheet(
                "background-color: #b71c1c; color: #fff; border-radius: 6px; font-size:9px;"
                "min-width:80px; max-width:110px; min-height:14px; max-height:22px;"
            )
            btn.clicked.connect(lambda _, row=i: self._eliminar_item(row))
            cell = QWidget()
            cell_layout = QHBoxLayout(cell)
            cell_layout.setContentsMargins(0, 0, 0, 0)
            cell_layout.setAlignment(Qt.AlignCenter)
            cell_layout.addWidget(btn)
            self.table.setCellWidget(i, 4, cell)

    def _actualizar_resumen(self):
        total = sum(item.get("total", 0) for item in self.venta_items)
        base_ret, iva_ret = self._compute_retencion_values()
        if self.retencion_checkbox.isChecked() and iva_ret > 0:
            neto = max(total - float(iva_ret), 0.0)
            tasa = float(self._retencion_rate_pct())
            self.total_label.setText(
                f"Total venta (con IVA): ${total:.2f}  Retención {tasa:.3f}%: ${iva_ret:.2f}  Neto: ${neto:.2f}"
            )
        else:
            self.total_label.setText(f"Total venta (con IVA): ${total:.2f}")
        self._update_retencion_summary()

    def _retencion_rate_pct(self) -> Decimal:
        if hasattr(self, "retencion_tasa_spin"):
            try:
                return Decimal(str(self.retencion_tasa_spin.value()))
            except Exception:
                return Decimal("0")
        return Decimal("0")

    def _retencion_codigo_value(self) -> str:
        if hasattr(self, "retencion_codigo_combo"):
            data = self.retencion_codigo_combo.currentData()
            if data not in (None, ""):
                return str(data)
        return "22"

    def _valid_geo_code(self, value: str | None) -> bool:
        if not value:
            return False
        digits = "".join(ch for ch in str(value) if ch.isdigit())
        if not digits:
            return False
        try:
            numero = int(digits)
        except ValueError:
            return False
        return 1 <= numero <= 22

    def _load_retencion_catalog(self) -> None:
        self._retencion_catalog_ok = False
        try:
            from retenciones.catalogos_retencion import CatalogosRetencion

            catalogos = CatalogosRetencion()
            entries = catalogos.entries("CAT-006")
            self.retencion_codigo_combo.clear()
            for entry in entries:
                label = f"{entry.code} – {entry.label}" if entry.label else entry.code
                self.retencion_codigo_combo.addItem(label, entry.code)
            idx = self.retencion_codigo_combo.findData("22")
            if idx >= 0:
                self.retencion_codigo_combo.setCurrentIndex(idx)
            self._retencion_catalog_ok = True
            self.retencion_group.setEnabled(True)
        except Exception as exc:
            logger.warning("No se pudo cargar catálogo CAT-006: %s", exc, exc_info=True)
            self.retencion_codigo_combo.clear()
            self.retencion_codigo_combo.addItem("Catálogo no disponible", "")
            self.retencion_checkbox.setChecked(False)
            self.retencion_group.setEnabled(False)
            QMessageBox.warning(
                self,
                "Catálogo de retención",
                "No se pudo cargar el catálogo CAT-006. "
                "La retención de IVA se desactivará para esta venta.\n\n"
                f"Detalle: {exc}",
            )

    def _compute_retencion_values(self) -> tuple[Decimal, Decimal]:
        """Return the taxable base and retained VAT for gravada items."""

        sumas = Decimal("0")
        descuentos = Decimal("0")
        q8 = Decimal("0.00000001")
        for item in self.venta_items:
            tipo_fiscal = (item.get("tipo_fiscal") or "").lower()
            if tipo_fiscal != "venta gravada":
                continue
            sumas += Decimal(str(item.get("subtotal", 0)))
            descuento_monto = Decimal(str(item.get("descuento_monto", 0)))
            descuentos += (descuento_monto / IVA_FACTOR).quantize(q8)

        base = sumas - descuentos
        if base < 0:
            base = Decimal("0")
        base = base.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        tasa_pct = self._retencion_rate_pct()
        tasa = tasa_pct / Decimal("100")
        iva_retenido = (base * tasa).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return base, iva_retenido

    def _update_retencion_summary(self) -> None:
        if not hasattr(self, "retencion_base_label"):
            return
        base, iva_retenido = self._compute_retencion_values()
        self.retencion_base_label.setText(f"Base sujeta: ${base:.2f}")
        self.retencion_iva_label.setText(
            f"IVA retenido ({float(self._retencion_rate_pct()):.3f}%): ${iva_retenido:.2f}"
        )

    def _eliminar_fila(self, row, col):
        if col == 5:
            self._eliminar_item(row)

    def _eliminar_item(self, row):
        if 0 <= row < len(self.venta_items):
            del self.venta_items[row]
            self._actualizar_tabla()
            self._recalcular_totales()
            self._actualizar_resumen()

    def _validar_y_accept(self):
        if not self.selected_cliente or "id" not in self.selected_cliente:
            QMessageBox.warning(
                self,
                "Validación",
                "Seleccione un cliente con NIT o NRC válido registrado antes de continuar.",
            )
            return
        if not self.venta_items:
            QMessageBox.warning(self, "Validación", "Debe agregar al menos un producto a la venta.")
            return
        nit_cliente = solo_digitos(get_field(self.selected_cliente, "nit", "") or "")
        nrc_cliente = solo_digitos(get_field(self.selected_cliente, "nrc", "") or "")
        nit_valido = bool(nit_cliente) and validar_nit(nit_cliente)
        nrc_valido = bool(nrc_cliente) and validar_nrc(nrc_cliente)
        if not (nit_valido or nrc_valido):
            QMessageBox.warning(
                self,
                "Validación",
                (
                    "El cliente seleccionado debe tener un NIT o NRC válido ya registrado. "
                    "Actualice los datos del cliente antes de realizar la venta a crédito fiscal."
                ),
            )
            return
        condicion_operacion = self.condicion_pago_combo.currentData()
        tercero_nombre = self.venta_a_cuenta_de_edit.text().strip()
        tercero_documento = self.venta_documento_edit.text().strip()
        if tercero_nombre or tercero_documento:
            nit_digits = solo_digitos(tercero_documento)
            if tercero_documento and len(nit_digits) not in (9, 14):
                respuesta = QMessageBox.question(
                    self,
                    "Venta a tercero inválida",
                    (
                        "El documento ingresado para 'Venta a cuenta de' debe contener "
                        "9 o 14 dígitos luego de quitar guiones y espacios.\n\n"
                        "Si continúas, la sección 'venta a tercero' del DTE quedará vacía.\n\n"
                        "¿Deseas continuar sin esos datos?"
                    ),
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if respuesta != QMessageBox.Yes:
                    return
        if self.retencion_checkbox.isChecked():
            if not getattr(self, "_retencion_catalog_ok", False):
                QMessageBox.warning(
                    self,
                    "Retención",
                    "No se pudo cargar el catálogo de retenciones (CAT-006).",
                )
                return
            base, reten = self._compute_retencion_values()
            tasa = self._retencion_rate_pct()
            if tasa <= 0:
                QMessageBox.warning(self, "Retención", "La tasa de retención debe ser mayor a 0%.")
                return
            if base <= 0 or reten <= 0:
                QMessageBox.warning(
                    self,
                    "Retención",
                    "Para aplicar retención, la base sujeta y el monto retenido deben ser mayores a 0.",
                )
                return
            codigo = self._retencion_codigo_value().strip()
            if not codigo:
                QMessageBox.warning(self, "Retención", "Seleccione un código de retención válido (CAT-006).")
                return
            geo_emisor = self.retencion_geo_emisor_combo.currentData()
            geo_receptor = self.retencion_geo_receptor_combo.currentData()
            if not (self._valid_geo_code(geo_emisor) and self._valid_geo_code(geo_receptor)):
                QMessageBox.warning(
                    self,
                    "Retención",
                    "Debe definir geocódigos emisor y receptor en el rango 01–22.",
                )
                return
        try:
            self.venta_validada.emit(self.get_data())
        except Exception:
            logger.exception("No se pudo emitir datos de venta CCF")
            QMessageBox.critical(self, "Error", "No se pudo preparar los datos de la venta.")
            return
        self.accept()

    def get_data(self):
        vendedor_idx = self.vendedor_combo.currentIndex()
        vendedor_id = None
        if vendedor_idx > 0:
            vendedor_id = self.vendedores_trabajadores[vendedor_idx - 1]["id"]

        sumas = Decimal("0")
        descuentos = Decimal("0")
        ventas_exentas = Decimal("0")
        ventas_no_sujetas = Decimal("0")
        iva = Decimal("0")
        q8 = Decimal("0.00000001")

        for item in self.venta_items:
            tipo_fiscal = item.get("tipo_fiscal", "").lower()
            base = Decimal(str(item.get("subtotal_con_descuento", 0)))
            if item.get("iva_tipo") == "desglosado":
                base = Decimal(str(item.get("subtotal", base)))

            if tipo_fiscal == "venta gravada":
                sumas += Decimal(str(item.get("subtotal", 0)))
                descuento_monto = Decimal(str(item.get("descuento_monto", 0)))
                descuento_base = (descuento_monto / IVA_FACTOR).quantize(q8)
                descuentos += descuento_base
                iva += Decimal(str(item.get("iva", 0)))
            elif tipo_fiscal == "venta exenta":
                ventas_exentas += base
            elif tipo_fiscal == "venta no sujeta":
                ventas_no_sujetas += base

        subtotal = (sumas - descuentos) + iva
        total = subtotal + ventas_exentas + ventas_no_sujetas

        condicion_operacion = self.condicion_pago_combo.currentData()
        if condicion_operacion == 2:
            # TODO(back): mapear los nuevos controles de cantidad/unidad al payload cuando el backend esté listo
            _ = self.plazo_spin.value()
            _ = self.plazo_combo.currentData()
            plazo_codigo = self._backend_pago_plazo
            periodo_codigo = self._backend_pago_periodo
        else:
            self._backend_pago_plazo = ""
            self._backend_pago_periodo = ""
            plazo_codigo = ""
            periodo_codigo = ""
        referencia = (
            self.referencia_edit.text().strip() if condicion_operacion == 2 else ""
        )

        cliente_info = self.selected_cliente if self.selected_cliente else {}
        nit_value = get_field(cliente_info, "nit", "") or ""
        nrc_value = get_field(cliente_info, "nrc", "") or ""

        data = {
            "cliente": cliente_info,
            "items": self.venta_items,
            "tipo_venta": "Manual",
            "precio_total_manual": float(self.precio_total_spin.value()),
            "iva_agregado": self.iva_agregado_radio.isChecked() if hasattr(self, "iva_agregado_radio") else False,
            "nrc": nrc_value or (self.nit_edit.text() if hasattr(self, "nit_edit") else ""),
            "nit": nit_value,
            "giro": self.giro_edit.text(),
            "email": self.email_edit.text(),
            "no_remision": self.no_remision_edit.text(),
            "orden_no": self.orden_no_edit.text(),
            "condicion_pago": self.condicion_pago_combo.currentText(),
            "venta_a_cuenta_de": self.venta_a_cuenta_de_edit.text(),
            "documento_venta_a_cuenta": self.venta_documento_edit.text(),
            "fecha_remision_anterior": self.fecha_remision_anterior.date().toString("yyyy-MM-dd"),
            "fecha_remision": self.fecha_remision.date().toString("yyyy-MM-dd"),
            "sumas": float(sumas.quantize(q8)),
            "descuentos": float(descuentos.quantize(q8)),
            "iva": float(iva.quantize(q8)),
            "subtotal": float(subtotal.quantize(q8)),
            "ventas_exentas": float(ventas_exentas.quantize(q8)),
            "ventas_no_sujetas": float(ventas_no_sujetas.quantize(q8)),
            "total": float(total.quantize(q8)),
            "fecha": QDate.currentDate().toString("yyyy-MM-dd"),
            "Distribuidor_id": (
                self.Distribuidor_combo.currentIndex()
                if self.Distribuidor_combo.currentIndex() >= 0 else None
            ),
            "vendedor_id": vendedor_id,
            "condicion_operacion": condicion_operacion,
            "pago_plazo": plazo_codigo,
            "pago_periodo": periodo_codigo,
            "pago_referencia": referencia,
        }
        base, iva_retenido = self._compute_retencion_values()
        geo_emisor = self.retencion_geo_emisor_combo.currentData() if hasattr(self, "retencion_geo_emisor_combo") else None
        geo_receptor = self.retencion_geo_receptor_combo.currentData() if hasattr(self, "retencion_geo_receptor_combo") else None
        data["_ui_retencion"] = normalize_retencion_payload(
            {
                "enabled": self.retencion_checkbox.isChecked(),
                "base": float(base),
                "montoRetenido": float(iva_retenido),
                "codigoRetencionMH": self._retencion_codigo_value(),
                "tasa": float(self._retencion_rate_pct()),
                "geoEmisor": geo_emisor,
                "geoReceptor": geo_receptor,
            }
        ) or {"enabled": False, "base": 0.0, "montoRetenido": 0.0, "codigoRetencionMH": "22", "tasa": 1.0}
        return data

    def _update_condicion_pago_fields(self):
        is_credit = self.condicion_pago_combo.currentData() == 2
        self.credit_fields_widget.setVisible(is_credit)
        if not is_credit:
            self.plazo_combo.setCurrentIndex(0)
            self.plazo_spin.setValue(1)
            self.referencia_edit.clear()
            self._backend_pago_plazo = ""
            self._backend_pago_periodo = ""
        self._sync_credit_term_payload()

    def load_payment_data(self, extra):
        if not extra:
            return
        data = {}
        if isinstance(extra, str):
            try:
                data = json.loads(extra)
            except (TypeError, ValueError):
                return
        elif isinstance(extra, dict):
            data = extra
        else:
            return

        self._backend_pago_plazo = ""
        self._backend_pago_periodo = ""

        condicion = data.get("condicion_operacion")
        if condicion not in {1, 2, 3}:
            condicion = data.get("condicionOperacion")
        if condicion in {1, 2, 3}:
            idx = self.condicion_pago_combo.findData(condicion)
            if idx >= 0:
                self.condicion_pago_combo.setCurrentIndex(idx)
        pagos = data.get("pagos") or []
        if pagos:
            pago = pagos[0]
            plazo_valor = pago.get("plazo")
            self._backend_pago_plazo = str(plazo_valor) if plazo_valor not in (None, "") else ""
            if plazo_valor in {"D", "M", "A"}:
                plazo_valor = {"D": "01", "M": "02", "A": "03"}.get(plazo_valor, plazo_valor)
            if plazo_valor is not None:
                for idx in range(self.plazo_combo.count()):
                    if (
                        self.plazo_combo.itemData(idx, CREDIT_TERM_BACKEND_ROLE)
                        == plazo_valor
                    ):
                        self.plazo_combo.setCurrentIndex(idx)
                        break
            periodo_valor = pago.get("periodo")
            self._backend_pago_periodo = str(periodo_valor) if periodo_valor not in (None, "") else ""
            if periodo_valor not in (None, ""):
                try:
                    self.plazo_spin.setValue(int(periodo_valor))
                except (TypeError, ValueError):
                    self.plazo_spin.setValue(1)
            referencia = pago.get("referencia")
            if referencia:
                self.referencia_edit.setText(str(referencia))
        self._update_condicion_pago_fields()
        self._load_retencion_state(data)

    def _load_retencion_state(self, extra: Mapping[str, Any]) -> None:
        if not hasattr(self, "retencion_checkbox"):
            return
        ret_block = None
        if isinstance(extra, Mapping):
            ret_block = extra.get("_ui_retencion") or extra.get("retencion_iva")
        elif isinstance(extra, str):
            try:
                parsed = json.loads(extra)
            except (TypeError, ValueError):
                parsed = {}
            if isinstance(parsed, Mapping):
                ret_block = parsed.get("_ui_retencion") or parsed.get("retencion_iva")
        normalized = normalize_retencion_payload(ret_block) if ret_block else None
        with QSignalBlocker(self.retencion_checkbox):
            self.retencion_checkbox.setChecked(bool(normalized and normalized.get("enabled")))
        if normalized:
            base = normalized.get("base") or normalized.get("baseSujeta") or 0.0
            reten = normalized.get("montoRetenido") or normalized.get("ivaRetenido") or 0.0
            tasa = normalized.get("tasa")
            if tasa not in (None, ""):
                try:
                    self.retencion_tasa_spin.setValue(float(tasa))
                except Exception:
                    pass
            codigo = normalized.get("codigoRetencionMH")
            if codigo:
                idx = self.retencion_codigo_combo.findData(str(codigo))
                if idx >= 0:
                    self.retencion_codigo_combo.setCurrentIndex(idx)
            geo_emisor = normalized.get("geoEmisor")
            geo_receptor = normalized.get("geoReceptor")
            if geo_emisor:
                idx = self.retencion_geo_emisor_combo.findData(str(geo_emisor))
                if idx >= 0:
                    self.retencion_geo_emisor_combo.setCurrentIndex(idx)
            if geo_receptor:
                idx = self.retencion_geo_receptor_combo.findData(str(geo_receptor))
                if idx >= 0:
                    self.retencion_geo_receptor_combo.setCurrentIndex(idx)
            self.retencion_base_label.setText(f"Base sujeta: ${float(base):.2f}")
            self.retencion_iva_label.setText(
                f"IVA retenido ({float(self._retencion_rate_pct()):.3f}%): ${float(reten):.2f}"
            )
        else:
            self.retencion_base_label.setText("Base sujeta: $0.00")
            self.retencion_iva_label.setText(
                f"IVA retenido ({float(self._retencion_rate_pct()):.3f}%): $0.00"
            )

    def _autofill_remision_fields(self, venta_extra):
        data = {}
        if isinstance(venta_extra, str):
            try:
                data = json.loads(venta_extra)
            except (TypeError, ValueError):
                data = {}
        elif isinstance(venta_extra, dict):
            data = dict(venta_extra)

        existing_remision = str(
            (data.get("no_remision") or data.get("noRemision") or "")
        ).strip()
        existing_orden = str((data.get("orden_no") or data.get("ordenNo") or "")).strip()

        if existing_remision:
            self.no_remision_edit.setText(existing_remision)
        if existing_orden:
            self.orden_no_edit.setText(existing_orden)

        if self.no_remision_edit.text().strip() and self.orden_no_edit.text().strip():
            return

        _, remision = peek_next_correlativo(self.db, "03")
        if not remision:
            return
        if not self.no_remision_edit.text().strip():
            self.no_remision_edit.setText(remision)
        if not self.orden_no_edit.text().strip():
            self.orden_no_edit.setText(remision)

class DistribuidorDialog(QDialog):
    def __init__(self, parent=None, Distribuidor=None):
        super().__init__(parent)
        self.setWindowTitle("Registrar/Editar Distribuidor")
        self.setMinimumWidth(900)
        main_layout = QVBoxLayout()
        self._distribuidor_id = Distribuidor.get("id") if Distribuidor else None

        # --- Datos principales ---
        datos_principales = QGroupBox("Datos principales")
        form1 = QFormLayout()
        self.codigo_edit = QLineEdit()
        self.nombre_edit = QLineEdit()
        self.telefono_edit = QLineEdit()
        self.email_edit = QLineEdit()
        self.cargo_edit = QLineEdit()
        self.sucursal_edit = QLineEdit()
        self.fecha_inicio_edit = QDateEdit(QDate.currentDate())
        self.fecha_inicio_edit.setCalendarPopup(True)

        form1.addRow("Código:", self.codigo_edit)
        form1.addRow("Nombre completo:", self.nombre_edit)
        form1.addRow("Teléfono:", self.telefono_edit)
        form1.addRow("Email:", self.email_edit)
        form1.addRow("Cargo:", self.cargo_edit)
        form1.addRow("Sucursal/Laboratorio:", self.sucursal_edit)
        form1.addRow("Fecha de inicio:", self.fecha_inicio_edit)
        datos_principales.setLayout(form1)

        # --- Detalles adicionales (opcional) ---
        detalles = QGroupBox("Detalles adicionales (opcional)")
        form2 = QFormLayout()
        self.direccion_edit = QLineEdit()
        self.departamento_edit = QComboBox()
        self.municipio_edit = QComboBox()
        municipio_view = QListView()
        municipio_view.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        municipio_view.setFrameShape(QFrame.NoFrame)
        municipio_view.setStyleSheet("border: none;")
        self.municipio_edit.setView(municipio_view)
        self.municipio_edit.setMaxVisibleItems(8)
        _populate_combo(self.departamento_edit, DEPARTAMENTOS)
        _populate_combo(self.municipio_edit, MUNICIPIOS)
        self.municipio_edit.setEnabled(False)
        self.departamento_edit.currentIndexChanged.connect(
            lambda *_: self.municipio_edit.setEnabled(bool(self.departamento_edit.currentData()))
        )
        self.tipo_contrato_edit = QLineEdit()
        self.comisiones_especificas_edit = QLineEdit()
        self.metodo_pago_edit = QLineEdit()
        self.nit_edit = QLineEdit()
        nit_validator = QRegularExpressionValidator(QRegularExpression(r"\d{0,14}"))
        self.nit_edit.setValidator(nit_validator)
        self.nit_edit.setMaxLength(14)
        self.nrc_edit = QLineEdit()
        self.cuenta_bancaria_edit = QLineEdit()
        self.notas_edit = QLineEdit()

        form2.addRow("Dirección:", self.direccion_edit)
        form2.addRow("Departamento:", self.departamento_edit)
        form2.addRow("Municipio:", self.municipio_edit)
        form2.addRow("Tipo de contrato:", self.tipo_contrato_edit)
        form2.addRow("Comisiones específicas:", self.comisiones_especificas_edit)
        form2.addRow("Método/periodicidad pago:", self.metodo_pago_edit)
        form2.addRow("NIT:", self.nit_edit)
        form2.addRow("NRC:", self.nrc_edit)
        form2.addRow("Cuenta bancaria:", self.cuenta_bancaria_edit)
        form2.addRow("Notas:", self.notas_edit)
        detalles.setLayout(form2)

        # --- Agrupa horizontalmente las secciones ---
        h_layout = QHBoxLayout()
        h_layout.addWidget(datos_principales)
        h_layout.addWidget(detalles)
        main_layout.addLayout(h_layout)

        # --- Botones ---
        btns = QHBoxLayout()
        self.btn_ok = QPushButton("Guardar")
        self.btn_cancel = QPushButton("Cancelar")
        btns.addWidget(self.btn_ok)
        btns.addWidget(self.btn_cancel)
        main_layout.addLayout(btns)
        self.setLayout(main_layout)

        self.btn_ok.clicked.connect(self._validar_y_aceptar)
        self.btn_cancel.clicked.connect(self.reject)

        # Si es edición, carga los datos existentes
        if Distribuidor:
            self.codigo_edit.setText(Distribuidor["codigo"] if "codigo" in Distribuidor.keys() else "")
            self.nombre_edit.setText(Distribuidor["nombre"] if "nombre" in Distribuidor.keys() else "")
            self.telefono_edit.setText(Distribuidor["telefono"] if "telefono" in Distribuidor.keys() else "")
            self.email_edit.setText(Distribuidor["email"] if "email" in Distribuidor.keys() else "")
            self.cargo_edit.setText(Distribuidor["cargo"] if "cargo" in Distribuidor.keys() else "")
            self.sucursal_edit.setText(Distribuidor["sucursal"] if "sucursal" in Distribuidor.keys() else "")
            if "fecha_inicio" in Distribuidor.keys() and Distribuidor["fecha_inicio"]:
                self.fecha_inicio_edit.setDate(QDate.fromString(Distribuidor["fecha_inicio"], "yyyy-MM-dd"))
            self.direccion_edit.setText(Distribuidor["direccion"] if "direccion" in Distribuidor.keys() else "")
            _set_combo_value(
                self.departamento_edit,
                DEPARTAMENTOS,
                Distribuidor.get("departamento"),
            )
            _set_combo_value(
                self.municipio_edit,
                MUNICIPIOS,
                Distribuidor.get("municipio"),
            )
            self.municipio_edit.setEnabled(bool(self.departamento_edit.currentData()))
            self.tipo_contrato_edit.setText(Distribuidor["tipo_contrato"] if "tipo_contrato" in Distribuidor.keys() else "")
            self.comisiones_especificas_edit.setText(Distribuidor["comisiones_especificas"] if "comisiones_especificas" in Distribuidor.keys() else "")
            self.metodo_pago_edit.setText(Distribuidor["metodo_pago"] if "metodo_pago" in Distribuidor.keys() else "")
            self.nit_edit.setText(Distribuidor["nit"] if "nit" in Distribuidor.keys() else "")
            self.nrc_edit.setText(Distribuidor["nrc"] if "nrc" in Distribuidor.keys() else "")
            self.cuenta_bancaria_edit.setText(Distribuidor["cuenta_bancaria"] if "cuenta_bancaria" in Distribuidor.keys() else "")
            self.notas_edit.setText(Distribuidor["notas"] if "notas" in Distribuidor.keys() else "")

    def _validar_y_aceptar(self):
        nombre = self.nombre_edit.text().strip()
        telefono = self.telefono_edit.text().strip()
        email = self.email_edit.text().strip()
        nit = self.nit_edit.text().strip()

        if not nombre:
            QMessageBox.warning(self, "Datos inválidos", "El nombre no puede estar vacío.")
            return
        if telefono and not validar_telefono(telefono):
            QMessageBox.warning(self, "Datos inválidos", "Debe ingresar un teléfono válido.")
            return
        if email and not validar_email(email):
            QMessageBox.warning(self, "Datos inválidos", "Debe ingresar un email válido.")
            return
        if nit and not validar_nit(nit):
            QMessageBox.warning(
                self,
                "Datos inválidos",
                "Debe ingresar un NIT válido (9 o 14 dígitos).",
            )
            return
        self.accept()

    def get_data(self):
        return {
            "codigo": self.codigo_edit.text(),
            "nombre": self.nombre_edit.text(),
            "telefono": self.telefono_edit.text(),
            "email": self.email_edit.text(),
            "cargo": self.cargo_edit.text(),
            "sucursal": self.sucursal_edit.text(),
            "fecha_inicio": self.fecha_inicio_edit.date().toString("yyyy-MM-dd"),
            "direccion": self.direccion_edit.text(),
            "departamento": self.departamento_edit.currentData(),
            "municipio": self.municipio_edit.currentData(),
            "tipo_contrato": self.tipo_contrato_edit.text(),
            "comisiones_especificas": self.comisiones_especificas_edit.text(),
            "metodo_pago": self.metodo_pago_edit.text(),
            "nit": self.nit_edit.text(),
            "nrc": self.nrc_edit.text(),
            "cuenta_bancaria": self.cuenta_bancaria_edit.text(),
            "notas": self.notas_edit.text()
        }

    def accept(self):
        db = getattr(getattr(self.parent(), "manager", None), "db", None)
        if db:
            codigo = self.codigo_edit.text().strip()
            nombre = self.nombre_edit.text().strip()
            if codigo:
                if self._distribuidor_id is None:
                    db.cursor.execute("SELECT 1 FROM Distribuidores WHERE codigo=?", (codigo,))
                else:
                    db.cursor.execute(
                        "SELECT 1 FROM Distribuidores WHERE codigo=? AND id<>?",
                        (codigo, self._distribuidor_id),
                    )
                if db.cursor.fetchone():
                    QMessageBox.warning(self, "Código duplicado", "Ya existe un distribuidor con ese código.")
                    return
            if nombre:
                if self._distribuidor_id is None:
                    db.cursor.execute("SELECT 1 FROM Distribuidores WHERE nombre=?", (nombre,))
                else:
                    db.cursor.execute(
                        "SELECT 1 FROM Distribuidores WHERE nombre=? AND id<>?",
                        (nombre, self._distribuidor_id),
                    )
                if db.cursor.fetchone():
                    QMessageBox.warning(self, "Nombre duplicado", "Ya existe un distribuidor con ese nombre.")
                    return
        super().accept()

class DistribuidorInfoDialog(QDialog):
    def __init__(self, distribuidor, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Información de Distribuidor")
        layout = QVBoxLayout()
        form = QFormLayout()

        fields = [
            ("Código:", distribuidor.get("codigo", "")),
            ("Nombre:", distribuidor.get("nombre", "")),
            ("Teléfono:", distribuidor.get("telefono", "")),
            ("Email:", distribuidor.get("email", "")),
            ("Cargo:", distribuidor.get("cargo", "")),
            ("Sucursal/Laboratorio:", distribuidor.get("sucursal", "")),
            ("Fecha de inicio:", distribuidor.get("fecha_inicio", "")),
            ("Dirección:", distribuidor.get("direccion", "")),
            ("Departamento:", distribuidor.get("departamento", "")),
            ("Municipio:", distribuidor.get("municipio", "")),
            ("Tipo de contrato:", distribuidor.get("tipo_contrato", "")),
            ("Comisiones específicas:", distribuidor.get("comisiones_especificas", "")),
            ("Método/periodicidad pago:", distribuidor.get("metodo_pago", "")),
            ("NIT:", distribuidor.get("nit", "")),
            ("NRC:", distribuidor.get("nrc", "")),
            ("Cuenta bancaria:", distribuidor.get("cuenta_bancaria", "")),
            ("Notas:", distribuidor.get("notas", "")),
        ]

        for label, value in fields:
            line = QLineEdit(value)
            line.setReadOnly(True)
            form.addRow(label, line)

        layout.addLayout(form)
        close_btn = QPushButton("Cerrar")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignRight)
        self.setLayout(layout)

class ClienteDialog(QDialog):
    def __init__(self, parent=None, cliente=None, codigo_sugerido=None):
        super().__init__(parent)
        self.setWindowTitle("Agregar/Editar Cliente")
        layout = QVBoxLayout()

        self.codigo_edit = QLineEdit()
        self.nombre_edit = QLineEdit()
        self.tipo_contribuyente_combo = QComboBox()
        self.tipo_contribuyente_combo.addItems(["Persona Natural", "Persona Jurídica"])
        self.nombre_comercial_edit = QLineEdit()
        self.nrc_edit = QLineEdit()
        self.nit_edit = QLineEdit()
        nit_validator = QRegularExpressionValidator(QRegularExpression(r"\d{0,14}"))
        self.nit_edit.setValidator(nit_validator)
        self.nit_edit.setMaxLength(14)
        self.dui_edit = QLineEdit()
        self.dui_edit.setValidator(QIntValidator(0, 999999999))
        self.dui_edit.setMaxLength(9)
        self.giro_edit = QLineEdit()
        self.codActividad_edit = QLineEdit()
        self.telefono_edit = QLineEdit()
        self.email_edit = QLineEdit()
        self.direccion_edit = QLineEdit()
        self.departamento_edit = QComboBox()
        self.municipio_edit = QComboBox()
        municipio_view = QListView()
        municipio_view.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        municipio_view.setFrameShape(QFrame.NoFrame)
        municipio_view.setStyleSheet("border: none;")
        self.municipio_edit.setView(municipio_view)
        self.municipio_edit.setMaxVisibleItems(8)
        _populate_combo(self.departamento_edit, DEPARTAMENTOS)
        _populate_combo(self.municipio_edit, MUNICIPIOS)
        self.municipio_edit.setEnabled(False)
        self.departamento_edit.currentIndexChanged.connect(
            lambda *_: self.municipio_edit.setEnabled(bool(self.departamento_edit.currentData()))
        )
        self._cliente_id = cliente.get("id") if cliente else None

        self.nombre_comercial_label = QLabel("Razón social (opcional):")
        form = [
            ("Código:", self.codigo_edit),
            ("Nombre completo:", self.nombre_edit),
            ("Tipo contribuyente:", self.tipo_contribuyente_combo),
            (self.nombre_comercial_label, self.nombre_comercial_edit),
            ("NRC:", self.nrc_edit),
            ("NIT:", self.nit_edit),
            ("DUI:", self.dui_edit),
            ("Giro:", self.giro_edit),
            ("Código de actividad:", self.codActividad_edit),
            ("Teléfono:", self.telefono_edit),
            ("Correo electrónico:", self.email_edit),
            ("Dirección:", self.direccion_edit),
            ("Departamento:", self.departamento_edit),
            ("Municipio:", self.municipio_edit),
        ]
        manager_obj = getattr(parent, "manager", None) if parent is not None else None
        clientes_existentes = (
            manager_obj._clientes if hasattr(manager_obj, "_clientes") else []
        )
        nombres_comerciales = sorted(
            {
                str(cli.get("nombreComercial", "")).strip()
                for cli in clientes_existentes
                if isinstance(cli, Mapping) and cli.get("nombreComercial")
            }
        )
        if nombres_comerciales:
            completer = QCompleter(nombres_comerciales, self.nombre_comercial_edit)
            completer.setCaseSensitivity(Qt.CaseInsensitive)
            completer.setFilterMode(Qt.MatchContains)
            self.nombre_comercial_edit.setCompleter(completer)

        for label, widget in form:
            if isinstance(label, str):
                label_widget = QLabel(label)
            else:
                label_widget = label
            row = QHBoxLayout()
            row.addWidget(label_widget)
            row.addWidget(widget)
            layout.addLayout(row)

        btns = QHBoxLayout()
        self.btn_ok = QPushButton("Guardar")
        self.btn_cancel = QPushButton("Cancelar")
        btns.addWidget(self.btn_ok)
        btns.addWidget(self.btn_cancel)
        layout.addLayout(btns)
        self.setLayout(layout)

        self.btn_ok.clicked.connect(self._validar_y_accept)
        self.btn_cancel.clicked.connect(self.reject)

        if codigo_sugerido and not cliente:
            self.codigo_edit.setText(codigo_sugerido)

        self.tipo_contribuyente_combo.currentTextChanged.connect(
            self._actualizar_tipo_contribuyente_estado
        )

        if cliente:
            self.codigo_edit.setText(cliente.get("codigo", ""))
            self.nombre_edit.setText(cliente.get("nombre", ""))
            self.nombre_comercial_edit.setText(cliente.get("nombreComercial", ""))
            self.nrc_edit.setText(cliente.get("nrc", ""))
            self.nit_edit.setText(cliente.get("nit", ""))
            self.dui_edit.setText(cliente.get("dui", ""))
            self.giro_edit.setText(cliente.get("giro", ""))
            self.codActividad_edit.setText(cliente.get("codActividad", ""))
            self.telefono_edit.setText(cliente.get("telefono", ""))
            self.email_edit.setText(cliente.get("email", ""))
            self.direccion_edit.setText(cliente.get("direccion", ""))
            _set_combo_value(self.departamento_edit, DEPARTAMENTOS, cliente.get("departamento"))
            _set_combo_value(self.municipio_edit, MUNICIPIOS, cliente.get("municipio"))
            self.municipio_edit.setEnabled(bool(self.departamento_edit.currentData()))
            tipo_contribuyente = cliente.get("tipoContribuyente")
            if not tipo_contribuyente:
                extras = self._parse_cliente_otros(cliente.get("otros"))
                tipo_contribuyente = extras.get("tipoContribuyente")
            if tipo_contribuyente:
                self.tipo_contribuyente_combo.setCurrentText(str(tipo_contribuyente))
        self._actualizar_tipo_contribuyente_estado(self.tipo_contribuyente_combo.currentText())


    def _validar_y_accept(self):
        nrc = self.nrc_edit.text().strip()
        if nrc and not validar_nrc(nrc):
            QMessageBox.warning(self, "Validación", "Ingrese un NRC válido.")
            return
        nit = self.nit_edit.text().strip()
        if nit and not validar_nit(nit):
            QMessageBox.warning(
                self,
                "Validación",
                "Ingrese un NIT válido (9 o 14 dígitos).",
            )
            return
        dui = self.dui_edit.text().strip()
        if dui and not validar_dui(dui):
            QMessageBox.warning(self, "Validación", "Ingrese un DUI válido.")
            return
        telefono = self.telefono_edit.text().strip()
        if telefono and not validar_telefono(telefono):
            QMessageBox.warning(self, "Validación", "Ingrese un teléfono válido.")
            return
        email = self.email_edit.text().strip()
        if email and not validar_email(email):
            QMessageBox.warning(self, "Validación", "Ingrese un correo electrónico válido.")
            return
        tipo_contribuyente = self.tipo_contribuyente_combo.currentText()
        if tipo_contribuyente == "Persona Jurídica":
            razon_social = self.nombre_comercial_edit.text().strip()
            if not razon_social:
                QMessageBox.warning(
                    self,
                    "Validación",
                    "Seleccione una razón social para personas jurídicas.",
                )
                return
        if nit:
            db = getattr(getattr(self.parent(), "manager", None), "db", None)
            if db and db.nit_exists(nit, exclude_id=self._cliente_id):
                QMessageBox.warning(self, "Validación", "El NIT ya está registrado.")
                return
        self.accept()

    def get_data(self):
        return {
            "codigo": self.codigo_edit.text().strip(),
            "nombre": self.nombre_edit.text().strip(),
            "nombreComercial": self.nombre_comercial_edit.text().strip(),
            "nrc": self.nrc_edit.text().strip(),
            "nit": self.nit_edit.text().strip(),
            "dui": self.dui_edit.text().strip(),
            "giro": self.giro_edit.text().strip(),
            "codActividad": self.codActividad_edit.text().strip(),
            "telefono": self.telefono_edit.text().strip(),
            "email": self.email_edit.text().strip(),
            "direccion": self.direccion_edit.text().strip(),
            "departamento": self.departamento_edit.currentData(),
            "municipio": self.municipio_edit.currentData(),
            "tipoContribuyente": self.tipo_contribuyente_combo.currentText(),
            "razonSocial": self.nombre_comercial_edit.text().strip(),
        }

    @staticmethod
    def _parse_cliente_otros(raw_otros):
        if not raw_otros:
            return {}
        if isinstance(raw_otros, Mapping):
            return dict(raw_otros)
        if isinstance(raw_otros, str):
            try:
                data = json.loads(raw_otros)
            except Exception:
                return {}
            return data if isinstance(data, dict) else {}
        return {}

    def _actualizar_tipo_contribuyente_estado(self, texto):
        requerido = texto == "Persona Jurídica"
        if requerido:
            self.nombre_comercial_label.setText("Razón social (*):")
            self.nombre_comercial_edit.setPlaceholderText("Razón social obligatoria")
        else:
            self.nombre_comercial_label.setText("Razón social (opcional):")
            self.nombre_comercial_edit.setPlaceholderText("Razón social (opcional)")

class VendedorDialog(QDialog):
    def __init__(self, Distribuidores, parent=None, vendedor=None, codigo_sugerido=None):
        super().__init__(parent)
        self.setWindowTitle("Agregar/Editar Vendedor")
        layout = QVBoxLayout()

        self.codigo_edit = QLineEdit()
        self.nombre_edit = QLineEdit()
        self.dui_edit = QLineEdit()
        self.dui_edit.setValidator(QRegularExpressionValidator(QRegularExpression(r"[0-9-]*")))
        self.dui_edit.setMaxLength(12)
        self.nit_edit = QLineEdit()
        self.nit_edit.setValidator(QRegularExpressionValidator(QRegularExpression(r"[0-9-]*")))
        self.nit_edit.setMaxLength(20)
        self.descripcion_edit = QLineEdit()
        self.Distribuidor_combo = QComboBox()
        self.Distribuidor_combo.setEditable(True)
        self.Distribuidor_combo.setInsertPolicy(QComboBox.NoInsert)
        line_edit = self.Distribuidor_combo.lineEdit()
        if line_edit is not None:
            line_edit.setPlaceholderText("Buscar distribuidor...")
        self.Distribuidores = Distribuidores
        self.Distribuidor_combo.addItem("Sin Distribuidor", None)
        for d in self.Distribuidores:
            self.Distribuidor_combo.addItem(d["nombre"], d["id"])
        completer = QCompleter(self.Distribuidor_combo.model(), self.Distribuidor_combo)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        if line_edit is not None:
            line_edit.setCompleter(completer)

            def _on_completer_activated(text):
                idx = self.Distribuidor_combo.findText(text, Qt.MatchExactly)
                if idx != -1:
                    self.Distribuidor_combo.setCurrentIndex(idx)

            completer.activated[str].connect(_on_completer_activated)
        self._vendedor_id = vendedor.get("id") if vendedor else None

        layout.addWidget(QLabel("Código:"))
        layout.addWidget(self.codigo_edit)
        layout.addWidget(QLabel("Nombre:"))
        layout.addWidget(self.nombre_edit)
        layout.addWidget(QLabel("DUI:"))
        layout.addWidget(self.dui_edit)
        layout.addWidget(QLabel("NIT:"))
        layout.addWidget(self.nit_edit)
        layout.addWidget(QLabel("Descripción:"))
        layout.addWidget(self.descripcion_edit)
        layout.addWidget(QLabel("Distribuidor:"))
        layout.addWidget(self.Distribuidor_combo)
        self.subject_excluded_chk = QCheckBox("Sujeto excluido (no emite CCF ni factura, sin IVA)")
        layout.addWidget(self.subject_excluded_chk)

        btns = QHBoxLayout()
        self.btn_ok = QPushButton("Guardar")
        self.btn_cancel = QPushButton("Cancelar")
        btns.addWidget(self.btn_ok)
        btns.addWidget(self.btn_cancel)
        layout.addLayout(btns)
        self.setLayout(layout)

        self.btn_ok.clicked.connect(self._validar_y_aceptar)
        self.btn_cancel.clicked.connect(self.reject)

        if codigo_sugerido and not vendedor:
            self.codigo_edit.setText(codigo_sugerido)

        if vendedor:
            self.codigo_edit.setText(vendedor.get("codigo", ""))
            self.nombre_edit.setText(vendedor.get("nombre", ""))
            self.dui_edit.setText(vendedor.get("dui", ""))
            self.nit_edit.setText(vendedor.get("nit", ""))
            self.descripcion_edit.setText(vendedor.get("descripcion", ""))
            Distribuidor_id = vendedor.get("Distribuidor_id")
            if Distribuidor_id:
                idx = self.Distribuidor_combo.findData(Distribuidor_id)
                if idx >= 0:
                    self.Distribuidor_combo.setCurrentIndex(idx)
            self.subject_excluded_chk.setChecked(bool(vendedor.get("is_subject_excluded")))

    def _validar_y_aceptar(self):
        nombre = self.nombre_edit.text().strip()
        if not nombre:
            QMessageBox.warning(self, "Datos inválidos", "El nombre no puede estar vacío.")
            return
        if self.Distribuidor_combo.currentData() is None:
            QMessageBox.warning(
                self,
                "Datos inválidos",
                "Debe seleccionar un distribuidor antes de guardar el vendedor.",
            )
            return
        dui_clean = "".join(ch for ch in self.dui_edit.text() if ch.isdigit())
        nit_clean = "".join(ch for ch in self.nit_edit.text() if ch.isdigit())
        if dui_clean and len(dui_clean) != 9:
            QMessageBox.warning(self, "Datos inválidos", "El DUI debe tener 9 dígitos (puede ingresar guion, se limpia automáticamente).")
            return
        if nit_clean and len(nit_clean) not in (0, 9, 14):
            QMessageBox.warning(self, "Datos inválidos", "El NIT debe tener 9 o 14 dígitos (puede ingresar guiones, se limpian automáticamente).")
            return
        if self.subject_excluded_chk.isChecked():
            nit_ok = len(nit_clean) in (9, 14)
            dui_ok = len(dui_clean) == 9
            if not (nit_ok or dui_ok):
                QMessageBox.warning(
                    self,
                    "Datos inválidos",
                    "Para sujetos excluidos debe registrar un NIT (9 o 14 dígitos) o un DUI (9 dígitos).",
                )
                return
        # Validaciones opcionales si existen los campos
        if hasattr(self, 'telefono_edit'):
            telefono = self.telefono_edit.text().strip()
            if telefono and not telefono.isdigit():
                QMessageBox.warning(self, "Datos inválidos", "El teléfono solo debe contener números.")
                return
        if hasattr(self, 'nit_edit'):
            nit = self.nit_edit.text().strip()
            if nit and not validar_nit(nit):
                QMessageBox.warning(
                    self,
                    "Datos inválidos",
                    "Debe ingresar un NIT válido (9 o 14 dígitos).",
                )
                return
        if hasattr(self, 'email_edit'):
            email = self.email_edit.text().strip()
            if email and not validar_email(email):
                QMessageBox.warning(self, "Datos inválidos", "Debe ingresar un email válido.")
                return
        self.accept()
    def get_data(self):
        return {
            "codigo": self.codigo_edit.text(),
            "nombre": self.nombre_edit.text(),
            "dui": self.dui_edit.text(),
            "nit": self.nit_edit.text(),
            "descripcion": self.descripcion_edit.text(),
            "Distribuidor_id": self.Distribuidor_combo.currentData(),
            "is_subject_excluded": 1 if self.subject_excluded_chk.isChecked() else 0,
        }

    def accept(self):
        db = getattr(getattr(self.parent(), "manager", None), "db", None)
        if db:
            codigo = self.codigo_edit.text().strip()
            nombre = self.nombre_edit.text().strip()
            if codigo:
                if self._vendedor_id is None:
                    db.cursor.execute("SELECT 1 FROM vendedores WHERE codigo=?", (codigo,))
                else:
                    db.cursor.execute(
                        "SELECT 1 FROM vendedores WHERE codigo=? AND id<>?",
                        (codigo, self._vendedor_id),
                    )
                if db.cursor.fetchone():
                    QMessageBox.warning(self, "Código duplicado", "Ya existe un vendedor con ese código.")
                    return
            if nombre:
                if self._vendedor_id is None:
                    db.cursor.execute("SELECT 1 FROM vendedores WHERE nombre=?", (nombre,))
                else:
                    db.cursor.execute(
                        "SELECT 1 FROM vendedores WHERE nombre=? AND id<>?",
                        (nombre, self._vendedor_id),
                    )
                if db.cursor.fetchone():
                    QMessageBox.warning(self, "Nombre duplicado", "Ya existe un vendedor con ese nombre.")
                    return
        super().accept()


class VentaDetalleDialog(QDialog):
    def __init__(self, venta, detalles, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Detalle de Venta")
        self.resize(960, 720)
        self.setMinimumSize(820, 600)
        layout = QVBoxLayout()

        vendedores = []
        productos = []
        clientes = []
        if parent and hasattr(parent, "manager"):
            vendedores = getattr(parent.manager, "_vendedores", [])
            productos = getattr(parent.manager, "_products", [])
            clientes = getattr(parent.manager, "_clientes", [])
        vendedores_dict = {v["id"]: v["nombre"] for v in vendedores}
        productos_dict = {p["id"]: p["nombre"] for p in productos}
        clientes_dict = {c["id"]: c.get("nombre", "") for c in clientes}

        vendedor_nombre = vendedores_dict.get(venta.get("vendedor_id"), "Desconocido")
        cliente_nombre = clientes_dict.get(venta.get("cliente_id"), "Desconocido")

        layout.addWidget(QLabel(f"Fecha: {venta.get('fecha', '')}"))
        layout.addWidget(QLabel(f"Cliente: {cliente_nombre}"))
        layout.addWidget(QLabel(f"Vendedor: {vendedor_nombre}"))
        layout.addWidget(QLabel(f"Total: ${venta.get('total', 0):.2f}"))

        # Mostrar dos columnas de descuento: porcentaje y monto
        table = QTableWidget(len(detalles), 8)
        table.setHorizontalHeaderLabels([
            "Producto",
            "Cantidad",
            "Precio U.",
            "Subtotal",
            "Desc %",
            "Desc $",
            "IVA",
            "Comisión",
        ])
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        for i, d in enumerate(detalles):
            nombre_producto = d.get("descripcion") or productos_dict.get(d.get("producto_id"), "Desconocido")
            precio_unitario = d.get("precio_unitario", 0)
            subtotal = d.get("cantidad", 0) * precio_unitario
            table.setItem(i, 0, QTableWidgetItem(nombre_producto))
            table.setItem(i, 1, QTableWidgetItem(str(d.get("cantidad", ""))))
            table.setItem(i, 2, QTableWidgetItem(f"${precio_unitario:.2f}"))
            table.setItem(i, 3, QTableWidgetItem(f"${subtotal:.2f}"))

            # Calcular monto y porcentaje de descuento
            descuento_valor = d.get("descuento", 0) or 0
            descuento_tipo = d.get("descuento_tipo") or "$"
            descuento_monto = d.get("descuento_monto")
            if descuento_monto is None:
                if descuento_tipo == "%":
                    descuento_monto = subtotal * (descuento_valor / 100)
                else:
                    descuento_monto = descuento_valor
            if descuento_tipo == "%":
                descuento_pct = descuento_valor
            else:
                descuento_pct = (descuento_monto / subtotal * 100) if subtotal else 0

            table.setItem(i, 4, QTableWidgetItem(f"{descuento_pct:.2f}%"))
            table.setItem(i, 5, QTableWidgetItem(f"${descuento_monto:.2f}"))
            table.setItem(i, 6, QTableWidgetItem(f"${d.get('iva', 0):.2f}"))
            table.setItem(i, 7, QTableWidgetItem(f"${d.get('comision', 0):.2f}"))
        table.resizeColumnsToContents()
        layout.addWidget(table)
        self.setLayout(layout)



class CompraDetalleDialog(QDialog):
    def __init__(self, compra, detalles, parent=None, catalogs: Optional[Catalogs] = None):
        super().__init__(parent)
        self.setWindowTitle("Detalle de Compra")
        # Amplía el tamaño inicial del diálogo para evitar que el usuario
        # tenga que redimensionarlo manualmente cuando se muestran compras
        # con mucha información.
        self.resize(960, 720)
        self.setMinimumSize(820, 600)
        layout = QVBoxLayout(self)

        logger.debug("DETALLES DE COMPRA: %s", detalles)

        catalogs, db = self._resolve_catalogs(parent, catalogs)

        logo_layout = QHBoxLayout()
        logo_label = QLabel()
        logo_label.setAlignment(Qt.AlignCenter)
        logo_pixmap = self._load_product_logo()
        if logo_pixmap is not None:
            logo_label.setPixmap(
                logo_pixmap.scaled(QSize(72, 72), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
        else:
            logo_label.setText("Productos")
        logo_layout.addWidget(logo_label, 0, Qt.AlignLeft)

        status_label = QLabel(
            "Catálogo de productos cargado para mostrar el detalle de la compra."
        )
        status_label.setWordWrap(True)
        status_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        logo_layout.addWidget(status_label, 1)

        layout.addLayout(logo_layout)

        def _coerce_product_name(info) -> str | None:
            if isinstance(info, str):
                text = info.strip()
                return text or None
            if isinstance(info, dict):
                for key in ("nombre", "descripcion", "name"):
                    value = info.get(key)
                    if isinstance(value, str) and value.strip():
                        return value.strip()
            return None

        PRODUCT_CODE_KEYS: tuple[str, ...] = (
            "codigo",
            "Codigo",
            "CODIGO",
            "product_code",
            "productCode",
            "codigo_producto",
            "codigoProducto",
            "codigo_barras",
            "codigoBarras",
        )
        PRODUCT_SKU_KEYS: tuple[str, ...] = (
            "sku",
            "Sku",
            "SKU",
            "product_sku",
            "productSku",
        )

        productos_dict: dict[int, str] = {}
        productos_por_codigo: dict[str, str] = {}
        productos_por_codigo_lower: dict[str, str] = {}

        def _coerce_lookup_key(value: Any) -> str | None:
            if isinstance(value, str):
                text = value.strip()
                return text or None
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                if isinstance(value, float) and not value.is_integer():
                    return None
                return str(int(value))
            return None

        def _remember_code_alias(code: str | None, name: str) -> None:
            if not code:
                return
            if code not in productos_por_codigo:
                productos_por_codigo[code] = name
            lowered = code.lower()
            if lowered not in productos_por_codigo_lower:
                productos_por_codigo_lower[lowered] = name

        def _register_product_aliases(
            pid: int, pdata: Mapping[str, Any] | None, name: str
        ) -> None:
            if not isinstance(pdata, Mapping):
                return
            for key in PRODUCT_CODE_KEYS + PRODUCT_SKU_KEYS:
                alias = _coerce_lookup_key(pdata.get(key))
                if alias:
                    _remember_code_alias(alias, name)
            _remember_code_alias(str(pid), name)

        for raw_pid, pdata in catalogs.products.items():
            pid = normalize_identifier(raw_pid)
            if pid is None:
                continue
            name = _coerce_product_name(pdata)
            if name:
                productos_dict[pid] = name
                _register_product_aliases(pid, pdata if isinstance(pdata, Mapping) else None, name)

        def _product_name_from_id(product_id: int | None) -> str | None:
            if product_id is None:
                return None
            if product_id in productos_dict:
                return productos_dict[product_id]
            source = catalogs.products.get(product_id)
            if source is None:
                source = catalogs.products.get(str(product_id))
            name = _coerce_product_name(source)
            if not name and db is not None:
                try:
                    db.cursor.execute(
                        "SELECT id, nombre, codigo, sku FROM productos WHERE id=?",
                        (product_id,),
                    )
                    row = db.cursor.fetchone()
                except Exception:
                    row = None
                    logger.exception(
                        "No fue posible obtener el nombre del producto %s",
                        product_id,
                    )
                if row:
                    try:
                        data = dict(row)
                    except Exception:
                        data = {}
                        if isinstance(row, tuple):
                            try:
                                data["id"] = row[0]
                                data["nombre"] = row[1]
                                data["codigo"] = row[2] if len(row) > 2 else None
                                data["sku"] = row[3] if len(row) > 3 else None
                            except Exception:
                                data = {"id": product_id}
                    value = data.get("nombre")
                    if isinstance(value, str) and value.strip():
                        name = value.strip()
                        codigo_value = _coerce_lookup_key(data.get("codigo"))
                        sku_value = _coerce_lookup_key(data.get("sku"))
                        _remember_code_alias(codigo_value, name)
                        _remember_code_alias(sku_value, name)
            if name:
                productos_dict[product_id] = name
                if isinstance(source, MutableMapping):
                    source.setdefault("id", product_id)
                    if not source.get("nombre"):
                        source["nombre"] = name
                    _register_product_aliases(product_id, source, name)
                else:
                    catalogs.products.setdefault(
                        product_id, {"id": product_id, "nombre": name}
                    )
                    _remember_code_alias(str(product_id), name)
            return name

        def _product_name_from_detail_id(detail_id: int | None) -> str | None:
            if detail_id is None or db is None:
                return None
            try:
                db.cursor.execute(
                    """
                    SELECT p.id AS producto_id, p.nombre, p.codigo, p.sku
                    FROM detalles_compra dc
                    JOIN productos p ON p.id = dc.producto_id
                    WHERE dc.id = ?
                    LIMIT 1
                    """,
                    (detail_id,),
                )
                row = db.cursor.fetchone()
            except Exception:
                logger.exception(
                    "No fue posible obtener el producto asociado al detalle %s",
                    detail_id,
                )
                return None
            if not row:
                return None
            try:
                data = dict(row)
            except Exception:
                data = {}
                if isinstance(row, tuple):
                    try:
                        data["producto_id"] = row[0]
                        data["nombre"] = row[1]
                        data["codigo"] = row[2] if len(row) > 2 else None
                        data["sku"] = row[3] if len(row) > 3 else None
                    except Exception:
                        data = {}

            name = _coerce_product_name(data)
            if not name:
                return None

            product_id = normalize_identifier(
                data.get("producto_id") or data.get("id")
            )
            if product_id is not None:
                productos_dict[product_id] = name
                entry = catalogs.products.get(product_id)
                if isinstance(entry, MutableMapping):
                    entry.setdefault("id", product_id)
                    if not entry.get("nombre"):
                        entry["nombre"] = name
                    for key in ("codigo", "sku"):
                        value = data.get(key)
                        if value and not entry.get(key):
                            entry[key] = value
                    _register_product_aliases(product_id, entry, name)
                else:
                    catalogs.products[product_id] = {
                        "id": product_id,
                        "nombre": name,
                        "codigo": data.get("codigo"),
                        "sku": data.get("sku"),
                    }
                    _register_product_aliases(
                        product_id,
                        catalogs.products.get(product_id),
                        name,
                    )

            _remember_code_alias(_coerce_lookup_key(data.get("codigo")), name)
            _remember_code_alias(_coerce_lookup_key(data.get("sku")), name)

            return name

        def _coerce_detail_text(value: Any) -> str | None:
            if isinstance(value, str):
                text = value.strip()
                if text:
                    return text
            return None

        def _lookup_product_name_by_code(value: Any) -> str | None:
            code = _coerce_lookup_key(value)
            if not code:
                return None
            name = productos_por_codigo.get(code)
            if name:
                return name
            lowered = code.lower()
            if lowered in productos_por_codigo_lower:
                return productos_por_codigo_lower[lowered]
            if db is None:
                return None
            try:
                db.cursor.execute(
                    """
                    SELECT id, nombre, codigo, sku
                    FROM productos
                    WHERE LOWER(codigo) = LOWER(?) OR LOWER(sku) = LOWER(?)
                    LIMIT 1
                    """,
                    (code, code),
                )
                row = db.cursor.fetchone()
            except Exception:
                logger.exception(
                    "No fue posible obtener el producto con código %s", code
                )
                return None
            if not row:
                return None
            try:
                data = dict(row)
            except Exception:
                data = {}
                if isinstance(row, tuple):
                    try:
                        data["id"] = row[0]
                        data["nombre"] = row[1]
                        data["codigo"] = row[2] if len(row) > 2 else None
                        data["sku"] = row[3] if len(row) > 3 else None
                    except Exception:
                        data = {}
            fetched_name = data.get("nombre")
            if isinstance(fetched_name, str):
                fetched_name = fetched_name.strip() or None
            else:
                fetched_name = None
            if not fetched_name:
                return None
            pid = normalize_identifier(data.get("id"))
            if pid is not None:
                productos_dict[pid] = fetched_name
                catalogs.products.setdefault(
                    pid,
                    {
                        "id": pid,
                        "nombre": fetched_name,
                        "codigo": data.get("codigo"),
                        "sku": data.get("sku"),
                    },
                )
                _remember_code_alias(str(pid), fetched_name)
            _remember_code_alias(_coerce_lookup_key(data.get("codigo")), fetched_name)
            _remember_code_alias(_coerce_lookup_key(data.get("sku")), fetched_name)
            _remember_code_alias(code, fetched_name)
            return fetched_name

        def _detail_product_name(detalle: Mapping[str, Any]) -> str:
            descripcion = _coerce_detail_text(detalle.get("descripcion"))
            if descripcion:
                return descripcion

            for key in (
                "producto",
                "producto_nombre",
                "nombre_producto",
                "nombre",
                "detalle",
            ):
                fallback = _coerce_detail_text(detalle.get(key))
                if fallback:
                    return fallback

            product_id: int | None = None
            for key in (
                "producto_id",
                "Producto_id",
                "product_id",
                "productoId",
                "productId",
                "ProductoId",
            ):
                product_id = normalize_identifier(detalle.get(key))
                if product_id is not None:
                    break

            name = _product_name_from_id(product_id)
            if name:
                return name

            for key in PRODUCT_CODE_KEYS + PRODUCT_SKU_KEYS:
                name = _lookup_product_name_by_code(detalle.get(key))
                if name:
                    return name

            detail_id = normalize_identifier(detalle.get("detalle_id"))
            if detail_id is None:
                detail_id = normalize_identifier(detalle.get("id"))
            name = _product_name_from_detail_id(detail_id)
            if name:
                return name

            name = _lookup_product_name_by_code(detalle.get("producto"))
            return name or "Desconocido"

        vendedor_nombre, distribuidor_nombre = resolve_party_names(compra, catalogs)

        info_grid = QGridLayout()
        row = 0
        info_grid.addWidget(QLabel(f"ID Compra: {compra.get('id', '')}"), row, 0)
        info_grid.addWidget(QLabel(f"Fecha: {compra.get('fecha', '')}"), row, 1)
        row += 1
        info_grid.addWidget(QLabel(f"Distribuidor: {distribuidor_nombre}"), row, 0)
        info_grid.addWidget(QLabel(f"Vendedor: {vendedor_nombre}"), row, 1)
        row += 1
        is_subject_excluded = bool(compra.get("is_subject_excluded_purchase"))
        dte_status = compra.get("subject_excluded_dte_status", "NO_APLICA") or "NO_APLICA"
        info_grid.addWidget(QLabel(f"Sujeto excluido: {'Sí' if is_subject_excluded else 'No'}"), row, 0)
        info_grid.addWidget(QLabel(f"Estado DTE sujeto excluido: {dte_status}"), row, 1)
        row += 1
        info_grid.addWidget(QLabel(f"Total general: ${compra.get('total', 0):.2f}"), row, 0)
        info_grid.addWidget(
            QLabel(f"Comisión %: {compra.get('comision_pct', 0) or 0:.2f}%"),
            row,
            1,
        )
        row += 1
        info_grid.addWidget(
            QLabel(f"Comisión monto: ${compra.get('comision_monto', 0) or 0:.2f}"),
            row,
            0,
        )
        info_grid.addWidget(
            QLabel(
                f"Cantidad registrada: {compra.get('cantidad', 0) or 0}"
            ),
            row,
            1,
        )
        row += 1
        info_grid.addWidget(
            QLabel(
                f"Precio unitario ref.: ${compra.get('precio_unitario', 0) or 0:.2f}"
            ),
            row,
            0,
        )
        producto_id = normalize_identifier(compra.get("producto_id"))
        if producto_id is not None:
            producto_nombre = _product_name_from_id(producto_id) or "Desconocido"
            info_grid.addWidget(
                QLabel(f"Producto asociado: {producto_nombre}"),
                row,
                1,
            )
        layout.addLayout(info_grid)

        fse_json_path = self._find_fse_json_path(compra)
        if fse_json_path:
            toggle_btn = QPushButton("Ver DTE sujeto excluido (JSON)")
            toggle_btn.setCheckable(True)
            layout.addWidget(toggle_btn, alignment=Qt.AlignLeft)

            json_view = QPlainTextEdit()
            json_view.setReadOnly(True)
            json_view.setLineWrapMode(QPlainTextEdit.NoWrap)
            try:
                with open(fse_json_path, "r", encoding="utf-8") as fh:
                    json_view.setPlainText(fh.read())
            except Exception as exc:
                json_view.setPlainText(f"No se pudo leer el JSON ({exc})")
            json_view.hide()
            layout.addWidget(json_view)

            def _toggle_json(checked: bool) -> None:
                json_view.setVisible(checked)
                toggle_btn.setText(
                    "Ocultar DTE sujeto excluido" if checked else "Ver DTE sujeto excluido (JSON)"
                )

            toggle_btn.toggled.connect(_toggle_json)

        headers = [
            "Producto",
            "Cantidad",
            "Precio U.",
            "Subtotal",
            "Descuento",
            "Tipo desc.",
            "IVA",
            "Tipo IVA",
            "Comisión %",
            "Comisión $",
            "Tipo comisión",
            "Código lote",
            "Registro sanitario",
            "Vencimiento",
        ]
        table = QTableWidget(len(detalles), len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        for i, d in enumerate(detalles):
            nombre_producto = _detail_product_name(d)
            precio_unitario = d.get("precio_unitario", d.get("precio", 0)) or 0
            subtotal = (d.get("cantidad", 0) or 0) * precio_unitario
            table.setItem(i, 0, QTableWidgetItem(nombre_producto))
            table.setItem(i, 1, QTableWidgetItem(str(d.get("cantidad", ""))))
            table.setItem(i, 2, QTableWidgetItem(f"${precio_unitario:.2f}"))
            table.setItem(i, 3, QTableWidgetItem(f"${subtotal:.2f}"))
            table.setItem(i, 4, QTableWidgetItem(f"${d.get('descuento', 0) or 0:.2f}"))
            table.setItem(i, 5, QTableWidgetItem(str(d.get("descuento_tipo", ""))))
            table.setItem(i, 6, QTableWidgetItem(f"${d.get('iva', 0) or 0:.2f}"))
            table.setItem(i, 7, QTableWidgetItem(str(d.get("iva_tipo", ""))))
            table.setItem(i, 8, QTableWidgetItem(f"{d.get('comision_pct', 0) or 0:.2f}%"))
            table.setItem(i, 9, QTableWidgetItem(f"${d.get('comision_monto', 0) or 0:.2f}"))
            table.setItem(i, 10, QTableWidgetItem(str(d.get("comision_tipo", ""))))
            table.setItem(i, 11, QTableWidgetItem(str(d.get("codigo_lote", ""))))
            table.setItem(i, 12, QTableWidgetItem(str(d.get("registro_sanitario", ""))))
            table.setItem(i, 13, QTableWidgetItem(str(d.get("fecha_vencimiento", ""))))
        table.resizeColumnsToContents()
        layout.addWidget(table)

    @staticmethod
    def _resolve_catalogs(parent, catalogs: Optional[Catalogs]) -> tuple[Catalogs, Optional[DB]]:
        manager = getattr(parent, "manager", None) if parent is not None else None
        if catalogs is None and parent is not None:
            catalogs = getattr(parent, "catalogs", None)
        if catalogs is None and manager is not None:
            catalogs = getattr(manager, "catalogs", None)

        db = None
        if manager is not None:
            db = getattr(manager, "db", None)
        if db is None and parent is not None:
            db = getattr(parent, "db", None)

        if catalogs is None:
            catalogs = Catalogs(vendors={}, distributors={}, products={}, db=db)
        else:
            if catalogs.db is None:
                catalogs.db = db

            def _populate_missing(target, source_iterable):
                if not isinstance(target, MutableMapping):
                    return
                for entry in source_iterable or []:
                    identifier = normalize_identifier(entry.get("id")) if isinstance(entry, Mapping) else None
                    if identifier is None or identifier in target:
                        continue
                    try:
                        target[identifier] = dict(entry)
                    except Exception:
                        # Fallback to raw entry when it cannot be cloned (e.g. sqlite rows)
                        target[identifier] = entry

            if manager is not None:
                vendor_source = getattr(manager, "_vendedores_compra", None)
                if not vendor_source and getattr(manager, "db", None):
                    try:
                        vendor_source = manager.db.get_vendedores_distribuidores()
                    except Exception:
                        vendor_source = None
                if vendor_source:
                    _populate_missing(catalogs.vendors, vendor_source)

                def _hydrate_from_id_map(target: MutableMapping, source):
                    if not isinstance(target, MutableMapping):
                        return
                    if not isinstance(source, Mapping):
                        return
                    for raw_identifier, raw_name in source.items():
                        identifier = normalize_identifier(raw_identifier)
                        if identifier is None:
                            continue
                        name = raw_name.strip() if isinstance(raw_name, str) else None
                        entry = target.get(identifier)
                        if entry is None:
                            if name:
                                target[identifier] = {"id": identifier, "nombre": name}
                            else:
                                target[identifier] = {"id": identifier}
                            continue
                        if isinstance(entry, MutableMapping):
                            entry.setdefault("id", identifier)
                            if name and not entry.get("nombre"):
                                entry["nombre"] = name
                            continue
                        try:
                            data = dict(entry)
                        except Exception:
                            data = {"id": identifier}
                        if name and not data.get("nombre"):
                            data["nombre"] = name
                        target[identifier] = data

                vendor_map = getattr(manager, "_vendedores_compra_by_id", None)
                if vendor_map:
                    _hydrate_from_id_map(catalogs.vendors, vendor_map)

                distributor_source = getattr(manager, "_Distribuidores", None)
                if not distributor_source and getattr(manager, "db", None):
                    try:
                        distributor_source = manager.db.get_Distribuidores()
                    except Exception:
                        distributor_source = None
                if distributor_source:
                    _populate_missing(catalogs.distributors, distributor_source)

                distributor_map = getattr(manager, "_Distribuidores_by_id", None)
                if distributor_map:
                    _hydrate_from_id_map(catalogs.distributors, distributor_map)

                product_source = getattr(manager, "_products", None)
                if not product_source and getattr(manager, "db", None):
                    try:
                        product_source = manager.db.get_productos()
                    except Exception:
                        product_source = None
                if product_source:
                    _populate_missing(catalogs.products, product_source)

        return catalogs, catalogs.db

    @staticmethod
    def _load_product_logo() -> QPixmap | None:
        """Load a representative logo for product operations if available."""

        base_dir = Path(__file__).resolve().parent
        candidates = [
            base_dir / ".." / "logoinventario.jpg",
            base_dir / ".." / "app" / "logoinventario.jpg",
        ]
        for candidate in candidates:
            try:
                path = candidate.resolve()
            except FileNotFoundError:
                continue
            if not path.exists():
                continue
            pixmap = QPixmap(str(path))
            if not pixmap.isNull():
                return pixmap
        return None

    @staticmethod
    def _find_fse_json_path(compra: Mapping[str, Any]) -> Path | None:
        """Busca el JSON del DTE de sujeto excluido para esta compra."""

        try:
            compra_id = normalize_identifier(compra.get("id"))
        except Exception:
            compra_id = None
        if compra_id is None:
            return None
        try:
            base_dir = Path(ensure_user_dir("dtes_sujeto_excluido"))
        except Exception:
            return None

        candidates: list[Path] = []
        try:
            pattern = f"fse_compra_{compra_id}_*.json"
            candidates = list(base_dir.glob(pattern))
            if not candidates:
                candidates = [p for p in base_dir.glob("*.json") if f"_{compra_id}" in p.name]
        except Exception:
            return None

        if not candidates:
            return None
        try:
            candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        except Exception:
            pass
        return candidates[0] if candidates else None

class LogoPreviewDialog(QDialog):
    """Permite seleccionar y previsualizar el logo del negocio."""

    def __init__(self, logo_path: str | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Logo de la empresa")
        self.selected_path: str | None = None

        layout = QVBoxLayout()

        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumSize(240, 160)
        self.preview.setFrameShape(QFrame.StyledPanel)
        layout.addWidget(self.preview)

        self.path_label = QLabel()
        self.path_label.setAlignment(Qt.AlignCenter)
        self.path_label.setWordWrap(True)
        layout.addWidget(self.path_label)

        select_btn = QPushButton("Seleccionar logo")
        select_btn.clicked.connect(self._select_logo)
        layout.addWidget(select_btn)

        button_box = QDialogButtonBox(QDialogButtonBox.Close)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self.setLayout(layout)
        self._update_preview(logo_path)

    def _update_preview(self, path: str | None):
        if path and os.path.exists(path):
            pixmap = QPixmap(path)
            if not pixmap.isNull():
                target_size = self.preview.size()
                if not target_size.width() or not target_size.height():
                    target_size = self.preview.minimumSize()
                if not target_size.width() or not target_size.height():
                    target_size = QSize(320, 200)
                scaled = pixmap.scaled(
                    target_size,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
                self.preview.setPixmap(scaled)
                self.path_label.setText(path)
                self.selected_path = path
                return
        self.preview.setPixmap(QPixmap())
        self.preview.setText("Sin logo seleccionado")
        self.path_label.setText("")
        self.selected_path = None

    def _select_logo(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar logo",
            "",
            "Imágenes (*.png *.jpg *.jpeg)",
        )
        if not file_path:
            return
        if not os.path.exists(file_path):
            QMessageBox.warning(self, "Logo", "No se pudo abrir el archivo seleccionado.")
            return
        pixmap = QPixmap(file_path)
        if pixmap.isNull():
            QMessageBox.warning(
                self,
                "Logo",
                "El archivo seleccionado no es una imagen válida.",
            )
            return
        target_size = self.preview.size()
        if not target_size.width() or not target_size.height():
            target_size = self.preview.minimumSize()
        if not target_size.width() or not target_size.height():
            target_size = QSize(320, 200)
        scaled = pixmap.scaled(
            target_size,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.preview.setPixmap(scaled)
        self.preview.setText("")
        self.path_label.setText(file_path)
        self.selected_path = file_path


class DatosNegocioDialog(QDialog):
    """Diálogo para editar los datos necesarios para la facturación."""

    def __init__(self, datos=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Datos del negocio")
        form = QFormLayout()
        self.logo_path: str | None = None
        self.nit = QLineEdit()
        self.nrc = QLineEdit()
        self.dui = QLineEdit()
        self.dui.setValidator(
            QRegularExpressionValidator(QRegularExpression(r"^\d{0,9}$"))
        )
        self.dui.setMaxLength(9)
        self.nombre = QLineEdit()
        self.nombre_comercial = QLineEdit()
        self.cod_giro = QLineEdit()
        self.desc_actividad = QLineEdit()
        self.tipo_contribuyente = QComboBox()
        self.tipo_contribuyente.addItems(TIPO_CONTRIBUYENTE_OPCIONES)
        self.tipo_contribuyente.currentTextChanged.connect(
            lambda *_: self._update_razon_social_state()
        )
        self.razon_social = QLineEdit()
        self.razon_social.setPlaceholderText("Opcional para persona natural")
        self.telefono = QLineEdit()
        self.correo = QLineEdit()
        self.departamento = QComboBox()
        self.municipio = QComboBox()
        # Limitar el alto del listado de municipios y mostrar scroll sin marcos en blanco
        municipio_view = QListView()
        municipio_view.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        municipio_view.setFrameShape(QFrame.NoFrame)
        municipio_view.setStyleSheet("border: none;")
        self.municipio.setView(municipio_view)
        self.municipio.setMaxVisibleItems(8)
        self.complemento = QLineEdit()
        _populate_combo(self.departamento, DEPARTAMENTOS)
        _populate_combo(self.municipio, MUNICIPIOS)
        self.municipio.setEnabled(False)
        self.departamento.currentIndexChanged.connect(
            lambda *_: self.municipio.setEnabled(bool(self.departamento.currentData()))
        )
        form.addRow("NIT:", self.nit)
        form.addRow("NRC:", self.nrc)
        form.addRow("DUI:", self.dui)
        form.addRow("Nombre:", self.nombre)
        form.addRow("Nombre comercial:", self.nombre_comercial)
        form.addRow("Código giro:", self.cod_giro)
        form.addRow("Descripción actividad:", self.desc_actividad)
        form.addRow("Tipo contribuyente:", self.tipo_contribuyente)
        form.addRow("Razón social:", self.razon_social)
        form.addRow("Teléfono:", self.telefono)
        form.addRow("Correo:", self.correo)
        form.addRow("Departamento:", self.departamento)
        form.addRow("Municipio:", self.municipio)
        form.addRow("Dirección:", self.complemento)
        self.btn_logo = QPushButton("Logo de la empresa")
        self.btn_logo.clicked.connect(self._open_logo_dialog)
        form.addRow("", self.btn_logo)
        btns = QHBoxLayout()
        self.btn_guardar = QPushButton("Guardar")
        self.btn_cancelar = QPushButton("Cancelar")
        btns.addWidget(self.btn_guardar)
        btns.addWidget(self.btn_cancelar)
        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addLayout(btns)
        self.setLayout(layout)
        self.btn_guardar.clicked.connect(self._on_save)
        self.btn_cancelar.clicked.connect(self.reject)
        if datos:
            logger.info("DatosNegocioDialog load_config keys=%s", list(datos.keys()))
            self.set_data(datos)
        else:
            self._update_logo_button()
        self._update_razon_social_state()

    def _on_save(self):
        try:
            data = self.get_data()
            logger.info(
                "DatosNegocioDialog save_config keys=%s",
                list(data.keys()),
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Validación", str(exc))
            return
        self.accept()

    def reject(self):
        logger.info("DatosNegocioDialog cancel_config")
        super().reject()

    def get_data(self):
        departamento = str(self.departamento.currentData() or "").zfill(2)
        municipio = str(self.municipio.currentData() or "")
        complemento = self.complemento.text()
        razon_social = self.razon_social.text().strip()
        tipo_contribuyente = self.tipo_contribuyente.currentText()
        if departamento not in CAT012_DEPARTAMENTOS:
            raise ValueError("Departamento inválido")
        if municipio not in CAT013_MUNICIPIOS:
            raise ValueError("Municipio inválido")
        if not complemento:
            raise ValueError("Dirección requerida")
        if tipo_contribuyente == "Persona Jurídica" and not razon_social:
            raise ValueError("La razón social es obligatoria para personas jurídicas")
        return {
            "nit": self.nit.text(),
            "nrc": self.nrc.text(),
            "dui": solo_digitos(self.dui.text()),
            "nombre": self.nombre.text(),
            "nombreComercial": self.nombre_comercial.text(),
            "cod_giro": self.cod_giro.text(),
            "codActividad": self.cod_giro.text(),
            "descActividad": self.desc_actividad.text(),
            "tipoContribuyente": tipo_contribuyente,
            "razonSocial": razon_social,
            "telefono": self.telefono.text(),
            "correo": self.correo.text(),
            "direccion": {
                "departamento": departamento,
                "municipio": municipio,
                "complemento": complemento,
            },
            "logo_path": self.logo_path,
        }

    def set_data(self, datos):
        self.nit.setText(datos.get("nit", ""))
        self.nrc.setText(datos.get("nrc", ""))
        self.dui.setText(datos.get("dui", ""))
        self.nombre.setText(datos.get("nombre", ""))
        self.nombre_comercial.setText(datos.get("nombreComercial", ""))
        self.cod_giro.setText(datos.get("cod_giro") or datos.get("codActividad", ""))
        self.desc_actividad.setText(datos.get("descActividad", ""))
        tipo = _normalize_tipo_contribuyente(datos.get("tipoContribuyente"))
        self.tipo_contribuyente.setCurrentText(tipo)
        self.razon_social.setText(datos.get("razonSocial", ""))
        self.telefono.setText(datos.get("telefono", ""))
        self.correo.setText(datos.get("correo", ""))
        dir_info = datos.get("direccion", {}) or {}
        departamento = dir_info.get("departamento")
        municipio = dir_info.get("municipio")
        _set_combo_value(
            self.departamento,
            DEPARTAMENTOS,
            str(departamento) if departamento else "",
        )
        _set_combo_value(
            self.municipio,
            MUNICIPIOS,
            str(municipio) if municipio else "",
        )
        self.municipio.setEnabled(bool(self.departamento.currentData()))
        self.complemento.setText(dir_info.get("complemento", ""))
        self.logo_path = None
        for key in ("logo_path", "logoPath", "logo"):
            path = datos.get(key)
            if path:
                self.logo_path = path
                break
        self._update_logo_button()
        self._update_razon_social_state()

    def _update_razon_social_state(self):
        is_persona_juridica = (
            self.tipo_contribuyente.currentText() == "Persona Jurídica"
        )
        if is_persona_juridica:
            self.razon_social.setPlaceholderText("Obligatoria para persona jurídica")
        else:
            self.razon_social.setPlaceholderText("Opcional para persona natural")

    def _open_logo_dialog(self):
        dlg = LogoPreviewDialog(self.logo_path, self)
        dlg.exec_()
        if dlg.selected_path:
            self.logo_path = dlg.selected_path
        self._update_logo_button()

    def _update_logo_button(self):
        if self.logo_path:
            self.btn_logo.setText("Logo de la empresa (seleccionado)")
            self.btn_logo.setToolTip(self.logo_path)
        else:
            self.btn_logo.setText("Logo de la empresa")
            self.btn_logo.setToolTip("Selecciona una imagen para usar como logo en las facturas")


class EmailConfigDialog(QDialog):
    def __init__(self, datos=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configuración de correo")
        layout = QVBoxLayout()
        form = QFormLayout()
        self.combo_email_provider = QComboBox()
        self.combo_email_provider.addItems([
            "Gmail",
            "Outlook",
            "Yahoo",
            "Zoho",
            "iCloud",
        ])
        self.smtp_server = QLineEdit()
        self.smtp_port = QLineEdit()
        self.email_usuario = QLineEdit()
        self.email_contrasena = QLineEdit()
        self.email_contrasena.setEchoMode(QLineEdit.Password)
        form.addRow("Proveedor:", self.combo_email_provider)
        form.addRow("Servidor SMTP:", self.smtp_server)
        form.addRow("Puerto SMTP:", self.smtp_port)
        form.addRow("Usuario:", self.email_usuario)
        form.addRow("Contraseña:", self.email_contrasena)
        layout.addLayout(form)
        btns = QHBoxLayout()
        self.btn_guardar = QPushButton("Guardar")
        self.btn_cancelar = QPushButton("Cancelar")
        btns.addWidget(self.btn_guardar)
        btns.addWidget(self.btn_cancelar)
        layout.addLayout(btns)
        self.setLayout(layout)
        self.btn_guardar.clicked.connect(self.accept)
        self.btn_cancelar.clicked.connect(self.reject)
        self.combo_email_provider.currentTextChanged.connect(self._update_smtp_fields)
        self._update_smtp_fields()
        if datos:
            logger.info("EmailConfigDialog load_config keys=%s", list(datos.keys()))
            self.set_data(datos)

    def _update_smtp_fields(self):
        provider = self.combo_email_provider.currentText()
        defaults = {
            "Gmail": ("smtp.gmail.com", 587),
            "Outlook": ("smtp.office365.com", 587),
            "Yahoo": ("smtp.mail.yahoo.com", 587),
            "Zoho": ("smtp.zoho.com", 587),
            "iCloud": ("smtp.mail.me.com", 587),
        }
        server, port = defaults.get(provider, ("", ""))
        self.smtp_server.setText(server)
        self.smtp_port.setText(str(port))
        self.smtp_server.setReadOnly(True)
        self.smtp_port.setReadOnly(True)

    def get_data(self):
        return {
            "email_provider": self.combo_email_provider.currentText(),
            "smtp_server": self.smtp_server.text(),
            "smtp_port": self.smtp_port.text(),
            "email_usuario": self.email_usuario.text(),
            "email_contrasena": self.email_contrasena.text(),
        }

    def set_data(self, datos):
        self.combo_email_provider.setCurrentText(datos.get("email_provider", "Gmail"))

        smtp_server = datos.get("smtp_server")
        if smtp_server:
            self.smtp_server.setText(smtp_server)

        smtp_port = datos.get("smtp_port")
        if smtp_port:
            self.smtp_port.setText(str(smtp_port))

        self.email_usuario.setText(datos.get("email_usuario", ""))
        self.email_contrasena.setText(datos.get("email_contrasena", ""))

    def accept(self):
        data = self.get_data()
        logger.info(
            "EmailConfigDialog save_config provider=%s user=%s",
            data.get("email_provider"),
            data.get("email_usuario"),
        )
        super().accept()

    def reject(self):
        logger.info("EmailConfigDialog cancel_config")
        super().reject()


def prompt_auth_credentials(parent=None, user="", password=""):
    """Abre un cuadro de diálogo para solicitar usuario y contraseña.

    Retorna una tupla ``(usuario, contraseña)`` si el usuario acepta, o ``(None, None)``
    si cancela la operación.
    """
    dialog = QDialog(parent)
    dialog.setWindowTitle("Autenticación")
    layout = QVBoxLayout(dialog)
    form = QFormLayout()
    layout.addLayout(form)
    user_edit = QLineEdit(user)
    pwd_edit = QLineEdit(password)
    pwd_edit.setEchoMode(QLineEdit.Password)
    form.addRow("Usuario:", user_edit)
    form.addRow("Contraseña:", pwd_edit)
    buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    layout.addWidget(buttons)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    if dialog.exec_() == QDialog.Accepted:
        return user_edit.text().strip(), pwd_edit.text().strip()
    return None, None


class DTECorrelativoConfigDialog(QDialog):
    _TIPO_DTE_DESC = {
        "01": "Consumidor final",
        "03": "Crédito fiscal",
        "04": "Nota de remisión",
        "05": "Nota de crédito",
        "06": "Nota de débito",
        "07": "Comprobante de retención",
        "14": "Factura sujeto excluido",
    }

    def __init__(self, db=None, prefijo="DTE-01-S001P001", parent=None):
        super().__init__(parent)
        self.db = db or DB()
        self.prefijo = prefijo
        self.setWindowTitle("Configuración de correlativo")
        self.resize(720, 520)

        layout = QVBoxLayout(self)
        self.correlativos_table = QTableWidget(0, 3)
        self.correlativos_table.setHorizontalHeaderLabels([
            "Tipo de DTE",
            "Correlativo",
            "",
        ])
        self.correlativos_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch
        )
        self.correlativos_table.verticalHeader().setVisible(False)
        layout.addWidget(self.correlativos_table)

        btns = QHBoxLayout()
        btns.addStretch()
        guardar = QPushButton("Guardar")
        cancelar = QPushButton("Cancelar")
        for boton in (guardar, cancelar):
            boton.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            boton.setFixedHeight(28)
        btns.addWidget(guardar)
        btns.addWidget(cancelar)
        layout.addLayout(btns)

        guardar.clicked.connect(self.accept)
        cancelar.clicked.connect(self.reject)

        self._load_correlativos()

    def _get_sucursal_punto(self):
        m = re.search(r"S(\d{3})P(\d{3})", self.prefijo)
        if m:
            return m.group(1), m.group(2)
        return "001", "001"

    def _load_correlativos(self):
        sucursal, punto = self._get_sucursal_punto()
        self.correlativos_table.setRowCount(0)
        self._correlativo_spins = {}
        self._original_correlativos = {}
        for tipo in ["01", "03", "04", "05", "06", "07", "14"]:
            row = self.correlativos_table.rowCount()
            self.correlativos_table.insertRow(row)
            tipo_desc = self._TIPO_DTE_DESC.get(tipo, tipo)
            self.correlativos_table.setItem(
                row,
                0,
                QTableWidgetItem(f"{tipo_desc} ({tipo})"),
            )
            spin = QSpinBox()
            spin.setMaximum(999999999)
            valor = self.db.get_dte_correlativo(tipo, sucursal, punto)
            spin.setValue(valor)
            self._original_correlativos[tipo] = valor
            self.correlativos_table.setCellWidget(row, 1, spin)
            btn = QPushButton("Reiniciar")
            btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            btn.setFixedHeight(20)
            btn.setStyleSheet(
                """
                QPushButton {
                    background-color: #c0392b;
                    color: white;
                    border-radius: 4px;
                    padding: 1px 10px;
                }
                QPushButton:hover {
                    background-color: #e74c3c;
                }
                QPushButton:pressed {
                    background-color: #922b21;
                }
                """
            )
            btn.clicked.connect(lambda _, t=tipo: self._reset_correlativo(t))
            self.correlativos_table.setCellWidget(row, 2, btn)
            self._correlativo_spins[tipo] = spin

    def _reset_correlativo(self, tipo):
        self._correlativo_spins[tipo].setValue(0)

    def accept(self):
        sucursal, punto = self._get_sucursal_punto()
        cambios = []
        for tipo, spin in self._correlativo_spins.items():
            valor = spin.value()
            if valor != self._original_correlativos.get(tipo, 0):
                cambios.append((tipo, valor))
        if cambios:
            if (
                QMessageBox.warning(
                    self,
                    "Advertencia",
                    "Modificar el correlativo puede generar inconsistencias con Hacienda. ¿Desea continuar?",
                    QMessageBox.Yes | QMessageBox.No,
                )
                != QMessageBox.Yes
            ):
                return
            for tipo, valor in cambios:
                self.db.set_dte_correlativo(tipo, sucursal, punto, valor)
        super().accept()


class DTEConfigDialog(QDialog):
    def __init__(
        self,
        dte_api=None,
        fe_config=None,
        env_config=None,
        parent=None,
        datos_negocio=None,
        db=None,
    ):
        super().__init__(parent)
        self.db = db or DB()
        self.setWindowTitle("Configuración de Facturación Electrónica")
        layout = QVBoxLayout()
        form = QFormLayout()
        self.dte_nit = QLineEdit()
        self.dte_pass = QLineEdit()
        self.dte_pass.setEchoMode(QLineEdit.Password)
        self.cert_path = QLineEdit()
        self.cert_path.setReadOnly(True)
        self.cert_btn = QPushButton("Seleccionar")
        self._cert_file_name: str | None = None
        self.api_user = QLineEdit()
        self.api_pwd = QLineEdit()
        self.api_pwd.setEchoMode(QLineEdit.Password)
        self.dte_activo = QCheckBox("Certificado activo")
        self.dte_activo.setChecked(True)
        self.tipo_contribuyente = QComboBox()
        self.tipo_contribuyente.addItems(TIPO_CONTRIBUYENTE_OPCIONES)
        self.tipo_contribuyente.currentTextChanged.connect(
            lambda *_: self._update_razon_social_state()
        )
        self.razon_social = QLineEdit()
        self.razon_social.setPlaceholderText("Opcional para persona natural")
        self.prefijo_control = QLineEdit("DTE-01-S001P001")
        self.modo_transmision = QComboBox()
        self.modo_transmision.addItems(["1 - Normal", "2 - Contingencia"])
        self.config_contingencia_btn = QPushButton("Configurar contingencia…")
        self.config_contingencia_btn.setVisible(False)
        self.config_contingencia_btn.clicked.connect(self._open_contingencia_config)
        self._contingencia_tipo: int | None = None
        self._contingencia_motivo: str = ""
        self.ambiente_hacienda = QComboBox()
        self.ambiente_hacienda.addItems(["00 - Pruebas", "01 - Producción"])
        self.token_hacienda = QLineEdit()
        self._token_pruebas = ""
        self._token_produccion = ""
        self._ambiente_actual = "pruebas"
        self.token_btn = QPushButton("Obtener")
        self.endpoint_hacienda = QLineEdit()
        self.auth_url = QLineEdit()
        self.recepcion_url = QLineEdit()
        self.evento_contingencia_url = QLineEdit()
        self.envio_automatico = QCheckBox("Activar envío automático a Hacienda")
        self.adjuntar_json_correo = QCheckBox("Adjuntar JSON firmado en correo al cliente")
        self.incluir_sello_pdf = QCheckBox("Incluir sello de recepción en el PDF (si existe)")
        self.guardar_respuesta_bd = QCheckBox("Guardar respuesta de Hacienda en base de datos")
        form.addRow("NIT certificación:", self.dte_nit)
        form.addRow("Contraseña firma:", self.dte_pass)
        cert_widget = QWidget()
        cert_layout = QHBoxLayout(cert_widget)
        cert_layout.setContentsMargins(0, 0, 0, 0)
        cert_layout.addWidget(self.cert_path)
        cert_layout.addWidget(self.cert_btn)
        form.addRow("Archivo certificado (.crt):", cert_widget)
        form.addRow("NIT usuario API:", self.api_user)
        form.addRow("Contraseña API:", self.api_pwd)
        form.addRow(self.dte_activo)
        form.addRow("Tipo contribuyente:", self.tipo_contribuyente)
        form.addRow("Razón social:", self.razon_social)
        form.addRow("Prefijo número control:", self.prefijo_control)
        modo_widget = QWidget()
        modo_layout = QHBoxLayout(modo_widget)
        modo_layout.setContentsMargins(0, 0, 0, 0)
        modo_layout.addWidget(self.modo_transmision)
        modo_layout.addWidget(self.config_contingencia_btn)
        form.addRow("Modo transmisión por defecto:", modo_widget)
        self.contingencia_summary = QLabel(
            "Configura el tipo de contingencia antes de guardar."
        )
        self.contingencia_summary.setWordWrap(True)
        self.contingencia_summary.setVisible(False)
        self.contingencia_summary.setStyleSheet("color: #57606a;")
        form.addRow("", self.contingencia_summary)
        form.addRow("Ambiente:", self.ambiente_hacienda)
        token_widget = QWidget()
        token_layout = QHBoxLayout(token_widget)
        token_layout.setContentsMargins(0, 0, 0, 0)
        token_layout.addWidget(self.token_hacienda)
        token_layout.addWidget(self.token_btn)
        form.addRow("Token autenticación:", token_widget)
        form.addRow("Endpoint API:", self.endpoint_hacienda)
        form.addRow("URL autenticación:", self.auth_url)
        form.addRow("URL recepción:", self.recepcion_url)
        form.addRow("URL evento contingencia:", self.evento_contingencia_url)
        form.addRow(self.envio_automatico)
        form.addRow(self.adjuntar_json_correo)
        form.addRow(self.incluir_sello_pdf)
        form.addRow(self.guardar_respuesta_bd)
        layout.addLayout(form)

        self.correlativos_btn = QPushButton("Configuración de correlativo")
        self.limpiar_facturas_btn = QPushButton("Limpiar facturas")
        self.limpiar_facturas_btn.setToolTip(
            "Borra todas las ventas, registros DTE y archivos generados."
        )
        layout.addWidget(self.correlativos_btn)
        layout.addWidget(self.limpiar_facturas_btn)

        btns = QHBoxLayout()
        self.btn_guardar = QPushButton("Guardar")
        self.btn_restaurar = QPushButton("Restaurar")
        self.btn_cancelar = QPushButton("Cancelar")
        btns.addWidget(self.btn_guardar)
        btns.addWidget(self.btn_restaurar)
        btns.addWidget(self.btn_cancelar)
        layout.addLayout(btns)
        self.setLayout(layout)
        self._datos_negocio_inicial = datos_negocio or {}
        self._negocio_updates: dict[str, str] = {}
        self.btn_guardar.clicked.connect(self.accept)
        self.btn_cancelar.clicked.connect(self.reject)
        self.btn_restaurar.clicked.connect(self._restore_defaults)
        self.btn_restaurar.clicked.connect(self._set_default_urls)
        self.token_btn.clicked.connect(self._fetch_token)
        self.cert_btn.clicked.connect(self._select_cert)
        self.ambiente_hacienda.currentIndexChanged.connect(self._handle_ambiente_changed)
        self.ambiente_hacienda.currentTextChanged.connect(self._set_default_urls)
        self.endpoint_hacienda.textChanged.connect(self._set_default_urls)
        self.correlativos_btn.clicked.connect(self._open_correlativos)
        self.limpiar_facturas_btn.clicked.connect(self._confirm_clear_invoices)
        self.modo_transmision.currentIndexChanged.connect(
            self._update_contingencia_visibility
        )
        self._ambiente_actual = self._current_env_key()
        if dte_api or fe_config or env_config:
            self.set_data(dte_api or {}, fe_config or {}, env_config or {})
        else:
            self._set_default_urls()
            self._update_contingencia_visibility()
            self._apply_negocio_defaults()
        self._update_razon_social_state()

    def _confirm_clear_invoices(self):
        reply = QMessageBox.question(
            self,
            "Limpiar facturas",
            (
                "Esta acción elimina todas las ventas y sus facturas del inventario, "
                "incluyendo los DTE guardados (PDF/JSON). No afectará productos, "
                "clientes ni configuraciones. ¿Deseas continuar?"
            ),
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        warning_box = QMessageBox(self)
        warning_box.setWindowTitle("Advertencia crítica")
        warning_box.setIcon(QMessageBox.Warning)
        warning_box.setText(
            "<span style='color:#b91c1c; font-weight:700;'>"
            "Esta función está creada solo para el ambiente de pruebas."
            "</span>"
        )
        warning_box.setInformativeText(
            "Proceda con extrema precaución: elimine facturas solo si necesita "
            "terminar pruebas y restaurar el sistema antes de producción."
        )
        btn_continuar = warning_box.addButton("Continuar", QMessageBox.YesRole)
        btn_cancelar = warning_box.addButton("Cancelar", QMessageBox.NoRole)
        warning_box.setDefaultButton(btn_cancelar)
        warning_box.exec_()
        if warning_box.clickedButton() is not btn_continuar:
            return

        final_box = QMessageBox(self)
        final_box.setWindowTitle("Confirmación final")
        final_box.setIcon(QMessageBox.Critical)
        final_box.setText("¿Está totalmente seguro de que desea continuar?")
        btn_si = final_box.addButton("Sí", QMessageBox.YesRole)
        btn_no = final_box.addButton("No", QMessageBox.NoRole)
        try:
            btn_no.setStyleSheet("color: #16a34a; font-weight: 700;")
            btn_si.setStyleSheet("color: #b91c1c; font-weight: 700;")
        except Exception:
            pass
        final_box.setDefaultButton(btn_no)
        final_box.exec_()
        if final_box.clickedButton() is not btn_si:
            return
        try:
            self._clear_sales_and_invoices()
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Error al limpiar",
                f"No se pudieron limpiar las facturas: {exc}",
            )
            return
        QMessageBox.information(
            self,
            "Inventario limpio",
            "Se eliminaron las ventas, facturas y archivos DTE almacenados.",
        )
        self._refresh_parent_views()

    def _clear_sales_and_invoices(self):
        self.db.limpiar_ventas_y_dtes()
        invoice_dirs = [
            FACTURAS_CONSUMIDOR_FINAL_DIR,
            FACTURAS_CREDITO_FISCAL_DIR,
            TICKETS_OUTPUT_DIR,
            NOTAS_DEBITO_DIR,
            NOTAS_CREDITO_DIR,
            NOTAS_REMISION_DIR,
            FACTURAS_ARCHIVE_CF_DIR,
            FACTURAS_ARCHIVE_CREDITO_DIR,
            DTES_DIR,
            DTE_FALLIDOS_DIR,
            DTES_PENDIENTES_DIR,
            DTE_FIRMADO_DIR,
            RETENCIONES_DIR,
            ensure_user_dir("dtes", "retenciones"),
            ensure_user_dir("dtes_sujeto_excluido"),
        ]
        for path in invoice_dirs:
            self._empty_directory(path)

    def _empty_directory(self, path: str | os.PathLike) -> None:
        folder = Path(path)
        folder.mkdir(parents=True, exist_ok=True)
        try:
            for child in folder.iterdir():
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
        except FileNotFoundError:
            return
        except Exception:
            logger.exception("No se pudo limpiar el directorio %s", path)
            raise

    def _refresh_parent_views(self) -> None:
        parent = self.parent()
        if parent is None:
            return
        try:
            def _do_refresh():
                try:
                    if hasattr(parent, "actualizar_estado_global"):
                        parent.actualizar_estado_global()
                        return
                    if hasattr(parent, "manager"):
                        parent.manager.refresh_data()
                        if hasattr(parent, "filter_products"):
                            parent.filter_products()
                    fact_tab = getattr(parent, "facturacion_tab", None)
                    if fact_tab is not None and hasattr(fact_tab, "refresh_and_reload"):
                        fact_tab.refresh_and_reload()
                    sales_tab = getattr(parent, "sales_tab", None)
                    if sales_tab is not None and hasattr(sales_tab, "load_sales"):
                        sales_tab.load_sales()
                    if hasattr(parent, "_actualizar_inventario_actual"):
                        parent._actualizar_inventario_actual()
                except Exception:
                    logger.exception("No se pudo refrescar vistas tras limpiar facturas")

            QTimer.singleShot(1000, _do_refresh)
        except Exception:
            logger.exception("No se pudo programar refresco tras limpiar facturas")

    def _open_correlativos(self):
        dlg = DTECorrelativoConfigDialog(
            db=self.db, prefijo=self.prefijo_control.text(), parent=self
        )
        dlg.exec_()

    def set_data(self, dte_api, fe_config, env_config):
        auth_conf = env_config.get("auth", {})
        self.dte_nit.setText(fe_config.get("nit", ""))
        frase = fe_config.get("passwordPri", "")
        if frase:
            try:
                self.dte_pass.setText(base64.b64decode(frase).decode())
            except Exception:
                self.dte_pass.setText("")
        self.api_user.setText(
            auth_conf.get("nitUsuario")
            or auth_conf.get("user")
            or auth_conf.get("nit")
            or ""
        )
        pwd_api = auth_conf.get("pwd") or auth_conf.get("password") or ""
        if pwd_api:
            try:
                self.api_pwd.setText(base64.b64decode(pwd_api).decode())
            except Exception:
                self.api_pwd.setText(pwd_api)
        self.dte_activo.setChecked(fe_config.get("activo", True))
        tipo = dte_api.get("tipo_contribuyente")
        if not tipo:
            tipo = self._datos_negocio_inicial.get("tipoContribuyente")
        if not tipo:
            tipo = self._datos_negocio_inicial.get("tipo_contribuyente")
        tipo = _normalize_tipo_contribuyente(tipo)
        self.tipo_contribuyente.setCurrentText(tipo)
        self.prefijo_control.setText(dte_api.get("prefijo_control", "DTE-01-S001P001"))
        with QSignalBlocker(self.modo_transmision):
            self.modo_transmision.setCurrentText(
                dte_api.get("modo_transmision", "1 - Normal")
            )
        self._contingencia_tipo = self._parse_tipo_contingencia(
            dte_api.get("tipo_contingencia")
        )
        self._contingencia_motivo = (dte_api.get("motivo_contin") or "").strip()
        self._update_contingencia_visibility()
        ambiente = str(dte_api.get("ambiente", "00")).lower()
        with QSignalBlocker(self.ambiente_hacienda):
            if ambiente in {"01", "1", "produccion", "producción"}:
                self.ambiente_hacienda.setCurrentIndex(1)
            else:
                self.ambiente_hacienda.setCurrentIndex(0)
        self._ambiente_actual = self._current_env_key()
        self._token_pruebas = str(dte_api.get("token_pruebas") or "")
        self._token_produccion = str(dte_api.get("token_produccion") or "")
        self._apply_token_for_env(self._ambiente_actual)
        self.endpoint_hacienda.setText(dte_api.get("url", ""))
        self.auth_url.setText(env_config.get("auth_url", ""))
        self.recepcion_url.setText(env_config.get("recepcion_url", ""))
        self.evento_contingencia_url.setText(
            env_config.get("evento_contingencia_url", "")
        )
        if (
            not self.endpoint_hacienda.text()
            or not self.auth_url.text()
            or not self.recepcion_url.text()
            or not self.evento_contingencia_url.text()
        ):
            self._set_default_urls()
        self.envio_automatico.setChecked(dte_api.get("envio_automatico", False))
        self.adjuntar_json_correo.setChecked(dte_api.get("adjuntar_json_correo", False))
        self.incluir_sello_pdf.setChecked(dte_api.get("incluir_sello_pdf", False))
        self.guardar_respuesta_bd.setChecked(dte_api.get("guardar_respuesta", False))
        razon = dte_api.get("razonSocial")
        if not razon:
            razon = self._datos_negocio_inicial.get("razonSocial", "")
        self.razon_social.setText(razon or "")
        self._update_razon_social_state()
        nit = fe_config.get("nit", "")
        self.cert_path.clear()
        self.cert_path.setToolTip("")
        cert_dir = resolve_signer_cert_dir()
        stored_name = fe_config.get("cert_file")
        self._cert_file_name = stored_name if stored_name else None
        candidate: Path | None = None
        if stored_name:
            candidate = cert_dir / stored_name
            if not candidate.is_file():
                candidate = None
        if candidate is None and nit:
            canonical = cert_dir / f"{nit}.crt"
            if canonical.is_file():
                candidate = canonical
                if not self._cert_file_name:
                    self._cert_file_name = canonical.name
        if candidate is not None:
            self.cert_path.setText(candidate.name)
            self.cert_path.setToolTip(str(candidate))

    def _apply_negocio_defaults(self):
        tipo = self._datos_negocio_inicial.get("tipoContribuyente")
        if not tipo:
            tipo = self._datos_negocio_inicial.get("tipo_contribuyente")
        self.tipo_contribuyente.setCurrentText(_normalize_tipo_contribuyente(tipo))
        razon = self._datos_negocio_inicial.get("razonSocial", "")
        self.razon_social.setText(razon or "")

    def _update_razon_social_state(self):
        is_persona_juridica = (
            self.tipo_contribuyente.currentText() == "Persona Jurídica"
        )
        if is_persona_juridica:
            self.razon_social.setPlaceholderText("Obligatoria para persona jurídica")
        else:
            self.razon_social.setPlaceholderText("Opcional para persona natural")

    def _restore_defaults(self):
        """Restaurar valores por defecto de URLs y token."""
        self.token_hacienda.clear()
        self.endpoint_hacienda.clear()
        self.auth_url.clear()
        self.recepcion_url.clear()
        self.evento_contingencia_url.clear()

    def _set_default_urls(self):
        base = self.endpoint_hacienda.text().strip()
        if not base:
            if "Producción" in self.ambiente_hacienda.currentText():
                base = "https://api.dtes.mh.gob.sv"
            else:
                base = "https://apitest.dtes.mh.gob.sv"
            self.endpoint_hacienda.setText(base)
        base = base.rstrip("/")
        self.auth_url.setText(f"{base}/seguridad/auth")
        self.recepcion_url.setText(f"{base}/fesv/recepciondte")
        self.evento_contingencia_url.setText(f"{base}/fesv/contingencia")

    def _current_env_key(self) -> str:
        return "produccion" if self.ambiente_hacienda.currentIndex() == 1 else "pruebas"

    def _store_current_token(self) -> None:
        value = self.token_hacienda.text()
        if self._ambiente_actual == "produccion":
            self._token_produccion = value
        else:
            self._token_pruebas = value

    def _apply_token_for_env(self, env: str) -> None:
        token = self._token_produccion if env == "produccion" else self._token_pruebas
        self.token_hacienda.setText(token or "")

    def _handle_ambiente_changed(self, index: int) -> None:
        self._store_current_token()
        self._ambiente_actual = self._current_env_key()
        self._apply_token_for_env(self._ambiente_actual)

    def _fetch_token(self):
        nit_default = self.api_user.text().strip()
        pwd_default = self.api_pwd.text().strip()
        nit, pwd = prompt_auth_credentials(self, nit_default, pwd_default)
        if nit is None:
            return
        if not nit or not pwd:
            QMessageBox.warning(self, "Datos faltantes", "Debe ingresar NIT y contraseña.")
            return
        url = self.auth_url.text().strip()
        if not url:
            self._set_default_urls()
            url = self.auth_url.text().strip()
        try:
            resp = requests.post(url, data={"user": nit, "pwd": pwd}, timeout=20)
            status_code = getattr(resp, "status_code", "N/A")
            resp_text = getattr(resp, "text", "")
            print(status_code)
            print(resp_text)
            if isinstance(status_code, int) and status_code >= 400:
                logger.error("Respuesta de Hacienda %s: %s", status_code, resp_text)
            else:
                logger.debug("Respuesta de Hacienda %s: %s", status_code, resp_text)
            resp.raise_for_status()
            info = resp.json()
            if info.get("status") == "OK":
                token = info.get("body", {}).get("token")
                if token:
                    self.token_hacienda.setText(token)
                    try:
                        QApplication.clipboard().setText(token)
                    except Exception:
                        pass
                    self.api_user.setText(nit)
                    self.api_pwd.setText(pwd)
                    return
                QMessageBox.warning(self, "Error", "Respuesta sin token válido.")
            else:
                msg = info.get("message") or info.get("error") or resp.text
                QMessageBox.warning(self, "Error", msg)
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"No se pudo obtener token: {exc}")

    def _select_cert(self):
        nit = self.dte_nit.text().strip()
        if not nit:
            QMessageBox.warning(self, "NIT requerido", "Ingrese el NIT antes de seleccionar el certificado.")
            return
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Seleccionar certificado", "", "Certificados (*.crt)"
        )
        if not file_path:
            return
        source_path = Path(file_path).expanduser().resolve()
        try:
            dest = copy_certificate_to_signer_dir(source_path, nit)
            if not dest.exists():
                QMessageBox.critical(
                    self,
                    "Error",
                    "No se pudo copiar el certificado al directorio configurado.",
                )
                return
            jws.set_cert_upload_dir(str(dest.parent))
            display_name = source_path.name or dest.name
            self.cert_path.clear()
            self.cert_path.setText(display_name)
            self.cert_path.setToolTip(str(dest))
            self._cert_file_name = dest.name
            QMessageBox.information(
                self,
                "Éxito",
                f"Certificado '{display_name}' copiado correctamente.",
            )

        except Exception as exc:
            QMessageBox.critical(self, "Error", f"No se pudo copiar el certificado: {exc}")

    def get_data(self):
        self._store_current_token()
        self._ambiente_actual = self._current_env_key()
        token_pruebas = self._token_pruebas
        token_produccion = self._token_produccion
        dte_api = {
            "url": self.endpoint_hacienda.text().strip(),
            "ambiente": self.ambiente_hacienda.currentText().split(" - ", 1)[0],
            "prefijo_control": self.prefijo_control.text(),
            "modo_transmision": self.modo_transmision.currentText(),
            "envio_automatico": self.envio_automatico.isChecked(),
            "adjuntar_json_correo": self.adjuntar_json_correo.isChecked(),
            "incluir_sello_pdf": self.incluir_sello_pdf.isChecked(),
            "guardar_respuesta": self.guardar_respuesta_bd.isChecked(),
            "tipo_contribuyente": self.tipo_contribuyente.currentText(),
        }
        razon_social = self.razon_social.text().strip()
        tipo_contribuyente = dte_api["tipo_contribuyente"]
        if tipo_contribuyente == "Persona Jurídica" and not razon_social:
            raise ValueError("La razón social es obligatoria para personas jurídicas")
        if razon_social:
            dte_api["razonSocial"] = razon_social
        if token_pruebas is not None and token_pruebas != "":
            dte_api["token_pruebas"] = token_pruebas
        if token_produccion is not None and token_produccion != "":
            dte_api["token_produccion"] = token_produccion
        fe_config = {
            "nit": self.dte_nit.text(),
            "passwordPri": base64.b64encode(self.dte_pass.text().encode()).decode() if self.dte_pass.text() else "",
            "activo": self.dte_activo.isChecked(),
        }
        if self._cert_file_name:
            fe_config["cert_file"] = self._cert_file_name
        urls = {
            "auth_url": self.auth_url.text().strip(),
            "auth": {
                "nitUsuario": self.api_user.text().strip(),
                "pwd": base64.b64encode(self.api_pwd.text().encode()).decode()
                if self.api_pwd.text()
                else "",
            },
        }
        recep = self.recepcion_url.text().strip()
        if recep:
            urls["recepcion_url"] = recep
        evento = self.evento_contingencia_url.text().strip()
        if evento:
            urls["evento_contingencia_url"] = evento
        if self._contingencia_tipo is not None:
            dte_api["tipo_contingencia"] = int(self._contingencia_tipo)
        else:
            dte_api["tipo_contingencia"] = None
        dte_api["motivo_contin"] = self._contingencia_motivo
        self._negocio_updates = {
            "razonSocial": razon_social,
            "tipoContribuyente": tipo_contribuyente,
        }
        return dte_api, fe_config, urls

    def get_negocio_updates(self) -> dict[str, str]:
        return dict(self._negocio_updates)

    def _parse_tipo_contingencia(self, value) -> int | None:
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _is_contingencia_selected(self) -> bool:
        text = self.modo_transmision.currentText().lower()
        return "contingencia" in text or self.modo_transmision.currentIndex() == 1

    def _update_contingencia_visibility(self):
        is_contingencia = self._is_contingencia_selected()
        self.config_contingencia_btn.setVisible(is_contingencia)
        self.contingencia_summary.setVisible(is_contingencia)
        if is_contingencia:
            self._update_contingencia_summary()

    def _update_contingencia_summary(self):
        if self._contingencia_tipo is None:
            self.contingencia_summary.setText(
                "Configura el tipo de contingencia antes de guardar."
            )
            self.contingencia_summary.setStyleSheet("color: #c0392b;")
            return
        descripcion = CONTINGENCIA.get(self._contingencia_tipo)
        texto = f"Tipo {self._contingencia_tipo}"
        if descripcion:
            texto += f" – {descripcion}"
        motivo = self._contingencia_motivo.strip()
        if self._contingencia_tipo == 5:
            if motivo:
                texto += f" | Motivo: {motivo}"
                self.contingencia_summary.setStyleSheet("color: #2d3436;")
            else:
                texto += " | Motivo requerido para el tipo 5."
                self.contingencia_summary.setStyleSheet("color: #c0392b;")
        elif motivo:
            texto += f" | Motivo: {motivo}"
            self.contingencia_summary.setStyleSheet("color: #2d3436;")
        else:
            self.contingencia_summary.setStyleSheet("color: #2d3436;")
        self.contingencia_summary.setText(texto)

    def _open_contingencia_config(self):
        dialog = ContingenciaConfigDialog(
            tipo=self._contingencia_tipo,
            motivo=self._contingencia_motivo,
            parent=self,
        )
        if dialog.exec_():
            data = dialog.get_config()
            self._contingencia_tipo = data["tipo"]
            self._contingencia_motivo = data["motivo"]
            self._update_contingencia_summary()

    def validate_before_save(self) -> bool:
        if (
            self.tipo_contribuyente.currentText() == "Persona Jurídica"
            and not self.razon_social.text().strip()
        ):
            QMessageBox.warning(
                self,
                "Validación",
                "La razón social es obligatoria para personas jurídicas.",
            )
            return False
        if self._is_contingencia_selected():
            if self._contingencia_tipo is None:
                QMessageBox.warning(
                    self,
                    "Configuración incompleta",
                    "Selecciona el tipo de contingencia antes de guardar.",
                )
                return False
            if self._contingencia_tipo == 5 and not self._contingencia_motivo.strip():
                QMessageBox.warning(
                    self,
                    "Configuración incompleta",
                    "Ingresa el motivo de contingencia requerido para el tipo 5.",
                )
                return False
        return True

    def accept(self):
        if not self.validate_before_save():
            return
        super().accept()


class ContingenciaConfigDialog(QDialog):
    def __init__(
        self,
        tipo: int | None = None,
        motivo: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Configurar contingencia")

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.tipo_combo = QComboBox(self)
        self.tipo_combo.addItem("Selecciona un tipo…", None)
        for codigo, descripcion in sorted(CONTINGENCIA.items()):
            self.tipo_combo.addItem(f"{codigo} - {descripcion}", codigo)
        if tipo in CONTINGENCIA:
            idx = self.tipo_combo.findData(tipo)
            if idx >= 0:
                self.tipo_combo.setCurrentIndex(idx)

        self.motivo_edit = QTextEdit(self)
        self.motivo_edit.setPlaceholderText(
            "Describe el motivo si aplica. Obligatorio para el tipo 5."
        )
        self.motivo_edit.setFixedHeight(80)
        self.motivo_edit.setPlainText(motivo or "")

        form.addRow("Tipo de contingencia (CAT-005):", self.tipo_combo)
        form.addRow("Motivo de contingencia:", self.motivo_edit)

        self.warning_label = QLabel("", self)
        self.warning_label.setWordWrap(True)
        self.warning_label.setStyleSheet("color: #c0392b;")
        form.addRow("", self.warning_label)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self._handle_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.tipo_combo.currentIndexChanged.connect(self._handle_tipo_changed)
        self._handle_tipo_changed(self.tipo_combo.currentIndex())
        self._config: dict[str, object] | None = None

    def _handle_tipo_changed(self, index: int) -> None:
        tipo = self.tipo_combo.itemData(index)
        if tipo == 5:
            self.warning_label.setText(
                "El motivo es obligatorio para el tipo de contingencia 5 (otros)."
            )
        else:
            self.warning_label.clear()

    def _handle_accept(self) -> None:
        tipo = self.tipo_combo.currentData()
        if tipo is None:
            QMessageBox.warning(
                self,
                "Datos incompletos",
                "Selecciona un tipo de contingencia (CAT-005).",
            )
            return
        motivo = self.motivo_edit.toPlainText().strip()
        if tipo == 5 and not motivo:
            QMessageBox.warning(
                self,
                "Datos incompletos",
                "El motivo es obligatorio para el tipo de contingencia 5.",
            )
            return
        self._config = {"tipo": int(tipo), "motivo": motivo}
        self.accept()

    def get_config(self) -> dict[str, object]:
        return self._config or {"tipo": None, "motivo": ""}


# Nuevo flujo manual para creación de CRE desde botón "Retención de IVA"
class RetencionIVADialog(QDialog):
    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.db = manager.db if manager else None
        self.setWindowTitle("Retención de IVA (CRE)")
        self.resize(520, 360)
        layout = QVBoxLayout(self)

        file_row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setReadOnly(True)
        select_btn = QPushButton("Seleccionar JSON…")
        select_btn.clicked.connect(self._seleccionar_json)
        file_row.addWidget(self.path_edit)
        file_row.addWidget(select_btn)
        layout.addLayout(file_row)

        self.info_labels: dict[str, QLabel] = {}

        def add_info(label: str) -> QLabel:
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
            value_lbl = QLabel("-")
            value_lbl.setWordWrap(True)
            row.addWidget(value_lbl, 1)
            layout.addLayout(row)
            self.info_labels[label] = value_lbl
            return value_lbl

        add_info("Número control origen:")
        add_info("Código generación origen:")
        add_info("Emisor:")
        add_info("Receptor:")
        add_info("Monto sujeto retención:")
        add_info("IVA retenido:")
        add_info("Fecha emisión:")

        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self)
        btn_box.accepted.connect(self._handle_accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

        self._payload: dict[str, Any] | None = None
        self._file_path: str | None = None

    def _seleccionar_json(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar DTE (JSON)",
            "",
            "Archivos JSON (*.json);;Todos los archivos (*)",
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"No se pudo leer el JSON:\n{exc}")
            return
        # Soporta JSON plano y JSON envuelto en {"dteJson": {...}}
        if isinstance(raw, dict) and "dteJson" in raw:
            data = raw.get("dteJson")
        else:
            data = raw
        ident = data.get("identificacion") or data.get("identificador") or {}
        tipo = str(ident.get("tipoDte") or "").zfill(2)
        if tipo != "03":
            QMessageBox.warning(
                self,
                "DTE inválido",
                "El archivo seleccionado no es un Crédito Fiscal (tipo DTE 03).",
            )
            return
        self._payload = data
        self._file_path = path
        self.path_edit.setText(path)
        self._poblar_info(data)

    def _poblar_info(self, data: Mapping[str, Any]) -> None:
        ident = data.get("identificacion") or {}
        emisor = data.get("emisor") or {}
        receptor = data.get("receptor") or {}
        resumen = data.get("resumen") or {}
        numero_control = ident.get("numeroControl") or ""
        codigo_generacion = ident.get("codigoGeneracion") or ""
        fec = ident.get("fecEmi") or ident.get("fechaEmision") or ""
        base = resumen.get("totalSujetoRetencion") or resumen.get("totalGravada") or 0
        retenido = resumen.get("totalIVAretenido") or resumen.get("ivaRete1") or 0

        def _fmt(val):
            try:
                return f"{float(val):.2f}"
            except Exception:
                return str(val or "")

        def _fmt_party(info: Mapping[str, Any]) -> str:
            nombre = info.get("nombre") or info.get("nombreComercial") or ""
            nit = info.get("nit") or info.get("numDocumento") or ""
            return f"{nombre} (NIT: {nit})" if nombre or nit else "-"

        setters = {
            "Número control origen:": numero_control or "-",
            "Código generación origen:": codigo_generacion or "-",
            "Emisor:": _fmt_party(emisor),
            "Receptor:": _fmt_party(receptor),
            "Monto sujeto retención:": _fmt(base),
            "IVA retenido:": _fmt(retenido),
            "Fecha emisión:": str(fec or "-"),
        }
        for label, text in setters.items():
            if label in self.info_labels:
                self.info_labels[label].setText(text)

    def _handle_accept(self):
        if not self._payload or not self.db:
            QMessageBox.warning(self, "Retención de IVA", "Seleccione primero un DTE válido.")
            return
        ident = self._payload.get("identificacion") or {}
        resumen = self._payload.get("resumen") or {}
        fecha_emision = str(ident.get("fecEmi") or date.today().isoformat())
        total = resumen.get("totalPagar") or resumen.get("montoTotalOperacion") or 0
        try:
            total_val = float(total)
        except Exception:
            total_val = 0.0
        modo_raw = None
        getter = getattr(getattr(self, "manager", None), "get_modo_transmision_actual", None)
        if callable(getter):
            try:
                modo_raw = getter()
            except Exception:
                modo_raw = None
        modo_str = str(modo_raw or "").strip().lower()
        modo_contingencia = modo_str in {"contingencia", "2", "02"}

        if modo_contingencia:
            QMessageBox.warning(
                self,
                "Retención de IVA",
                "No se pueden emitir comprobantes de retención en modo contingencia. "
                "Cambia el modo de transmisión a Normal e inténtalo de nuevo (Hacienda no lo permite).",
            )
            return

        extra = {
            "retencion_manual": True,
            "origen": "RETENCION_IVA_MANUAL",
            "cr_origen": {
                "codigo_generacion": ident.get("codigoGeneracion"),
                "numero_control": ident.get("numeroControl"),
            },
        }
        try:
            # Venta “soporte” marcada para identificarla en reportes si se requiere excluir.
            venta_id = self.db.add_venta(
                fecha_emision,
                total_val,
                estado="Pagada",
                extra=extra,
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Retención de IVA",
                f"No se pudo registrar la venta asociada al CRE:\n{exc}",
            )
            return

        try:
            service = RetencionCRService(self.db)
            with loading_dialog(self, "Generando comprobante de retención…"):
                payload = service.prepare_cr(
                    venta_id,
                    factura=self._payload,
                    modo_contingencia=modo_contingencia,
                )
            with loading_dialog(self, "Enviando comprobante de retención…"):
                resp = service.send_cr(venta_id)
        except Exception as exc:
            logger.exception("Error en flujo manual de CRE", exc_info=exc)
            QMessageBox.critical(
                self,
                "Retención de IVA",
                f"No se pudo generar o enviar el CRE:\n{exc}",
            )
            return

        estado = str(resp.get("estado") or "").strip()
        sello = (
            resp.get("sello")
            or resp.get("selloRecibido")
            or resp.get("selloRecepcion")
            or ""
        )
        partes = [f"Estado: {estado or 'Desconocido'}"]
        if sello:
            partes.append(f"Sello: {sello}")
        QMessageBox.information(
            self,
            "Retención de IVA",
            "\n".join(partes),
        )
        self.accept()

class TrabajadorDialog(QDialog):
    def __init__(self, trabajador=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Trabajador")
        layout = QVBoxLayout()
        form = QFormLayout()
        self.codigo = QLineEdit()
        self.nombre = QLineEdit()
        self.dui = QLineEdit()
        self.dui.setValidator(
            QRegularExpressionValidator(QRegularExpression(r"^\d{0,9}$"))
        )
        self.dui.setMaxLength(9)
        self.nit = QLineEdit()
        self.fecha_nacimiento = QDateEdit(QDate.currentDate())
        self.fecha_nacimiento.setCalendarPopup(True)
        self.cargo = QLineEdit()
        self.area = QLineEdit()
        self.fecha_contratacion = QDateEdit(QDate.currentDate())
        self.fecha_contratacion.setCalendarPopup(True)
        self.telefono = QLineEdit()
        self.email = QLineEdit()
        self.direccion = QLineEdit()
        self.salario_base = QDoubleSpinBox()
        self.salario_base.setMaximum(1000000)
        self.salario_base.setDecimals(2)
        self.comentarios = QLineEdit()
        self.es_vendedor = QCheckBox("¿Es vendedor?")

        form.addRow("Código:", self.codigo)
        form.addRow("Nombre completo:", self.nombre)
        form.addRow("DUI:", self.dui)
        form.addRow("NIT:", self.nit)
        form.addRow("Fecha de nacimiento:", self.fecha_nacimiento)
        form.addRow("Cargo o puesto:", self.cargo)
        form.addRow("Área / Departamento:", self.area)
        form.addRow("Fecha de contratación:", self.fecha_contratacion)
        form.addRow("Teléfono:", self.telefono)
        form.addRow("Correo electrónico:", self.email)
        form.addRow("Dirección:", self.direccion)
        form.addRow("Salario base:", self.salario_base)
        form.addRow("Comentarios:", self.comentarios)
        form.addRow(self.es_vendedor)
        layout.addLayout(form)

        btns = QHBoxLayout()
        self.btn_ok = QPushButton("Guardar")
        self.btn_cancel = QPushButton("Cancelar")
        btns.addWidget(self.btn_ok)
        btns.addWidget(self.btn_cancel)
        layout.addLayout(btns)
        self.setLayout(layout)

        self.btn_ok.clicked.connect(self._validar_y_accept)
        self.btn_cancel.clicked.connect(self.reject)

        self._trabajador_id = trabajador.get("id") if trabajador else None

        if trabajador:
            self.codigo.setText(trabajador.get("codigo", ""))
            self.nombre.setText(trabajador.get("nombre", ""))
            self.dui.setText(trabajador.get("dui", ""))
            self.nit.setText(trabajador.get("nit", ""))
            if trabajador.get("fecha_nacimiento"):
                self.fecha_nacimiento.setDate(QDate.fromString(trabajador["fecha_nacimiento"], "yyyy-MM-dd"))
            self.cargo.setText(trabajador.get("cargo", ""))
            self.area.setText(trabajador.get("area", ""))
            if trabajador.get("fecha_contratacion"):
                self.fecha_contratacion.setDate(QDate.fromString(trabajador["fecha_contratacion"], "yyyy-MM-dd"))
            self.telefono.setText(trabajador.get("telefono", ""))
            self.email.setText(trabajador.get("email", ""))
            self.direccion.setText(trabajador.get("direccion", ""))
            self.salario_base.setValue(trabajador.get("salario_base", 0) or 0)
            self.comentarios.setText(trabajador.get("comentarios", ""))
            self.es_vendedor.setChecked(trabajador.get("es_vendedor", 0) == 1)

    def _validar_y_accept(self):
        codigo = self.codigo.text().strip()
        nombre = self.nombre.text().strip()
        nit = self.nit.text().strip()
        email = self.email.text().strip()

        if nit and not validar_nit(nit):
            QMessageBox.warning(
                self,
                "Validación",
                "El NIT ingresado no es válido; debe tener 9 o 14 dígitos.",
            )
            return
        if email and not validar_email(email):
            QMessageBox.warning(self, "Validación", "El correo electrónico ingresado no es válido.")
            return

        if codigo:
            db = getattr(getattr(self.parent(), "manager", None), "db", None)
            if db:
                for t in db.get_trabajadores():
                    if t.get("codigo") == codigo and t.get("id") != self._trabajador_id:
                        QMessageBox.warning(self, "Validación", "El código ya está registrado.")
                        return

        self.accept()

    def get_data(self):
        return {
            "codigo": self.codigo.text().strip(),
            "nombre": self.nombre.text().strip(),
            "dui": self.dui.text().strip(),
            "nit": self.nit.text().strip(),
            "fecha_nacimiento": self.fecha_nacimiento.date().toString("yyyy-MM-dd"),
            "cargo": self.cargo.text().strip(),
            "area": self.area.text().strip(),
            "fecha_contratacion": self.fecha_contratacion.date().toString("yyyy-MM-dd"),
            "telefono": self.telefono.text().strip(),
            "email": self.email.text().strip(),
            "direccion": self.direccion.text().strip(),
            "salario_base": self.salario_base.value(),
            "comentarios": self.comentarios.text().strip(),
            "es_vendedor": self.es_vendedor.isChecked()
        }


class EstadoVentaDialog(QDialog):
    """Dialogo simple para seleccionar el estado de una venta."""

    def __init__(self, estado_actual="Pagada", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Estado de la venta")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Seleccione el estado de la venta:"))
        self.estado_combo = QComboBox()
        self.estado_combo.addItems([
            "Pagada",
            "Pendiente",
            "Anulada o Cancelada",
            "Borrador o Preliminar",
            "Enviada",
            "En Contingencia",
        ])
        idx = self.estado_combo.findText(estado_actual)
        if idx >= 0:
            self.estado_combo.setCurrentIndex(idx)
        layout.addWidget(self.estado_combo)
        btns = QHBoxLayout()
        ok_btn = QPushButton("Aceptar")
        cancel_btn = QPushButton("Cancelar")
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btns.addWidget(ok_btn)
        btns.addWidget(cancel_btn)
        layout.addLayout(btns)

    def get_estado(self):
        return self.estado_combo.currentText()



class UserEditDialog(QDialog):
    def __init__(self, username="", password="", role="user", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Usuario")
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.username_edit = QLineEdit(username)
        self.password_edit = QLineEdit(password)
        self.password_edit.setEchoMode(QLineEdit.Password)
        toggle_btn = QPushButton("👁")
        toggle_btn.setCheckable(True)
        toggle_btn.setFixedWidth(32)
        toggle_btn.clicked.connect(self._toggle_password_visibility)
        pwd_row = QHBoxLayout()
        pwd_row.setContentsMargins(0, 0, 0, 0)
        pwd_row.setSpacing(6)
        pwd_row.addWidget(self.password_edit)
        pwd_row.addWidget(toggle_btn)
        self.role_combo = QComboBox()
        self.role_combo.addItems(["guest", "user", "admin"])
        idx = self.role_combo.findText(role)
        if idx >= 0:
            self.role_combo.setCurrentIndex(idx)
        form.addRow("Usuario:", self.username_edit)
        form.addRow("Contraseña:", pwd_row)
        form.addRow("Rol:", self.role_combo)
        layout.addLayout(form)
        btns = QHBoxLayout()
        ok_btn = QPushButton("Aceptar")
        cancel_btn = QPushButton("Cancelar")
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btns.addWidget(ok_btn)
        btns.addWidget(cancel_btn)
        layout.addLayout(btns)

    def _toggle_password_visibility(self, checked: bool):
        self.password_edit.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)

    def get_data(self):
        return (
            self.username_edit.text().strip(),
            self.password_edit.text().strip(),
            self.role_combo.currentText(),
        )


class RoleDelegate(QStyledItemDelegate):
    """Pinta badges de rol en la tabla de usuarios."""

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        text = str(index.data() or "").strip().lower()
        bg = QColor("#F3F4F6")
        fg = QColor("#4B5563")
        if text == "admin":
            bg = QColor("#F3E8FF")
            fg = QColor("#7E22CE")
        elif text == "user":
            bg = QColor("#E0F2FE")
            fg = QColor("#0369A1")
        rect = QRectF(option.rect.adjusted(10, 12, -10, -12))
        path = QPainterPath()
        path.addRoundedRect(rect, 10, 10)
        painter.setPen(Qt.NoPen)
        painter.setBrush(bg)
        painter.drawPath(path)
        painter.setPen(fg)
        font = painter.font()
        font.setBold(True)
        base_size = font.pointSize()
        if base_size <= 0:
            base_size = 12
        font.setPointSize(base_size)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignCenter, index.data())
        painter.restore()

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), 48)


class UserConfigDialog(QDialog):
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("Configuración de usuarios")
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(16)

        card = QFrame()
        card.setObjectName("ModernCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 16, 16, 16)
        card_layout.setSpacing(12)

        title = QLabel("Usuarios y Permisos")
        title_font = title.font()
        base_size = title_font.pointSize()
        if base_size <= 0:
            base_size = 12
        title_font.setPointSize(base_size + 4)
        title_font.setBold(True)
        title.setFont(title_font)
        subtitle = QLabel("Gestione los usuarios del sistema y sus niveles de acceso.")
        subtitle.setStyleSheet("color: #6b7280;")
        card_layout.addWidget(title)
        card_layout.addWidget(subtitle)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["ID", "USUARIO", "ROL", "ACCIONES"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setFrameShape(QFrame.NoFrame)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setDefaultSectionSize(68)
        self.table.verticalHeader().hide()
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setDefaultAlignment(Qt.AlignCenter)
        header.setFixedHeight(54)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setStyleSheet(self.table.styleSheet() + "font-size: 15px;")
        self.role_delegate = RoleDelegate(self.table)
        self.table.setItemDelegateForColumn(2, self.role_delegate)
        card_layout.addWidget(self.table)
        self.table.setColumnHidden(0, True)

        footer = QHBoxLayout()
        footer.setSpacing(10)
        add_btn = QPushButton("Nuevo Usuario")
        add_btn.setObjectName("PrimaryActionButton")
        add_btn.setMinimumHeight(50)
        add_btn.setStyleSheet(add_btn.styleSheet() + "font-size: 15px;")
        edit_btn = QPushButton("Editar")
        edit_btn.setObjectName("SecondaryActionButton")
        edit_btn.setMinimumHeight(50)
        edit_btn.setStyleSheet(edit_btn.styleSheet() + "font-size: 15px;")
        del_btn = QPushButton("Eliminar")
        del_btn.setObjectName("DangerActionButton")
        del_btn.setMinimumHeight(50)
        del_btn.setStyleSheet(del_btn.styleSheet() + "font-size: 15px;")
        footer.addWidget(add_btn)
        footer.addStretch(1)
        footer.addWidget(edit_btn)
        footer.addWidget(del_btn)
        card_layout.addLayout(footer)

        add_btn.clicked.connect(self._add_user)
        edit_btn.clicked.connect(self._edit_user)
        del_btn.clicked.connect(self._delete_user)

        main_layout.addWidget(card)
        self.refresh()

    def refresh(self):
        users = self.db.get_users()
        self.table.setRowCount(len(users))
        for row, u in enumerate(users):
            self.table.setItem(row, 0, QTableWidgetItem(str(u["id"])))
            user_item = QTableWidgetItem(u["username"])
            user_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 1, user_item)
            role_item = QTableWidgetItem(u["role"])
            role_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 2, role_item)
            self._set_action_cell(row)
        self.table.resizeRowsToContents()

    def _set_action_cell(self, row):
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(4, 0, 8, 0)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignCenter)
        edit_btn = QPushButton("✏️")
        edit_btn.setProperty("class", "table-icon-btn")
        edit_btn.setFixedSize(80, 46)
        edit_btn_font = edit_btn.font()
        edit_btn_font.setPointSize(24)
        edit_btn_font.setFamily(edit_btn_font.defaultFamily())
        edit_btn.setFont(edit_btn_font)
        edit_btn.setStyleSheet("text-align: center; color: #0ea5e9; font-size: 26px;")
        edit_btn.clicked.connect(lambda _, r=row: self._select_and_edit(r))
        del_btn = QPushButton("🗑")
        del_btn.setProperty("class", "table-icon-btn")
        del_btn.setFixedSize(80, 46)
        del_btn_font = del_btn.font()
        del_btn_font.setPointSize(24)
        del_btn_font.setFamily("Segoe UI Symbol")
        del_btn.setFont(del_btn_font)
        del_btn.setStyleSheet("text-align: center; color: #dc2626; font-size: 26px;")
        del_btn.clicked.connect(lambda _, r=row: self._select_and_delete(r))
        layout.addWidget(edit_btn)
        layout.addWidget(del_btn)
        self.table.setCellWidget(row, 3, container)

    def _select_and_edit(self, row: int):
        if row >= 0:
            self.table.selectRow(row)
            self._edit_user()

    def _select_and_delete(self, row: int):
        if row >= 0:
            self.table.selectRow(row)
            self._delete_user()

    def _add_user(self):
        dlg = UserEditDialog(parent=self)
        if dlg.exec_() == QDialog.Accepted:
            username, password, role = dlg.get_data()
            if not username or not password:
                QMessageBox.warning(self, "Error", "Usuario y contraseña requeridos")
                return
            if not self._check_limit(role):
                return
            try:
                self.db.add_user(username, password, role)
            except Exception:
                QMessageBox.warning(self, "Error", "No se pudo crear el usuario")
            self.refresh()

    def _edit_user(self):
        row = self.table.currentRow()
        if row < 0:
            return
        user_id = int(self.table.item(row, 0).text())
        current = self.db.get_user(user_id)
        dlg = UserEditDialog(
            current["username"], current["password"], current["role"], self
        )
        if dlg.exec_() == QDialog.Accepted:
            username, password, role = dlg.get_data()
            if not username or not password:
                QMessageBox.warning(self, "Error", "Usuario y contraseña requeridos")
                return
            if role != current["role"] and not self._check_limit(role):
                return
            try:
                self.db.update_user(user_id, username, password, role)
            except ValueError as exc:
                QMessageBox.warning(self, "Error", str(exc))
                return
            except Exception as exc:
                logger.exception("No se pudo actualizar el usuario")
                QMessageBox.critical(self, "Error", f"No se pudo actualizar el usuario: {exc}")
                return
            self.refresh()

    def _delete_user(self):
        row = self.table.currentRow()
        if row < 0:
            return
        user_id = int(self.table.item(row, 0).text())
        if (
            QMessageBox.question(self, "Eliminar", "¿Desea eliminar el usuario?")
            == QMessageBox.Yes
        ):
            self.db.delete_user(user_id)
            self.refresh()

    def _check_limit(self, role):
        users = self.db.get_users()
        limits = {"guest": 1, "user": 6, "admin": 3}
        count = sum(1 for u in users if u["role"] == role)
        if count >= limits[role]:
            QMessageBox.warning(
                self, "Error", "Se alcanzó el límite para el rol seleccionado"
            )
            return False
        return True
