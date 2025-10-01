from decimal import Decimal, getcontext, ROUND_HALF_UP
import json
import logging
import base64
import requests
from datetime import date, timedelta

logger = logging.getLogger(__name__)
from PyQt5.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QSpinBox,
    QDoubleSpinBox, QPushButton, QListWidget, QListWidgetItem, QMessageBox, QCheckBox, QRadioButton, QComboBox,
    QDateEdit, QTableWidget, QTableWidgetItem, QGroupBox, QFormLayout, QButtonGroup,
    QAbstractItemView, QTextEdit, QStackedLayout, QWidget, QHeaderView, QSizePolicy,
    QFileDialog, QDialogButtonBox, QListView, QFrame, QCompleter
)
from PyQt5.QtCore import Qt, QDate, QUrl, QRegularExpression, QSignalBlocker, QEvent
from PyQt5.QtGui import (
    QColor,
    QDesktopServices,
    QIntValidator,
    QRegularExpressionValidator,
)

import os
import shutil
import re

from db import DB

from utils import jws
from utils.catalogos import CONTINGENCIA
from utils.sanitize import solo_digitos
from svfe.config import CAT012_DEPARTAMENTOS, CAT013_MUNICIPIOS
getcontext().prec = 28
getcontext().rounding = ROUND_HALF_UP
IVA_RATE = Decimal("0.13")
IVA_FACTOR = Decimal("1") + IVA_RATE

CREDIT_TERM_BACKEND_ROLE = Qt.UserRole + 1


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
    """Valida que el NIT contenga exactamente 14 dígitos.

    Una cadena vacía se considera válida para permitir que el campo sea opcional.
    """
    import re
    if nit == "":
        return True
    if not nit:
        return False
    nit_pattern = r"^\d{14}$"
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
        self.lista_clientes = QListWidget()
        self.clientes_mostrados = []
        self._mostrar_clientes(self.db.get_clientes())
        layout.addWidget(self.lista_clientes)
        self.btn_ok = QPushButton("Seleccionar")
        self.btn_ok.clicked.connect(self._handle_accept)
        layout.addWidget(self.btn_ok)
        self.setLayout(layout)
        self.search_bar.textChanged.connect(self._filtrar_clientes)
        self.selected_cliente = None
        self.lista_clientes.itemSelectionChanged.connect(self._seleccionar_cliente)

    def _mostrar_clientes(self, clientes):
        self.lista_clientes.clear()
        self.clientes_mostrados = clientes[:]  # <-- Actualiza la lista de mostrados
        for cli in clientes:
            codigo = get_field(cli, "codigo", "")
            nombre = get_field(cli, "nombre", "")
            nit = get_field(cli, "nit", "")
            texto = f"{codigo} | {nombre} | NIT: {nit}"
            self.lista_clientes.addItem(texto)

    def _filtrar_clientes(self, texto):
        filtrados = self.db.get_clientes(texto)
        self._mostrar_clientes(filtrados)

    def _seleccionar_cliente(self, item=None):
        idx = self.lista_clientes.currentRow()
        if idx >= 0:
            self.selected_cliente = self.clientes_mostrados[idx]  # <-- Usa la lista de mostrados

    def _handle_accept(self):
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
        self.fecha_inicio.dateChanged.connect(lambda *_: self._collect_params())
        self.fecha_fin.dateChanged.connect(lambda *_: self._collect_params())
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
            self._collect_params()

    def _apply_quick_range(self):
        if not self.filtrar_fechas_chk.isChecked():
            self._collect_params()
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
        self._collect_params()

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
    def _collect_params(self):
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
                QMessageBox.warning(self, "Validación", "No se ha seleccionado ningún cliente.")
                return None
            params["cliente_id"] = self.clientes_mostrados[idx].get("id")
        if modo == "vendedor":
            idx = self.vendedor_table.currentRow()
            if idx < 0 or idx >= len(self.vendedores_mostrados):
                QMessageBox.warning(self, "Validación", "No se ha seleccionado ningún vendedor.")
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

    def _mostrar_productos(self, productos):
        self.product_list.clear()
        for p in productos:
            texto = (
                f"{p['nombre']} | Código: {p['codigo']} | Stock: {p['stock']} | "
                f"Vence: {p.get('fecha_vencimiento', '')}"
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
                f"{p['nombre']} | Código: {p['codigo']} | Stock: {p['stock']} | "
                f"Vence: {p.get('fecha_vencimiento', '')}"
            ).lower()
        ]
        self._mostrar_productos(filtrados)

    def _toggle_comision_inputs(self, state):
        enabled = self.comision_chk.isChecked()
        self.comision_pct_spin.setEnabled(enabled)
        self.comision_tipo_combo.setEnabled(enabled)
        if not enabled:
            self.comision_pct_spin.setValue(0)
        if hasattr(self, "_recalcular_totales"):
            self._recalcular_totales()

    def _actualizar_Distribuidor_por_producto(self):
        idx = self.product_list.currentRow()
        if idx < 0 or idx >= len(self.productos):
            return
        lote = self.productos[idx]
        distribuidor_id = lote.get("Distribuidor_id")
        Distribuidores = getattr(self, "Distribuidores", None)
        if Distribuidores is None and hasattr(self, "parent") and self.parent() and hasattr(self.parent(), "manager"):
            Distribuidores = getattr(self.parent().manager, "_Distribuidores", None)
        if Distribuidores:
            for i, dist in enumerate(Distribuidores):
                if dist.get("id") == distribuidor_id:
                    self.Distribuidor_combo.setCurrentIndex(i)
                    break

    def _abrir_selector_cliente(self):
        selector = ClienteSelectorDialog(self.db, self)
        if selector.exec_():
            cli = selector.get_selected_cliente()
            if cli:
                nombre = get_field(cli, "codigo", "") or get_field(cli, "nombre", "")
                nit = get_field(cli, "nit", "")
                self.selected_cliente = cli
                self.cliente_label.setText(f"{nombre} | NIT: {nit}")
                for attr, key in [
                    ("nrc_edit", "nrc"),
                    ("nit_edit", "nit"),
                    ("giro_edit", "giro"),
                    ("email_edit", "email"),
                ]:
                    widget = getattr(self, attr, None)
                    if widget is not None:
                        widget.setText(get_field(cli, key, ""))

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
        self.setWindowTitle("Registrar Venta")


        main_layout = QHBoxLayout()

        self.productos = productos
        self.vendedores_trabajadores = vendedores_trabajadores
        self.venta_items = []


        left_layout = QVBoxLayout()

        # Barra de búsqueda de productos
        self.product_search = QLineEdit()
        self.product_search.setPlaceholderText("Buscar producto por nombre o código...")
        left_layout.addWidget(self.product_search)

        # Lista de productos
        self.product_list = QListWidget()
        self._productos_original = list(productos)
        self._mostrar_productos(productos)
        left_layout.addWidget(self.product_list)

        # Tipo de venta
        left_layout.addWidget(QLabel("Tipo de venta:"))
        self.tipo_minorista = QRadioButton("Minorista")
        self.tipo_mayorista_unit = QRadioButton("Mayorista (unitario)")
        self.tipo_mayorista_total = QRadioButton("Mayorista (total personalizado)")
        self.tipo_minorista.setChecked(True)
        tipo_layout = QHBoxLayout()
        tipo_layout.addWidget(self.tipo_minorista)
        tipo_layout.addWidget(self.tipo_mayorista_unit)
        tipo_layout.addWidget(self.tipo_mayorista_total)
        left_layout.addLayout(tipo_layout)

        # Cantidad
        left_layout.addWidget(QLabel("Cantidad:"))
        self.cantidad_spin = QSpinBox()
        self.cantidad_spin.setMinimum(1)
        self.cantidad_spin.setMaximum(100000)
        left_layout.addWidget(self.cantidad_spin)

        # Precio unitario y total
        precio_layout = QHBoxLayout()
        self.precio_spin = QDoubleSpinBox()
        self.precio_spin.setMinimum(0)
        self.precio_spin.setMaximum(1000000)
        self.precio_spin.setDecimals(2)
        self.precio_spin.setPrefix("$")
        precio_layout.addWidget(QLabel("Precio unitario:"))
        precio_layout.addWidget(self.precio_spin)
        self.precio_total_spin = QDoubleSpinBox()
        self.precio_total_spin.setMinimum(0)
        self.precio_total_spin.setMaximum(100000000)
        self.precio_total_spin.setDecimals(2)
        self.precio_total_spin.setPrefix("$")
        precio_layout.addWidget(QLabel("Precio total:"))
        precio_layout.addWidget(self.precio_total_spin)
        left_layout.addLayout(precio_layout)

        # Descuento
        descuento_layout = QHBoxLayout()
        descuento_layout.addWidget(QLabel("Descuento:"))
        self.descuento_spin = QDoubleSpinBox()
        self.descuento_spin.setMinimum(0)
        self.descuento_spin.setMaximum(1000000)
        self.descuento_spin.setDecimals(2)
        self.descuento_spin.setValue(0)
        descuento_layout.addWidget(self.descuento_spin)
        self.descuento_tipo_combo = QComboBox()
        self.descuento_tipo_combo.addItems(["%", "$"])
        descuento_layout.addWidget(self.descuento_tipo_combo)
        left_layout.addLayout(descuento_layout)

        self.descuento_spin.valueChanged.connect(self._recalcular_totales)
        self.descuento_tipo_combo.currentIndexChanged.connect(self._on_descuento_tipo_changed)

        # IVA eliminado: ya no se muestran opciones para aplicar IVA


        # --- Clasificación fiscal individual por producto ---
        fiscal_layout = QHBoxLayout()
        fiscal_layout.addWidget(QLabel("Tipo fiscal:"))
        self.tipo_fiscal_combo = QComboBox()
        self.tipo_fiscal_combo.addItems(["Venta gravada", "Venta exenta", "Venta no sujeta"])
        fiscal_layout.addWidget(self.tipo_fiscal_combo)
        left_layout.addLayout(fiscal_layout)

        # Botón agregar a venta
        self.btn_agregar = QPushButton("Agregar a venta")
        left_layout.addWidget(self.btn_agregar)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([
            "Producto", "Cantidad", "Precio U.", "Descuento", "Tipo fiscal", "Eliminar"
        ])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        left_layout.addWidget(self.table)
        self.btn_agregar.clicked.connect(self._agregar_a_venta)
        self.table.cellClicked.connect(self._eliminar_fila)

        right_layout = QVBoxLayout()
        
        # Combo de vendedor trabajador
        right_layout.addWidget(QLabel("Vendedor (trabajador):"))
        self.vendedor_combo = QComboBox()
        self.vendedor_combo.addItem("Sin vendedor")
        for v in vendedores_trabajadores:
            self.vendedor_combo.addItem(v["nombre"])
        right_layout.addWidget(self.vendedor_combo)

        # Comisión para el vendedor
        self.comision_chk = QCheckBox("Aplicar comisión")
        right_layout.addWidget(self.comision_chk)
        com_layout = QHBoxLayout()
        com_layout.addWidget(QLabel("%:"))
        self.comision_pct_spin = QDoubleSpinBox()
        self.comision_pct_spin.setRange(0, 100)
        self.comision_pct_spin.setDecimals(2)
        self.comision_pct_spin.setEnabled(False)
        com_layout.addWidget(self.comision_pct_spin)
        self.comision_tipo_combo = QComboBox()
        self.comision_tipo_combo.addItems(["Añadida al total", "Desglosada (incluida en el precio)"])
        self.comision_tipo_combo.setEnabled(False)
        com_layout.addWidget(self.comision_tipo_combo)
        right_layout.addLayout(com_layout)
        self.comision_label = QLabel("Comisión: $0.00")
        right_layout.addWidget(self.comision_label)
        self.comision_chk.stateChanged.connect(self._toggle_comision_inputs)
        self.comision_pct_spin.valueChanged.connect(self._recalcular_totales)
        self.comision_tipo_combo.currentIndexChanged.connect(self._recalcular_totales)

        # Cliente selector
        right_layout.addWidget(QLabel("Cliente:"))
        self.cliente_btn = QPushButton("Seleccionar Cliente")
        self.cliente_label = QLabel("(Ningún cliente seleccionado)")
        right_layout.addWidget(self.cliente_btn)
        right_layout.addWidget(self.cliente_label)
        self.selected_cliente = None

        # Campo "Venta a cuenta de"
        right_layout.addWidget(QLabel("Venta a cuenta de:"))
        self.venta_a_cuenta_de_edit = QLineEdit()
        self.venta_a_cuenta_de_edit.setPlaceholderText("Nombre")
        right_layout.addWidget(self.venta_a_cuenta_de_edit)
        right_layout.addWidget(QLabel("DUI/NIT:"))
        self.venta_documento_edit = QLineEdit()
        self.venta_documento_edit.setPlaceholderText("Documento")
        right_layout.addWidget(self.venta_documento_edit)

        # Distribuidor
        right_layout.addWidget(QLabel("Distribuidor:"))
        self.Distribuidor_combo = QComboBox()
        self.Distribuidor_combo.addItems(Distribuidores)
        right_layout.addWidget(self.Distribuidor_combo)

        # Resumen (sin IVA para consumidor final)
        self.precio_label = QLabel("Precio U.: $0.00")
        self.sumas_label = QLabel("Sumas: $0.00")
        self.subtotal_label = QLabel("Subtotal: $0.00")
        self.total_label = QLabel("Venta total: $0.00")
        right_layout.addWidget(self.precio_label)
        right_layout.addWidget(self.sumas_label)
        right_layout.addWidget(self.subtotal_label)
        right_layout.addWidget(self.total_label)

        right_layout.addWidget(QLabel("Condición de pago:"))
        self.condicion_pago_combo = QComboBox()
        self.condicion_pago_combo.addItem("Contado", 1)
        self.condicion_pago_combo.addItem("Crédito", 2)
        self.condicion_pago_combo.addItem("Otros", 3)
        right_layout.addWidget(self.condicion_pago_combo)

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

        right_layout.addWidget(self.credit_fields_widget)

        right_layout.addWidget(QLabel("Estado:"))
        self.estado_combo = QComboBox()
        self.estado_combo.addItems(["Pagada", "Pendiente"])
        right_layout.addWidget(self.estado_combo)

        # Botón para registrar la venta
        self.btn_ok = QPushButton("Registrar")
        right_layout.addWidget(self.btn_ok)
        self.btn_ok.clicked.connect(self._validar_y_accept)  

        # --- AGREGA LOS DOS LAYOUTS AL PRINCIPAL ---
        main_layout.addLayout(left_layout, 2)
        main_layout.addLayout(right_layout, 1)
        self.setLayout(main_layout)

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

        # Agrupa tipo de venta en su propio grupo
        self.tipo_venta_group = QButtonGroup(self)
        self.tipo_venta_group.setExclusive(True)
        self.tipo_venta_group.addButton(self.tipo_minorista)
        self.tipo_venta_group.addButton(self.tipo_mayorista_unit)
        self.tipo_venta_group.addButton(self.tipo_mayorista_total)

        # Estado
        self.productos_data = productos

        # Conexiones
        self.cliente_btn.clicked.connect(self._abrir_selector_cliente)
        self.product_list.currentRowChanged.connect(self._actualizar_precio_defecto)
        self.tipo_minorista.toggled.connect(self._actualizar_precio_defecto)
        self.tipo_mayorista_unit.toggled.connect(self._actualizar_precio_defecto)
        self.tipo_mayorista_total.toggled.connect(self._actualizar_precio_defecto)
        self.cantidad_spin.valueChanged.connect(self._recalcular_totales)
        self.precio_spin.valueChanged.connect(self._recalcular_totales)
        self.precio_total_spin.valueChanged.connect(self._recalcular_totales)
        self.product_search.textChanged.connect(self._filtrar_productos)

        # Permitir edición según tipo de venta
        self.tipo_minorista.toggled.connect(self._toggle_precio_edicion)
        self.tipo_mayorista_unit.toggled.connect(self._toggle_precio_edicion)
        self.tipo_mayorista_total.toggled.connect(self._toggle_precio_edicion)

        # --- INICIO BLOQUE NUEVO: Actualizar combo de Distribuidor en tiempo real según producto seleccionado ---
        self.product_list.currentRowChanged.connect(self._actualizar_Distribuidor_por_producto)
        # --- FIN BLOQUE NUEVO ---

        # Ajusta el máximo del descuento según el tipo seleccionado
        self._on_descuento_tipo_changed()
        self._update_condicion_pago_fields()
        self.load_payment_data(venta_extra)

    def set_productos_data(self, productos_data):
        self.productos_data = productos_data

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
        precio = 0
        if prod:
            if self.tipo_minorista.isChecked():
                precio = get_field(prod, "precio_venta_minorista", 0)
            elif self.tipo_mayorista_unit.isChecked() or self.tipo_mayorista_total.isChecked():
                precio = get_field(prod, "precio_venta_mayorista", 0)
        self.precio_spin.blockSignals(True)
        self.precio_total_spin.blockSignals(True)
        self.precio_spin.setValue(float(precio))
        self.precio_total_spin.setValue(float(precio) * self.cantidad_spin.value())
        self.precio_spin.blockSignals(False)
        self.precio_total_spin.blockSignals(False)
        self._toggle_precio_edicion()
        self._recalcular_totales()

    def _toggle_precio_edicion(self):
        # Permitir editar el campo correspondiente según el tipo de venta
        if self.tipo_minorista.isChecked():
            self.precio_spin.setEnabled(True)
            self.precio_total_spin.setEnabled(False)
        elif self.tipo_mayorista_unit.isChecked():
            self.precio_spin.setEnabled(True)
            self.precio_total_spin.setEnabled(False)
        elif self.tipo_mayorista_total.isChecked():
            self.precio_spin.setEnabled(False)
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

        # --- Sincroniza precio unitario y total en modo mayorista total ---
        if self.tipo_mayorista_total.isChecked():
            precio_total = self.precio_total_spin.value()
            precio_unitario = round(precio_total / cantidad, 6) if cantidad > 0 else 0
            self.precio_spin.blockSignals(True)
            self.precio_spin.setValue(precio_unitario)
            self.precio_spin.blockSignals(False)
        else:
            precio_unitario = self.precio_spin.value()
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

        return {
            "cliente": self.selected_cliente if self.selected_cliente else {},
            "items": self.venta_items,
            "tipo_venta": (
                "Minorista" if self.tipo_minorista.isChecked()
                else "Mayorista (unitario)" if self.tipo_mayorista_unit.isChecked()
                else "Mayorista (total personalizado)"
            ),
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

    def _agregar_a_venta(self):
        idx = self.product_list.currentRow()
        if idx < 0:
            QMessageBox.warning(self, "Validación", "Seleccione un producto del inventario actual.")
            return
        lote = self.productos[idx]
        cantidad = self.cantidad_spin.value()

        # --- Cálculo de precio unitario según tipo de venta ---
        if self.tipo_mayorista_total.isChecked():
            precio_total = self.precio_total_spin.value()
            precio = round(precio_total / cantidad, 6) if cantidad > 0 else 0
        else:
            precio = self.precio_spin.value()
            precio_total = precio * cantidad

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

        self.venta_items.append({
            "lote_id": lote["lote_id"],
            "producto_id": lote["producto_id"],
            "producto": lote["nombre"],
            "cantidad": cantidad,
            "precio": precio,  # Precio unitario con IVA; neto se calcula en DTE
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
            "fecha_vencimiento": lote.get("fecha_vencimiento", "")
        })
        self._actualizar_tabla()
        self._recalcular_totales()
        self._actualizar_resumen()

    def _actualizar_tabla(self):
        self.table.setRowCount(len(self.venta_items))
        for i, item in enumerate(self.venta_items):
            self.table.setItem(i, 0, QTableWidgetItem(item["producto"]))
            self.table.setItem(i, 1, QTableWidgetItem(str(item["cantidad"])))
            self.table.setItem(i, 2, QTableWidgetItem(f"${item['precio']:.2f}"))
            self.table.setItem(i, 3, QTableWidgetItem(f"{item['descuento']}{item['descuento_tipo']}"))
            self.table.setItem(i, 4, QTableWidgetItem(item.get("tipo_fiscal", "")))
            btn = QPushButton("Eliminar")
            btn.setStyleSheet(
                "background-color: #b71c1c; color: #fff; border-radius: 6px; font-size:9px;"
                "min-width:70px; max-width:100px; min-height:10px; max-height:15px;"
            )

            btn.clicked.connect(lambda _, row=i: self._eliminar_item(row))
            self.table.setCellWidget(i, 5, btn)

    def _actualizar_resumen(self):
        sumas = sum(i["subtotal"] for i in self.venta_items)
        descuentos = sum(i.get("descuento_monto", 0) for i in self.venta_items)
        subtotal = sumas - descuentos
        total = sum(i.get("total", 0) for i in self.venta_items)

        self.sumas_label.setText(f"Sumas: ${sumas:.2f}")
        self.subtotal_label.setText(f"Subtotal: ${subtotal:.2f}")
        self.total_label.setText(f"Venta total: ${total:.2f}")

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
        if not self.product_list.currentItem():
            QMessageBox.warning(self, "Validación", "Seleccione un producto.")
            return
        if self.cantidad_spin.value() <= 0:
            QMessageBox.warning(self, "Validación", "La cantidad debe ser mayor que cero.")
            return
        if self.precio_spin.value() <= 0:
            QMessageBox.warning(self, "Validación", "El precio debe ser mayor que cero.")
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
        self.accept()

class ProductDialog(QDialog):
    def __init__(self, vendedores, Distribuidores, parent=None, producto=None):
        super().__init__(parent)
        self.setWindowTitle("Producto")
        layout = QVBoxLayout()

        # Datos básicos del producto
        self.codigo_edit = QLineEdit()
        self.codigo_edit.installEventFilter(self)
        self.sku_edit = QLineEdit()
        self.nombre_edit = QLineEdit()
        self.precio_compra_spin = QDoubleSpinBox()
        self.precio_compra_spin.setMaximum(1000000)
        self.precio_compra_spin.setDecimals(2)
        self.precio_venta_minorista_spin = QDoubleSpinBox()
        self.precio_venta_minorista_spin.setMaximum(1000000)
        self.precio_venta_minorista_spin.setDecimals(2)
        self.precio_venta_mayorista_spin = QDoubleSpinBox()
        self.precio_venta_mayorista_spin.setMaximum(1000000)
        self.precio_venta_mayorista_spin.setDecimals(2)

        layout.addWidget(QLabel("Código:"))
        layout.addWidget(self.codigo_edit)
        layout.addWidget(QLabel("SKU:"))
        layout.addWidget(self.sku_edit)
        layout.addWidget(QLabel("Nombre:"))
        layout.addWidget(self.nombre_edit)
        layout.addWidget(QLabel("Precio de compra:"))
        layout.addWidget(self.precio_compra_spin)
        layout.addWidget(QLabel("Precio venta minorista:"))
        layout.addWidget(self.precio_venta_minorista_spin)
        layout.addWidget(QLabel("Precio venta mayorista:"))
        layout.addWidget(self.precio_venta_mayorista_spin)

        btns = QHBoxLayout()
        self.btn_ok = QPushButton("Guardar")
        self.btn_cancel = QPushButton("Cancelar")
        btns.addWidget(self.btn_ok)
        btns.addWidget(self.btn_cancel)
        layout.addLayout(btns)
        self.setLayout(layout)

        self.btn_ok.clicked.connect(self.accept)
        self.btn_cancel.clicked.connect(self.reject)

        if producto:
            self.nombre_edit.setText(producto.get("nombre", ""))
            self.codigo_edit.setText(producto.get("codigo", ""))
            self.sku_edit.setText(producto.get("sku", ""))
            self.precio_compra_spin.setValue(producto.get("precio_compra", 0))
            self.precio_venta_minorista_spin.setValue(producto.get("precio_venta_minorista", 0))
            self.precio_venta_mayorista_spin.setValue(producto.get("precio_venta_mayorista", 0))

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

    def get_data(self):
        return {
            "nombre": self.nombre_edit.text(),
            "codigo": self.codigo_edit.text(),
            "sku": self.sku_edit.text(),
            "precio_compra": self.precio_compra_spin.value(),
            "precio_venta_minorista": self.precio_venta_minorista_spin.value(),
            "precio_venta_mayorista": self.precio_venta_mayorista_spin.value()
        }

class RegisterPurchaseDialog(QDialog):
    
    def __init__(self, productos, Distribuidores, Vendedores, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Registrar Compra")
        self.productos = productos
        self.Distribuidores = Distribuidores
        self.Vendedores = Vendedores
        self._vendedores_map = {v["id"]: v for v in self.Vendedores}
        self.compra_items = []

        layout = QVBoxLayout()

        # Mapeo producto -> vendedor y vendedor -> Distribuidor
        self._producto_vendedor_map = {}
        self._vendedor_Distribuidor_map = {}
        for v in self.Vendedores:
            self._vendedor_Distribuidor_map[v["id"]] = v.get("Distribuidor_id")
        for p in self.productos:
            self._producto_vendedor_map[p["nombre"]] = p.get("vendedor_id")

        # Vendedor
        vendedor_layout = QHBoxLayout()
        vendedor_layout.addWidget(QLabel("Vendedor:"))
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
        vendedor_layout.addWidget(self.vendedor_combo)
        layout.addLayout(vendedor_layout)

        # Distribuidor (no editable)
        Distribuidor_layout = QHBoxLayout()
        Distribuidor_layout.addWidget(QLabel("Distribuidor:"))
        self.Distribuidor_combo = QComboBox()
        self.Distribuidor_combo.setEnabled(False)
        Distribuidor_layout.addWidget(self.Distribuidor_combo)
        layout.addLayout(Distribuidor_layout)

        # Producto
        producto_layout = QHBoxLayout()
        producto_layout.addWidget(QLabel("Producto:"))
        self.product_list = QListWidget()
        self.product_list.addItems([p["nombre"] for p in productos])
        producto_layout.addWidget(self.product_list)
        layout.addLayout(producto_layout)

        # Cantidad, precio unitario y precio total
        cantidad_layout = QHBoxLayout()
        cantidad_layout.addWidget(QLabel("Cantidad:"))
        self.cantidad_spin = QSpinBox()
        self.cantidad_spin.setMinimum(1)
        self.cantidad_spin.setMaximum(100000)
        cantidad_layout.addWidget(self.cantidad_spin)
        cantidad_layout.addWidget(QLabel("Precio unitario:"))
        self.precio_unitario_spin = QDoubleSpinBox()
        self.precio_unitario_spin.setMinimum(0)
        self.precio_unitario_spin.setMaximum(1000000)
        self.precio_unitario_spin.setDecimals(2)
        cantidad_layout.addWidget(self.precio_unitario_spin)
        cantidad_layout.addWidget(QLabel("Precio total:"))
        self.precio_total_spin = QDoubleSpinBox()
        self.precio_total_spin.setMinimum(0)
        self.precio_total_spin.setMaximum(100000000)
        self.precio_total_spin.setDecimals(2)
        cantidad_layout.addWidget(self.precio_total_spin)
        cantidad_layout.addWidget(QLabel("Fecha vencimiento:"))
        self.fecha_vencimiento_edit = QDateEdit(QDate.currentDate())
        self.fecha_vencimiento_edit.setCalendarPopup(True)
        cantidad_layout.addWidget(self.fecha_vencimiento_edit)
        layout.addLayout(cantidad_layout)
        descuento_layout = QHBoxLayout()
        descuento_layout.addWidget(QLabel("Descuento:"))
        self.descuento_spin = QDoubleSpinBox()
        self.descuento_spin.setMinimum(0)
        self.descuento_spin.setMaximum(1000000)
        self.descuento_spin.setDecimals(2)
        self.descuento_spin.setValue(0)
        descuento_layout.addWidget(self.descuento_spin)

        self.descuento_tipo_combo = QComboBox()
        self.descuento_tipo_combo.addItems(["%", "$"])
        descuento_layout.addWidget(self.descuento_tipo_combo)

        layout.addLayout(descuento_layout)

        # IVA con checkbox y radios
        iva_layout = QHBoxLayout()
        self.iva_checkbox = QCheckBox("Aplicar IVA")
        self.iva_checkbox.setChecked(False)
        iva_layout.addWidget(self.iva_checkbox)
        self.iva_desglosado_radio = QRadioButton("IVA desglosado (restar del precio)")
        self.iva_desglosado_radio.setChecked(False)
        self.iva_desglosado_radio.setEnabled(False)
        iva_layout.addWidget(self.iva_desglosado_radio)
        self.iva_añadido_radio = QRadioButton("IVA añadido (sumar al precio)")
        self.iva_añadido_radio.setChecked(False)
        self.iva_añadido_radio.setEnabled(False)
        iva_layout.addWidget(self.iva_añadido_radio)
        layout.addLayout(iva_layout)

        # Agrupa IVA en su propio grupo
        self.iva_group = QButtonGroup(self)
        self.iva_group.setExclusive(True)
        self.iva_group.addButton(self.iva_desglosado_radio)
        self.iva_group.addButton(self.iva_añadido_radio)

        # Resumen
        self.subtotal_label = QLabel("Subtotal: $0.00")
        self.iva_label = QLabel("IVA: $0.00")
        self.comision_label_resumen = QLabel("Comisión: $0.00")
        self.total_label = QLabel("TOTAL: $0.00")
        layout.addWidget(self.subtotal_label)
        layout.addWidget(self.iva_label)
        layout.addWidget(self.comision_label_resumen)
        layout.addWidget(self.total_label)

        # Conexiones para IVA
        self.iva_checkbox.stateChanged.connect(self._toggle_iva_radios)
        self.iva_desglosado_radio.toggled.connect(self._actualizar_total_general)

        # Comisión (ahora del vendedor)
        comision_layout = QHBoxLayout()
        comision_layout.addWidget(QLabel("Comisión (%):"))
        self.comision_pct_spin = QDoubleSpinBox()
        self.comision_pct_spin.setRange(0, 100)
        self.comision_pct_spin.setDecimals(2)
        self.comision_pct_spin.setValue(0)
        comision_layout.addWidget(self.comision_pct_spin)

        comision_layout.addWidget(QLabel("Tipo:"))
        self.comision_tipo_combo = QComboBox()
        self.comision_tipo_combo.addItems(["Añadida al total", "Desglosada (incluida en el precio)"])
        comision_layout.addWidget(self.comision_tipo_combo)

        layout.addLayout(comision_layout)

        # Botón agregar a compra
        self.btn_agregar = QPushButton("Agregar a compra")
        layout.addWidget(self.btn_agregar)

        # En el __init__ de RegisterPurchaseDialog, donde creas la tabla:
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels([
            "Producto", "Cantidad", "Precio U.", "Subtotal", "IVA", "Comisión", "Total", "Vencimiento", "Eliminar"
        ])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.table)

        # Total general de la compra
        total_general_layout = QHBoxLayout()
        self.total_general_label = QLabel("Total compra: $0.00")
        total_general_layout.addWidget(self.total_general_label)
        layout.addLayout(total_general_layout)

        # Botón registrar compra
        self.btn_registrar = QPushButton("Registrar Compra")
        self.btn_cancelar = QPushButton("Cancelar")
        botones_layout = QHBoxLayout()
        botones_layout.addStretch(1)
        botones_layout.addWidget(self.btn_registrar)
        botones_layout.addWidget(self.btn_cancelar)
        layout.addLayout(botones_layout)

        self.setLayout(layout)

        # --- CONEXIONES ---
        self.btn_cancelar.clicked.connect(self.reject)
        self.btn_registrar.clicked.connect(self._registrar_compra)
        self.btn_agregar.clicked.connect(self._agregar_a_compra)
        self.table.cellClicked.connect(self._eliminar_fila)
        self.product_list.currentRowChanged.connect(self._actualizar_vendedor_y_Distribuidor)
        self.vendedor_combo.currentIndexChanged.connect(self._actualizar_Distribuidor)
        self.comision_pct_spin.valueChanged.connect(self._actualizar_total_general)
        self.product_list.currentRowChanged.connect(self._actualizar_precio_unitario_por_producto)
        self._actualizar_precio_unitario_por_producto()

        # Inicializa combos
        if productos:
            self.product_list.setCurrentRow(0)
            self._actualizar_vendedor_y_Distribuidor()
        self._actualizar_total_general()
        
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

    # --- NUEVO MÉTODO ---
    def _actualizar_precio_unitario_por_producto(self):
        idx = self.product_list.currentRow()
        if idx < 0 or idx >= len(self.productos):
            self.precio_unitario_spin.setValue(0)
            return
        prod = self.productos[idx]
        precio = prod.get("precio_compra", 0)
        self.precio_unitario_spin.blockSignals(True)
        self.precio_unitario_spin.setValue(float(precio))
        self.precio_unitario_spin.blockSignals(False)
        self._calcular_preview_item()

    def _calcular_preview_item(self):
        cantidad = self.cantidad_spin.value()

        precio_unit = self.precio_unitario_spin.value()
        precio_total = self.precio_total_spin.value()

        # Si el total es editable y el usuario lo modificó, ajusta el precio unitario
        if self.precio_total_spin.isEnabled() and self.precio_total_spin.hasFocus():
            precio_unit = round(precio_total / cantidad, 6) if cantidad > 0 else 0
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
            descuento_monto = descuento_valor
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
        if self.iva_checkbox.isChecked():
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

        self.subtotal_label.setText(f"Subtotal: ${subtotal:.2f}")
        self.iva_label.setText(f"IVA: ${iva:.2f}")
        self.comision_label_resumen.setText(f"Comisión: ${comision_monto:.2f}")
        self.total_label.setText(f"TOTAL: ${total_final:.2f}")
        
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
        subtotal_general = sum(item.get("subtotal", item["cantidad"] * item["precio"]) for item in self.compra_items)
        iva_general = sum(item.get("iva", 0) for item in self.compra_items)
        comision_general = sum(item.get("comision_monto", 0) for item in self.compra_items)
        total_general = sum(item.get("total", 0) for item in self.compra_items)

        self.subtotal_label.setText(f"Subtotal: ${subtotal_general:.2f}")
        self.iva_label.setText(f"IVA: ${iva_general:.2f}")
        self.comision_label_resumen.setText(f"Comisión: ${comision_general:.2f}")
        self.total_label.setText(f"TOTAL: ${total_general:.2f}")
        self.total_general_label.setText(f"Total compra: ${total_general:.2f}")

    def _actualizar_vendedor_y_Distribuidor(self):
        idx = self.product_list.currentRow()
        if idx < 0:
            return
        producto = self.productos[idx]
        vendedor_id = producto.get("vendedor_id")
        # Selecciona el vendedor correspondiente
        combo_idx = self.vendedor_combo.findData(vendedor_id)
        self.vendedor_combo.blockSignals(True)
        if combo_idx >= 0:
            self.vendedor_combo.setCurrentIndex(combo_idx)
        else:
            self.vendedor_combo.setCurrentIndex(0)
        self.vendedor_combo.blockSignals(False)
        self._actualizar_Distribuidor()

    def _actualizar_Distribuidor(self):
        vendedor_id = self.vendedor_combo.currentData()
        self.Distribuidor_combo.clear()
        if vendedor_id is None:
            self.comision_label_resumen.setText("Comisión vendedor: 0%")
            self.comision_pct_spin.setValue(0)
            return
        vendedor = self._vendedores_map.get(vendedor_id)
        if not vendedor:
            self.comision_label_resumen.setText("Comisión vendedor: 0%")
            self.comision_pct_spin.setValue(0)
            return
        Distribuidor_id = self._vendedor_Distribuidor_map.get(vendedor_id)
        if Distribuidor_id is None:
            Distribuidor_id = vendedor.get("Distribuidor_id")
        for d in self.Distribuidores:
            if d["id"] == Distribuidor_id:
                self.Distribuidor_combo.addItem(d["nombre"], d["id"])
                break
        # Actualiza comisión base del vendedor
        comision = vendedor.get("comision_base", 0)
        try:
            comision_val = float(comision) if comision is not None else 0.0
        except Exception:
            comision_val = 0.0
        self.comision_label_resumen.setText(f"Comisión vendedor: {comision_val}%")
        self.comision_pct_spin.setValue(comision_val)

    def _agregar_a_compra(self):
        producto = self.product_list.currentItem().text() if self.product_list.currentItem() else ""
        cantidad = self.cantidad_spin.value()
        precio = self.precio_unitario_spin.value()
        if not producto or cantidad <= 0 or precio <= 0:
            QMessageBox.warning(self, "Validación", "Seleccione producto, cantidad y precio válidos.")
            return

        # --- CÁLCULO DE SUBTOTAL Y DESCUENTO ---
        subtotal = cantidad * precio
        descuento_pct = self.descuento_spin.value()
        descuento_monto = subtotal * (descuento_pct / 100)
        subtotal_con_descuento = subtotal - descuento_monto

        # --- CÁLCULO DE COMISIÓN SEGÚN TIPO (antes del IVA) ---
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

        # --- CÁLCULO DE IVA ---
        iva = 0
        iva_tipo = "ninguno"
        if self.iva_checkbox.isChecked():
            if self.iva_desglosado_radio.isChecked():
                iva = base_iva * 13 / 113
                iva_tipo = "desglosado"
                total = subtotal_con_descuento
            elif self.iva_añadido_radio.isChecked():
                iva = base_iva * 0.13
                iva_tipo = "añadido"
                total = subtotal_con_descuento + iva
            else:
                total = subtotal_con_descuento
                iva = 0
                iva_tipo = "ninguno"
        else:
            total = subtotal_con_descuento
            iva = 0
            iva_tipo = "ninguno"

        # --- TOTAL FINAL CON COMISIÓN ---
        if comision_tipo == "Añadida al total":
            total_con_comision = total + comision_monto
        else:
            total_con_comision = total  # El total ya incluye la comisión o no hay

        fecha_vencimiento = self.fecha_vencimiento_edit.date().toString("yyyy-MM-dd")

        self.compra_items.append({
            "producto": producto,
            "cantidad": cantidad,
            "precio": precio,
            "subtotal": subtotal,
            "descuento_pct": descuento_pct,
            "descuento_monto": descuento_monto,
            "descuento": descuento_monto,  # para compatibilidad con lo que ya tienes
            "descuento_tipo": "%",  # <--- agrega este campo (ajusta si tienes lógica de descuento)
            "iva": iva,
            "iva_tipo": iva_tipo,
            "comision_pct": comision_pct,
            "comision_monto": comision_monto,
            "comision_tipo": "",
            "total": total_con_comision,
            "fecha_vencimiento": fecha_vencimiento
        })
        self._actualizar_tabla()
        self._actualizar_total_general()

    def _actualizar_tabla(self):
        self.table.setRowCount(len(self.compra_items))
        for i, item in enumerate(self.compra_items):
            self.table.setItem(i, 0, QTableWidgetItem(item["producto"]))
            self.table.setItem(i, 1, QTableWidgetItem(str(item["cantidad"])))
            self.table.setItem(i, 2, QTableWidgetItem(f"${item['precio']:.2f}"))
            self.table.setItem(i, 3, QTableWidgetItem(f"${item['subtotal']:.2f}"))
            self.table.setItem(i, 4, QTableWidgetItem(f"${item['iva']:.2f}"))
            # Comisión (monto y porcentaje)
            comision_text = f"${item.get('comision_monto', 0):.2f} ({item.get('comision_pct', 0)}%)"
            self.table.setItem(i, 5, QTableWidgetItem(comision_text))
            self.table.setItem(i, 6, QTableWidgetItem(f"${item['total']:.2f}"))
            self.table.setItem(i, 7, QTableWidgetItem(item.get("fecha_vencimiento", "")))
            btn = QPushButton("Eliminar")
            btn.setStyleSheet(
                "background-color: #b71c1c; color: #fff; border-radius: 6px; font-size:9px;"
                "min-width:70px; max-width:100px; min-height:10px; max-height:15px;"
            )
            btn.clicked.connect(lambda _, row=i: self._eliminar_item(row))
            self.table.setCellWidget(i, 8, btn)

    def _eliminar_fila(self, row, col):
        if col == 8:
            self._eliminar_item(row)

    def _eliminar_item(self, row):
        if 0 <= row < len(self.compra_items):
            del self.compra_items[row]
            self._actualizar_tabla()
            self._actualizar_total_general()

    def _registrar_compra(self):
        if not self.compra_items:
            QMessageBox.warning(self, "Validación", "Debe agregar al menos un producto a la compra.")
            return

        # Validar que cada producto exista antes de registrar la compra
        productos_dict = {p["nombre"]: p["id"] for p in self.productos}
        for item in self.compra_items:
            producto_id = productos_dict.get(item["producto"])
            if producto_id is None:
                QMessageBox.warning(
                    self,
                    "Producto no válido",
                    f"El producto '{item['producto']}' no existe. Registro cancelado."
                )
                return
            item["producto_id"] = producto_id

        # Obtén los datos DIRECTAMENTE de los combos y la lista de items
        fecha = QDate.currentDate().toString("yyyy-MM-dd")
        total_general = sum(item["total"] for item in self.compra_items)
        vendedor_id = self.vendedor_combo.currentData()
        Distribuidor_id = (
            self.Distribuidor_combo.currentData()
            if self.Distribuidor_combo.count() > 0
            else None
        )

        if vendedor_id is None or Distribuidor_id is None:
            respuesta = QMessageBox.question(
                self,
                "Confirmaci\u00f3n",
                "esta a punto de agregar una compra sin vendedor, esto puede causar errores en el sistema, esta seguro de continuar?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if respuesta != QMessageBox.Yes:
                return

        comision_total = sum(item.get("comision_monto", 0) for item in self.compra_items)
        compra_id = self.parent().manager.db.add_compra_detallada({
            "fecha": fecha,
            "producto_id": None,
            "cantidad": 0,
            "precio_unitario": 0,
            "total": total_general,
            "Distribuidor_id": Distribuidor_id,
            "comision_pct": 0,
            "comision_monto": comision_total,  # <-- Aquí la suma real
            "vendedor_id": vendedor_id
        })

        # Guarda cada detalle de compra con todos los campos
        for item in self.compra_items:
            producto_id = item["producto_id"]
            self.parent().manager.db.add_detalle_compra(
                compra_id,
                producto_id,
                item["cantidad"],
                item["precio"],
                item.get("fecha_vencimiento", ""),
                item.get("descuento_monto", 0),      # <--- monto de descuento
                item.get("descuento_tipo", "%"),      # <--- tipo de descuento
                item.get("iva", 0),
                item.get("iva_tipo", ""),
                item.get("comision_pct", 0),
                item.get("comision_monto", 0),
                item.get("comision_tipo", "")
            )
            # Aumenta el stock del producto
            self.parent().manager.aumentar_stock(producto_id, item["cantidad"])

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
        main_layout = QHBoxLayout()

        # --- LADO IZQUIERDO ---
        left_layout = QVBoxLayout()
        self.productos = productos
        self.venta_items = []
        self.Distribuidores = Distribuidores
        self.vendedores_trabajadores = vendedores_trabajadores

        # Distribuidor
        left_layout.addWidget(QLabel("Distribuidor:"))
        self.Distribuidor_combo = QComboBox()
        if isinstance(Distribuidores[0], dict):
            self.Distribuidor_combo.addItems([d["nombre"] for d in Distribuidores])
        else:
            self.Distribuidor_combo.addItems(Distribuidores)
        left_layout.addWidget(self.Distribuidor_combo)

        # Barra de búsqueda de productos
        self.product_search = QLineEdit()
        self.product_search.setPlaceholderText("Buscar producto por nombre o código...")
        left_layout.addWidget(self.product_search)

        # Lista de productos
        self.product_list = QListWidget()
        self._productos_original = list(productos)
        self._mostrar_productos(productos)
        left_layout.addWidget(self.product_list)

        # Tipo de venta
        left_layout.addWidget(QLabel("Tipo de venta:"))
        self.tipo_minorista = QRadioButton("Minorista")
        self.tipo_mayorista_unit = QRadioButton("Mayorista (unitario)")
        self.tipo_mayorista_total = QRadioButton("Mayorista (total personalizado)")
        self.tipo_minorista.setChecked(True)
        tipo_layout = QHBoxLayout()
        tipo_layout.addWidget(self.tipo_minorista)
        tipo_layout.addWidget(self.tipo_mayorista_unit)
        tipo_layout.addWidget(self.tipo_mayorista_total)
        left_layout.addLayout(tipo_layout)
        self.tipo_venta_group = QButtonGroup(self)
        self.tipo_venta_group.setExclusive(True)
        self.tipo_venta_group.addButton(self.tipo_minorista)
        self.tipo_venta_group.addButton(self.tipo_mayorista_unit)
        self.tipo_venta_group.addButton(self.tipo_mayorista_total)

        # Cantidad
        left_layout.addWidget(QLabel("Cantidad:"))
        self.cantidad_spin = QSpinBox()
        self.cantidad_spin.setMinimum(1)
        self.cantidad_spin.setMaximum(100000)
        left_layout.addWidget(self.cantidad_spin)


        # Precio unitario y total
        precio_layout = QHBoxLayout()
        self.precio_spin = QDoubleSpinBox()
        self.precio_spin.setMinimum(0)
        self.precio_spin.setMaximum(1000000)
        self.precio_spin.setDecimals(2)
        self.precio_spin.setPrefix("$")
        precio_layout.addWidget(QLabel("Precio unitario:"))
        precio_layout.addWidget(self.precio_spin)
        self.precio_total_spin = QDoubleSpinBox()
        self.precio_total_spin.setMinimum(0)
        self.precio_total_spin.setMaximum(100000000)
        self.precio_total_spin.setDecimals(2)
        self.precio_total_spin.setPrefix("$")
        precio_layout.addWidget(QLabel("Precio total:"))
        precio_layout.addWidget(self.precio_total_spin)
        left_layout.addLayout(precio_layout)

        # Descuento
        descuento_layout = QHBoxLayout()
        descuento_layout.addWidget(QLabel("Descuento:"))
        self.descuento_spin = QDoubleSpinBox()
        self.descuento_spin.setMinimum(0)
        self.descuento_spin.setMaximum(1000000)
        self.descuento_spin.setDecimals(2)
        self.descuento_spin.setValue(0)
        descuento_layout.addWidget(self.descuento_spin)
        self.descuento_tipo_combo = QComboBox()
        self.descuento_tipo_combo.addItems(["%", "$"])
        descuento_layout.addWidget(self.descuento_tipo_combo)
        left_layout.addLayout(descuento_layout)
        self.descuento_spin.valueChanged.connect(self._recalcular_totales)
        self.descuento_tipo_combo.currentIndexChanged.connect(self._on_descuento_tipo_changed)

        # IVA eliminado: ya no se muestran opciones para aplicar IVA

        # Selector de tipo fiscal
        tipo_fiscal_layout = QHBoxLayout()
        tipo_fiscal_layout.addWidget(QLabel("Tipo fiscal:"))
        self.tipo_fiscal_combo = QComboBox()
        self.tipo_fiscal_combo.addItems(["Venta gravada", "Venta exenta", "Venta no sujeta"])
        tipo_fiscal_layout.addWidget(self.tipo_fiscal_combo)
        left_layout.addLayout(tipo_fiscal_layout)

        # Resumen del producto actual
        self.item_precio_label = QLabel("Precio U. sin IVA: $0.00")
        self.item_sumas_label = QLabel("Sumas sin IVA: $0.00")
        self.item_total_sin_desc_label = QLabel("Total con IVA sin descuento: $0.00")
        self.item_descuento_label = QLabel("Descuento: -$0.00")
        self.item_subtotal_label = QLabel("Subtotal final (con IVA): $0.00")
        left_layout.addWidget(self.item_precio_label)
        left_layout.addWidget(self.item_sumas_label)
        left_layout.addWidget(self.item_total_sin_desc_label)
        left_layout.addWidget(self.item_descuento_label)
        left_layout.addWidget(self.item_subtotal_label)

        # Botón agregar a venta
        self.btn_agregar = QPushButton("Agregar a venta")
        left_layout.addWidget(self.btn_agregar)
        self.btn_agregar.clicked.connect(self._agregar_a_venta)

        # Tabla de productos agregados
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([
            "Cantidad", "Producto", "P. Unit. (IVA inc.)", "Descuento", "Total", "Eliminar"
        ])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        left_layout.addWidget(self.table)
        self.table.cellClicked.connect(self._eliminar_fila)

        # Resumen de la venta
        self.total_label = QLabel("Total venta (con IVA): $0.00")
        left_layout.addWidget(self.total_label)

        # Botón para registrar la venta
        self.btn_ok = QPushButton("Registrar")
        self.btn_ok.clicked.connect(self._validar_y_accept)
        left_layout.addWidget(self.btn_ok)

        # --- LADO DERECHO: datos del cliente ---
        right_layout = QVBoxLayout()

        right_layout.addWidget(QLabel("Vendedor (trabajador):"))
        self.vendedor_combo = QComboBox()
        self.vendedor_combo.addItem("Sin vendedor")
        for v in vendedores_trabajadores:
            self.vendedor_combo.addItem(v["nombre"])
        self.vendedores_trabajadores = vendedores_trabajadores
        right_layout.addWidget(self.vendedor_combo)

        self.comision_chk = QCheckBox("Aplicar comisión")
        right_layout.addWidget(self.comision_chk)
        com_layout = QHBoxLayout()
        com_layout.addWidget(QLabel("%:"))
        self.comision_pct_spin = QDoubleSpinBox()
        self.comision_pct_spin.setRange(0, 100)
        self.comision_pct_spin.setDecimals(2)
        self.comision_pct_spin.setEnabled(False)
        com_layout.addWidget(self.comision_pct_spin)
        self.comision_tipo_combo = QComboBox()
        self.comision_tipo_combo.addItems(["Añadida al total", "Desglosada (incluida en el precio)"])
        self.comision_tipo_combo.setEnabled(False)
        com_layout.addWidget(self.comision_tipo_combo)
        right_layout.addLayout(com_layout)
        self.comision_label = QLabel("Comisión: $0.00")
        right_layout.addWidget(self.comision_label)
        self.comision_chk.stateChanged.connect(self._toggle_comision_inputs)
        self.comision_pct_spin.valueChanged.connect(self._recalcular_totales)
        self.comision_tipo_combo.currentIndexChanged.connect(self._recalcular_totales)

        right_layout.addWidget(QLabel("Cliente:"))
        self.cliente_btn = QPushButton("Seleccionar Cliente")
        self.cliente_label = QLabel("(Ningún cliente seleccionado)")
        right_layout.addWidget(self.cliente_btn)
        right_layout.addWidget(self.cliente_label)
        self.selected_cliente = None

        right_layout.addWidget(QLabel("NRC:"))
        self.nrc_edit = QLineEdit()
        self.nrc_edit.setPlaceholderText("NRC del cliente")
        right_layout.addWidget(self.nrc_edit)

        right_layout.addWidget(QLabel("NIT:"))
        self.nit_edit = QLineEdit()
        nit_validator = QRegularExpressionValidator(QRegularExpression(r"\d{0,14}"))
        self.nit_edit.setValidator(nit_validator)
        self.nit_edit.setMaxLength(14)
        self.nit_edit.setPlaceholderText("NIT del cliente")
        right_layout.addWidget(self.nit_edit)

        right_layout.addWidget(QLabel("Giro:"))
        self.giro_edit = QLineEdit()
        self.giro_edit.setPlaceholderText("Giro del cliente")
        right_layout.addWidget(self.giro_edit)

        right_layout.addWidget(QLabel("Correo electrónico:"))
        self.email_edit = QLineEdit()
        self.email_edit.setPlaceholderText("Correo electrónico")
        right_layout.addWidget(self.email_edit)
        right_layout.addStretch(1)

        right_layout.addWidget(QLabel("No. Remisión:"))
        self.no_remision_edit = QLineEdit()
        self.no_remision_edit.setPlaceholderText("Número de remisión")
        right_layout.addWidget(self.no_remision_edit)

        right_layout.addWidget(QLabel("Orden No.:"))
        self.orden_no_edit = QLineEdit()
        self.orden_no_edit.setPlaceholderText("Número de orden")
        right_layout.addWidget(self.orden_no_edit)

        right_layout.addWidget(QLabel("Condición de pago:"))
        self.condicion_pago_combo = QComboBox()
        self.condicion_pago_combo.addItem("Contado", 1)
        self.condicion_pago_combo.addItem("Crédito", 2)
        self.condicion_pago_combo.addItem("Otros", 3)
        right_layout.addWidget(self.condicion_pago_combo)

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

        right_layout.addWidget(self.credit_fields_widget)

        right_layout.addWidget(QLabel("Venta a cuenta de:"))
        self.venta_a_cuenta_de_edit = QLineEdit()
        self.venta_a_cuenta_de_edit.setPlaceholderText("Venta a cuenta de")
        right_layout.addWidget(self.venta_a_cuenta_de_edit)
        right_layout.addWidget(QLabel("DUI/NIT:"))
        self.venta_documento_edit = QLineEdit()
        self.venta_documento_edit.setPlaceholderText("Documento")
        right_layout.addWidget(self.venta_documento_edit)

        right_layout.addWidget(QLabel("Fecha nota de remisión anterior:"))
        self.fecha_remision_anterior = QDateEdit(QDate.currentDate())
        self.fecha_remision_anterior.setCalendarPopup(True)
        right_layout.addWidget(self.fecha_remision_anterior)

        right_layout.addWidget(QLabel("Fecha de remisión:"))
        self.fecha_remision = QDateEdit(QDate.currentDate())
        self.fecha_remision.setCalendarPopup(True)
        right_layout.addWidget(self.fecha_remision)

        # --- Agrega ambos layouts al principal ---
        main_layout.addLayout(left_layout, 2)
        main_layout.addLayout(right_layout, 1)
        self.setLayout(main_layout)

        # Estado
        self.productos_data = productos

        # Conexiones adicionales
        self.cliente_btn.clicked.connect(self._abrir_selector_cliente)
        self.product_list.currentRowChanged.connect(self._actualizar_precio_defecto)
        self.tipo_minorista.toggled.connect(self._actualizar_precio_defecto)
        self.tipo_mayorista_unit.toggled.connect(self._actualizar_precio_defecto)
        self.tipo_mayorista_total.toggled.connect(self._actualizar_precio_defecto)
        self.cantidad_spin.valueChanged.connect(self._recalcular_totales)
        self.precio_spin.valueChanged.connect(self._recalcular_totales)
        self.precio_total_spin.valueChanged.connect(self._recalcular_totales)
        self.product_search.textChanged.connect(self._filtrar_productos)
        self.tipo_minorista.toggled.connect(self._toggle_precio_edicion)
        self.tipo_mayorista_unit.toggled.connect(self._toggle_precio_edicion)
        self.tipo_mayorista_total.toggled.connect(self._toggle_precio_edicion)
        self.product_list.currentRowChanged.connect(self._actualizar_Distribuidor_por_producto)

        if productos:
            self.product_list.setCurrentRow(0)
            self._actualizar_precio_defecto()
        self._actualizar_resumen()
        self._on_descuento_tipo_changed()
        self._update_condicion_pago_fields()
        self.load_payment_data(venta_extra)

    def set_productos_data(self, productos_data):
        self.productos_data = productos_data

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
        precio = 0
        if prod:
            if self.tipo_minorista.isChecked():
                precio = get_field(prod, "precio_venta_minorista", 0)
            elif self.tipo_mayorista_unit.isChecked():
                precio = get_field(prod, "precio_venta_mayorista", 0)
            else:
                precio = get_field(prod, "precio_venta_mayorista", 0)
        self.precio_spin.blockSignals(True)
        self.precio_total_spin.blockSignals(True)
        self.precio_spin.setValue(float(precio))
        self.precio_total_spin.setValue(float(precio) * self.cantidad_spin.value())
        self.precio_spin.blockSignals(False)
        self.precio_total_spin.blockSignals(False)
        self._toggle_precio_edicion()
        self._recalcular_totales()

    def _toggle_precio_edicion(self):
        if self.tipo_minorista.isChecked():
            self.precio_spin.setEnabled(True)
            self.precio_total_spin.setEnabled(False)
        elif self.tipo_mayorista_unit.isChecked():
            self.precio_spin.setEnabled(True)
            self.precio_total_spin.setEnabled(False)
        elif self.tipo_mayorista_total.isChecked():
            self.precio_spin.setEnabled(False)
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
        cantidad = Decimal(self.cantidad_spin.value())

        if self.tipo_mayorista_total.isChecked():
            precio_total_con_iva = Decimal(str(self.precio_total_spin.value()))
            precio_unitario_con_iva = precio_total_con_iva / cantidad if cantidad > 0 else Decimal("0")
            self.precio_spin.blockSignals(True)
            self.precio_spin.setValue(float(precio_unitario_con_iva))
            self.precio_spin.blockSignals(False)
        else:
            precio_unitario_con_iva = Decimal(str(self.precio_spin.value()))
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

        self.item_precio_label.setText(f"Precio U. sin IVA: ${precio_unitario_sin_iva_disp:.2f}")
        self.item_sumas_label.setText(f"Sumas sin IVA: ${sumas_disp:.2f}")
        self.item_total_sin_desc_label.setText(f"Total con IVA sin descuento: ${total_sin_desc_disp:.2f}")
        self.item_descuento_label.setText(f"Descuento: -${descuento_disp:.2f}")
        self.item_subtotal_label.setText(f"Subtotal final (con IVA): ${subtotal_final_disp:.2f}")
        self.comision_label.setText(f"Comisión: ${comision_disp:.2f}")

    def _agregar_a_venta(self):
        idx = self.product_list.currentRow()
        if idx < 0:
            QMessageBox.warning(self, "Validación", "Seleccione un producto del inventario actual.")
            return
        lote = self.productos[idx]
        cantidad = Decimal(self.cantidad_spin.value())

        if self.tipo_mayorista_total.isChecked():
            precio_total_con_iva = Decimal(str(self.precio_total_spin.value()))
            precio_unitario_con_iva = precio_total_con_iva / cantidad if cantidad > 0 else Decimal("0")
        else:
            precio_unitario_con_iva = Decimal(str(self.precio_spin.value()))
            precio_total_con_iva = precio_unitario_con_iva * cantidad

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
            precio_unitario_sin_iva = precio_unitario_con_iva / IVA_FACTOR
            subtotal_sin_iva = precio_unitario_sin_iva * cantidad
            subtotal_con_descuento_sin_iva = importe_con_iva_para_desglose / IVA_FACTOR
            iva = importe_con_iva_para_desglose - subtotal_con_descuento_sin_iva
        else:
            precio_unitario_sin_iva = precio_unitario_con_iva
            subtotal_sin_iva = precio_unitario_sin_iva * cantidad
            subtotal_con_descuento_sin_iva = importe_con_iva_para_desglose
            iva = Decimal("0")

        q8 = Decimal("0.00000001")
        self.venta_items.append({
            "lote_id": lote["lote_id"],
            "producto_id": lote["producto_id"],
            "producto": lote["nombre"],
            "cantidad": int(cantidad),
            "precio": float(precio_unitario_sin_iva.quantize(q8)),
            "precio_con_iva": float(precio_unitario_con_iva.quantize(q8)),
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
            "fecha_vencimiento": lote.get("fecha_vencimiento", "")
        })

        self._actualizar_tabla()
        self._recalcular_totales()
        self._actualizar_resumen()


    def _actualizar_tabla(self):
        self.table.setRowCount(len(self.venta_items))
        for i, item in enumerate(self.venta_items):
            self.table.setItem(i, 0, QTableWidgetItem(str(item["cantidad"])))
            self.table.setItem(i, 1, QTableWidgetItem(item["producto"]))
            self.table.setItem(i, 2, QTableWidgetItem(f"${item['precio_con_iva']:.2f}"))
            self.table.setItem(i, 3, QTableWidgetItem(f"{item['descuento']}{item['descuento_tipo']}"))
            self.table.setItem(i, 4, QTableWidgetItem(f"${item['total']:.2f}"))
            btn = QPushButton("Eliminar")
            btn.setStyleSheet(
                "background-color: #b71c1c; color: #fff; border-radius: 6px; font-size:9px;"
                "min-width:70px; max-width:100px; min-height:10px; max-height:15px;"
            )
            btn.clicked.connect(lambda _, row=i: self._eliminar_item(row))
            self.table.setCellWidget(i, 5, btn)

    def _actualizar_resumen(self):
        total = sum(item.get("total", 0) for item in self.venta_items)
        self.total_label.setText(f"Total venta (con IVA): ${total:.2f}")

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
            QMessageBox.warning(self, "Validación", "Debe seleccionar un cliente válido.")
            return
        if not self.venta_items:
            QMessageBox.warning(self, "Validación", "Debe agregar al menos un producto a la venta.")
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

        return {
            "cliente": self.selected_cliente if self.selected_cliente else {},
            "items": self.venta_items,
            "tipo_venta": (
                "Minorista" if self.tipo_minorista.isChecked()
                else "Mayorista (unitario)" if self.tipo_mayorista_unit.isChecked()
                else "Mayorista (total personalizado)"
            ),
            "precio_total_manual": float(self.precio_total_spin.value()),
            "iva_agregado": self.iva_agregado_radio.isChecked() if hasattr(self, "iva_agregado_radio") else False,
            "nrc": self.nrc_edit.text(),
            "nit": self.nit_edit.text(),
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
            QMessageBox.warning(self, "Datos inválidos", "Debe ingresar un NIT válido.")
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

        form = [
            ("Código:", self.codigo_edit),
            ("Nombre completo:", self.nombre_edit),
            ("Nombre comercial:", self.nombre_comercial_edit),
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
        for label, widget in form:
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
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


    def _validar_y_accept(self):
        nrc = self.nrc_edit.text().strip()
        if nrc and not validar_nrc(nrc):
            QMessageBox.warning(self, "Validación", "Ingrese un NRC válido.")
            return
        nit = self.nit_edit.text().strip()
        if nit and not validar_nit(nit):
            QMessageBox.warning(self, "Validación", "Ingrese un NIT válido.")
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
        }

class VendedorDialog(QDialog):
    def __init__(self, Distribuidores, parent=None, vendedor=None, codigo_sugerido=None):
        super().__init__(parent)
        self.setWindowTitle("Agregar/Editar Vendedor")
        layout = QVBoxLayout()

        self.codigo_edit = QLineEdit()
        self.nombre_edit = QLineEdit()
        self.dui_edit = QLineEdit()
        self.dui_edit.setValidator(QIntValidator(0, 999999999))
        self.dui_edit.setMaxLength(9)
        self.descripcion_edit = QLineEdit()
        self.Distribuidor_combo = QComboBox()
        self.Distribuidores = Distribuidores
        self.Distribuidor_combo.addItem("Sin Distribuidor", None)
        for d in self.Distribuidores:
            self.Distribuidor_combo.addItem(d["nombre"], d["id"])
        self._vendedor_id = vendedor.get("id") if vendedor else None

        layout.addWidget(QLabel("Código:"))
        layout.addWidget(self.codigo_edit)
        layout.addWidget(QLabel("Nombre:"))
        layout.addWidget(self.nombre_edit)
        layout.addWidget(QLabel("DUI:"))
        layout.addWidget(self.dui_edit)
        layout.addWidget(QLabel("Descripción:"))
        layout.addWidget(self.descripcion_edit)
        layout.addWidget(QLabel("Distribuidor:"))
        layout.addWidget(self.Distribuidor_combo)

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
            self.descripcion_edit.setText(vendedor.get("descripcion", ""))
            Distribuidor_id = vendedor.get("Distribuidor_id")
            if Distribuidor_id:
                idx = self.Distribuidor_combo.findData(Distribuidor_id)
                if idx >= 0:
                    self.Distribuidor_combo.setCurrentIndex(idx)

    def _validar_y_aceptar(self):
        nombre = self.nombre_edit.text().strip()
        if not nombre:
            QMessageBox.warning(self, "Datos inválidos", "El nombre no puede estar vacío.")
            return
        if hasattr(self, 'telefono_edit'):
            telefono = self.telefono_edit.text().strip()
            if not telefono:
                QMessageBox.warning(self, "Datos inválidos", "El teléfono no puede estar vacío.")
                return
        if hasattr(self, 'nit_edit'):
            nit = self.nit_edit.text().strip()
            if not nit or not validar_nit(nit):
                QMessageBox.warning(self, "Datos inválidos", "Debe ingresar un NIT válido.")
                return
        if hasattr(self, 'email_edit'):
            email = self.email_edit.text().strip()
            if not email or not validar_email(email):
                QMessageBox.warning(self, "Datos inválidos", "Debe ingresar un email válido.")
                return
        self.accept()
    def get_data(self):
        return {
            "codigo": self.codigo_edit.text(),
            "nombre": self.nombre_edit.text(),
            "dui": self.dui_edit.text(),
            "descripcion": self.descripcion_edit.text(),
            "Distribuidor_id": self.Distribuidor_combo.currentData(),
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
    def __init__(self, compra, detalles, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Detalle de Compra")
        layout = QVBoxLayout()

        # Depuración: registra los detalles que llegan
        logger.debug("DETALLES DE COMPRA: %s", detalles)

        # --- Obtén los nombres de vendedor y Distribuidor ---
        vendedores = []
        Distribuidores = []
        productos = []
        if parent and hasattr(parent, "manager"):
            vendedores = getattr(parent.manager, "_vendedores", [])
            Distribuidores = getattr(parent.manager, "_Distribuidores", [])
            productos = getattr(parent.manager, "_products", [])
        vendedores_dict = {v["id"]: v["nombre"] for v in vendedores}
        Distribuidores_dict = {d["id"]: d["nombre"] for d in Distribuidores}
        productos_dict = {p["id"]: p["nombre"] for p in productos}

        vendedor_nombre = vendedores_dict.get(compra.get("vendedor_id"), "Desconocido")
        Distribuidor_nombre = Distribuidores_dict.get(compra.get("Distribuidor_id"), "Desconocido")

        layout.addWidget(QLabel(f"Fecha: {compra.get('fecha', '')}"))
        layout.addWidget(QLabel(f"Vendedor: {vendedor_nombre}"))
        layout.addWidget(QLabel(f"Distribuidor: {Distribuidor_nombre}"))
        layout.addWidget(QLabel(f"Total general: ${compra.get('total', 0):.2f}"))

        # --- Tabla de detalles ---
        table = QTableWidget(len(detalles), 8)
        table.setHorizontalHeaderLabels([
            "Producto", "Cantidad", "Precio U.", "Subtotal", "Descuento",
            "IVA", "Comisión", "Vencimiento"
        ])
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        for i, d in enumerate(detalles):
            nombre_producto = productos_dict.get(d.get("producto_id"), "Desconocido")
            precio_unitario = d.get("precio_unitario", d.get("precio", 0))
            subtotal = d.get("cantidad", 0) * precio_unitario
            table.setItem(i, 0, QTableWidgetItem(nombre_producto))
            table.setItem(i, 1, QTableWidgetItem(str(d.get("cantidad", ""))))
            table.setItem(i, 2, QTableWidgetItem(f"${precio_unitario:.2f}"))
            table.setItem(i, 3, QTableWidgetItem(f"${subtotal:.2f}"))
            table.setItem(i, 4, QTableWidgetItem(f"${d.get('descuento', 0):.2f}"))
            table.setItem(i, 5, QTableWidgetItem(f"${d.get('iva', 0):.2f}"))
            # Mostrar el monto de la comisión:
            table.setItem(i, 6, QTableWidgetItem(f"${d.get('comision_monto', 0):.2f}"))
            table.setItem(i, 7, QTableWidgetItem(str(d.get("fecha_vencimiento", ""))))
        table.resizeColumnsToContents()
        layout.addWidget(table)
        self.setLayout(layout)

class DatosNegocioDialog(QDialog):
    """Diálogo para editar los datos necesarios para la facturación."""

    def __init__(self, datos=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Datos del negocio")
        form = QFormLayout()
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
        self.tipo_contribuyente = QLineEdit()
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
        form.addRow("Teléfono:", self.telefono)
        form.addRow("Correo:", self.correo)
        form.addRow("Departamento:", self.departamento)
        form.addRow("Municipio:", self.municipio)
        form.addRow("Dirección:", self.complemento)
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
            self.set_data(datos)

    def _on_save(self):
        try:
            self.get_data()
        except ValueError as exc:
            QMessageBox.warning(self, "Validación", str(exc))
            return
        self.accept()

    def get_data(self):
        departamento = str(self.departamento.currentData() or "").zfill(2)
        municipio = str(self.municipio.currentData() or "")
        complemento = self.complemento.text()
        if departamento not in CAT012_DEPARTAMENTOS:
            raise ValueError("Departamento inválido")
        if municipio not in CAT013_MUNICIPIOS:
            raise ValueError("Municipio inválido")
        if not complemento:
            raise ValueError("Dirección requerida")
        return {
            "nit": self.nit.text(),
            "nrc": self.nrc.text(),
            "dui": solo_digitos(self.dui.text()),
            "nombre": self.nombre.text(),
            "nombreComercial": self.nombre_comercial.text(),
            "cod_giro": self.cod_giro.text(),
            "codActividad": self.cod_giro.text(),
            "descActividad": self.desc_actividad.text(),
            "tipoContribuyente": self.tipo_contribuyente.text(),
            "telefono": self.telefono.text(),
            "correo": self.correo.text(),
            "direccion": {
                "departamento": departamento,
                "municipio": municipio,
                "complemento": complemento,
            },
        }

    def set_data(self, datos):
        self.nit.setText(datos.get("nit", ""))
        self.nrc.setText(datos.get("nrc", ""))
        self.dui.setText(datos.get("dui", ""))
        self.nombre.setText(datos.get("nombre", ""))
        self.nombre_comercial.setText(datos.get("nombreComercial", ""))
        self.cod_giro.setText(datos.get("cod_giro") or datos.get("codActividad", ""))
        self.desc_actividad.setText(datos.get("descActividad", ""))
        self.tipo_contribuyente.setText(datos.get("tipoContribuyente", ""))
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
        guardar = QPushButton("Guardar")
        cancelar = QPushButton("Cancelar")
        btns.addWidget(guardar)
        btns.addWidget(cancelar)
        layout.addLayout(btns)
        self.setLayout(layout)
        guardar.clicked.connect(self.accept)
        cancelar.clicked.connect(self.reject)
        self.combo_email_provider.currentTextChanged.connect(self._update_smtp_fields)
        self._update_smtp_fields()
        if datos:
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
    def __init__(self, db=None, prefijo="DTE-01-S001P001", parent=None):
        super().__init__(parent)
        self.db = db or DB()
        self.prefijo = prefijo
        self.setWindowTitle("Configuración de correlativo")

        layout = QVBoxLayout(self)
        self.correlativos_table = QTableWidget(0, 3)
        self.correlativos_table.setHorizontalHeaderLabels([
            "Tipo",
            "Correlativo",
            "",
        ])
        self.correlativos_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch
        )
        self.correlativos_table.verticalHeader().setVisible(False)
        layout.addWidget(self.correlativos_table)

        btns = QHBoxLayout()
        guardar = QPushButton("Guardar")
        cancelar = QPushButton("Cancelar")
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
        for tipo in ["01", "03", "04", "05", "06"]:
            row = self.correlativos_table.rowCount()
            self.correlativos_table.insertRow(row)
            self.correlativos_table.setItem(row, 0, QTableWidgetItem(tipo))
            spin = QSpinBox()
            spin.setMaximum(999999999)
            valor = self.db.get_dte_correlativo(tipo, sucursal, punto)
            spin.setValue(valor)
            self._original_correlativos[tipo] = valor
            self.correlativos_table.setCellWidget(row, 1, spin)
            btn = QPushButton("Reiniciar")
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
    def __init__(self, dte_api=None, fe_config=None, env_config=None, parent=None, db=None):
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
        self.api_user = QLineEdit()
        self.api_pwd = QLineEdit()
        self.api_pwd.setEchoMode(QLineEdit.Password)
        self.dte_activo = QCheckBox("Certificado activo")
        self.dte_activo.setChecked(True)
        self.tipo_contribuyente = QComboBox()
        self.tipo_contribuyente.addItems(["Persona Natural", "Persona Jurídica"])
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
        form.addRow(self.envio_automatico)
        form.addRow(self.adjuntar_json_correo)
        form.addRow(self.incluir_sello_pdf)
        form.addRow(self.guardar_respuesta_bd)
        layout.addLayout(form)

        self.correlativos_btn = QPushButton("Configuración de correlativo")
        layout.addWidget(self.correlativos_btn)

        btns = QHBoxLayout()
        guardar = QPushButton("Guardar")
        restaurar = QPushButton("Restaurar")
        cancelar = QPushButton("Cancelar")
        btns.addWidget(guardar)
        btns.addWidget(restaurar)
        btns.addWidget(cancelar)
        layout.addLayout(btns)
        self.setLayout(layout)
        guardar.clicked.connect(self.accept)
        cancelar.clicked.connect(self.reject)
        restaurar.clicked.connect(self._restore_defaults)
        restaurar.clicked.connect(self._set_default_urls)
        self.token_btn.clicked.connect(self._fetch_token)
        self.cert_btn.clicked.connect(self._select_cert)
        self.ambiente_hacienda.currentIndexChanged.connect(self._handle_ambiente_changed)
        self.ambiente_hacienda.currentTextChanged.connect(self._set_default_urls)
        self.endpoint_hacienda.textChanged.connect(self._set_default_urls)
        self.correlativos_btn.clicked.connect(self._open_correlativos)
        self.modo_transmision.currentIndexChanged.connect(
            self._update_contingencia_visibility
        )
        self._ambiente_actual = self._current_env_key()
        if dte_api or fe_config or env_config:
            self.set_data(dte_api or {}, fe_config or {}, env_config or {})
        else:
            self._set_default_urls()
            self._update_contingencia_visibility()

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
        self.tipo_contribuyente.setCurrentText(dte_api.get("tipo_contribuyente", "Persona Natural"))
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
        if (
            not self.endpoint_hacienda.text()
            or not self.auth_url.text()
            or not self.recepcion_url.text()
        ):
            self._set_default_urls()
        self.envio_automatico.setChecked(dte_api.get("envio_automatico", False))
        self.adjuntar_json_correo.setChecked(dte_api.get("adjuntar_json_correo", False))
        self.incluir_sello_pdf.setChecked(dte_api.get("incluir_sello_pdf", False))
        self.guardar_respuesta_bd.setChecked(dte_api.get("guardar_respuesta", False))
        nit = fe_config.get("nit", "")
        cert = os.path.join(jws.CERT_UPLOAD_DIR, f"{nit}.crt") if nit else ""
        if cert and os.path.isfile(cert):
            self.cert_path.setText(cert)

    def _restore_defaults(self):
        """Restaurar valores por defecto de URLs y token."""
        self.token_hacienda.clear()
        self.endpoint_hacienda.clear()
        self.auth_url.clear()
        self.recepcion_url.clear()

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
        try:
            dest_dir = os.path.abspath(jws.CERT_UPLOAD_DIR)
            os.makedirs(dest_dir, exist_ok=True)
            # Remove any existing files so only the new certificate remains
            for name in os.listdir(dest_dir):
                existing = os.path.join(dest_dir, name)
                try:
                    if os.path.isfile(existing) or os.path.islink(existing):
                        os.remove(existing)
                    elif os.path.isdir(existing):
                        shutil.rmtree(existing)
                except Exception as cleanup_exc:
                    logger.warning("No se pudo eliminar %s: %s", existing, cleanup_exc)
            dest = os.path.join(dest_dir, f"{nit}.crt")
            shutil.copy(file_path, dest)
            os.chmod(dest, 0o644)
            jws.set_cert_upload_dir(dest_dir)
            self.cert_path.setText(dest)
            QMessageBox.information(self, "Éxito", "Certificado copiado correctamente.")
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
        if token_pruebas is not None and token_pruebas != "":
            dte_api["token_pruebas"] = token_pruebas
        if token_produccion is not None and token_produccion != "":
            dte_api["token_produccion"] = token_produccion
        fe_config = {
            "nit": self.dte_nit.text(),
            "passwordPri": base64.b64encode(self.dte_pass.text().encode()).decode() if self.dte_pass.text() else "",
            "activo": self.dte_activo.isChecked(),
        }
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
        if self._contingencia_tipo is not None:
            dte_api["tipo_contingencia"] = int(self._contingencia_tipo)
        else:
            dte_api["tipo_contingencia"] = None
        dte_api["motivo_contin"] = self._contingencia_motivo
        return dte_api, fe_config, urls

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

    def accept(self):
        if self._is_contingencia_selected():
            if self._contingencia_tipo is None:
                QMessageBox.warning(
                    self,
                    "Configuración incompleta",
                    "Selecciona el tipo de contingencia antes de guardar.",
                )
                return
            if self._contingencia_tipo == 5 and not self._contingencia_motivo.strip():
                QMessageBox.warning(
                    self,
                    "Configuración incompleta",
                    "Ingresa el motivo de contingencia requerido para el tipo 5.",
                )
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
            QMessageBox.warning(self, "Validación", "El NIT ingresado no es válido.")
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
        self.role_combo = QComboBox()
        self.role_combo.addItems(["guest", "user", "admin"])
        idx = self.role_combo.findText(role)
        if idx >= 0:
            self.role_combo.setCurrentIndex(idx)
        form.addRow("Usuario:", self.username_edit)
        form.addRow("Contraseña:", self.password_edit)
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

    def get_data(self):
        return (
            self.username_edit.text().strip(),
            self.password_edit.text().strip(),
            self.role_combo.currentText(),
        )


class UserConfigDialog(QDialog):
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("Configuración de usuarios")
        layout = QVBoxLayout(self)
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["ID", "Usuario", "Rol"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.table)
        btns = QHBoxLayout()
        add_btn = QPushButton("Agregar")
        edit_btn = QPushButton("Editar")
        del_btn = QPushButton("Eliminar")
        btns.addWidget(add_btn)
        btns.addWidget(edit_btn)
        btns.addWidget(del_btn)
        layout.addLayout(btns)
        add_btn.clicked.connect(self._add_user)
        edit_btn.clicked.connect(self._edit_user)
        del_btn.clicked.connect(self._delete_user)
        self.refresh()

    def refresh(self):
        users = self.db.get_users()
        self.table.setRowCount(len(users))
        for row, u in enumerate(users):
            self.table.setItem(row, 0, QTableWidgetItem(str(u["id"])))
            self.table.setItem(row, 1, QTableWidgetItem(u["username"]))
            self.table.setItem(row, 2, QTableWidgetItem(u["role"]))

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
            except Exception:
                QMessageBox.warning(self, "Error", "No se pudo actualizar el usuario")
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


