from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QTableView, QLineEdit,
    QPushButton, QTabWidget, QMessageBox, QSplitter, QMenuBar, QAction, QFileDialog,
    QListWidget, QListWidgetItem, QLabel, QComboBox, QTableWidget, QTableWidgetItem, QDialog,
    QDateEdit, QCheckBox, QTextEdit, QAbstractItemView, QHeaderView, QSizePolicy,
    QInputDialog, QFormLayout, QDialogButtonBox, QSpinBox, QFrame, QButtonGroup, QRadioButton,
    QStyledItemDelegate, QStyleOptionViewItem, QStyle, QStackedWidget, QApplication,
    QProgressBar, QScrollArea, QGridLayout, QTextEdit
)
from PyQt5.QtCore import Qt, QDate, QThread, pyqtSignal, QTimer, QRectF, QSize, QEvent, QModelIndex
from PyQt5.QtGui import QColor, QPainter, QBrush, QPainterPath, QPen
import os
import json
import sys
import subprocess
import unicodedata
from typing import Mapping
from pathlib import Path
import inventory_manager as im
from paths import (
    AUTO_BACKUP_DIR,
    DATOS_NEGOCIO_PATH,
    CONFIG_NEGOCIO_PATH,
    LAST_INVENTORY_PATH,
)
from dialogs import (
    RegisterSaleDialog,
    ProductDialog,
    RegisterPurchaseDialog,
    DistribuidorDialog,
    DistribuidorInfoDialog,
    ClienteDialog,
    EstadoCuentaDialog,
    UserConfigDialog,
    CompraDetalleDialog,
    SaleConfirmationDialog,
)

from sales_tab import SalesTab
from facturacion_tab import FacturacionTab
from datetime import datetime, date, timedelta

from num2words import num2words  # Instala las dependencias con: pip install -r requirements.txt

from factura_sv import generar_factura_electronica_pdf
from decimal import Decimal, ROUND_HALF_UP
from utils.fiscal_extra import build_fiscal_extra
from utils.resumen import sync_condicion_operacion_flags
from utils.monto import monto_a_texto_sv
from utils.jws import sign_json
from utils.firmador import iniciar_firmador, detener_firmador, firmador_activo
from mh_auth import invalidate_token_cache
from utils.party_resolver import normalize_identifier, resolve_party_names
from utils.sanitize import solo_digitos
from utils.facturacion_records import (
    TIPO_DTE_DESC,
    canonical_tipo_label,
    get_facturacion_rows,
)
import dte
from utils.doc_generation import generate_invoice_pdf, generate_ticket_pdf
import logging

logger = logging.getLogger(__name__)


def _nit_digits(value: object) -> str:
    return solo_digitos(value) if value else ""


def _normalize_env_code(value: object) -> str:
    text = (str(value or "")).strip().lower()
    if text in {"01", "1", "produccion", "producción", "production", "prod"}:
        return "01"
    return "00"


def _clear_manual_tokens(dte_api: dict) -> bool:
    cleared = False
    for key in ("token_pruebas", "token_produccion"):
        if dte_api.get(key):
            dte_api[key] = ""
            cleared = True
    return cleared


def _update_env_nits(config: dict, nit: str) -> bool:
    if not nit:
        return False
    changed = False
    for key, value in config.items():
        if not isinstance(value, dict):
            continue
        fe_conf = value.get("firma_electronica")
        if isinstance(fe_conf, dict):
            if _nit_digits(fe_conf.get("nit")) != nit:
                fe_conf["nit"] = nit
                changed = True
        else:
            value["firma_electronica"] = {"nit": nit}
            changed = True
    return changed


def _sync_configs(datos: dict, config: dict, *, nit_hint: str | None = None, ambiente_hint: str | None = None) -> tuple[bool, bool, bool]:
    """Align negocio/config data returning (datos_changed, config_changed, tokens_reset)."""
    dte_api = datos.setdefault("dte_api", {})
    current_nit = _nit_digits(nit_hint or datos.get("nit"))
    prev_nit = _nit_digits(datos.get("nit"))
    prev_env = _normalize_env_code(dte_api.get("ambiente"))
    env_code = _normalize_env_code(ambiente_hint or dte_api.get("ambiente") or config.get("ambiente"))

    datos_changed = False
    config_changed = False
    tokens_reset = False

    if current_nit and prev_nit != current_nit:
        datos["nit"] = current_nit
        datos_changed = True
    if current_nit and _nit_digits(dte_api.get("nit")) != current_nit:
        dte_api["nit"] = current_nit
        datos_changed = True
    if env_code and prev_env != env_code:
        dte_api["ambiente"] = env_code
        datos_changed = True
    if env_code and config.get("ambiente") != env_code:
        config["ambiente"] = env_code
        config_changed = True
    if current_nit:
        config_changed |= _update_env_nits(config, current_nit)

    if current_nit and prev_nit != current_nit:
        tokens_reset = _clear_manual_tokens(dte_api)
    if env_code and prev_env != env_code:
        tokens_reset = _clear_manual_tokens(dte_api) or tokens_reset

    return datos_changed, config_changed, tokens_reset


class StockDelegate(QStyledItemDelegate):
    """Delegate para mostrar badges de stock en la tabla de productos."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index):
        try:
            stock_value = float(index.data(Qt.DisplayRole))
        except (ValueError, TypeError):
            stock_value = 0

        if stock_value <= 5:
            bg_color = QColor("#FEF2F2")
            text_color = QColor("#B91C1C")
            text = f"Crítico ({int(stock_value)})"
        elif stock_value <= 15:
            bg_color = QColor("#FFFBEB")
            text_color = QColor("#B45309")
            text = f"Bajo ({int(stock_value)})"
        else:
            bg_color = QColor("#ECFDF5")
            text_color = QColor("#047857")
            text = f"En Stock ({int(stock_value)})"

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)

        # Fondo base
        if option.state & QStyle.State_Selected:
            painter.fillRect(option.rect, QColor("#F0F9FF"))
        else:
            painter.fillRect(option.rect, QColor("white"))

        # Badge
        badge_rect = QRectF(option.rect)
        badge_rect.adjust(15, 10, -15, -10)
        path = QPainterPath()
        path.addRoundedRect(badge_rect, 6, 6)

        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(bg_color))
        painter.drawPath(path)

        painter.setPen(text_color)
        font = painter.font()
        font.setBold(True)
        font.setPointSize(9)
        painter.setFont(font)
        painter.drawText(badge_rect, Qt.AlignCenter, text)
        painter.restore()


class BatchQuantityDelegate(QStyledItemDelegate):
    """Badge de cantidad exacta para lotes."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index):
        try:
            amount = int(index.data(Qt.DisplayRole))
        except (ValueError, TypeError):
            amount = 0

        # Fondo tipo tarjeta
        card_rect = QRectF(option.rect)
        card_rect.adjust(0, 4, 0, -4)
        base_color = QColor("#FFFFFF") if index.row() % 2 == 0 else QColor("#F8FAFC")
        border_color = QColor("#E2E8F0")
        if option.state & QStyle.State_Selected:
            base_color = QColor("#E0F2FE")
            border_color = QColor("#BAE6FD")

        if amount <= 0:
            bg_color = QColor("#E5E7EB")
            text_color = QColor("#6B7280")
        elif amount <= 10:
            bg_color = QColor("#FEE2E2")
            text_color = QColor("#991B1B")
        else:
            bg_color = QColor("#ECFDF3")
            text_color = QColor("#166534")

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)

        card_path = QPainterPath()
        card_path.addRoundedRect(card_rect, 8, 8)
        painter.setPen(QPen(border_color))
        painter.setBrush(QBrush(base_color))
        painter.drawPath(card_path)

        badge_rect = QRectF(option.rect)
        badge_rect.adjust(10, 8, -10, -8)
        radius = min(badge_rect.height() / 2, 12)

        path = QPainterPath()
        path.addRoundedRect(badge_rect, radius, radius)

        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(bg_color))
        painter.fillPath(path, QBrush(bg_color))

        painter.setPen(QPen(text_color))
        font = option.font
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(badge_rect, Qt.AlignCenter, str(amount))
        painter.restore()


class ExpirationDelegate(QStyledItemDelegate):
    """Badge de vencimiento con semáforo temporal."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index):
        text = str(index.data(Qt.DisplayRole) or "").strip()
        parsed_date = None
        for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
            try:
                parsed_date = datetime.strptime(text, fmt).date()
                break
            except ValueError:
                continue

        today = date.today()
        if parsed_date:
            delta_days = (parsed_date - today).days
            display = parsed_date.isoformat()
            if delta_days < 0:
                bg_color, text_color = QColor("#111827"), QColor("#F8FAFC")
            elif delta_days < 90:
                bg_color, text_color = QColor("#FEE2E2"), QColor("#991B1B")
            elif delta_days < 180:
                bg_color, text_color = QColor("#FFF7ED"), QColor("#9A3412")
            else:
                bg_color, text_color = QColor("#ECFDF3"), QColor("#166534")
        else:
            display = text or "—"
            bg_color, text_color = QColor("#E5E7EB"), QColor("#475569")

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)

        card_rect = QRectF(option.rect)
        card_rect.adjust(0, 4, 0, -4)
        base_color = QColor("#FFFFFF") if index.row() % 2 == 0 else QColor("#F8FAFC")
        border_color = QColor("#E2E8F0")
        if option.state & QStyle.State_Selected:
            base_color = QColor("#E0F2FE")
            border_color = QColor("#BAE6FD")

        card_path = QPainterPath()
        card_path.addRoundedRect(card_rect, 8, 8)
        painter.setPen(QPen(border_color))
        painter.setBrush(QBrush(base_color))
        painter.drawPath(card_path)

        badge_rect = QRectF(option.rect)
        badge_rect.adjust(10, 8, -10, -8)
        radius = min(badge_rect.height() / 2, 12)

        path = QPainterPath()
        path.addRoundedRect(badge_rect, radius, radius)

        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(bg_color))
        painter.fillPath(path, QBrush(bg_color))

        painter.setPen(QPen(text_color))
        font = option.font
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(badge_rect, Qt.AlignCenter, display)
        painter.restore()


class CardRowDelegate(QStyledItemDelegate):
    """Crea fondo tipo tarjeta con márgenes para filas de tabla."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)

        card_rect_f = QRectF(option.rect)
        card_rect_f.adjust(0, 4, 0, -4)
        radius = 8

        if option.state & QStyle.State_Selected:
            bg_color = QColor("#E0F2FE")
            border_color = QColor("#BAE6FD")
        else:
            bg_color = QColor("#FFFFFF") if index.row() % 2 == 0 else QColor("#F8FAFC")
            border_color = QColor("#E2E8F0")

        path = QPainterPath()
        path.addRoundedRect(card_rect_f, radius, radius)

        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(bg_color))
        painter.fillPath(path, painter.brush())

        painter.setPen(QPen(border_color))
        painter.drawPath(path)

        # Pintar contenido sobre el fondo personalizado
        content_option = QStyleOptionViewItem(option)
        content_option.rect = card_rect_f.toRect().adjusted(10, 0, -10, 0)
        content_option.backgroundBrush = QBrush(Qt.NoBrush)
        super().paint(painter, content_option, index)
        painter.restore()


class CardBackgroundDelegate(QStyledItemDelegate):
    """Fondo de tarjeta para columnas estándar de la tabla de inventario actual."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)

        rect = QRectF(option.rect).adjusted(-1, 4, 1, -4)
        radius = 10
        col = index.column()
        last_col = index.model().columnCount() - 1

        if option.state & QStyle.State_Selected:
            bg_color = QColor("#E0F2FE")
            border_color = QColor("#BAE6FD")
            text_color = option.palette.highlightedText().color()
        else:
            bg_color = QColor("#FFFFFF") if index.row() % 2 == 0 else QColor("#F8FAFC")
            border_color = QColor("#E2E8F0")
            text_color = option.palette.text().color()

        path = QPainterPath()
        if col == 0:
            path.moveTo(rect.right(), rect.top())
            path.lineTo(rect.left() + radius, rect.top())
            path.quadTo(rect.left(), rect.top(), rect.left(), rect.top() + radius)
            path.lineTo(rect.left(), rect.bottom() - radius)
            path.quadTo(rect.left(), rect.bottom(), rect.left() + radius, rect.bottom())
            path.lineTo(rect.right(), rect.bottom())
            path.lineTo(rect.right(), rect.top())
        elif col == last_col:
            path.moveTo(rect.left(), rect.top())
            path.lineTo(rect.right() - radius, rect.top())
            path.quadTo(rect.right(), rect.top(), rect.right(), rect.top() + radius)
            path.lineTo(rect.right(), rect.bottom() - radius)
            path.quadTo(rect.right(), rect.bottom(), rect.right() - radius, rect.bottom())
            path.lineTo(rect.left(), rect.bottom())
            path.lineTo(rect.left(), rect.top())
        else:
            path.addRect(rect)

        painter.setPen(QPen(border_color))
        painter.setBrush(QBrush(bg_color))
        painter.fillPath(path, painter.brush())
        painter.drawPath(path)

        text_rect = QRectF(option.rect).adjusted(12, 0, -12, 0)
        painter.setPen(text_color)
        painter.setFont(option.font)
        painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, str(index.data() or ""))
        painter.restore()


class ModernListDelegate(QStyledItemDelegate):
    """Pinta elementos de lista modernos con iconos de acción a la derecha."""

    editClicked = pyqtSignal(QModelIndex)
    deleteClicked = pyqtSignal(QModelIndex)

    def paint(self, painter, option: QStyleOptionViewItem, index):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)

        if option.state & QStyle.State_Selected:
            painter.fillRect(option.rect, QColor("#E0F2FE"))
        elif option.state & QStyle.State_MouseOver:
            painter.fillRect(option.rect, QColor("#F8FAFC"))
        else:
            painter.fillRect(option.rect, QColor("white"))

        painter.setPen(QPen(QColor("#F1F5F9"), 1))
        painter.drawLine(option.rect.bottomLeft(), option.rect.bottomRight())

        text_rect = QRectF(option.rect).adjusted(15, 0, -180, 0)
        painter.setPen(QColor("#1E293B"))
        font = painter.font()
        font.setPointSize(14)
        painter.setFont(font)
        painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, str(index.data()))

        icon_size = 48
        del_btn_rect = QRectF(
            option.rect.right() - icon_size - 10,
            option.rect.center().y() - icon_size / 2,
            icon_size,
            icon_size,
        )
        edit_btn_rect = QRectF(
            del_btn_rect.left() - icon_size - 8,
            del_btn_rect.top(),
            icon_size,
            icon_size,
        )

        delete_path = QPainterPath()
        delete_path.addRoundedRect(del_btn_rect, 6, 6)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#FEE2E2"))
        painter.drawPath(delete_path)

        edit_path = QPainterPath()
        edit_path.addRoundedRect(edit_btn_rect, 6, 6)
        painter.setBrush(QColor("#E0F2FE"))
        painter.drawPath(edit_path)

        icon_font = painter.font()
        icon_font.setPointSize(22)
        painter.setFont(icon_font)

        painter.setPen(QColor("#DC2626"))
        painter.drawText(del_btn_rect, Qt.AlignCenter, "🗑️")

        painter.setPen(QColor("#0284C7"))
        painter.drawText(edit_btn_rect, Qt.AlignCenter, "✏️")

        painter.restore()

    def editorEvent(self, event, model, option, index):
        if event.type() == QEvent.MouseButtonRelease:
            icon_size = 48
            del_btn_rect = QRectF(
                option.rect.right() - icon_size - 10,
                option.rect.center().y() - icon_size / 2,
                icon_size,
                icon_size,
            )
            edit_btn_rect = QRectF(
                del_btn_rect.left() - icon_size - 8,
                del_btn_rect.top(),
                icon_size,
                icon_size,
            )
            click_pos = event.pos()
            if del_btn_rect.contains(click_pos):
                self.deleteClicked.emit(index)
                return True
            if edit_btn_rect.contains(click_pos):
                self.editClicked.emit(index)
                return True
        return False

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), 82)


class ModernSidebar(QFrame):
    """Barra lateral moderna con botones superiores e items de sistema en el footer."""

    def __init__(
        self,
        nav_items: list[tuple[str, str, int]],
        bottom_items: list[tuple[str, str, int]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ModernSidebar")
        self.setFixedWidth(260)
        self._buttons: dict[int, QPushButton] = {}
        self._buttons_by_name: dict[str, QPushButton] = {}
        self._button_group = QButtonGroup(self)
        self._button_group.setExclusive(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 20, 10, 20)
        layout.setSpacing(12)

        for label, object_name, index in nav_items:
            self._create_btn(layout, label, object_name, index)

        layout.addStretch(1)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        line.setStyleSheet("background-color: #E5E7EB; border: none; max-height: 1px;")
        layout.addWidget(line)

        for label, object_name, index in bottom_items:
            self._create_btn(layout, label, object_name, index, is_bottom=True)

        self.setStyleSheet(
            """
            #ModernSidebar {
                background-color: #f8fafc;
                border-right: 1px solid #e5e7eb;
            }
            #ModernSidebar QPushButton {
                background: transparent;
                border: none;
                color: #1f2937;
                padding: 12px 20px;
                min-width: 0px;
                text-align: left;
                border-radius: 10px;
                font-weight: 700;
                font-size: 15px;
            }
            #ModernSidebar QPushButton:hover {
                background-color: #d1fae5;
                color: #0f766e;
            }
            #ModernSidebar QPushButton:checked {
                background-color: #99f6e4;
                color: #0f766e;
            }
            #btn_nav_config {
                color: #6B7280;
            }
            #btn_nav_logout {
                color: #b91c1c;
            }
        """
        )

    def _create_btn(self, layout: QVBoxLayout, label: str, obj_name: str, idx: int, is_bottom: bool = False) -> None:
        btn = QPushButton(label, self)
        btn.setObjectName(obj_name)
        btn.setCheckable(not is_bottom)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        btn.setMinimumWidth(0)
        if is_bottom:
            btn.setStyleSheet("text-align: left; padding: 12px 15px; color: #6B7280;")
        layout.addWidget(btn)
        self._buttons[idx] = btn
        self._buttons_by_name[obj_name] = btn
        if not is_bottom:
            self._button_group.addButton(btn, idx)

    def connect_to_index_change(self, handler):
        self._button_group.buttonClicked[int].connect(handler)

    def set_active_index(self, index: int) -> None:
        btn = self._button_group.button(index)
        if btn:
            btn.setChecked(True)

    def get_button(self, obj_name: str) -> QPushButton | None:
        return self._buttons_by_name.get(obj_name)


class SettingsDialog(QDialog):
    """Contenedor de configuración con sidebar y contenido apilado."""

    config_saved = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Configuración del Sistema")
        self.resize(900, 600)
        self.setModal(True)
        self.negocio_widget = None
        self.facturacion_widget = None
        self.correo_widget = None
        self.usuarios_widget = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.category_list = QListWidget()
        self.category_list.setFixedWidth(220)
        self.category_list.setObjectName("SettingsSidebar")

        items = [
            ("🏢 Datos del Negocio", "negocio"),
            ("🧾 Facturación Electrónica", "facturacion"),
            ("📧 Configuración de Correo", "correo"),
            ("👥 Usuarios y Permisos", "usuarios"),
            ("🧰 Herramientas del Sistema", "page_tools"),
        ]
        is_admin = getattr(parent, "user", {}).get("role", "admin") == "admin" if parent else True
        for label, key in items:
            if not is_admin and key in {"negocio", "facturacion", "correo", "usuarios"}:
                continue
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, key)
            self.category_list.addItem(item)

        self.content_stack = QStackedWidget()
        self.content_stack.setObjectName("SettingsContent")

        parent_ref = parent if isinstance(parent, QWidget) else None
        is_admin = getattr(parent, "user", {}).get("role", "admin") == "admin" if parent else True
        # Página 0: Datos del negocio (contenido embebido)
        if is_admin:
            negocio_widget = None
            try:
                from dialogs import DatosNegocioDialog

                datos = {}
                import os, json

                if os.path.exists(DATOS_NEGOCIO_PATH):
                    try:
                        with open(DATOS_NEGOCIO_PATH, "r", encoding="utf-8") as fh:
                            datos = json.load(fh)
                            logger.info("SettingsDialog load_config negocio keys=%s", list(datos.keys()))
                    except Exception:
                        datos = {}
                negocio_widget = DatosNegocioDialog(datos, self)
                negocio_widget.setWindowFlags(Qt.Widget)
            except Exception:
                negocio_widget = QWidget()
            self.negocio_widget = negocio_widget
            self.content_stack.addWidget(negocio_widget)
            self._connect_embedded_negocio()

            # Página 1: Facturación Electrónica (contenido embebido)
            facturacion_widget = None
            try:
                from dialogs import DTEConfigDialog

                import os, json

                datos = {}
                config = {}
                if os.path.exists(DATOS_NEGOCIO_PATH):
                    try:
                        with open(DATOS_NEGOCIO_PATH, "r", encoding="utf-8") as fh:
                            datos = json.load(fh)
                    except Exception:
                        datos = {}
                if os.path.exists(CONFIG_NEGOCIO_PATH):
                    try:
                        with open(CONFIG_NEGOCIO_PATH, "r", encoding="utf-8") as fh:
                            config = json.load(fh)
                    except Exception:
                        config = {}
                dte_api = datos.get("dte_api", {})
                ambiente = config.get("ambiente", "pruebas")
                env_conf = config.get(ambiente, {})
                fe_config = env_conf.get("firma_electronica", {})
                dialog_kwargs = {}
                try:
                    import inspect

                    params = inspect.signature(DTEConfigDialog.__init__).parameters
                    if "db" in params:
                        dialog_kwargs["db"] = getattr(parent_ref, "manager", None).db if parent_ref and hasattr(parent_ref, "manager") else None
                except Exception:
                    dialog_kwargs = {}
                facturacion_widget = DTEConfigDialog(
                    dte_api,
                    fe_config,
                    env_conf,
                    self,
                    datos_negocio=datos,
                    **dialog_kwargs,
                )
                facturacion_widget.setWindowFlags(Qt.Widget)
            except Exception:
                facturacion_widget = QWidget()
            self.facturacion_widget = facturacion_widget
            facturacion_scroll = QScrollArea()
            facturacion_scroll.setWidgetResizable(True)
            facturacion_scroll.setFrameShape(QFrame.NoFrame)
            facturacion_scroll.setWidget(facturacion_widget)
            self.content_stack.addWidget(facturacion_scroll)
            self._connect_embedded_facturacion()

            # Página 2: Configuración de Correo (contenido embebido)
            correo_widget = None
            try:
                from dialogs import EmailConfigDialog

                import os, json

                datos = {}
                if os.path.exists(DATOS_NEGOCIO_PATH):
                    try:
                        with open(DATOS_NEGOCIO_PATH, "r", encoding="utf-8") as fh:
                            datos = json.load(fh)
                            logger.info("SettingsDialog load_config correo keys=%s", list(datos.keys()))
                    except Exception:
                        datos = {}
                correo_widget = EmailConfigDialog(datos, self)
                correo_widget.setWindowFlags(Qt.Widget)
            except Exception:
                correo_widget = QWidget()
            self.correo_widget = correo_widget
            self.content_stack.addWidget(correo_widget)
            self._connect_embedded_correo()

            # Página 3: Usuarios y Permisos (contenido embebido)
            usuarios_widget = None
            try:
                from dialogs import UserConfigDialog

                db_ref = None
                if parent_ref and hasattr(parent_ref, "manager"):
                    db_ref = getattr(parent_ref.manager, "db", None)
                usuarios_widget = UserConfigDialog(db=db_ref, parent=self)
                usuarios_widget.setWindowFlags(Qt.Widget)
            except Exception:
                usuarios_widget = QWidget()
            self.usuarios_widget = usuarios_widget
            self.content_stack.addWidget(usuarios_widget)

        # Página 4: Herramientas del Sistema
        tools_widget = QWidget()
        tools_layout = QVBoxLayout(tools_widget)
        tools_layout.setContentsMargins(24, 24, 24, 24)
        tools_layout.setSpacing(12)

        tools_title = QLabel("Herramientas Administrativas")
        title_font = tools_title.font()
        base_size = title_font.pointSize() or 12
        title_font.setPointSize(base_size + 2)
        title_font.setBold(True)
        tools_title.setFont(title_font)
        tools_layout.addWidget(tools_title)

        desc = QLabel("Accesos directos para mantenimiento y depuración del sistema.")
        desc.setStyleSheet("color: #475569;")
        tools_layout.addWidget(desc)

        def _create_tool_btn(text, handler):
            btn = QPushButton(text)
            btn.setObjectName("SecondaryActionButton")
            btn.setMinimumHeight(46)
            if handler:
                btn.clicked.connect(handler)
            return btn

        grid = QGridLayout()
        grid.setSpacing(12)
        parent_ref = parent if isinstance(parent, QWidget) else None

        btn_update = _create_tool_btn(
            "Actualizar Estado de DTEs",
            getattr(parent_ref, "actualizar_estado_global", None),
        )
        btn_firmador = _create_tool_btn(
            "Iniciar Firmador Local",
            getattr(parent_ref, "iniciar_firmador", None),
        )
        btn_firmar_manual = _create_tool_btn(
            "Firmar DTE Manualmente...",
            getattr(parent_ref, "firmar_dte_manual", None),
        )
        btn_debug = _create_tool_btn(
            "Debug: Venta vs DTE",
            getattr(parent_ref, "_debug_venta_vs_dte", None),
        )

        grid.addWidget(btn_update, 0, 0)
        grid.addWidget(btn_firmador, 0, 1)
        grid.addWidget(btn_firmar_manual, 1, 0)
        grid.addWidget(btn_debug, 1, 1)

        tools_layout.addLayout(grid)
        tools_layout.addStretch(1)

        self.content_stack.addWidget(tools_widget)

        layout.addWidget(self.category_list)
        layout.addWidget(self.content_stack)

        self.category_list.currentRowChanged.connect(self.content_stack.setCurrentIndex)
        self.category_list.setCurrentRow(0)

        self._apply_styles()

    def _make_launcher_page(self, title: str, handler) -> QWidget:
        page = QWidget()
        vbox = QVBoxLayout(page)
        vbox.setContentsMargins(24, 24, 24, 24)
        vbox.setSpacing(12)
        lbl = QLabel(title)
        font = lbl.font()
        base_size = font.pointSize()
        if base_size <= 0:
            base_size = 12
        font.setPointSize(base_size + 2)
        font.setBold(True)
        lbl.setFont(font)
        vbox.addWidget(lbl)
        desc = QLabel("Abre el formulario existente en una ventana separada.")
        desc.setStyleSheet("color:#6b7280;")
        vbox.addWidget(desc)
        btn = QPushButton(f"Abrir {title}")
        btn.setObjectName("PrimaryActionButton")
        btn.setMinimumHeight(42)
        if handler:
            btn.clicked.connect(handler)
        else:
            btn.setEnabled(False)
        vbox.addWidget(btn)
        vbox.addStretch(1)
        return page

    def _apply_styles(self):
        self.setStyleSheet(
            """
            QDialog { background-color: #f3f4f6; }
            QListWidget#SettingsSidebar {
                background-color: #1e293b;
                color: #e2e8f0;
                border: none;
                font-size: 14px;
                outline: none;
            }
            QListWidget#SettingsSidebar::item {
                padding: 15px 20px;
                border-bottom: 1px solid #334155;
            }
            QListWidget#SettingsSidebar::item:selected {
                background-color: #3b82f6;
                color: white;
                font-weight: bold;
            }
            QStackedWidget#SettingsContent {
                background-color: white;
            }
            /* Estilos para formularios de configuración */
            QStackedWidget#SettingsContent QLineEdit,
            QStackedWidget#SettingsContent QComboBox {
                background-color: #FFFFFF;
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                padding: 8px 10px;
                font-size: 13px;
                color: #1E293B;
            }
            QStackedWidget#SettingsContent QLineEdit:focus,
            QStackedWidget#SettingsContent QComboBox:focus {
                border: 2px solid #3B82F6;
            }
            QStackedWidget#SettingsContent QLabel {
                color: #475569;
                font-weight: 600;
                margin-top: 5px;
            }
            QStackedWidget#SettingsContent QCheckBox {
                spacing: 8px;
                font-size: 13px;
                color: #334155;
                margin: 4px 0;
            }
            QStackedWidget#SettingsContent QPushButton {
                background-color: #F1F5F9;
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                padding: 6px 12px;
                font-weight: 600;
                color: #475569;
            }
            QStackedWidget#SettingsContent QPushButton:hover {
                background-color: #E2E8F0;
                color: #1E293B;
            }
            /* Tabla Limpia Estilo Steam */
QTableWidget {
                background-color: white;
                alternate-background-color: #F3F4F6;
                gridline-color: transparent;
                border: none;
                selection-background-color: #dbeafe;
                selection-color: #0f172a;
            }
            QHeaderView::section {
                background-color: white;
                border: none;
                border-bottom: 2px solid #E5E7EB;
                font-weight: bold;
                color: #4B5563;
                padding: 8px;
            }
            QPushButton[class="table-icon-btn"] {
                background-color: transparent;
                border: none;
                padding: 6px;
                border-radius: 8px;
                min-width: 32px;
                min-height: 32px;
            }
            QPushButton[class="table-icon-btn"]:hover {
                background-color: #F3F4F6;
            }
            QPushButton[class="table-icon-btn"][role="view"]:hover {
                background-color: #F1F5F9;
            }
            QPushButton[class="table-icon-btn"][role="edit"]:hover {
                background-color: #EBF5FF;
            }
            QPushButton[class="table-icon-btn"][role="delete"]:hover {
                background-color: #FEF2F2;
            }
            """
        )

    def _disconnect_clicked(self, button: QPushButton) -> None:
        try:
            button.clicked.disconnect()
        except Exception:
            pass

    def _connect_embedded_negocio(self) -> None:
        widget = self.negocio_widget
        if widget is None or not hasattr(widget, "btn_guardar"):
            return
        self._disconnect_clicked(widget.btn_guardar)
        widget.btn_guardar.clicked.connect(self._handle_negocio_save)
        if hasattr(widget, "btn_cancelar"):
            self._disconnect_clicked(widget.btn_cancelar)
            widget.btn_cancelar.clicked.connect(self.reject)

    def _connect_embedded_facturacion(self) -> None:
        widget = self.facturacion_widget
        if widget is None or not hasattr(widget, "btn_guardar"):
            return
        self._disconnect_clicked(widget.btn_guardar)
        widget.btn_guardar.clicked.connect(self._handle_facturacion_save)
        if hasattr(widget, "btn_cancelar"):
            self._disconnect_clicked(widget.btn_cancelar)
            widget.btn_cancelar.clicked.connect(self.reject)

    def _connect_embedded_correo(self) -> None:
        widget = self.correo_widget
        if widget is None or not hasattr(widget, "btn_guardar"):
            return
        self._disconnect_clicked(widget.btn_guardar)
        widget.btn_guardar.clicked.connect(self._handle_correo_save)
        if hasattr(widget, "btn_cancelar"):
            self._disconnect_clicked(widget.btn_cancelar)
            widget.btn_cancelar.clicked.connect(self.reject)

    def _load_json_file(self, path: str) -> dict:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    return json.load(fh)
            except Exception:
                return {}
        return {}

    def _handle_negocio_save(self) -> None:
        widget = self.negocio_widget
        if widget is None or not hasattr(widget, "get_data"):
            return
        try:
            datos_nuevos = widget.get_data()
        except ValueError as exc:
            QMessageBox.warning(self, "Validación", str(exc))
            return
        datos = self._load_json_file(DATOS_NEGOCIO_PATH)
        config = self._load_json_file(CONFIG_NEGOCIO_PATH)
        datos.update(datos_nuevos)
        dir_info = datos.get("direccion") or {}
        dir_info.setdefault("departamento", "")
        dir_info.setdefault("municipio", "")
        datos["direccion"] = dir_info
        datos_changed, config_changed, tokens_reset = _sync_configs(
            datos,
            config,
            nit_hint=datos_nuevos.get("nit"),
            ambiente_hint=(datos.get("dte_api") or {}).get("ambiente"),
        )
        try:
            with open(DATOS_NEGOCIO_PATH, "w", encoding="utf-8") as f:
                json.dump(datos, f, ensure_ascii=False, indent=2)
            if config_changed:
                with open(CONFIG_NEGOCIO_PATH, "w", encoding="utf-8") as f:
                    json.dump(config, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"No se pudo guardar la configuración: {exc}")
            return
        if config_changed or datos_changed or tokens_reset:
            invalidate_token_cache()
        if tokens_reset:
            QMessageBox.information(
                self,
                "Tokens reiniciados",
                "Los tokens almacenados se limpiaron porque cambiaste el NIT o el ambiente. "
                "Vuelve a obtener un token en Configuración > Facturación Electrónica.",
            )
            QMessageBox.information(self, "Datos del negocio", "Datos guardados exitosamente.")
        self.config_saved.emit("negocio")

    def _handle_facturacion_save(self) -> None:
        widget = self.facturacion_widget
        if widget is None or not hasattr(widget, "get_data"):
            return
        if hasattr(widget, "validate_before_save") and not widget.validate_before_save():
            return
        datos = self._load_json_file(DATOS_NEGOCIO_PATH)
        config = self._load_json_file(CONFIG_NEGOCIO_PATH)
        try:
            new_dte_api, new_fe, new_urls = widget.get_data()
        except ValueError as exc:
            QMessageBox.warning(self, "Validación", str(exc))
            return
        negocio_updates = getattr(widget, "get_negocio_updates", lambda: {})()
        if isinstance(negocio_updates, Mapping):
            datos.update(negocio_updates)
        ambiente = new_dte_api["ambiente"]
        datos["dte_api"] = new_dte_api
        config["ambiente"] = ambiente
        config.setdefault(ambiente, {})
        config[ambiente]["firma_electronica"] = new_fe
        config[ambiente]["auth_url"] = new_urls.get("auth_url", "")
        config[ambiente]["recepcion_url"] = new_urls.get("recepcion_url", "")
        if "evento_contingencia_url" in new_urls:
            config[ambiente]["evento_contingencia_url"] = new_urls["evento_contingencia_url"]
        if "auth" in new_urls:
            config[ambiente]["auth"] = new_urls["auth"]
        datos_changed, _config_changed_extra, tokens_reset = _sync_configs(
            datos,
            config,
            nit_hint=new_fe.get("nit"),
            ambiente_hint=new_dte_api.get("ambiente"),
        )
        try:
            with open(DATOS_NEGOCIO_PATH, "w", encoding="utf-8") as f:
                json.dump(datos, f, ensure_ascii=False, indent=2)
            with open(CONFIG_NEGOCIO_PATH, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"No se pudo guardar la configuración: {exc}")
            return
        invalidate_token_cache()
        if tokens_reset:
            QMessageBox.information(
                self,
                "Tokens reiniciados",
                "Los tokens almacenados se limpiaron porque cambiaste el NIT o el ambiente. "
                "Obtén un token nuevo antes de volver a enviar DTE.",
            )
        QMessageBox.information(self, "Facturación electrónica", "Datos guardados exitosamente.")
        self.config_saved.emit("facturacion")

    def _handle_correo_save(self) -> None:
        widget = self.correo_widget
        if widget is None or not hasattr(widget, "get_data"):
            return
        datos = self._load_json_file(DATOS_NEGOCIO_PATH)
        try:
            datos.update(widget.get_data())
        except Exception as exc:
            QMessageBox.warning(self, "Validación", str(exc))
            return
        try:
            with open(DATOS_NEGOCIO_PATH, "w", encoding="utf-8") as f:
                json.dump(datos, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"No se pudo guardar la configuración: {exc}")
            return
        QMessageBox.information(self, "Configuración de correo", "Datos guardados exitosamente.")
        self.config_saved.emit("correo")


def redondear(valor):
    return float(Decimal(str(valor)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def build_payment_condition_extra(data):
    condicion = data.get("condicion_operacion")
    if condicion not in {1, 2, 3}:
        return {}

    extra: dict = {}
    sync_condicion_operacion_flags(extra, condicion)
    if condicion == 2:
        plazo = data.get("pago_plazo")
        periodo = data.get("pago_periodo")
        if not plazo or not periodo:
            return extra
        pago = {
            "codigo": "01",
            "montoPago": float(data.get("total", 0) or 0),
            "plazo": plazo,
            "periodo": periodo,
        }
        referencia = (data.get("pago_referencia") or "").strip()
        if referencia:
            pago["referencia"] = referencia
        extra["pagos"] = [pago]
        extra["pago_plazo"] = plazo
        extra["pago_periodo"] = periodo
        if referencia:
            extra["pago_referencia"] = referencia
    return extra


class ExportThread(QThread):
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, filename, tab_order):
        super().__init__()
        self.filename = filename
        self.tab_order = tab_order

    def run(self):
        """Run the export in a background thread.

        A new ``InventoryManager`` instance is created so that this thread uses
        its own database connection, avoiding any cross-thread usage of the
        main application's connection.
        """
        try:
            manager = im.InventoryManager(im.DB(), enable_auto_backup=False)
            manager.exportar_inventario_json(
                self.filename, tab_order=self.tab_order
            )
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))


class EditarLoteDialog(QDialog):
    """Diálogo para editar los datos de un lote."""

    def __init__(
        self,
        parent=None,
        *,
        producto: str = "",
        codigo: str = "",
        cantidad: int = 0,
        codigo_lote: str = "",
        registro_sanitario: str = "",
        fecha_vencimiento: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Editar lote")

        layout = QVBoxLayout(self)
        descripcion = QLabel(f"Producto: {producto} ({codigo})")
        descripcion.setWordWrap(True)
        layout.addWidget(descripcion)

        form = QFormLayout()

        self.cantidad_spin = QSpinBox()
        self.cantidad_spin.setMinimum(0)
        self.cantidad_spin.setMaximum(1_000_000_000)
        self.cantidad_spin.setValue(max(0, cantidad))
        form.addRow("Cantidad:", self.cantidad_spin)

        self.codigo_lote_edit = QLineEdit(codigo_lote)
        self.codigo_lote_edit.setPlaceholderText("Código de lote")
        form.addRow("Código de lote:", self.codigo_lote_edit)

        self.registro_sanitario_edit = QLineEdit(registro_sanitario)
        self.registro_sanitario_edit.setPlaceholderText("Registro sanitario")
        form.addRow("Registro sanitario:", self.registro_sanitario_edit)

        self.fecha_vencimiento_edit = QDateEdit()
        self.fecha_vencimiento_edit.setCalendarPopup(True)
        self.fecha_vencimiento_edit.setDisplayFormat("yyyy-MM-dd")
        self.fecha_vencimiento_edit.setMinimumDate(QDate(1900, 1, 1))
        self.fecha_vencimiento_edit.setMaximumDate(QDate(7999, 12, 31))
        fecha_actual = QDate.currentDate()
        self.fecha_vencimiento_edit.setDate(fecha_actual)

        self.sin_fecha_checkbox = QCheckBox("Sin fecha de vencimiento")
        self.sin_fecha_checkbox.toggled.connect(
            lambda checked: self.fecha_vencimiento_edit.setEnabled(not checked)
        )

        if fecha_vencimiento:
            fecha_qt = QDate.fromString(fecha_vencimiento, "yyyy-MM-dd")
            if fecha_qt.isValid():
                self.fecha_vencimiento_edit.setDate(fecha_qt)
                self.sin_fecha_checkbox.setChecked(False)
            else:
                self.sin_fecha_checkbox.setChecked(True)
                self.fecha_vencimiento_edit.setEnabled(False)
        else:
            self.sin_fecha_checkbox.setChecked(True)
            self.fecha_vencimiento_edit.setEnabled(False)

        form.addRow("Fecha de vencimiento:", self.fecha_vencimiento_edit)
        layout.addLayout(form)
        layout.addWidget(self.sin_fecha_checkbox)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_values(self) -> tuple[int, str, str, str]:
        cantidad = self.cantidad_spin.value()
        codigo_lote = self.codigo_lote_edit.text().strip()
        registro_sanitario = self.registro_sanitario_edit.text().strip()
        fecha_vencimiento = ""
        if not self.sin_fecha_checkbox.isChecked():
            fecha_vencimiento = self.fecha_vencimiento_edit.date().toString("yyyy-MM-dd")
        return cantidad, codigo_lote, registro_sanitario, fecha_vencimiento


class MainWindow(QMainWindow):
    # Generic signal emitted whenever sales or payment data changes. Tabs
    # that need to stay in sync can listen for this signal to refresh
    # immediately instead of waiting for the periodic timers.
    data_changed = pyqtSignal()

    def __init__(self, user=None, *, skip_firmador_check: bool = False):
        super().__init__()
        self.user = user or {"username": "admin", "role": "admin"}
        self.setWindowTitle("Inventario Farmacia")
        self.setWindowState(self.windowState() | Qt.WindowMaximized)
        self.setMinimumSize(1024, 720)
        self.db = im.DB()
        self.manager = im.InventoryManager(self.db, enable_auto_backup=True)
        self.ultimo_archivo_json = None  # Guarda la ruta del último archivo .json usado
        self._load_last_inventory_path()
        self._alerto_vendedores_inconsistentes = False
        self.firmador_proc = None
        self._guest_read_only = (self.user.get("role") == "guest")
        # Contador de cambios en la base de datos para detectar si hay datos sin guardar
        self._mark_saved()
        self._setup_ui()
        self._apply_styles()
        self._apply_guest_restrictions()
        QTimer.singleShot(0, self.showMaximized)
        if not skip_firmador_check:
            QTimer.singleShot(0, self._verificar_firmador)

        # Timer to periodically refresh the "Estados de cuenta" table so it
        # stays synchronized with new sales or payments made from any tab.
        self._historial_timer = QTimer(self)
        self._historial_timer.setInterval(10000)  # 10 seconds
        self._historial_timer.timeout.connect(self._mostrar_historial_general)
        self._historial_timer.start()

        # When data changes elsewhere emit a signal so the tabs refresh
        # immediately instead of waiting for the timer interval.
        self.data_changed.connect(self.facturacion_tab.refresh_and_reload)
        self.data_changed.connect(self._mostrar_historial_general)

    def iniciar_firmador(self):
        """Lanza el servicio externo de firmado de documentos."""
        if self.firmador_proc and self.firmador_proc.poll() is None:
            QMessageBox.information(
                self,
                "Firmador",
                "El firmador ya está corriendo, no es necesario volver a ejecutarlo.",
            )
            return
        if firmador_activo():
            QMessageBox.information(
                self,
                "Firmador",
                "El firmador ya está corriendo, no es necesario volver a ejecutarlo.",
            )
            return
        try:
            self.firmador_proc = iniciar_firmador()
            QMessageBox.information(
                self, "Firmador", "El firmador está corriendo."
            )
        except FileNotFoundError as exc:
            QMessageBox.critical(self, "Error", f"No se encontró el firmador:\n{exc}")
        except RuntimeError:
            QMessageBox.information(
                self,
                "Firmador",
                "El firmador ya está corriendo, no es necesario volver a ejecutarlo.",
            )
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"No se pudo iniciar el firmador:\n{exc}")

    def _verificar_firmador(self):
        if firmador_activo() or (self.firmador_proc and self.firmador_proc.poll() is None):
            return

        loader = QDialog(self)
        loader.setWindowTitle("Iniciando servicios")
        loader.setModal(True)
        loader.setWindowFlags(loader.windowFlags() & ~Qt.WindowCloseButtonHint)
        vbox = QVBoxLayout(loader)
        vbox.setContentsMargins(20, 20, 20, 20)
        vbox.setSpacing(12)
        lbl = QLabel("Iniciando servicios...")
        lbl.setAlignment(Qt.AlignCenter)
        vbox.addWidget(lbl)
        progress = QProgressBar()
        progress.setRange(0, 0)
        vbox.addWidget(progress)
        loader.resize(320, 120)
        loader.show()
        QApplication.processEvents()

        ok, err = self._iniciar_firmador_silencioso()
        loader.accept()
        if not ok and err:
            QMessageBox.critical(self, "Firmador", err)

    def _is_guest(self) -> bool:
        return bool(getattr(self, "_guest_read_only", False))

    def _deny_guest(self) -> None:
        QMessageBox.warning(
            self,
            "Permisos",
            "Los invitados solo pueden visualizar. Cambia de usuario para realizar esta acción.",
        )

    def _apply_guest_restrictions(self) -> None:
        if not self._is_guest():
            return
        btn_names = [
            "btn_add_product",
            "btn_edit_product",
            "btn_delete_product",
            "btn_register_sale",
            "btn_register_credito_fiscal",
            "btn_register_purchase",
            "btn_guardar_rapido",
            "btn_cargar_inventario",
            "btn_add_cliente",
            "btn_edit_cliente",
            "btn_delete_cliente",
            "btn_add_trabajador",
            "btn_edit_trabajador",
            "btn_delete_trabajador",
            "btn_add_vendedor",
            "btn_add_distribuidor",
        ]
        for name in btn_names:
            btn = getattr(self, name, None)
            if btn:
                btn.setEnabled(False)

    def _iniciar_firmador_silencioso(self) -> tuple[bool, str | None]:
        if self.firmador_proc and self.firmador_proc.poll() is None:
            return True, None
        if firmador_activo():
            return True, None
        try:
            self.firmador_proc = iniciar_firmador()
            return True, None
        except FileNotFoundError as exc:
            return False, f"No se encontró el firmador:\n{exc}"
        except RuntimeError:
            return True, None
        except Exception as exc:
            return False, f"No se pudo iniciar el firmador:\n{exc}"

    @staticmethod
    def _parse_invoice_datetime(value):
        if isinstance(value, datetime):
            return value
        if not value:
            return None
        if isinstance(value, str):
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
                try:
                    return datetime.strptime(value, fmt)
                except ValueError:
                    continue
        return None

    @staticmethod
    def _normalize_envio_text(value: str) -> str:
        lowered = str(value or "").strip().lower()
        if not lowered:
            return ""
        normalized = unicodedata.normalize("NFKD", lowered)
        return "".join(ch for ch in normalized if not unicodedata.combining(ch))

    def _is_ticket_sale(self, venta: Mapping[str, object] | None) -> bool:
        """Determina si la venta debe tratarse como ticket (sin datos fiscales del cliente)."""
        if not venta:
            return False
        getter_cf = getattr(self.manager.db, "get_venta_credito_fiscal", None)
        if getter_cf:
            try:
                if getter_cf(venta["id"]):  # type: ignore[index]
                    return False
            except Exception:
                pass
        cid = venta.get("cliente_id") if isinstance(venta, Mapping) else None
        if not cid:
            return True
        cliente = None
        getter = getattr(self.manager.db, "get_cliente", None)
        if getter:
            try:
                cliente = getter(cid)
            except Exception:
                cliente = None
        if not cliente:
            return True
        nit = (cliente.get("nit") or "").strip() if isinstance(cliente, Mapping) else ""
        dui = (cliente.get("dui") or "").strip() if isinstance(cliente, Mapping) else ""
        return not nit and not dui

    def _generate_sale_pdf(self, venta_id: int):
        venta = self.manager.db.get_venta_by_id(venta_id)
        if venta and self._is_ticket_sale(venta):
            return generate_ticket_pdf(self.manager, venta_id)
        return generate_invoice_pdf(self.manager, venta_id)

    def _get_latest_invoice_row(self):
        cur = getattr(self.manager.db, "cursor", None)
        if cur is None:
            return None
        try:
            row = cur.execute(
                """
                SELECT e.estado, e.estado_ui, e.estado_ui_tag, e.id, e.venta_id
                FROM dte_envios AS e
                JOIN ventas AS v ON v.id = e.venta_id
                ORDER BY v.id DESC, e.id DESC
                LIMIT 1
                """
            ).fetchone()
            if row:
                return dict(row)
        except Exception:
            logger.exception("No se pudo obtener el último estado de envío DTE (join)")
        try:
            row = cur.execute(
                """
                SELECT estado, estado_ui, estado_ui_tag, id, venta_id
                FROM dte_envios
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
            return dict(row) if row else None
        except Exception:
            logger.exception("No se pudo obtener el último estado de envío DTE")
            return None

    def _ensure_last_invoice_sent(self) -> bool:
        latest_row = self._get_latest_invoice_row()
        if latest_row:
            estado_candidates = [
                latest_row.get("estado"),
                latest_row.get("estado_ui"),
            ]
            success_tokens = {"transmitido", "recibido", "procesado", "aceptado", "enviado"}
            estado_ok = True
            estado_norm = ""
            for candidate in estado_candidates:
                estado_norm = str(candidate or "").strip().lower()
                if not estado_norm:
                    continue
                estado_ok = any(estado_norm.startswith(tok) for tok in success_tokens)
                break
            if not estado_ok:
                resp = QMessageBox.question(
                    self,
                    "Documento pendiente",
                    (
                        "El último DTE no ha sido enviado (estado: "
                        f"{estado_norm or 'pendiente'}). ¿Deseas continuar de todos modos?\n\n"
                        "Recomendado: envía o corrige ese DTE antes de registrar una nueva venta."
                    ),
                    QMessageBox.Yes | QMessageBox.No,
                )
                if resp != QMessageBox.Yes:
                    return False
        try:
            venta_row = self.manager.db.cursor.execute(
                "SELECT id, estado FROM ventas ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if venta_row:
                try:
                    estado_venta = venta_row["estado"]
                except Exception:
                    estado_venta = venta_row[1] if len(venta_row) > 1 else None
                estado_norm = str(estado_venta or "").strip().lower()
                if estado_norm and estado_norm.startswith("pendiente"):
                    resp = QMessageBox.question(
                        self,
                        "Documento pendiente",
                        (
                            "La última venta sigue en estado pendiente. ¿Deseas continuar de todos modos?\n\n"
                            "Recomendado: envía o corrige ese DTE antes de registrar una nueva venta."
                        ),
                        QMessageBox.Yes | QMessageBox.No,
                    )
                    if resp != QMessageBox.Yes:
                        return False
        except Exception:
            logger.exception("No se pudo verificar estados de ventas pendientes")
        return True

    def generar_factura_pdf(self):
        """Función de generación de facturas no disponible."""
        QMessageBox.information(self, "Factura", "Función no disponible en esta versión.")

    def _setup_ui(self):
        # --- BARRA SUPERIOR HORIZONTAL ---
        menubar = QMenuBar(self)
        self.setMenuBar(menubar)

        # Menú Archivo
        archivo_menu = menubar.addMenu("Archivo")
        nuevo_inventario_action = QAction("Nuevo inventario", self)
        nuevo_inventario_action.triggered.connect(self.nuevo_inventario)
        guardar_como_action = QAction("Guardar como...", self)
        guardar_como_action.triggered.connect(self.guardar_como)
        cargar_inventario_action = QAction("Cargar inventario...", self)
        cargar_inventario_action.triggered.connect(self.cargar_inventario)
        cargar_respaldo_action = QAction("Cargar copia de seguridad...", self)
        cargar_respaldo_action.triggered.connect(self.cargar_copia_seguridad)
        cargar_respaldo_manual_action = QAction("Cargar copia de seguridad (seleccionar)...", self)
        cargar_respaldo_manual_action.triggered.connect(self.cargar_copia_seguridad_manual)
        firmar_dte_action = QAction("Firmar DTE...", self)
        firmar_dte_action.triggered.connect(self.firmar_dte_manual)
        archivo_menu.addAction(nuevo_inventario_action)
        archivo_menu.addAction(guardar_como_action)
        archivo_menu.addAction(cargar_inventario_action)
        archivo_menu.addAction(cargar_respaldo_action)
        archivo_menu.addAction(cargar_respaldo_manual_action)

        # Menú superior reducido: sólo ayuda/otros si aplica (configuración movida a SettingsDialog)

        # --- BOTONES LATERALES ---
        self.btn_add_product = QPushButton("Agregar Producto")
        self.btn_edit_product = QPushButton("Editar Producto")
        self.btn_register_sale = QPushButton("Registrar Venta")
        # Botón con salto de línea para que el texto quepa bien
        self.btn_register_credito_fiscal = QPushButton("Registrar Venta\nCrédito Fiscal")
        self.btn_register_purchase = QPushButton("Registrar Compra")
        self.btn_delete_product = QPushButton("Eliminar Producto")
        self.btn_guardar_rapido = QPushButton("Guardar\nRápido")
        self.btn_cargar_inventario = QPushButton("Cargar Inventario")
        self.btn_guardar_inicio = QPushButton("Guardar inventario")

        # Ajustes de tamaño y estilo inicial para acciones principales
        for btn in [
            self.btn_add_product,
            self.btn_edit_product,
            self.btn_delete_product,
            self.btn_guardar_rapido,
            self.btn_guardar_inicio,
            self.btn_cargar_inventario,
        ]:
            btn.setMinimumHeight(46)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(btn.styleSheet() + "font-size: 15px;")

        if self.user["role"] == "guest":
            for btn in [
                self.btn_add_product,
                self.btn_edit_product,
                self.btn_register_sale,
                self.btn_register_credito_fiscal,
                self.btn_register_purchase,
                self.btn_delete_product,
                self.btn_guardar_rapido,
                self.btn_guardar_inicio,
                self.btn_cargar_inventario,
            ]:
                btn.setEnabled(False)
        # Preferimos un diseño limpio: ocultar acciones redundantes en esta vista
        for btn in [self.btn_register_sale, self.btn_register_credito_fiscal, self.btn_register_purchase]:
            btn.hide()

        # --- Pestaña de inventario con distribución vertical ---
        # 1) Botones principales
        self.btn_add_product.setText("Nuevo producto")
        self.btn_add_product.setObjectName("PrimaryActionButton")
        self.btn_add_product.setCursor(Qt.PointingHandCursor)

        self.btn_edit_product.setText("Editar")
        self.btn_edit_product.setObjectName("SecondaryActionButton")
        self.btn_edit_product.setCursor(Qt.PointingHandCursor)

        self.btn_delete_product.setText("Eliminar")
        self.btn_delete_product.setObjectName("DangerActionButton")
        self.btn_delete_product.setCursor(Qt.PointingHandCursor)

        self.btn_guardar_rapido.setText("Guardar rápido")
        self.btn_guardar_rapido.setObjectName("SecondaryActionButton")
        self.btn_guardar_rapido.setCursor(Qt.PointingHandCursor)
        self.btn_guardar_inicio.setObjectName("SecondaryActionButton")
        self.btn_guardar_inicio.setCursor(Qt.PointingHandCursor)
        self.btn_guardar_inicio.setStyleSheet(self.btn_guardar_inicio.styleSheet() + "font-size: 15px;")

        self.btn_cargar_inventario.setText("Recargar")
        self.btn_cargar_inventario.setObjectName("SecondaryActionButton")
        self.btn_cargar_inventario.setCursor(Qt.PointingHandCursor)

        for btn in [self.btn_register_sale, self.btn_register_credito_fiscal, self.btn_register_purchase]:
            btn.hide()

        # 2) Encabezado con más aire y alineación central
        header_layout = QHBoxLayout()
        header_layout.setAlignment(Qt.AlignVCenter)

        title_label = QLabel("Inventario de Productos")
        title_font = title_label.font()
        title_font.setPointSize(26)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setStyleSheet("color: #111827;")
        header_layout.addWidget(title_label)
        header_layout.addStretch(1)

        actions_layout = QHBoxLayout()
        actions_layout.setSpacing(15)
        actions_layout.setAlignment(Qt.AlignVCenter)
        actions_layout.addWidget(self.btn_guardar_inicio)
        actions_layout.addWidget(self.btn_cargar_inventario)
        actions_layout.addWidget(self.btn_edit_product)
        actions_layout.addWidget(self.btn_delete_product)
        actions_layout.addWidget(self.btn_add_product)
        header_layout.addLayout(actions_layout)

        # 3) Tarjeta de filtros espaciosa
        filter_card = QFrame()
        filter_card.setObjectName("InventoryFilterCard")
        filter_layout = QVBoxLayout(filter_card)
        filter_layout.setContentsMargins(20, 20, 20, 20)
        filter_layout.setSpacing(15)

        search_row = QHBoxLayout()
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("\ud83d\udd0d Buscar por nombre, código o sustancia...")
        self.search_bar.setMinimumHeight(42)
        self.search_bar.setStyleSheet("font-size: 15px;")
        self.search_bar.textChanged.connect(self.filter_products)
        search_row.addWidget(self.search_bar)

        filters_row = QHBoxLayout()
        lbl_style = "color: #4B5563; font-weight: 600;"

        lbl_vend = QLabel("Vendedor:")
        lbl_vend.setStyleSheet(lbl_style)
        filters_row.addWidget(lbl_vend)
        self.vendedor_combo_filtro = QComboBox()
        self.vendedor_combo_filtro.setMinimumHeight(40)
        self.vendedor_combo_filtro.setStyleSheet("font-size: 14px;")
        self.vendedor_combo_filtro.addItem("Todos", None)
        for v in self.manager.get_vendedores_compra():
            self.vendedor_combo_filtro.addItem(v["nombre"], v["id"])
        self.vendedor_combo_filtro.currentIndexChanged.connect(self.filter_products)
        filters_row.addWidget(self.vendedor_combo_filtro)
        filters_row.addSpacing(20)

        lbl_dist = QLabel("Distribuidor:")
        lbl_dist.setStyleSheet(lbl_style)
        filters_row.addWidget(lbl_dist)
        self.distribuidor_combo_filtro = QComboBox()
        self.distribuidor_combo_filtro.setMinimumHeight(40)
        self.distribuidor_combo_filtro.setStyleSheet("font-size: 14px;")
        self.distribuidor_combo_filtro.addItem("Todos", None)
        for d in self.manager._Distribuidores:
            self.distribuidor_combo_filtro.addItem(d["nombre"], d["id"])
        self.distribuidor_combo_filtro.currentIndexChanged.connect(self.filter_products)
        filters_row.addWidget(self.distribuidor_combo_filtro)
        filters_row.addSpacing(20)

        lbl_stock = QLabel("Ordenar:")
        lbl_stock.setStyleSheet(lbl_style)
        filters_row.addWidget(lbl_stock)
        self.stock_sort_combo = QComboBox()
        self.stock_sort_combo.setMinimumHeight(40)
        self.stock_sort_combo.setStyleSheet("font-size: 14px;")
        self.stock_sort_combo.addItems(["Ordenar por stock", "Más stock a menos", "Menos stock a más"])
        self.stock_sort_combo.currentIndexChanged.connect(self.filter_products)
        filters_row.addWidget(self.stock_sort_combo)
        filters_row.addStretch(1)

        filter_layout.addLayout(search_row)
        filter_layout.addLayout(filters_row)

        # Tabla principal
        self.product_table = QTableView()
        self.product_table.setModel(self.manager.get_products_model())
        self.product_table.setSelectionBehavior(QTableView.SelectRows)
        self.product_table.setSelectionMode(QTableView.SingleSelection)
        self.product_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.product_table.clicked.connect(self._on_table_clicked)
        self.product_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.product_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.product_table.setShowGrid(False)
        self.product_table.setFrameShape(QFrame.NoFrame)
        self.product_table.setAlternatingRowColors(False)
        self.product_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.product_table.setSelectionMode(QTableView.SingleSelection)
        self.product_table.setStyleSheet(self.product_table.styleSheet() + "font-size: 14px;")

        self.product_table.verticalHeader().hide()
        self.product_table.verticalHeader().setDefaultSectionSize(64)

        header = self.product_table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header.setFixedHeight(50)

        self.stock_delegate = StockDelegate(self.product_table)
        self.product_table.setItemDelegateForColumn(3, self.stock_delegate)
        self.selected_row = None

        # 4) Layout principal con márgenes amplios
        inventory_layout = QVBoxLayout()
        inventory_layout.setContentsMargins(40, 40, 40, 30)
        inventory_layout.setSpacing(25)
        inventory_layout.addLayout(header_layout)
        inventory_layout.addSpacing(25)
        inventory_layout.addWidget(filter_card)
        inventory_layout.addWidget(self.product_table)

        tab_widget = QWidget()
        tab_layout = QVBoxLayout()
        tab_layout.setContentsMargins(0, 0, 0, 0)
        tab_layout.addLayout(inventory_layout)
        tab_widget.setLayout(tab_layout)

        # --- PESTAÑA DE vendEGORÍAS Y DistribuidorES ---
        vend_dist_tab = QWidget()
        self.vendedores_tab = vend_dist_tab
        self.setup_vendedores_distribuidores_ui()

        # --- PESTAÑA DE CLIENTES ---
        self.clientes_tab = QWidget()
        self.setup_clientes_ui()

        # --- PESTAÑA DE VENTAS ---
        self.sales_tab = SalesTab(self.manager, self)

        # --- PESTAÑA DE COMPRAS ---
        from purchases_tab import PurchasesTab
        self.compras_tab = PurchasesTab(self.manager, self)

        # --- PESTAÑA DE INVENTARIO ACTUAL ---
        inventario_actual_tab = QWidget()
        inventario_actual_layout = QVBoxLayout(inventario_actual_tab)
        inventario_actual_layout.setContentsMargins(30, 30, 30, 30)
        inventario_actual_layout.setSpacing(20)

        inventario_card = QFrame()
        inventario_card.setObjectName("ModernCard")
        inventario_card_layout = QVBoxLayout(inventario_card)
        inventario_card_layout.setContentsMargins(16, 16, 16, 16)
        inventario_card_layout.setSpacing(12)

        filtros_actual_layout = QHBoxLayout()
        filtros_actual_layout.setSpacing(10)
        self.search_inventario_actual = QLineEdit()
        self.search_inventario_actual.setPlaceholderText("Buscar lote por producto o código...")
        self.search_inventario_actual.setMinimumHeight(46)
        self.search_inventario_actual.setStyleSheet("font-size: 14px;")
        self.actual_search_bar = self.search_inventario_actual  # Compatibilidad con filtros previos
        filtros_actual_layout.addWidget(self.search_inventario_actual, 2)

        self.actual_stock_only_cb = QCheckBox("Solo con existencia")
        self.actual_stock_only_cb.setChecked(True)
        self.actual_stock_only_cb.setStyleSheet("font-size: 13px;")
        filtros_actual_layout.addWidget(self.actual_stock_only_cb)

        self.inventario_view_combo = QComboBox()
        self.inventario_view_combo.addItems(["Lotes", "Inventario general"])
        self.inventario_view_combo.setMinimumHeight(42)
        self.inventario_view_combo.setStyleSheet("font-size: 13px;")
        filtros_actual_layout.addWidget(self.inventario_view_combo)

        filtros_actual_layout.addStretch(1)

        self.btn_refresh_inventario = QPushButton("🔄 Recargar")
        self.btn_refresh_inventario.setObjectName("SecondaryActionButton")
        self.btn_refresh_inventario.setCursor(Qt.PointingHandCursor)
        self.btn_refresh_inventario.setMinimumHeight(42)
        self.btn_refresh_inventario.setStyleSheet("font-size: 13px; padding: 10px 14px;")
        filtros_actual_layout.addWidget(self.btn_refresh_inventario, 0, Qt.AlignRight)

        inventario_card_layout.addLayout(filtros_actual_layout)

        self.inventario_actual_table = QTableWidget(0, 10)
        self.inventario_actual_table.setHorizontalHeaderLabels([
            "Producto",
            "Código",
            "Cantidad",
            "Precio compra",
            "Código lote",
            "Registro sanitario",
            "Fecha compra",
            "Fecha vencimiento",
            "Distribuidor",
            "Acciones",
        ])
        self.inventario_actual_table.verticalHeader().hide()
        self.inventario_actual_table.setFrameShape(QFrame.NoFrame)
        self.inventario_actual_table.setShowGrid(False)
        self.inventario_actual_table.setAlternatingRowColors(False)
        self.inventario_actual_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.inventario_actual_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.inventario_actual_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.inventario_actual_table.verticalHeader().setDefaultSectionSize(60)
        header = self.inventario_actual_table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setDefaultAlignment(Qt.AlignCenter)
        header.setSectionResizeMode(0, QHeaderView.Stretch)           # Producto (principal)
        header.resizeSection(0, 300)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)  # Código
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)  # Cantidad
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)  # Precio compra
        header.setSectionResizeMode(4, QHeaderView.Stretch)           # Código lote (flex)
        header.resizeSection(4, 160)
        header.setSectionResizeMode(5, QHeaderView.Stretch)           # Registro sanitario (flex)
        header.resizeSection(5, 160)
        header.setSectionResizeMode(6, QHeaderView.ResizeToContents)  # Fecha compra
        header.setSectionResizeMode(7, QHeaderView.ResizeToContents)  # Fecha vencimiento
        header.setSectionResizeMode(8, QHeaderView.Stretch)           # Distribuidor (flex)
        header.resizeSection(8, 180)
        header.setSectionResizeMode(9, QHeaderView.ResizeToContents)  # Acciones
        card_delegate = CardBackgroundDelegate(self.inventario_actual_table)
        self.inventario_actual_table.setItemDelegate(card_delegate)
        self.inventario_actual_table.setItemDelegateForColumn(2, BatchQuantityDelegate(self.inventario_actual_table))
        self.inventario_actual_table.setItemDelegateForColumn(7, ExpirationDelegate(self.inventario_actual_table))
        self.inventario_actual_table.setWordWrap(False)
        inventario_card_layout.addWidget(self.inventario_actual_table)

        self.inventario_general_table = QTableWidget(0, 4)
        self.inventario_general_table.setHorizontalHeaderLabels([
            "Producto",
            "Código",
            "Precio",
            "Stock",
        ])
        self.inventario_general_table.verticalHeader().hide()
        self.inventario_general_table.setFrameShape(QFrame.NoFrame)
        self.inventario_general_table.setShowGrid(False)
        self.inventario_general_table.setAlternatingRowColors(False)
        self.inventario_general_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.inventario_general_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.inventario_general_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.inventario_general_table.verticalHeader().setDefaultSectionSize(60)
        general_header = self.inventario_general_table.horizontalHeader()
        general_header.setStretchLastSection(True)
        general_header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        general_header.setSectionResizeMode(QHeaderView.Stretch)
        general_delegate = CardBackgroundDelegate(self.inventario_general_table)
        self.inventario_general_table.setItemDelegate(general_delegate)
        self.inventario_general_table.setItemDelegateForColumn(3, StockDelegate(self.inventario_general_table))
        self.inventario_general_table.setVisible(False)
        inventario_card_layout.addWidget(self.inventario_general_table)

        inventario_actual_layout.addWidget(inventario_card)
        inventario_actual_tab.setLayout(inventario_actual_layout)

        # --- AGREGA LAS CUATRO PESTAÑAS AL QTabWidget ---
        self.tabs = QTabWidget()
        self.tabs.setMovable(True)
        tab_widget.setObjectName("Inicio")
        vend_dist_tab.setObjectName("Vendedores y Distribuidores")
        self.clientes_tab.setObjectName("Clientes")
        self.sales_tab.setObjectName("Ventas")
        self.compras_tab.setObjectName("Compras")
        inventario_actual_tab.setObjectName("InventarioActual")
        self.facturacion_tab = FacturacionTab(self.manager, self)
        self.facturacion_tab.setObjectName("Facturacion")

        self.tabs.addTab(tab_widget, "Inicio")
        self.tabs.addTab(vend_dist_tab, "Vendedores y Distribuidores")
        self.tabs.addTab(self.clientes_tab, "Clientes")
        self.tabs.addTab(self.sales_tab, "Ventas")
        self.tabs.addTab(self.compras_tab, "Compras")
        self.tabs.addTab(inventario_actual_tab, "Inventario")
        self.tabs.addTab(self.facturacion_tab, "Facturacion")
        inicio_index = self._find_tab_index("Inventario")
        if inicio_index != -1:
            self.tabs.setCurrentIndex(inicio_index)

        # --- PESTAÑA DE TRABAJADORES ---
        trabajadores_tab = QWidget()
        trabajadores_tab.setObjectName("Trabajadores")
        trabajadores_layout = QVBoxLayout(trabajadores_tab)
        trabajadores_layout.setContentsMargins(30, 30, 30, 30)
        trabajadores_layout.setSpacing(20)

        trabajadores_card = QFrame()
        trabajadores_card.setObjectName("ModernCard")
        trab_card_layout = QVBoxLayout(trabajadores_card)
        trab_card_layout.setContentsMargins(20, 25, 20, 20)
        trab_card_layout.setSpacing(15)

        trab_title = QLabel("Trabajadores")
        trab_title.setStyleSheet("font-size: 20px; font-weight: bold; color: #1a1a1a;")
        trab_card_layout.addWidget(trab_title)

        self.trabajadores_search = QLineEdit()
        self.trabajadores_search.setPlaceholderText("🔍 Buscar trabajador...")
        self.trabajadores_search.setMinimumHeight(40)
        self.trabajadores_search.textChanged.connect(self._actualizar_tabla_trabajadores)
        trab_card_layout.addWidget(self.trabajadores_search)

        filtro_layout = QHBoxLayout()
        self.trabajadores_filtro_vendedor = QCheckBox("Solo vendedores")
        self.trabajadores_filtro_vendedor.stateChanged.connect(self._actualizar_tabla_trabajadores)
        self.trabajadores_filtro_area = QLineEdit()
        self.trabajadores_filtro_area.setPlaceholderText("Filtrar por área/departamento")
        self.trabajadores_filtro_area.textChanged.connect(self._actualizar_tabla_trabajadores)
        filtro_layout.addWidget(self.trabajadores_filtro_vendedor)
        filtro_layout.addWidget(self.trabajadores_filtro_area)
        filtro_layout.addStretch(1)
        trab_card_layout.addLayout(filtro_layout)

        self.trabajadores_list = QListWidget()
        self.trabajadores_list.setFrameShape(QFrame.NoFrame)
        self.trabajadores_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.trabajadores_list.setMouseTracking(True)
        self.trab_delegate = ModernListDelegate(self.trabajadores_list)
        self.trabajadores_list.setItemDelegate(self.trab_delegate)
        self.trab_delegate.editClicked.connect(self._on_trabajador_edit_clicked)
        self.trab_delegate.deleteClicked.connect(self._on_trabajador_delete_clicked)
        trab_card_layout.addWidget(self.trabajadores_list)

        btns = QHBoxLayout()
        self.btn_add_trabajador = QPushButton("Nuevo Trabajador")
        self.btn_add_trabajador.setObjectName("PrimaryActionButton")
        self.btn_add_trabajador.setCursor(Qt.PointingHandCursor)
        btn_edit_trabajador = QPushButton("Editar")
        btn_edit_trabajador.setObjectName("SecondaryActionButton")
        btn_delete_trabajador = QPushButton("Eliminar")
        btn_delete_trabajador.setObjectName("DangerActionButton")
        self.btn_edit_trabajador = btn_edit_trabajador
        self.btn_delete_trabajador = btn_delete_trabajador
        for btn in (self.btn_add_trabajador, btn_edit_trabajador, btn_delete_trabajador):
            btn.setMinimumHeight(52)
            btn.setStyleSheet(btn.styleSheet() + "font-size: 16px;")

        btns.addWidget(self.btn_add_trabajador)
        btns.addStretch(1)
        btns.addWidget(btn_edit_trabajador)
        btns.addWidget(btn_delete_trabajador)
        trab_card_layout.addLayout(btns)

        trabajadores_layout.addWidget(trabajadores_card)
        trabajadores_tab.setLayout(trabajadores_layout)
        self.tabs.addTab(trabajadores_tab, "Trabajadores")

        # --- PESTAÑA DE ESTADOS DE CUENTA (REPORTES) ---
        self.estados_cuenta_tab = self.setup_estados_cuenta_ui()
        self.tabs.addTab(self.estados_cuenta_tab, "Estados de cuenta")

        # Siempre iniciar en la pestaña de inicio (Inventario)
        self._reset_tabs_to_default_order()
        inicio_index = self._find_tab_index("Inicio")
        if inicio_index != -1:
            self.tabs.setCurrentIndex(inicio_index)

        nav_items = [
            ("Inicio", "btn_nav_inventario", 0),
            ("Vendedores y\nDistribuidores", "btn_nav_vendedores", 1),
            ("Clientes", "btn_nav_clientes", 2),
            ("Ventas", "btn_nav_ventas", 3),
            ("Compras", "btn_nav_compras", 4),
            ("Inventario", "btn_nav_inventario_actual", 5),
            ("Facturacion", "btn_nav_facturacion", 6),
            ("Trabajadores", "btn_nav_trabajadores", 7),
            ("Estados de cuenta", "btn_nav_estado_cuenta", 8),
        ]
        bottom_items = [
            ("Guardar rápido", "btn_nav_guardar", 9),
            ("Configuración", "btn_nav_config", 10),
            ("Cerrar Sesión", "btn_nav_logout", 11),
        ]
        self.sidebar = ModernSidebar(nav_items, bottom_items, self)
        self.sidebar.connect_to_index_change(self.tabs.setCurrentIndex)
        self.tabs.currentChanged.connect(self.sidebar.set_active_index)
        self.sidebar.set_active_index(self.tabs.currentIndex())
        save_btn = self.sidebar.get_button("btn_nav_guardar")
        if save_btn:
            save_btn.clicked.connect(self.guardar_rapido)
        config_btn = self.sidebar.get_button("btn_nav_config")
        if config_btn:
            config_btn.clicked.connect(self._abrir_settings_dialog)
        logout_btn = self.sidebar.get_button("btn_nav_logout")
        if logout_btn:
            logout_btn.clicked.connect(self.cerrar_sesion)

        container = QWidget()
        root_layout = QHBoxLayout(container)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.tabs.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        root_layout.addWidget(self.sidebar)
        root_layout.addWidget(self.tabs, 1)
        root_layout.setStretch(0, 0)
        root_layout.setStretch(1, 1)
        self.tabs.tabBar().hide()
        self.setCentralWidget(container)

        # Conexiones
        self.btn_add_trabajador.clicked.connect(self._agregar_trabajador)
        self.btn_edit_trabajador.clicked.connect(self._editar_trabajador)
        self.btn_delete_trabajador.clicked.connect(self._eliminar_trabajador)
        self._actualizar_tabla_trabajadores()

        # Conexiones
        self.btn_guardar_rapido.clicked.connect(self.guardar_rapido)
        self.btn_guardar_inicio.clicked.connect(self.guardar_rapido)
        self.btn_cargar_inventario.clicked.connect(self.cargar_inventario)
        self.btn_add_product.clicked.connect(self.agregar_producto)
        self.btn_edit_product.clicked.connect(self.editar_producto)
        self.btn_register_sale.clicked.connect(self.registrar_venta)
        self.btn_register_credito_fiscal.clicked.connect(self.registrar_venta_credito_fiscal)
        self.btn_register_purchase.clicked.connect(self.registrar_compra)
        self.btn_delete_product.clicked.connect(self.eliminar_producto)
        self.btn_add_cliente.clicked.connect(self._agregar_cliente)
        self.btn_edit_cliente.clicked.connect(self._editar_cliente)
        self.btn_delete_cliente.clicked.connect(self._eliminar_cliente)
        self.cliente_search.textChanged.connect(self._actualizar_tabla_clientes)
        self.actual_search_bar.textChanged.connect(self._actualizar_inventario_actual)
        self.actual_stock_only_cb.toggled.connect(self._actualizar_inventario_actual)
        self.inventario_view_combo.currentIndexChanged.connect(self._actualizar_inventario_actual)
        self.btn_refresh_inventario.clicked.connect(self._actualizar_inventario_actual)
        self._actualizar_tabla_clientes()  # <-- SOLO AGREGA ESTA LÍNEA AL FINAL DE _setup_ui
        self.selected_row = None
        if hasattr(self, "inventario_view_combo"):
            self.inventario_view_combo.setCurrentIndex(1)  # Inventario general por defecto
        self._actualizar_inventario_actual()  # <-- AGREGA ESTA LÍNEA AL FINAL DE _setup_ui

    def _abrir_settings_dialog(self):
        if self._is_guest():
            self._deny_guest()
            return
        dlg = SettingsDialog(self)
        try:
            dlg.config_saved.connect(self._on_config_saved)
        except Exception:
            logger.exception("No se pudo conectar señal de config guardada")
        dlg.exec_()
        # Refresca la vista aunque el diálogo no emita señal (ej. usuarios/permisos)
        try:
            self._on_config_saved("settings_close")
        except Exception:
            logger.exception("No se pudo refrescar tras cerrar configuración")

    def _on_config_saved(self, section: str | None = None) -> None:
        """Refresca datos y vistas tras guardar cualquier configuración."""
        logger.info("Refrescando datos tras guardar configuración: %s", section)
        try:
            self.manager.refresh_data()
        except Exception:
            logger.exception("No se pudo refrescar datos del manager después de guardar config")
        try:
            self._actualizar_arbol_vendedores()
        except Exception:
            logger.exception("No se pudo refrescar árbol de vendedores")
        try:
            self._actualizar_arbol_Distribuidores()
        except Exception:
            logger.exception("No se pudo refrescar árbol de distribuidores")
        try:
            self.filter_products()
        except Exception:
            logger.exception("No se pudo refrescar listado de productos")
        try:
            self._actualizar_inventario_actual()
        except Exception:
            logger.exception("No se pudo refrescar inventario actual")
        try:
            self._actualizar_tabla_clientes()
        except Exception:
            logger.exception("No se pudo refrescar tabla de clientes")
        if hasattr(self, "compras_tab") and hasattr(self.compras_tab, "load_purchases"):
            try:
                self.compras_tab.load_purchases()
            except Exception:
                logger.exception("No se pudo refrescar pestaña de compras tras guardar config")
        if hasattr(self, "sales_tab") and hasattr(self.sales_tab, "load_sales"):
            try:
                self.sales_tab.load_sales()
            except Exception:
                logger.exception("No se pudo refrescar pestaña de ventas tras guardar config")
        self._refresh_pos_if_available()
        try:
            self.data_changed.emit()
        except Exception:
            logger.exception("No se pudo emitir data_changed tras guardar config")

    def _apply_styles(self):
        self.setStyleSheet(
            """
            QFrame#InventoryFilterCard {
                background-color: #ffffff;
                border: 1px solid #e5e7eb;
                border-radius: 12px;
            }
            QFrame#ModernCard {
                background-color: #ffffff;
                border: 1px solid #E2E8F0;
                border-radius: 16px;
                border-bottom: 3px solid #F1F5F9;
            }
            QListWidget {
                background-color: transparent;
                border: none;
                outline: none;
            }
            QListWidget::item {
                border-bottom: 1px solid #F1F5F9;
                padding: 10px;
            }
            QListWidget::item:selected {
                background-color: transparent;
            }
            QListWidget::item:hover {
                background-color: transparent;
            }
            QLineEdit {
                border: 1px solid #dcdde1;
                border-radius: 8px;
                padding: 8px 10px;
                font-size: 14px;
            }
            QTableView {
                background: #fff;
                border-radius: 8px;
                font-size: 13px;
            }
            /* TABLA MODERNA */
            QTableView {
                background-color: white;
                border: 1px solid #F3F4F6;
                border-radius: 8px;
                gridline-color: transparent;
            }
            QTableView::item {
                border-bottom: 1px solid #F3F4F6;
                padding-left: 10px;
            }
            QTableView::item:selected {
                background-color: #F0F9FF;
                color: #0369A1;
                border-bottom: 1px solid #E0F2FE;
            }
            QHeaderView::section {
                background-color: white;
                color: #6B7280;
                font-weight: bold;
                text-transform: uppercase;
                border: none;
                border-bottom: 2px solid #E5E7EB;
                padding-left: 10px;
            }
            QPushButton#PrimaryActionButton {
                background-color: #0ea5e9;
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 10px 14px;
                font-weight: 600;
            }
            QPushButton#PrimaryActionButton:hover {
                background-color: #0284c7;
            }
            QPushButton#SecondaryActionButton {
                background-color: #ffffff;
                color: #1f2937;
                border: 1px solid #e5e7eb;
                border-radius: 6px;
                padding: 10px 14px;
                font-weight: 600;
            }
            QPushButton#SecondaryActionButton:hover {
                background-color: #f8fafc;
                border-color: #cbd5e1;
            }
            QPushButton#DangerActionButton {
                background-color: #ef4444;
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 10px 14px;
                font-weight: 600;
            }
            QPushButton#DangerActionButton:hover {
                background-color: #dc2626;
            }
        """
        )

    def filter_products(self):
        search = self.search_bar.text()
        vendedor_id = self.vendedor_combo_filtro.currentData()

        Distribuidor_id = None
        if hasattr(self, "distribuidor_combo_filtro"):
            Distribuidor_id = self.distribuidor_combo_filtro.currentData()


        # Orden por stock
        stock_sort = None
        if hasattr(self, "stock_sort_combo"):
            stock_sort = self.stock_sort_combo.currentIndex()

        self.manager.filter_products(
            vendedor_id=vendedor_id,
            Distribuidor_id=Distribuidor_id,
            search=search,
        )
        productos = self.manager._products

        if stock_sort == 1:  # Más stock a menos
            productos = sorted(productos, key=lambda x: x.get("stock", 0), reverse=True)
        elif stock_sort == 2:  # Menos stock a más
            productos = sorted(productos, key=lambda x: x.get("stock", 0))

        self.manager._model.update_data(productos)
        self.product_table.setModel(self.manager.get_products_model())

    def setup_vendedores_distribuidores_ui(self):
        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(30, 30, 30, 30)
        main_layout.setSpacing(25)

        vendedores_card = QFrame()
        vendedores_card.setObjectName("ModernCard")
        card_layout = QVBoxLayout(vendedores_card)
        card_layout.setContentsMargins(20, 25, 20, 20)
        card_layout.setSpacing(15)

        vendedores_title = QLabel("Vendedores")
        vendedores_title.setStyleSheet("font-size: 20px; font-weight: bold; color: #1a1a1a;")
        card_layout.addWidget(vendedores_title)

        self.vendedores_search = QLineEdit()
        self.vendedores_search.setPlaceholderText("\ud83d\udd0d Buscar vendedor...")
        self.vendedores_search.setMinimumHeight(40)
        self.vendedores_search.textChanged.connect(self._actualizar_arbol_vendedores)
        card_layout.addWidget(self.vendedores_search)

        self.vendedores_list = QListWidget()
        self.vendedores_list.setFrameShape(QFrame.NoFrame)
        self.vendedores_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.vend_delegate = ModernListDelegate(self.vendedores_list)
        self.vendedores_list.setItemDelegate(self.vend_delegate)
        self.vendedores_list.setMouseTracking(True)
        self.vend_delegate.editClicked.connect(self._on_vendedor_edit_clicked)
        self.vend_delegate.deleteClicked.connect(self._on_vendedor_delete_clicked)
        card_layout.addWidget(self.vendedores_list)

        vend_btns_layout = QHBoxLayout()
        self.btn_add_vendedor = QPushButton("Nuevo Vendedor")
        self.btn_add_vendedor.setObjectName("PrimaryActionButton")
        self.btn_add_vendedor.setCursor(Qt.PointingHandCursor)
        btn_edit_vendedor = QPushButton("Editar")
        btn_edit_vendedor.setObjectName("SecondaryActionButton")
        btn_delete_vendedor = QPushButton("Eliminar")
        btn_delete_vendedor.setObjectName("DangerActionButton")
        for btn in (self.btn_add_vendedor, btn_edit_vendedor, btn_delete_vendedor):
            btn.setMinimumHeight(52)
            btn.setStyleSheet(btn.styleSheet() + "font-size: 16px;")

        self.btn_add_vendedor.clicked.connect(self._agregar_vendedor)
        btn_edit_vendedor.clicked.connect(self._editar_vendedor)
        btn_delete_vendedor.clicked.connect(self._eliminar_vendedor)

        vend_btns_layout.addWidget(self.btn_add_vendedor)
        vend_btns_layout.addStretch(1)
        vend_btns_layout.addWidget(btn_edit_vendedor)
        vend_btns_layout.addWidget(btn_delete_vendedor)
        card_layout.addLayout(vend_btns_layout)

        main_layout.addWidget(vendedores_card)

        distribuidores_card = QFrame()
        distribuidores_card.setObjectName("ModernCard")
        card_layout_d = QVBoxLayout(distribuidores_card)
        card_layout_d.setContentsMargins(20, 25, 20, 20)
        card_layout_d.setSpacing(15)

        title_d = QLabel("Distribuidores")
        title_d.setStyleSheet("font-size: 20px; font-weight: bold; color: #1a1a1a;")
        card_layout_d.addWidget(title_d)

        self.distribuidores_search = QLineEdit()
        self.distribuidores_search.setPlaceholderText("\ud83d\udd0d Buscar distribuidor...")
        self.distribuidores_search.setMinimumHeight(40)
        self.distribuidores_search.textChanged.connect(self._actualizar_arbol_Distribuidores)
        card_layout_d.addWidget(self.distribuidores_search)

        self.distribuidores_list = QListWidget()
        self.distribuidores_list.setFrameShape(QFrame.NoFrame)
        self.distribuidores_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.distrib_delegate = ModernListDelegate(self.distribuidores_list)
        self.distribuidores_list.setItemDelegate(self.distrib_delegate)
        self.distribuidores_list.setMouseTracking(True)
        self.distrib_delegate.editClicked.connect(self._on_distribuidor_edit_clicked)
        self.distrib_delegate.deleteClicked.connect(self._on_distribuidor_delete_clicked)
        card_layout_d.addWidget(self.distribuidores_list)

        btns_layout_d = QHBoxLayout()
        self.btn_add_distribuidor = QPushButton("Nuevo Distribuidor")
        self.btn_add_distribuidor.setObjectName("PrimaryActionButton")
        self.btn_add_distribuidor.setCursor(Qt.PointingHandCursor)
        btn_info = QPushButton("Ver Información")
        btn_info.setObjectName("SecondaryActionButton")
        btn_edit_d = QPushButton("Editar")
        btn_edit_d.setObjectName("SecondaryActionButton")
        btn_delete_d = QPushButton("Eliminar")
        btn_delete_d.setObjectName("DangerActionButton")
        for btn in (self.btn_add_distribuidor, btn_info, btn_edit_d, btn_delete_d):
            btn.setMinimumHeight(52)
            btn.setStyleSheet(btn.styleSheet() + "font-size: 16px;")

        self.btn_add_distribuidor.clicked.connect(self._agregar_Distribuidor)
        btn_info.clicked.connect(self._mostrar_info_Distribuidor)
        btn_edit_d.clicked.connect(self._editar_Distribuidor)
        btn_delete_d.clicked.connect(self._eliminar_Distribuidor)

        btns_layout_d.addWidget(self.btn_add_distribuidor)
        btns_layout_d.addStretch(1)
        btns_layout_d.addWidget(btn_info)
        btns_layout_d.addWidget(btn_edit_d)
        btns_layout_d.addWidget(btn_delete_d)
        card_layout_d.addLayout(btns_layout_d)

        main_layout.addWidget(distribuidores_card)

        if self.vendedores_tab.layout():
            QWidget().setLayout(self.vendedores_tab.layout())
        self.vendedores_tab.setLayout(main_layout)
        self._actualizar_arbol_vendedores()
        self._actualizar_arbol_Distribuidores()

    def setup_estados_cuenta_ui(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)

        title = QLabel("Reportes de Estados de Cuenta")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #1E293B;")
        layout.addWidget(title)

        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(20)

        label_style = "color: #334155; font-weight: 600; font-size: 13px;"
        input_style = (
            "QComboBox, QDateEdit, QLineEdit {"
            "  min-height: 38px;"
            "  font-size: 13px;"
            "  padding: 6px 10px;"
            "  border: 1px solid #E2E8F0;"
            "  border-radius: 8px;"
            "}"
        )
        radio_style = "QRadioButton { font-size: 13px; color: #1F2937; }"

        today = QDate.currentDate()
        start_month = QDate(today.year(), today.month(), 1)
        end_month = start_month.addMonths(1).addDays(-1)

        def build_reporte_card(icon_text, title_text, combo_placeholder, radio_labels, default_idx, button_text, button_color):
            card = QFrame()
            card.setObjectName("ModernCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(20, 20, 20, 20)
            card_layout.setSpacing(14)

            header = QHBoxLayout()
            icon = QLabel(icon_text)
            icon_font = icon.font()
            icon_font.setPointSize(18)
            icon.setFont(icon_font)
            title_lbl = QLabel(title_text)
            title_lbl.setStyleSheet("font-size: 18px; font-weight: 700; color: #0F172A;")
            header.addWidget(icon)
            header.addSpacing(6)
            header.addWidget(title_lbl)
            header.addStretch(1)
            card_layout.addLayout(header)

            combo_label = QLabel("Seleccionar " + combo_placeholder)
            combo_label.setStyleSheet(label_style)
            combo = QComboBox()
            combo.addItem("Todos")
            combo.setStyleSheet(input_style)
            card_layout.addWidget(combo_label)
            card_layout.addWidget(combo)

            rango_lbl = QLabel("Rango de Fechas")
            rango_lbl.setStyleSheet(label_style)
            card_layout.addWidget(rango_lbl)
            filtro_fecha_chk = QCheckBox("Filtrar por fechas")
            filtro_fecha_chk.setStyleSheet("font-size: 13px; color: #0F172A;")
            rango_layout = QHBoxLayout()
            desde_lbl = QLabel("Desde")
            desde_lbl.setStyleSheet(label_style)
            hasta_lbl = QLabel("Hasta")
            hasta_lbl.setStyleSheet(label_style)
            desde_edit = QDateEdit(start_month)
            desde_edit.setCalendarPopup(True)
            desde_edit.setStyleSheet(input_style)
            hasta_edit = QDateEdit(end_month)
            hasta_edit.setCalendarPopup(True)
            hasta_edit.setStyleSheet(input_style)
            dash = QLabel("—")
            dash.setStyleSheet("color: #94A3B8; font-size: 16px;")
            rango_layout.addWidget(desde_lbl)
            rango_layout.addWidget(desde_edit)
            rango_layout.addWidget(dash)
            rango_layout.addWidget(hasta_lbl)
            rango_layout.addWidget(hasta_edit)
            card_layout.addWidget(filtro_fecha_chk)
            card_layout.addLayout(rango_layout)
            desde_edit.setEnabled(False)
            hasta_edit.setEnabled(False)

            def _toggle_dates(checked: bool):
                desde_edit.setEnabled(checked)
                hasta_edit.setEnabled(checked)

            filtro_fecha_chk.toggled.connect(_toggle_dates)

            tipo_lbl = QLabel("Tipo de Reporte")
            tipo_lbl.setStyleSheet(label_style)
            card_layout.addWidget(tipo_lbl)
            radios_layout = QVBoxLayout()
            radio_group = QButtonGroup(card)
            radio_widgets = []
            for idx, text in enumerate(radio_labels):
                rb = QRadioButton(text)
                rb.setStyleSheet(radio_style)
                rb.setChecked(idx == default_idx)
                radio_group.addButton(rb, idx)
                radio_widgets.append(rb)
                radios_layout.addWidget(rb)
            card_layout.addLayout(radios_layout)

            btn = QPushButton(button_text)
            btn.setMinimumHeight(46)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(
                f"background-color: {button_color}; color: white; font-weight: 700; "
                "border: none; border-radius: 10px; font-size: 15px; padding: 12px;"
            )
            card_layout.addWidget(btn)

            return card, combo, filtro_fecha_chk, desde_edit, hasta_edit, radio_group, radio_widgets, btn

        cliente_card, self.reportes_cliente_combo, self.reportes_cliente_filtro_fecha, self.reportes_cliente_desde, self.reportes_cliente_hasta, self.reportes_cliente_tipo_group, self.reportes_cliente_radios, self.reportes_cliente_btn = build_reporte_card(
            "👤",
            "Reportes de Clientes (Compras y Saldos)",
            "Cliente",
            ["Historial de Compras"],
            0,
            "Generar Reporte Cliente",
            "#2563EB",
        )

        vendedor_card, self.reportes_vendedor_combo, self.reportes_vendedor_filtro_fecha, self.reportes_vendedor_desde, self.reportes_vendedor_hasta, self.reportes_vendedor_tipo_group, self.reportes_vendedor_radios, self.reportes_vendedor_btn = build_reporte_card(
            "💼",
            "Reportes de Vendedores (Ventas y Desempeño)",
            "Vendedor",
            ["Total Ventas"],
            0,
            "Generar Reporte Vendedor",
            "#0F766E",
        )

        cards_layout.addWidget(cliente_card)
        cards_layout.addWidget(vendedor_card)
        layout.addLayout(cards_layout)

        self.reportes_cliente_btn.clicked.connect(self._generar_reporte_cliente)
        self.reportes_vendedor_btn.clicked.connect(self._generar_reporte_vendedor)

        preview_title = QLabel("Previsualización de Reporte Reciente")
        preview_title.setStyleSheet("font-size: 16px; font-weight: 600; color: #1F2937;")
        layout.addWidget(preview_title)

        preview_frame = QFrame()
        preview_frame.setObjectName("PreviewPlaceholder")
        preview_frame.setStyleSheet("background-color: #F1F5F9; border: 1px dashed #CBD5E1; border-radius: 12px;")
        preview_layout = QVBoxLayout(preview_frame)
        preview_layout.setContentsMargins(24, 32, 24, 32)
        preview_label = QLabel("Aquí se mostrará la previsualización del reporte generado.")
        preview_label.setAlignment(Qt.AlignCenter)
        preview_label.setStyleSheet("color: #475569; font-size: 14px;")
        preview_layout.addWidget(preview_label)
        layout.addWidget(preview_frame)

        layout.addStretch(1)
        self._populate_estados_reportes_data()
        return tab

    def _on_vendedor_edit_clicked(self, index: QModelIndex):
        self.vendedores_list.setCurrentIndex(index)
        self._editar_vendedor()

    def _on_vendedor_delete_clicked(self, index: QModelIndex):
        self.vendedores_list.setCurrentIndex(index)
        self._eliminar_vendedor()

    def _on_distribuidor_edit_clicked(self, index: QModelIndex):
        self.distribuidores_list.setCurrentIndex(index)
        self._editar_Distribuidor()

    def _on_distribuidor_delete_clicked(self, index: QModelIndex):
        self.distribuidores_list.setCurrentIndex(index)
        self._eliminar_Distribuidor()

    def _on_trabajador_edit_clicked(self, index: QModelIndex):
        if hasattr(self, "trabajadores_list"):
            self.trabajadores_list.setCurrentIndex(index)
        self._editar_trabajador()

    def _on_trabajador_delete_clicked(self, index: QModelIndex):
        if hasattr(self, "trabajadores_list"):
            self.trabajadores_list.setCurrentIndex(index)
        self._eliminar_trabajador()

    def show_sales_dialog(self):
        """Atajo desde el sidebar para abrir el flujo de venta."""
        self.registrar_venta()

    def setup_clientes_ui(self):
        layout = QVBoxLayout(self.clientes_tab)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)

        title = QLabel("Gestión de Clientes")
        title_font = title.font()
        title_font.setPointSize(24)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)

        card = QFrame()
        card.setObjectName("ModernCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 20, 20, 20)
        card_layout.setSpacing(16)

        header_row = QHBoxLayout()
        header_row.setSpacing(12)

        self.search_bar_clientes = QLineEdit()
        self.search_bar_clientes.setPlaceholderText("Buscar cliente por nombre, código, NIT, etc.")
        self.search_bar_clientes.setMinimumHeight(46)
        self.search_bar_clientes.setStyleSheet("font-size: 15px;")
        self.search_bar_clientes.textChanged.connect(self._actualizar_tabla_clientes)
        header_row.addWidget(self.search_bar_clientes, 1)

        lbl_style = "color: #4B5563; font-weight: 600;"
        lbl_vend = QLabel("Vendedor:")
        lbl_vend.setStyleSheet(lbl_style)
        header_row.addWidget(lbl_vend)
        self.cliente_vendedor_filtro = QComboBox()
        self.cliente_vendedor_filtro.setMinimumHeight(42)
        self.cliente_vendedor_filtro.setStyleSheet("font-size: 14px;")
        self.cliente_vendedor_filtro.addItem("Todos")
        header_row.addWidget(self.cliente_vendedor_filtro)

        lbl_dep = QLabel("Departamento:")
        lbl_dep.setStyleSheet(lbl_style)
        header_row.addWidget(lbl_dep)
        self.cliente_departamento_filtro = QComboBox()
        self.cliente_departamento_filtro.setMinimumHeight(42)
        self.cliente_departamento_filtro.setStyleSheet("font-size: 14px;")
        self.cliente_departamento_filtro.addItem("Todos")
        header_row.addWidget(self.cliente_departamento_filtro)

        header_row.addStretch(1)
        card_layout.addLayout(header_row)

        self.clientes_table = QTableWidget(0, 10)
        self.clientes_table.setHorizontalHeaderLabels([
            "Código", "Nombre", "NRC", "NIT", "DUI", "Giro", "Teléfono", "Correo", "Departamento", "Municipio"
        ])
        self.clientes_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.clientes_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.clientes_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.clientes_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.clientes_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.clientes_table.setFrameShape(QFrame.NoFrame)
        self.clientes_table.setShowGrid(False)
        self.clientes_table.setAlternatingRowColors(False)
        self.clientes_table.setStyleSheet(self.clientes_table.styleSheet() + "font-size: 14px;")
        self.clientes_table.verticalHeader().hide()
        self.clientes_table.verticalHeader().setDefaultSectionSize(60)
        header = self.clientes_table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header.setFixedHeight(50)
        card_layout.addWidget(self.clientes_table)

        footer = QHBoxLayout()
        self.btn_add_cliente = QPushButton("Nuevo Cliente")
        self.btn_add_cliente.setObjectName("PrimaryActionButton")
        self.btn_add_cliente.setMinimumHeight(50)
        self.btn_add_cliente.setStyleSheet(self.btn_add_cliente.styleSheet() + "font-size: 15px;")
        footer.addWidget(self.btn_add_cliente)
        footer.addStretch(1)
        self.btn_edit_cliente = QPushButton("Editar Cliente")
        self.btn_edit_cliente.setObjectName("SecondaryActionButton")
        self.btn_edit_cliente.setMinimumHeight(50)
        self.btn_edit_cliente.setStyleSheet(self.btn_edit_cliente.styleSheet() + "font-size: 15px;")
        self.btn_delete_cliente = QPushButton("Eliminar Cliente")
        self.btn_delete_cliente.setObjectName("DangerActionButton")
        self.btn_delete_cliente.setMinimumHeight(50)
        self.btn_delete_cliente.setStyleSheet(self.btn_delete_cliente.styleSheet() + "font-size: 15px;")
        footer.addWidget(self.btn_edit_cliente)
        footer.addWidget(self.btn_delete_cliente)
        card_layout.addLayout(footer)

        layout.addWidget(card)
        self.cliente_search = self.search_bar_clientes

    def agregar_producto(self):
        if self._is_guest():
            self._deny_guest()
            return
        dialog = ProductDialog(self.manager._vendedores, self.manager._Distribuidores, self)
        if dialog.exec_():
            data = dialog.get_data()
            self.manager.add_producto(
                data["nombre"], data["codigo"], data["sku"], None, None,
                data["precio_compra"], data["precio_venta_minorista"], data["precio_venta_mayorista"], 0,
                presentaciones=data.get("presentaciones"),
            )
            self._actualizar_arbol_vendedores()
            self._actualizar_arbol_Distribuidores()
            if hasattr(self, "vendedor_combo_filtro"):
                self.vendedor_combo_filtro.blockSignals(True)
                self.vendedor_combo_filtro.setCurrentIndex(0)
                self.vendedor_combo_filtro.blockSignals(False)

            self.filter_products()
            QMessageBox.information(self, "Producto", "Producto agregado correctamente.")

    def editar_producto(self):
        if self._is_guest():
            self._deny_guest()
            return
        prod = self._get_selected_product()
        if not prod:
            QMessageBox.warning(self, "Editar producto", "Seleccione un producto para editar.")
            return
        dialog = ProductDialog(self.manager._vendedores, self.manager._Distribuidores, self, producto=prod)
        if dialog.exec_():
            data = dialog.get_data()
            self.manager.edit_producto(
                prod["id"],
                data["nombre"], data["codigo"], data["sku"],
                prod.get("vendedor_id"),  # Mantén el vendedor original
                prod.get("Distribuidor_id"),  # Mantén el Distribuidor original
                data["precio_compra"], data["precio_venta_minorista"], data["precio_venta_mayorista"], data.get("stock", prod.get("stock", 0)),
                presentaciones=data.get("presentaciones"),
            )
            self.filter_products()
            QMessageBox.information(self, "Producto", "Producto editado correctamente.")
        self.selected_row = None

    def eliminar_producto(self):
        if self._is_guest():
            self._deny_guest()
            return
        prod = self._get_selected_product()
        if not prod:
            QMessageBox.warning(self, "Eliminar producto", "Seleccione un producto para eliminar.")
            return
        confirm = QMessageBox.question(self, "Eliminar", f"¿Eliminar producto '{prod['nombre']}'?", QMessageBox.Yes | QMessageBox.No)
        if confirm == QMessageBox.Yes:
            self.manager.delete_producto(prod["id"])
            self._actualizar_arbol_vendedores()
            self._actualizar_arbol_Distribuidores()
            self.filter_products()
            QMessageBox.information(self, "Producto eliminado", f"El producto '{prod['nombre']}' ha sido eliminado.")
        self.selected_row = None

    def _auto_enviar_factura(self, venta_id: int, tipo_dte: str | None = None) -> tuple[bool, str, dict]:
        """Envía la factura asociada a la venta y devuelve (ok, detalle, meta)."""
        preview_data = None
        snapshot_paths: list[str] = []
        try:
            preview_data = dte.generar_dte_json(self.manager.db, venta_id, tipo_dte=tipo_dte)
            snapshot_paths = list(dte._iter_snapshot_json_paths(preview_data))  # type: ignore[attr-defined]
        except Exception:
            snapshot_paths = []
        try:
            resp = dte.enviar_factura(self.manager.db, venta_id, tipo_dte=tipo_dte)
            estado = (
                resp.get("estado")
                or resp.get("estadoDte")
                or resp.get("descripcionEstado")
                or resp.get("descripcionEstadoDte")
                or "Enviado"
            )
            estado_text = str(estado)
            rejected = "rechaz" in estado_text.lower()
            json_path = None
            if rejected and preview_data:
                for candidate in snapshot_paths:
                    if candidate and Path(candidate).exists():
                        json_path = candidate
                        break
            meta = {
                "rejected": rejected,
                "json_path": json_path,
                "tipo_dte": tipo_dte,
                "respuesta": resp,
            }
            return not rejected, estado_text, meta
        except Exception as exc:  # pragma: no cover - se informa al usuario
            logger.exception("Error al enviar factura automáticamente (venta_id=%s)", venta_id, exc_info=exc)
            return False, str(exc), {"rejected": False, "json_path": None, "tipo_dte": tipo_dte}

    def _handle_dte_rechazo(self, venta_id: int, tipo_dte: str, estado: str, meta: dict) -> None:
        """Ofrece editar los datos del cliente en el JSON cuando Hacienda rechaza el DTE."""
        json_path = meta.get("json_path")
        self._registrar_estado_dte_ui(venta_id, tipo_dte, "pendiente")
        prompt = QMessageBox(self)
        prompt.setIcon(QMessageBox.Warning)
        prompt.setWindowTitle("Factura rechazada por Hacienda")
        prompt.setText("La factura fue rechazada por Hacienda.")
        prompt.setInformativeText(
            "¿Deseas editar los datos del cliente en el JSON y reintentar el envío?"
        )
        prompt.setDetailedText(str(meta.get("respuesta") or estado))
        prompt.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        prompt.setDefaultButton(QMessageBox.Yes)
        if prompt.exec_() != QMessageBox.Yes:
            return
        if not json_path or not Path(json_path).exists():
            QMessageBox.warning(
                self,
                "Archivo no encontrado",
                "No se encontró el archivo JSON de la factura fallida para editar.",
            )
            return
        warn = QMessageBox(self)
        warn.setIcon(QMessageBox.Warning)
        warn.setWindowTitle("ADVERTENCIA")
        warn.setText(
            "Este NO es un error del sistema. Hacienda rechazó el DTE por datos erróneos."
        )
        warn.setInformativeText(
            "¿Deseas editar el DTE y reintentar el envío?"
        )
        warn.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        warn.setDefaultButton(QMessageBox.No)
        if warn.exec_() != QMessageBox.Yes:
            return
        confirm = QMessageBox(self)
        confirm.setIcon(QMessageBox.Warning)
        confirm.setWindowTitle("Proceder con cuidado")
        confirm.setText(
            "Ciertos cambios pueden traer problemas con Hacienda o contabilidad."
        )
        confirm.setInformativeText(
            "Proceda solo si está seguro. Vertex no se hace responsable por manipulaciones erróneas en los DTE."
        )
        confirm.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        confirm.setButtonText(QMessageBox.Yes, "Continuar")
        confirm.setButtonText(QMessageBox.No, "Regresar")
        confirm.setDefaultButton(QMessageBox.No)
        if confirm.exec_() != QMessageBox.Yes:
            return
        self._editar_dte_receptor_y_reenviar(venta_id, tipo_dte, json_path)

    def _editar_dte_receptor_y_reenviar(self, venta_id: int, tipo_dte: str, json_path: str) -> None:
        """Permite editar la sección de receptor del DTE fallido y reintentar el envío."""
        try:
            with open(json_path, "r", encoding="utf-8") as fh:
                dte_data = json.load(fh)
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Error al leer DTE",
                f"No se pudo leer el JSON del DTE:\n{exc}",
            )
            return

        receptor = dte_data.get("receptor") or {}
        editor = QDialog(self)
        editor.setWindowTitle("Editar datos del cliente (JSON)")
        layout = QVBoxLayout(editor)
        layout.addWidget(QLabel("Edita únicamente los datos del cliente (objeto JSON)."))
        text_edit = QTextEdit()
        text_edit.setPlainText(json.dumps(receptor, ensure_ascii=False, indent=2))
        text_edit.setLineWrapMode(QTextEdit.NoWrap)
        layout.addWidget(text_edit)
        btns = QHBoxLayout()
        btns.addStretch(1)
        btn_ok = QPushButton("Guardar y reenviar")
        btn_cancel = QPushButton("Cancelar")
        btns.addWidget(btn_cancel)
        btns.addWidget(btn_ok)
        layout.addLayout(btns)
        btn_cancel.clicked.connect(editor.reject)
        btn_ok.clicked.connect(editor.accept)

        if editor.exec_() != QDialog.Accepted:
            return

        try:
            nuevo_receptor = json.loads(text_edit.toPlainText() or "{}")
            if not isinstance(nuevo_receptor, dict):
                raise ValueError("El receptor debe ser un objeto JSON.")
        except Exception as exc:
            QMessageBox.warning(
                self,
                "JSON inválido",
                f"No se pudo interpretar el JSON del cliente:\n{exc}",
            )
            return

        dte_data["receptor"] = nuevo_receptor
        try:
            with open(json_path, "w", encoding="utf-8") as fh:
                json.dump(dte_data, fh, ensure_ascii=False, indent=2)
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Error al guardar",
                f"No se pudo escribir el JSON actualizado:\n{exc}",
            )
            return

        try:
            resp = dte._enviar_documento(self.manager.db, venta_id, dte_data)  # type: ignore[attr-defined]
            estado = (
                resp.get("estado")
                or resp.get("estadoDte")
                or resp.get("descripcionEstado")
                or resp.get("descripcionEstadoDte")
                or "Enviado"
            )
            estado_text = str(estado)
            rejected = "rechaz" in estado_text.lower()
            if rejected:
                QMessageBox.warning(
                    self,
                    "Factura aún rechazada",
                    f"La factura sigue siendo rechazada.\nDetalle: {estado_text}",
                )
                self._registrar_estado_dte_ui(venta_id, tipo_dte, "pendiente")
            else:
                self._registrar_estado_dte_ui(venta_id, tipo_dte, "enviado")
                QMessageBox.information(
                    self,
                    "Factura reenviada",
                    f"La factura se envió nuevamente.\nEstado: {estado_text}",
                )
        except Exception as exc:
            logger.exception("No se pudo reenviar el DTE tras editar receptor")
            QMessageBox.critical(
                self,
                "Reenvío fallido",
                f"No se pudo reenviar la factura tras editar el cliente:\n{exc}",
            )
            self._registrar_estado_dte_ui(venta_id, tipo_dte, "pendiente")

    def _mostrar_confirmacion_venta(self) -> int:
        dialog = SaleConfirmationDialog(self)
        return dialog.exec_()

    def _generar_dte_sin_enviar(self, venta_id: int, tipo_dte: str) -> tuple[bool, str]:
        """Genera y firma el DTE pero no lo envía a Hacienda."""
        try:
            data = dte.generar_dte_json(self.manager.db, venta_id, tipo_dte=tipo_dte)
            try:
                dte.recalcular_totales(data, incluir_iva=True)
            except Exception:
                pass
            try:
                data = dte.apply_schema_patch(data)
            except Exception:
                pass
            signed = sign_json(data)
            try:
                dte._save_signed_dte(data, signed, fallido=False)
            except Exception:
                pass
            ident = data.get("identificacion") or {}
            try:
                self.manager.db.registrar_envio_dte(
                    venta_id,
                    "manual",
                    "Pendiente",
                    "",
                    codigo_generacion=ident.get("codigoGeneracion"),
                    numero_control=ident.get("numeroControl"),
                    ambiente=ident.get("ambiente"),
                )
            except Exception:
                pass
            return True, "DTE generado y guardado (pendiente de envío)."
        except Exception as exc:  # pragma: no cover - se informa al usuario
            logger.exception("Error al generar DTE sin enviar (venta_id=%s)", venta_id, exc_info=exc)
            return False, str(exc)

    def registrar_venta(self):
        if self._is_guest():
            self._deny_guest()
            return
        if not self._ensure_last_invoice_sent():
            return
        # Obtén los lotes con stock > 0 del inventario actual
        productos_lote = []
        compras = self.manager.db.get_compras()
        productos_dict = {p["id"]: p for p in self.manager._products}
        for compra in compras:
            detalles = self.manager.db.get_detalles_compra(compra["id"])
            for d in detalles:
                prod = productos_dict.get(d["producto_id"])
                if not prod:
                    continue
                if d.get("cantidad", 0) > 0:
                    # Incluye info de lote, producto, distribuidor y precios de venta
                    productos_lote.append({
                        "lote_id": d["id"],
                        "producto_id": d["producto_id"],
                        "nombre": prod.get("nombre", ""),
                        "codigo": prod.get("codigo", ""),
                        "codigo_lote": d.get("codigo_lote", ""),
                        "registro_sanitario": d.get("registro_sanitario", ""),
                        "stock": d.get("cantidad", 0),
                        "precio_unitario": d.get("precio_unitario", 0),
                        "vendedor_id": prod.get("vendedor_id"),
                        "Distribuidor_id": compra.get("Distribuidor_id"),
                        "fecha_vencimiento": d.get("fecha_vencimiento", ""),
                        "precio_venta_minorista": prod.get("precio_venta_minorista", 0),
                        "precio_venta_mayorista": prod.get("precio_venta_mayorista", 0),
                        "presentaciones": prod.get("presentaciones"),
                    })
        Distribuidores = [v["nombre"] for v in self.manager._Distribuidores]
        vendedores_trabajadores = self.manager.db.get_trabajadores(solo_vendedores=True)
        dialog = RegisterSaleDialog(productos_lote, Distribuidores, vendedores_trabajadores, self)
        try:
            if dialog.exec_():
                data = dialog.get_data()
                self._procesar_venta_consumidor_final(data, dialog.Distribuidor_combo.currentText())
                dialog.clear_carrito()

        except Exception as e:
            QMessageBox.critical(self, "Error al registrar venta", str(e))
            self._actualizar_historial()

    def registrar_compra(self):
        if self._is_guest():
            self._deny_guest()
            return
        productos = [dict(p) for p in self.manager._products]
        Distribuidores = [dict(v) for v in self.manager._Distribuidores]
        proveedores = [dict(v) for v in self.manager.get_vendedores_compra()]
        dialog = RegisterPurchaseDialog(
            productos,
            Distribuidores,
            proveedores,
            self
        )
        try:
            result = dialog.exec_()
            if result == QDialog.Accepted:
                msg = "Compra registrada correctamente."
                # Nota: si el proveedor es sujeto excluido, el hook genera y guarda el DTE 14 localmente.
                if getattr(dialog, "is_subject_excluded_purchase", False):
                    msg += "\nSe generó el DTE de sujeto excluido (pendiente de envío)."
                QMessageBox.information(self, "Compra", msg)
                self.manager.refresh_data()
                self.compras_tab.refresh_filters()
                self.compras_tab.load_purchases()
                self.sales_tab.load_sales()
                self.filter_products()
                self._actualizar_historial()
                self._actualizar_inventario_actual()
                self._refresh_pos_if_available()
        except Exception as e:
            QMessageBox.critical(self, "Error al registrar compra", str(e))

    def _procesar_venta_consumidor_final(self, data: dict, distribuidor_nombre: str | None = None):
        """Guarda la venta CF y ejecuta el flujo de confirmación/envío."""
        items = data.get("items", [])
        if not items:
            raise ValueError("Debe agregar al menos un producto a la venta.")
        # Refresca inventario para asegurar IDs vigentes
        self.manager.refresh_data()
        productos_map = {}
        code_map = {}
        sku_map = {}
        name_map = {}
        try:
            productos_all = self.manager.db.get_productos()
        except Exception as exc:
            logger.warning("POS.CF no se pudo leer productos completos: %s", exc)
            productos_all = list(getattr(self.manager, "_products", []))
        for p in productos_all:
            try:
                pid = int(p.get("id"))
            except Exception:
                pid = p.get("id")
            productos_map[pid] = p
            productos_map[str(pid)] = p
            code = str(p.get("codigo") or "").strip().lower()
            if code:
                code_map[code] = p
            sku = str(p.get("sku") or "").strip().lower()
            if sku:
                sku_map[sku] = p
            name = str(p.get("nombre") or "").strip().lower()
            if name:
                name_map[name] = p
        logger.info("POS.CF productos_map_size=%s first_ids=%s", len(productos_map), list(productos_map.keys())[:5])
        total = data.get("total", 0)
        fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cliente_id = data["cliente"]["id"] if data.get("cliente") and "id" in data["cliente"] else None
        Distribuidor = next(
            (v for v in self.manager._Distribuidores if v["nombre"] == (distribuidor_nombre or "")),
            None,
        )
        Distribuidor_id = Distribuidor["id"] if Distribuidor else None
        vendedor_id = data.get("vendedor_id")
        extra = build_fiscal_extra(data)
        ret_block = data.get("_ui_retencion") if isinstance(data.get("_ui_retencion"), dict) else None
        if ret_block:
            extra["_ui_retencion"] = ret_block
        payment_extra = build_payment_condition_extra(data)
        if payment_extra:
            extra.update(payment_extra)

        if data.get("venta_a_cuenta_de") or data.get("documento_venta_a_cuenta"):
            extra["venta_a_cuenta_de"] = data.get("venta_a_cuenta_de", "")
            extra["documento_venta_a_cuenta"] = data.get("documento_venta_a_cuenta", "")

        choice = self._mostrar_confirmacion_venta()
        if choice == QDialog.Rejected:
            return

        estado = data.get("estado", "Pagada")
        if choice == SaleConfirmationDialog.RESULT_SAVE_DTE:
            estado = "Pendiente de Envío"
        elif choice == SaleConfirmationDialog.RESULT_SAVE_LOCAL:
            estado = "Venta Interna"

        self._log_retencion_state("SAVE", "01", ret_block, total)

        venta_id = self.manager.db.add_venta(
            fecha,
            total,
            cliente_id=cliente_id,
            Distribuidor_id=Distribuidor_id,
            vendedor_id=vendedor_id,
            extra=extra or None,
            estado=estado,
        )
        for item in items:
            product_id = item.get("producto_id")
            if not product_id:
                raise ValueError("No se pudo determinar el producto de un ítem; refresque inventario.")
            try:
                pid_int = int(product_id)
            except Exception:
                pid_int = product_id
            prod = productos_map.get(pid_int) or productos_map.get(str(pid_int))
            if not prod:
                code_val = str(item.get("codigo") or "").strip().lower()
                sku_val = str(item.get("sku") or "").strip().lower()
                name_val = str(item.get("producto") or "").strip().lower()
                prod = code_map.get(code_val) or sku_map.get(sku_val) or name_map.get(name_val)
                if prod:
                    product_id = prod.get("id")
                    try:
                        pid_int = int(product_id)
                    except Exception:
                        pid_int = product_id
                if not prod:
                    logger.error(
                        "POS.CF producto_id_no_match id=%s code=%s sku=%s nombre=%s mapa_size=%s sample_keys=%s items=%s",
                        product_id,
                        code_val,
                        sku_val,
                        name_val,
                        len(productos_map),
                        list(productos_map.keys())[:10],
                        items,
                    )
                    raise ValueError(f"El producto con id {product_id} ya no existe en inventario. Refresque la lista.")
            if prod.get("stock", 0) < item["cantidad"]:
                raise ValueError(f"No hay suficiente stock para el producto {prod['nombre']}.")
            extra_data = item.get("extra") or (
                {"lote_id": item.get("lote_id"), "producto_id": product_id, "cantidad": item.get("cantidad")}
                if item.get("lote_id") is not None else None
            )
            self.manager.db.add_detalle_venta(
                venta_id,
                prod["id"],
                item["cantidad"],
                item["precio"],
                item.get("descuento", 0),
                item.get("descuento_tipo", ""),
                item.get("iva", 0),
                item.get("comision_monto", 0),
                item.get("iva_tipo", ""),
                item.get("tipo_fiscal", "Gravada"),
                extra_data,
                item.get("precio_con_iva", 0),
                item.get("vendedor_id", vendedor_id)
            )
            if prod and "lote_id" in item:
                self.manager.db.disminuir_stock_lote(item["lote_id"], item["cantidad"])
                self.manager.db.actualizar_stock_producto(item["producto_id"])

        self.manager.refresh_data()
        self.filter_products()
        self.sales_tab.load_sales()
        texto_base = f"Venta registrada correctamente.\nTotal: ${total:.2f}"
        if choice == SaleConfirmationDialog.RESULT_SEND_DTE:
            envio_ok, envio_msg, envio_meta = self._auto_enviar_factura(venta_id, tipo_dte="01")
            try:
                self._generate_sale_pdf(venta_id)
            except Exception:
                logger.exception("No se pudo generar PDF de factura para venta_id=%s", venta_id)
            if envio_ok:
                self._registrar_estado_dte_ui(venta_id, "01", "enviado")
                texto_base += f"\nFactura enviada automáticamente (estado: {envio_msg})."
                QMessageBox.information(self, "Venta", texto_base)
            else:
                if envio_meta.get("rejected"):
                    self._handle_dte_rechazo(venta_id, "01", envio_msg, envio_meta)
                else:
                    self._registrar_estado_dte_ui(venta_id, "01", "pendiente")
                    texto_base += f"\nNo se pudo enviar la factura automáticamente: {envio_msg}"
                    QMessageBox.warning(self, "Venta", texto_base)
        elif choice == SaleConfirmationDialog.RESULT_SAVE_DTE:
            gen_ok, gen_msg = self._generar_dte_sin_enviar(venta_id, tipo_dte="01")
            if gen_ok:
                self._registrar_estado_dte_ui(venta_id, "01", "pendiente")
                try:
                    self._generate_sale_pdf(venta_id)
                except Exception:
                    logger.exception("No se pudo generar PDF de factura para venta_id=%s", venta_id)
                texto_base += f"\n{gen_msg}"
                QMessageBox.information(self, "Venta", texto_base)
            else:
                texto_base += f"\nNo se pudo generar el DTE: {gen_msg}"
                QMessageBox.warning(self, "Venta", texto_base)
        else:
            texto_base += "\nVenta registrada localmente (sin DTE)."
            QMessageBox.information(self, "Venta", texto_base)
        self._actualizar_historial()
        self._actualizar_inventario_actual()
        self.sales_tab.load_sales()
        self._refresh_pos_if_available()
        self.data_changed.emit()
        self.data_changed.emit()

    def _procesar_venta_credito_fiscal(self, data: dict, distribuidor_nombre: str | None = None):
        """Guarda la venta CCF y ejecuta el flujo de confirmación/envío."""
        logger.debug("IVA calculado en get_data: %s", data.get("iva"))
        items = data.get("items", [])
        if not items:
            raise ValueError("Debe agregar al menos un producto a la venta.")
        # Refresca inventario para asegurar IDs vigentes
        self.manager.refresh_data()
        productos_map = {}
        code_map = {}
        sku_map = {}
        name_map = {}
        try:
            productos_all = self.manager.db.get_productos()
        except Exception as exc:
            logger.warning("POS.CCF no se pudo leer productos completos: %s", exc)
            productos_all = list(getattr(self.manager, "_products", []))
        for p in productos_all:
            try:
                pid = int(p.get("id"))
            except Exception:
                pid = p.get("id")
            productos_map[pid] = p
            productos_map[str(pid)] = p
            code = str(p.get("codigo") or "").strip().lower()
            if code:
                code_map[code] = p
            sku = str(p.get("sku") or "").strip().lower()
            if sku:
                sku_map[sku] = p
            name = str(p.get("nombre") or "").strip().lower()
            if name:
                name_map[name] = p
        logger.info("POS.CCF productos_map_size=%s first_ids=%s", len(productos_map), list(productos_map.keys())[:5])

        sumas = data.get("sumas", 0)
        descuentos = data.get("descuentos", 0)
        iva = data.get("iva", 0)
        subtotal = data.get("subtotal", 0)
        venta_total = data.get("total", 0)
        total_letras = monto_a_texto_sv(venta_total)

        fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        Distribuidor = next((v for v in self.manager._Distribuidores if v["nombre"] == (distribuidor_nombre or "")), None)
        Distribuidor_id = Distribuidor["id"] if Distribuidor else None
        # Normaliza IDs de cliente, distribuidor y vendedor para evitar FK inválidas
        clientes = []
        try:
            clientes = self.manager.db.get_clientes()
        except Exception:
            clientes = list(getattr(self.manager, "_clientes", []))
        def _valid_id(target_id, rows):
            if not target_id:
                return None
            for r in rows:
                try:
                    rid = int(r.get("id"))
                except Exception:
                    rid = r.get("id")
                if rid == target_id:
                    return target_id
            logger.warning("FK no encontrada; se omite id=%s", target_id)
            return None

        cliente_id = _valid_id(data["cliente"]["id"] if data.get("cliente") and "id" in data["cliente"] else None, clientes)
        Distribuidor_id = _valid_id(Distribuidor_id, getattr(self.manager, "_Distribuidores", []))
        vendedor_id = _valid_id(data.get("vendedor_id"), self.manager.db.get_trabajadores(solo_vendedores=True))

        extra = build_fiscal_extra(data)
        extra["total_letras"] = total_letras
        ret_block = data.get("_ui_retencion") if isinstance(data.get("_ui_retencion"), dict) else None
        if ret_block:
            extra["_ui_retencion"] = ret_block
        payment_extra = build_payment_condition_extra(data)
        if payment_extra:
            extra.update(payment_extra)

        if data.get("venta_a_cuenta_de") or data.get("documento_venta_a_cuenta"):
            extra["venta_a_cuenta_de"] = data.get("venta_a_cuenta_de", "")
            extra["documento_venta_a_cuenta"] = data.get("documento_venta_a_cuenta", "")

        choice = self._mostrar_confirmacion_venta()
        if choice == QDialog.Rejected:
            return

        estado = data.get("estado", "Pagada")
        if choice == SaleConfirmationDialog.RESULT_SAVE_DTE:
            estado = "Pendiente de Envío"
        elif choice == SaleConfirmationDialog.RESULT_SAVE_LOCAL:
            estado = "Venta Interna"

        self._log_retencion_state("SAVE", "03", ret_block, venta_total)

        venta_id = self.manager.db.add_venta_credito_fiscal(
            cliente_id=cliente_id,
            fecha=fecha,
            total=venta_total,
            nrc=data.get("nrc", ""),
            nit=data.get("nit", ""),
            giro=data.get("giro", ""),
            Distribuidor_id=Distribuidor_id,
            vendedor_id=vendedor_id,
            no_remision=data.get("no_remision", ""),
            orden_no=data.get("orden_no", ""),
            condicion_pago=data.get("condicion_pago", ""),
            venta_a_cuenta_de=data.get("venta_a_cuenta_de", ""),
            documento_venta_a_cuenta=data.get("documento_venta_a_cuenta", ""),
            fecha_remision_anterior=data.get("fecha_remision_anterior", ""),
            fecha_remision=data.get("fecha_remision", ""),
            sumas=sumas,
            descuentos=descuentos,
            iva=iva,
            subtotal=subtotal,
            ventas_exentas=data.get("ventas_exentas", 0),
            ventas_no_sujetas=data.get("ventas_no_sujetas", 0),
            total_letras=total_letras,
            extra=extra or None,
            estado=estado,
        )
        if not venta_id:
            raise ValueError("No se pudo registrar la venta a crédito fiscal.")

        for item in items:
            product_id = item.get("producto_id")
            if not product_id:
                raise ValueError("No se pudo determinar el producto de un ítem; refresque inventario.")
            try:
                pid_int = int(product_id)
            except Exception:
                pid_int = product_id
            prod = productos_map.get(pid_int) or productos_map.get(str(pid_int))
            if not prod:
                code_val = str(item.get("codigo") or "").strip().lower()
                sku_val = str(item.get("sku") or "").strip().lower()
                name_val = str(item.get("producto") or "").strip().lower()
                prod = code_map.get(code_val) or sku_map.get(sku_val) or name_map.get(name_val)
                if prod:
                    product_id = prod.get("id")
                    try:
                        pid_int = int(product_id)
                    except Exception:
                        pid_int = product_id
                if not prod:
                    logger.error(
                        "POS.CCF producto_id_no_match id=%s code=%s sku=%s nombre=%s mapa_size=%s sample_keys=%s items=%s",
                        product_id,
                        code_val,
                        sku_val,
                        name_val,
                        len(productos_map),
                        list(productos_map.keys())[:10],
                        items,
                    )
                    raise ValueError(f"El producto con id {product_id} ya no existe en inventario. Refresque la lista.")
            if prod.get("stock", 0) < item["cantidad"]:
                raise ValueError(f"No hay suficiente stock para el producto {prod['nombre']}.")
            extra_data = item.get("extra") or (
                {"lote_id": item.get("lote_id"), "producto_id": product_id, "cantidad": item.get("cantidad")}
                if item.get("lote_id") is not None else None
            )
            self.manager.db.add_detalle_venta(
                venta_id,
                prod["id"],
                item["cantidad"],
                item["precio"],
                item.get("descuento", 0),
                item.get("descuento_tipo", ""),
                item.get("iva", 0),
                item.get("comision_monto", 0),
                item.get("iva_tipo", ""),
                item.get("tipo_fiscal", "Gravada"),
                extra_data,
                item.get("precio_con_iva", 0),
                item.get("vendedor_id", vendedor_id)
            )
            if prod and "lote_id" in item:
                self.manager.db.disminuir_stock_lote(item["lote_id"], item["cantidad"])
                self.manager.db.actualizar_stock_producto(item["producto_id"])

        self.manager.refresh_data()
        self.filter_products()
        self.sales_tab.load_sales()
        texto_base = f"Venta registrada correctamente.\nTotal: ${venta_total:.2f}"
        if choice == SaleConfirmationDialog.RESULT_SEND_DTE:
            envio_ok, envio_msg, envio_meta = self._auto_enviar_factura(venta_id, tipo_dte="03")
            try:
                generate_invoice_pdf(self.manager, venta_id)
            except Exception:
                logger.exception("No se pudo generar PDF de factura CF para venta_id=%s", venta_id)
            if envio_ok:
                self._registrar_estado_dte_ui(venta_id, "03", "enviado")
                texto_base += f"\nFactura enviada automáticamente (estado: {envio_msg})."
                QMessageBox.information(self, "Venta a Crédito Fiscal", texto_base)
            else:
                if envio_meta.get("rejected"):
                    self._handle_dte_rechazo(venta_id, "03", envio_msg, envio_meta)
                else:
                    self._registrar_estado_dte_ui(venta_id, "03", "pendiente")
                    texto_base += f"\nNo se pudo enviar la factura automáticamente: {envio_msg}"
                    QMessageBox.warning(self, "Venta a Crédito Fiscal", texto_base)
        elif choice == SaleConfirmationDialog.RESULT_SAVE_DTE:
            gen_ok, gen_msg = self._generar_dte_sin_enviar(venta_id, tipo_dte="03")
            if gen_ok:
                self._registrar_estado_dte_ui(venta_id, "03", "pendiente")
                try:
                    generate_invoice_pdf(self.manager, venta_id)
                except Exception:
                    logger.exception("No se pudo generar PDF de factura CF para venta_id=%s", venta_id)
                texto_base += f"\n{gen_msg}"
                QMessageBox.information(self, "Venta a Crédito Fiscal", texto_base)
            else:
                texto_base += f"\nNo se pudo generar el DTE: {gen_msg}"
                QMessageBox.warning(self, "Venta a Crédito Fiscal", texto_base)
        else:
            texto_base += "\nVenta registrada localmente (sin DTE)."
            QMessageBox.information(self, "Venta a Crédito Fiscal", texto_base)

        self._actualizar_historial()
        self._actualizar_inventario_actual()
        self._refresh_pos_if_available()
        self.sales_tab.load_sales()
        self.data_changed.emit()

    def registrar_venta_credito_fiscal(self):
        if self._is_guest():
            self._deny_guest()
            return
        if not self._ensure_last_invoice_sent():
            return
        try:
            # Arma la lista de productos disponibles para la venta (con stock > 0)
            productos_lote = []
            compras = self.manager.db.get_compras()
            productos_dict = {p["id"]: p for p in self.manager._products}
            for compra in compras:
                detalles = self.manager.db.get_detalles_compra(compra["id"])
                for d in detalles:
                    prod = productos_dict.get(d["producto_id"])
                    if not prod:
                        continue
                    if d.get("cantidad", 0) > 0:
                        productos_lote.append({
                            "lote_id": d["id"],
                            "producto_id": d["producto_id"],
                            "nombre": prod.get("nombre", ""),
                            "codigo": prod.get("codigo", ""),
                            "codigo_lote": d.get("codigo_lote", ""),
                            "registro_sanitario": d.get("registro_sanitario", ""),
                            "stock": d.get("cantidad", 0),
                            "precio_unitario": d.get("precio_unitario", 0),
                            "Distribuidor_id": compra.get("Distribuidor_id"),
                            "fecha_vencimiento": d.get("fecha_vencimiento", ""),
                            "precio_venta_minorista": prod.get("precio_venta_minorista", 0),
                            "precio_venta_mayorista": prod.get("precio_venta_mayorista", 0),
                        })

            if not productos_lote:
                QMessageBox.warning(self, "Venta a Crédito Fiscal", "No hay productos con stock disponible para vender.")
                return

            clientes = self.manager.db.get_clientes()
            if not clientes:
                raise ValueError("No hay clientes registrados.")
            from dialogs import RegisterCreditoFiscalDialog
            Distribuidores = [dict(v) for v in self.manager._Distribuidores]
            vendedores_trabajadores = self.manager.db.get_trabajadores(solo_vendedores=True)
            dialog = RegisterCreditoFiscalDialog(productos_lote, Distribuidores, vendedores_trabajadores, self)
            dialog.set_productos_data(productos_lote)
            if dialog.exec_():
                data = dialog.get_data()
                self._procesar_venta_credito_fiscal(data, dialog.Distribuidor_combo.currentText())
                dialog.clear_carrito()

        except Exception as e:
            QMessageBox.critical(self, "Error al registrar venta a crédito fiscal", str(e))

    def _log_retencion_state(self, stage: str, tipo_dte: str, block: dict | None, total: float | int | Decimal | None) -> None:
        block = block or {}
        enabled = bool(block.get("enabled"))
        base = block.get("base")
        if base in (None, ""):
            base = block.get("baseSujeta", 0)
        retenido = block.get("montoRetenido")
        if retenido in (None, ""):
            retenido = block.get("ivaRetenido", 0)
        try:
            base_val = float(base or 0)
        except Exception:
            base_val = 0.0
        try:
            reten_val = float(retenido or 0)
        except Exception:
            reten_val = 0.0
        try:
            total_val = float(total or 0)
        except Exception:
            total_val = 0.0
        logger.info(
            "RETENCION.%s enabled=%s base=%.2f retenido=%.2f tipo=%s total=%.2f",
            stage,
            enabled,
            base_val,
            reten_val,
            tipo_dte,
            total_val,
        )

    def _refresh_pos_if_available(self):
        """Actualiza widgets POS (CF/CCF) con inventario reciente si existen."""
        if hasattr(self, "sales_tab") and hasattr(self.sales_tab, "_refresh_pos_data"):
            try:
                self.sales_tab._refresh_pos_data()
            except Exception as exc:  # pragma: no cover - solo log
                logger.warning("No se pudo refrescar el POS: %s", exc)

    def _registrar_estado_dte_ui(
        self,
        venta_id: int,
        tipo_dte: str,
        estado: str,
        *,
        codigo_generacion: str | None = None,
        numero_control: str | None = None,
        ambiente: str | None = None,
    ) -> None:
        """Guarda un registro mínimo de estado DTE para reflejarlo en la pestaña de ventas."""
        try:
            self.manager.db.registrar_envio_dte(
                venta_id=venta_id,
                modo="ui",
                estado=estado,
                sello="",
                respuesta_json="",
                codigo_lote=None,
                codigo_generacion=codigo_generacion,
                numero_control=numero_control,
                ambiente=ambiente,
            )
        except Exception as exc:
            logger.warning("No se pudo registrar estado DTE (venta_id=%s): %s", venta_id, exc)

    def _post_guardado_exitoso(self, filename):
        self.ultimo_archivo_json = filename
        with open(LAST_INVENTORY_PATH, "w", encoding="utf-8") as f:
            json.dump({"ultimo": filename}, f)
        self._mark_saved()

    def _exportar_inventario(
        self,
        filename,
        *,
        titulo_dialogo,
        mensaje_exito,
        asincrono=True,
        mostrar_mensajes=True,
    ):
        tab_order = self.get_tab_order()
        if asincrono:
            thread = ExportThread(filename, tab_order)

            def on_finished():
                self._post_guardado_exitoso(filename)
                if mostrar_mensajes:
                    QMessageBox.information(
                        self,
                        titulo_dialogo,
                        mensaje_exito,
                    )

            def on_error(error):
                if mostrar_mensajes:
                    QMessageBox.critical(
                        self,
                        "Error",
                        f"No se pudo guardar el inventario:\n{error}",
                    )

            thread.finished.connect(on_finished)
            thread.error.connect(on_error)
            thread.start()
            self.export_thread = thread
            return thread

        try:
            manager = im.InventoryManager(im.DB(), enable_auto_backup=False)
            manager.exportar_inventario_json(filename, tab_order=tab_order)
        except Exception as exc:
            if mostrar_mensajes:
                QMessageBox.critical(
                    self,
                    "Error",
                    f"No se pudo guardar el inventario:\n{exc}",
                )
            return False

        self._post_guardado_exitoso(filename)
        if mostrar_mensajes:
            QMessageBox.information(
                self,
                titulo_dialogo,
                mensaje_exito,
            )
        return True

    def _cargar_inventario_desde_archivo(
        self,
        filename: str,
        *,
        titulo_dialogo: str,
        mensaje_exito: str,
    ) -> bool:
        try:
            data = self.manager.importar_inventario_json(filename)
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"No se pudo cargar el inventario:\n{exc}")
            self._actualizar_historial()
            return False

        ventas_importadas = self.manager.db.get_ventas()
        if not ventas_importadas and isinstance(data, dict):
            for venta in data.get("ventas", []):
                self.manager.db.add_venta(
                    venta.get("fecha"),
                    venta.get("total", 0),
                    cliente_id=venta.get("cliente_id"),
                    Distribuidor_id=venta.get("Distribuidor_id"),
                    vendedor_id=venta.get("vendedor_id"),
                    extra=venta.get("extra"),
                    estado=venta.get("estado", "Pagada"),
                )

        if isinstance(data, dict) and data.get("tab_order"):
            self.set_tab_order(data["tab_order"])
        self.ultimo_archivo_json = filename
        try:
            with open(LAST_INVENTORY_PATH, "w", encoding="utf-8") as fh:
                json.dump({"ultimo": filename}, fh)
        except OSError as exc:
            logger.exception("No se pudo actualizar la ruta del último inventario: %s", exc)
        self.compras_tab.refresh_filters()
        self.filter_products()
        self.compras_tab.refresh_filters()
        self.compras_tab.load_purchases()
        self.sales_tab.load_sales()
        self._actualizar_tabla_clientes()
        self._mostrar_historial_general()
        self._actualizar_arbol_vendedores()
        self._actualizar_arbol_Distribuidores()
        self._actualizar_tabla_trabajadores()
        self._actualizar_inventario_actual()
        self._actualizar_historial()
        self._cargar_personas_estado()
        self._mark_saved()
        QMessageBox.information(self, titulo_dialogo, mensaje_exito)
        return True

    def guardar_como(self):
        if self._is_guest():
            self._deny_guest()
            return False
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Guardar inventario como",
            "",
            "Archivos JSON (*.json);;Todos los archivos (*)",
        )
        if not filename:
            return False

        self._exportar_inventario(
            filename,
            titulo_dialogo="Guardar como",
            mensaje_exito="Inventario guardado correctamente.",
        )
        return True

    def cargar_inventario(self):
        if self._is_guest():
            self._deny_guest()
            return
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Cargar inventario",
            "",
            "Archivos JSON (*.json);;Todos los archivos (*)",
        )
        if filename:
            self._cargar_inventario_desde_archivo(
                filename,
                titulo_dialogo="Cargar inventario",
                mensaje_exito="Inventario cargado correctamente.",
            )

    def cargar_copia_seguridad(self):
        backup_dir = Path(AUTO_BACKUP_DIR)
        try:
            entries = list(backup_dir.glob("*.json")) if backup_dir.is_dir() else []
        except OSError as exc:
            QMessageBox.critical(
                self,
                "Error",
                f"No se pudo acceder a las copias de seguridad:\n{exc}",
            )
            return

        candidates = []
        for entry in entries:
            try:
                if entry.is_file():
                    candidates.append((entry.stat().st_mtime, entry))
            except OSError:
                logger.exception("No se pudo inspeccionar el respaldo %s", entry)
        if not candidates:
            QMessageBox.information(
                self,
                "Cargar copia de seguridad",
                "No se encontraron copias de seguridad disponibles.",
            )
            return

        candidates.sort(reverse=True)
        latest_backup = str(candidates[0][1])
        self._cargar_inventario_desde_archivo(
            latest_backup,
            titulo_dialogo="Cargar copia de seguridad",
            mensaje_exito="Copia de seguridad cargada correctamente.",
        )

    def cargar_copia_seguridad_manual(self):
        """Permite elegir manualmente qué respaldo cargar."""
        start_dir = str(Path(AUTO_BACKUP_DIR))
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar copia de seguridad",
            start_dir if os.path.isdir(start_dir) else "",
            "Archivos JSON (*.json);;Todos los archivos (*)",
        )
        if not filename:
            return
        self._cargar_inventario_desde_archivo(
            filename,
            titulo_dialogo="Cargar copia de seguridad",
            mensaje_exito="Copia de seguridad cargada correctamente.",
        )

    def actualizar_estado_global(self):
        """Recarga datos, listas e inventario para evitar desincronizaciones."""
        try:
            if hasattr(self, "manager"):
                self.manager.refresh_data()
                if hasattr(self, "filter_products"):
                    self.filter_products()
            if hasattr(self, "facturacion_tab") and hasattr(
                self.facturacion_tab, "refresh_and_reload"
            ):
                self.facturacion_tab.refresh_and_reload()
            if hasattr(self, "sales_tab") and hasattr(self.sales_tab, "load_sales"):
                self.sales_tab.load_sales()
            if hasattr(self, "_actualizar_inventario_actual"):
                self._actualizar_inventario_actual()
        except Exception:
            logger.exception("No se pudo actualizar el estado global")

    def firmar_dte_manual(self):
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar DTE",
            "",
            "Archivos JSON (*.json);;Todos los archivos (*)",
        )
        if not filename:
            return
        try:
            with open(filename, "r", encoding="utf-8") as fh:
                contenido = fh.read()
            token = sign_json(contenido)
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"No se pudo firmar el DTE:\n{exc}")
            return
        default_jws = os.path.splitext(filename)[0] + ".jws"
        save_path, _ = QFileDialog.getSaveFileName(
            self,
            "Guardar JWS",
            default_jws,
            "Archivos JWS (*.jws);;Todos los archivos (*)",
        )
        if not save_path:
            return
        try:
            with open(save_path, "w", encoding="utf-8") as fh:
                fh.write(token)
            QMessageBox.information(
                self,
                "Firmado",
                f"DTE firmado guardado en:\n{save_path}",
            )
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"No se pudo guardar el archivo:\n{exc}")

    def guardar_rapido(self, *, asincrono=True, mostrar_mensajes=True):
        if self._is_guest():
            self._deny_guest()
            return False
        filename = self.ultimo_archivo_json
        if not filename:
            filename, _ = QFileDialog.getSaveFileName(
                self,
                "Guardar inventario",
                "",
                "Archivos JSON (*.json);;Todos los archivos (*)",
            )
            if not filename:
                if mostrar_mensajes:
                    QMessageBox.warning(
                        self,
                        "Guardar rápido",
                        "Primero debes guardar o cargar un inventario manualmente.",
                    )
                return False

        resultado = self._exportar_inventario(
            filename,
            titulo_dialogo="Guardar rápido",
            mensaje_exito=f"Inventario guardado en:\n{filename}",
            asincrono=asincrono,
            mostrar_mensajes=mostrar_mensajes,
        )

        if asincrono:
            return resultado is not None
        return bool(resultado)

    def cargar_rapido(self):
        if self._is_guest():
            self._deny_guest()
            return
        import os
        if self.ultimo_archivo_json and os.path.exists(self.ultimo_archivo_json):
            try:
                data = self.manager.importar_inventario_json(self.ultimo_archivo_json)
                if isinstance(data, dict) and data.get("tab_order"):
                    self.set_tab_order(data["tab_order"])
                self.compras_tab.refresh_filters()

                self.compras_tab.load_purchases()
                self.sales_tab.load_sales()

                self.filter_products()
                self._actualizar_tabla_clientes()  # <-- SOLO AGREGA ESTA LÍNEA
                self._mostrar_historial_general()
                self._mark_saved()
                QMessageBox.information(self, "Cargar rápido", f"Inventario cargado de:\n{self.ultimo_archivo_json}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"No se pudo cargar el inventario:\n{e}")
        else:
            QMessageBox.warning(self, "Cargar rápido", "No hay un inventario guardado previamente para cargar.")

    def cerrar_sesion(self):
        reply = QMessageBox.question(
            self,
            "Cerrar sesión",
            "¿Desea cerrar la sesión actual?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        # Al confirmar, mostrar nuevamente el diálogo de selección de usuario
        from PyQt5.QtWidgets import QApplication, QLineEdit
        from user_picker_dialog import UserPickerDialog
        from db import DB

        app = QApplication.instance()

        # Cerrar la ventana actual antes de abrir el selector de usuarios
        self.close()

        db = DB()
        users = [
            {"id": u["id"], "name": u["username"], "subtitle": u.get("role", "")}
            for u in db.get_users()
        ]
        dlg = UserPickerDialog(users, multi_select=False, parent=None)
        if dlg.exec_() != QDialog.Accepted:
            app.quit()
            return

        selected = dlg.selected_user_ids()
        if not selected:
            app.quit()
            return

        user_id = selected if not isinstance(selected, list) else selected[0]
        user = db.get_user(user_id)
        if not user:
            app.quit()
            return

        if user["username"] != "invitado":
            while True:
                password, ok = QInputDialog.getText(
                    None,
                    "Contraseña",
                    f"Ingrese la contraseña para {user['username']}",
                    QLineEdit.Password,
                )
                if not ok:
                    app.quit()
                    return
                if db.authenticate(user["username"], password):
                    break
                QMessageBox.warning(None, "Error", "Contraseña incorrecta")

        # Abrir una nueva ventana principal para el usuario seleccionado
        nueva_ventana = MainWindow(user)
        nueva_ventana.show()
        # Mantener referencia para evitar que se recolecte
        self._next_window = nueva_ventana

    def nuevo_inventario(self):
        if self._is_guest():
            self._deny_guest()
            return
        reply = QMessageBox.question(
            self,
            "Nuevo inventario",
            "¿Estás seguro de que quieres borrar todo el inventario actual? Esta acción no se puede deshacer.",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            try:
                self.manager.db.limpiar_inventario()
            except Exception as exc:
                QMessageBox.warning(
                    self,
                    "Nuevo inventario",
                    f"No se pudo limpiar la base de datos: {exc}",
                )
                return
            self.manager.db.limpiar_productos()
            self.manager.db.limpiar_vendedores()
            self.manager.db.limpiar_Distribuidores()
            # Reset last loaded inventory so old data is not reimported
            self.ultimo_archivo_json = None
            try:
                if os.path.exists(LAST_INVENTORY_PATH):
                    os.remove(LAST_INVENTORY_PATH)
            except OSError:
                pass
            self.manager.refresh_data()
            self.compras_tab.refresh_filters()

            self.compras_tab.load_purchases()

            self.sales_tab.load_sales()  # <-- AGREGA ESTA LÍNEA

            self._actualizar_tabla_trabajadores()  # <-- AGREGA ESTA LÍNEA
            self.filter_products()
            self._actualizar_arbol_vendedores()
            self._actualizar_arbol_Distribuidores()
            self._actualizar_tabla_clientes()
            self._mostrar_historial_general()
            self._actualizar_historial()
            self._cargar_personas_estado()
            if hasattr(self, "vendedor_combo_filtro"):
                self.vendedor_combo_filtro.setCurrentIndex(0)
            if hasattr(self, "distribuidor_combo_filtro"):
                self.distribuidor_combo_filtro.setCurrentIndex(0)
            self._actualizar_inventario_actual()
            QMessageBox.information(self, "Nuevo inventario", "Inventario limpio y listo para usar.")

    def _verificar_vendedores_inconsistentes(self):
        """Notifica si existen vendedores sin distribuidor asignado."""
        try:
            inconsistentes = self.manager.db.get_vendedores_sin_distribuidor()
        except Exception:
            logger.exception("No se pudo verificar vendedores sin distribuidor")
            return
        if inconsistentes:
            if not self._alerto_vendedores_inconsistentes:
                nombres = ", ".join(v.get("nombre", "") for v in inconsistentes if v.get("nombre"))
                detalle = nombres or "Se encontraron vendedores sin distribuidor."
                QMessageBox.warning(
                    self,
                    "Vendedores sin distribuidor",
                    f"{detalle}\nEdite o elimine estos vendedores antes de continuar.",
                )
                self._alerto_vendedores_inconsistentes = True
        else:
            self._alerto_vendedores_inconsistentes = False

    def _actualizar_arbol_vendedores(self):
        self._verificar_vendedores_inconsistentes()
        search = ""
        if hasattr(self, "vendedores_search"):
            search = (self.vendedores_search.text() or "").strip().lower()
        self.vendedores_list.clear()
        for vend in self.manager.get_vendedores_compra():
            text = f"{vend.get('codigo', '')} - {vend['nombre']}"
            haystack = " ".join(
                [
                    vend.get("codigo", "") or "",
                    vend.get("nombre", "") or "",
                    vend.get("descripcion", "") or "",
                ]
            ).lower()
            if search and search not in haystack:
                continue
            vend_item = QListWidgetItem(text)
            vend_item.setData(Qt.UserRole, vend.get("id"))
            self.vendedores_list.addItem(vend_item)

    def _actualizar_arbol_Distribuidores(self):
        search = ""
        if hasattr(self, "distribuidores_search"):
            search = (self.distribuidores_search.text() or "").strip().lower()
        self.distribuidores_list.clear()
        for dist in self.manager._Distribuidores:
            text = dist.get("nombre", "")
            haystack = " ".join(
                [
                    dist.get("codigo", "") or "",
                    dist.get("nombre", "") or "",
                    dist.get("telefono", "") or "",
                    dist.get("email", "") or "",
                ]
            ).lower()
            if search and search not in haystack:
                continue
            dist_item = QListWidgetItem(text)
            dist_item.setData(Qt.UserRole, dist.get("id"))
            self.distribuidores_list.addItem(dist_item)

    def _actualizar_lista_Distribuidores(self):
        self.Distribuidores_list.clear()
        for dist in self.manager.get_Distribuidor_names():
            self.Distribuidores_list.addItem(dist)

    def _agregar_vendedor(self):
        if self._is_guest():
            self._deny_guest()
            return
        from dialogs import VendedorDialog
        codigo = self.manager.db.get_next_vendedor_codigo()
        dialog = VendedorDialog(self.manager._Distribuidores, self, codigo_sugerido=codigo)
        if dialog.exec_():
            data = dialog.get_data()
            try:
                self.manager.db.add_vendedor(
                    data["nombre"],
                    descripcion=data["descripcion"],
                    Distribuidor_id=data["Distribuidor_id"],
                    codigo=data["codigo"],
                    dui=data["dui"],
                    nit=data.get("nit"),
                    is_subject_excluded=data.get("is_subject_excluded", 0),

                )
            except ValueError as exc:
                QMessageBox.warning(self, "Vendedor", str(exc))
                return
            except Exception as exc:
                logger.exception("No se pudo agregar el vendedor")
                QMessageBox.critical(self, "Vendedor", f"No se pudo agregar el vendedor: {exc}")
                return
            self.manager.refresh_data()
            self.compras_tab.refresh_filters()
            self._actualizar_arbol_vendedores()
            QMessageBox.information(self, "Vendedor", "Vendedor agregado correctamente.")

    def _editar_vendedor(self):
        if self._is_guest():
            self._deny_guest()
            return
        from dialogs import VendedorDialog
        item = self.vendedores_list.currentItem()
        if item is None and self.vendedores_list.selectedItems():
            item = self.vendedores_list.selectedItems()[0]
        if item is None:
            QMessageBox.warning(self, "Editar vendedor", "Seleccione una vendedor para editar.")
            return
        vendedor_id = item.data(Qt.UserRole)
        vendedor = next(
            (
                c
                for c in self.manager.get_vendedores_compra()
                if c["id"] == vendedor_id
            ),
            None,
        )
        if not vendedor:
            QMessageBox.warning(self, "Editar vendedor", "No se encontró la vendedor seleccionada.")
            return
        dialog = VendedorDialog(self.manager._Distribuidores, self, vendedor=vendedor)
        if dialog.exec_():
            data = dialog.get_data()
            try:
                self.manager.db.update_vendedor(
                    vendedor["id"],
                    data["codigo"],
                    data["nombre"],
                    data["descripcion"],
                    data["Distribuidor_id"],
                    dui=data["dui"],
                    nit=data.get("nit"),
                    is_subject_excluded=data.get("is_subject_excluded", 0),

                )
            except ValueError as exc:
                QMessageBox.warning(self, "Vendedor", str(exc))
                return
            except Exception as exc:
                logger.exception("No se pudo editar el vendedor")
                QMessageBox.critical(self, "Vendedor", f"No se pudo editar el vendedor: {exc}")
                return
            self.manager.refresh_data()
            self.compras_tab.refresh_filters()
            self._actualizar_arbol_vendedores()
            QMessageBox.information(self, "Vendedor", "Vendedor editado correctamente.")

    def _eliminar_vendedor(self):
        if self._is_guest():
            self._deny_guest()
            return
        item = self.vendedores_list.currentItem()
        if item is None and self.vendedores_list.selectedItems():
            item = self.vendedores_list.selectedItems()[0]
        if item is None:
            QMessageBox.warning(self, "Eliminar vendedor", "Seleccione un vendedor para eliminar.")
            return
        vendedor_id = item.data(Qt.UserRole)
        nombre = item.text()
        confirm = QMessageBox.question(
            self,
            "Eliminar",
            f"¿Eliminar vendedor '{nombre}'?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm == QMessageBox.Yes:
            try:
                self.manager.db.delete_vendedor_completo(vendedor_id)
            except ValueError:
                QMessageBox.warning(
                    self,
                    "Eliminar vendedor",
                    "El vendedor tiene registros asociados y no puede eliminarse.",
                )
                return
            except Exception as exc:
                logger.exception("No se pudo eliminar el vendedor")
                QMessageBox.critical(self, "Eliminar vendedor", f"No se pudo eliminar el vendedor: {exc}")
                return
            self.manager.refresh_data()
            self.compras_tab.refresh_filters()
            self._actualizar_arbol_vendedores()
            self._actualizar_arbol_Distribuidores()
            QMessageBox.information(
                self,
                "Vendedor eliminado",
                f"El vendedor '{nombre}' ha sido eliminado.",
            )

    def _agregar_Distribuidor(self):
        if self._is_guest():
            self._deny_guest()
            return
        dialog = DistribuidorDialog(self)
        if dialog.exec_():
            data = dialog.get_data()
            self.manager.db.add_Distribuidor_detallado(data)
            self.manager.refresh_data()
            self.compras_tab.refresh_filters()
            self._actualizar_arbol_Distribuidores()
            QMessageBox.information(self, "Distribuidor", "Distribuidor agregado correctamente.")

    def _editar_Distribuidor(self):
        if self._is_guest():
            self._deny_guest()
            return
        item = self.distribuidores_list.currentItem()
        if item is None and self.distribuidores_list.selectedItems():
            item = self.distribuidores_list.selectedItems()[0]
        if item is None:
            QMessageBox.warning(self, "Editar Distribuidor", "Seleccione un Distribuidor para editar.")
            return
        dist_id = item.data(Qt.UserRole)
        # Busca el Distribuidor en la base de datos
        Distribuidor = next((v for v in self.manager._Distribuidores if v["id"] == dist_id), None)
        if not Distribuidor:
            QMessageBox.warning(self, "Editar Distribuidor", "No se encontró el Distribuidor seleccionado.")
            return
        dialog = DistribuidorDialog(self, Distribuidor=Distribuidor)
        if dialog.exec_():
            data = dialog.get_data()
            # Actualiza el Distribuidor en la base de datos
            self.manager.db.cursor.execute("""
                UPDATE Distribuidores SET
                    codigo=?, nombre=?, telefono=?, email=?, cargo=?, sucursal=?,
                    fecha_inicio=?, direccion=?, departamento=?, municipio=?,
                    tipo_contrato=?, comisiones_especificas=?, metodo_pago=?, nit=?, nrc=?,
                    cuenta_bancaria=?, notas=?
                WHERE id=?
            """, (
                data.get("codigo", ""),
                data.get("nombre", ""),
                data.get("telefono", ""),
                data.get("email", ""),
                data.get("cargo", ""),
                data.get("sucursal", ""),
                data.get("fecha_inicio", ""),
                data.get("direccion", ""),
                data.get("departamento", ""),
                data.get("municipio", ""),
                data.get("tipo_contrato", ""),
                data.get("comisiones_especificas", ""),
                data.get("metodo_pago", ""),
                data.get("nit", ""),
                data.get("nrc", ""),
                data.get("cuenta_bancaria", ""),
                data.get("notas", ""),
                Distribuidor["id"]
            ))
            self.manager.db.conn.commit()
            self.manager.refresh_data()
            self.compras_tab.refresh_filters()
            self._actualizar_arbol_Distribuidores()
            QMessageBox.information(self, "Distribuidor", "Distribuidor editado correctamente.")
        self.selected_row = None

    def _mostrar_info_Distribuidor(self):
        item = self.distribuidores_list.currentItem()
        if item is None and self.distribuidores_list.selectedItems():
            item = self.distribuidores_list.selectedItems()[0]
        if item is None:
            QMessageBox.information(self, "Información de Distribuidor", "Seleccione un Distribuidor para ver su información.")
            return
        dist_id = item.data(Qt.UserRole)
        Distribuidor = next((v for v in self.manager._Distribuidores if v["id"] == dist_id), None)
        if not Distribuidor:
            QMessageBox.warning(self, "Información de Distribuidor", "No se encontró el Distribuidor seleccionado.")
            return

        dialog = DistribuidorInfoDialog(Distribuidor, self)
        dialog.exec_()

    def _eliminar_Distribuidor(self):
        if self._is_guest():
            self._deny_guest()
            return
        item = self.distribuidores_list.currentItem()
        if item is None and self.distribuidores_list.selectedItems():
            item = self.distribuidores_list.selectedItems()[0]
        if item is None:
            QMessageBox.warning(
                self, "Eliminar Distribuidor", "Seleccione un Distribuidor para eliminar."
            )
            return
        dist_id = item.data(Qt.UserRole)
        confirm = QMessageBox.question(
            self,
            "Eliminar Distribuidor",
            f"¿Eliminar Distribuidor '{item.text()}'?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            self.manager.db.delete_Distribuidor(dist_id)
        except ValueError:
            QMessageBox.warning(
                self,
                "Eliminar Distribuidor",
                "No se puede eliminar el Distribuidor porque tiene registros asociados.",
            )
            return
        self.manager.refresh_data()
        self.compras_tab.refresh_filters()
        self._actualizar_arbol_Distribuidores()
        self._actualizar_arbol_vendedores()
        QMessageBox.information(
            self, "Distribuidor", "Distribuidor eliminado correctamente."
        )

    def _actualizar_tabla_clientes(self):
        search = self.cliente_search.text()
        clientes = self.manager.db.get_clientes(search)
        self.clientes_table.setRowCount(len(clientes))
        for row, cli in enumerate(clientes):
            self.clientes_table.setItem(row, 0, QTableWidgetItem(cli.get("codigo", "")))
            self.clientes_table.setItem(row, 1, QTableWidgetItem(cli.get("nombre", "")))
            self.clientes_table.setItem(row, 2, QTableWidgetItem(cli.get("nrc", "")))
            self.clientes_table.setItem(row, 3, QTableWidgetItem(cli.get("nit", "")))
            self.clientes_table.setItem(row, 4, QTableWidgetItem(cli.get("dui", "")))
            self.clientes_table.setItem(row, 5, QTableWidgetItem(cli.get("giro", "")))
            self.clientes_table.setItem(row, 6, QTableWidgetItem(cli.get("telefono", "")))
            self.clientes_table.setItem(row, 7, QTableWidgetItem(cli.get("email", "")))
            self.clientes_table.setItem(row, 8, QTableWidgetItem(cli.get("departamento", "")))
            self.clientes_table.setItem(row, 9, QTableWidgetItem(cli.get("municipio", "")))

    def _get_selected_cliente(self):
        row = self.clientes_table.currentRow()
        if row < 0:
            return None
        codigo = self.clientes_table.item(row, 0).text()
        clientes = self.manager.db.get_clientes()
        for cli in clientes:
            if cli.get("codigo", "") == codigo:
                return cli
        return None

    def _agregar_cliente(self):
        if self._is_guest():
            self._deny_guest()
            return
        codigo = self.manager.db.get_next_cliente_codigo()
        dialog = ClienteDialog(self, codigo_sugerido=codigo)
        if dialog.exec_():
            data = dialog.get_data()
            try:
                self.manager.add_cliente(
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
            except ValueError as e:
                QMessageBox.warning(dialog, "Cliente", str(e))
                return
            self._actualizar_tabla_clientes()
            QMessageBox.information(self, "Cliente", "Cliente agregado correctamente.")

    def _editar_cliente(self):
        if self._is_guest():
            self._deny_guest()
            return
        cli = self._get_selected_cliente()
        if not cli:
            QMessageBox.warning(self, "Editar cliente", "Seleccione un cliente para editar.")
            return
        dialog = ClienteDialog(self, cliente=cli)
        if dialog.exec_():
            data = dialog.get_data()
            try:
                self.manager.update_cliente(
                    cli["id"],
                    data["codigo"],
                    data["nombre"],
                    data["nrc"],
                    data["nit"],
                    data["dui"],
                    data["giro"],
                    data["telefono"],
                    data["email"],
                    data["direccion"],
                    data["departamento"],
                    data["municipio"],
                    codActividad=data["codActividad"],
                    nombreComercial=data["nombreComercial"],
                    tipoContribuyente=data["tipoContribuyente"],
                    razonSocial=data["razonSocial"],
                )
            except ValueError as e:
                QMessageBox.warning(dialog, "Cliente", str(e))
                return
            self._actualizar_tabla_clientes()
            QMessageBox.information(self, "Cliente", "Cliente editado correctamente.")

    def _eliminar_cliente(self):
        if self._is_guest():
            self._deny_guest()
            return
        cli = self._get_selected_cliente()
        if not cli:
            QMessageBox.warning(self, "Eliminar cliente", "Seleccione un cliente para eliminar.")
            return
        confirm = QMessageBox.question(self, "Eliminar", f"¿Eliminar cliente '{cli['nombre']}'?", QMessageBox.Yes | QMessageBox.No)
        if confirm == QMessageBox.Yes:
            self.manager.delete_cliente(cli["id"])
            self._actualizar_tabla_clientes()
            QMessageBox.information(self, "Cliente eliminado", f"El cliente '{cli['nombre']}' ha sido eliminado.")

    def _actualizar_historial(self):
        """Recarga la tabla de historial."""
        self._mostrar_historial_general()
            

    def _limpiar_filtros_historial(self):
        """Método mantenido por compatibilidad."""
        pass

    def eventFilter(self, obj, event):
        return super().eventFilter(obj, event)

    def _actualizar_inventario_actual(self):
        search_raw = self.actual_search_bar.text() or ""
        search = search_raw.lower()
        stock_only = self.actual_stock_only_cb.isChecked() if hasattr(self, "actual_stock_only_cb") else True
        view_combo = getattr(self, "inventario_view_combo", None)
        general_view = view_combo is not None and view_combo.currentText().lower().startswith("inventario")
        if hasattr(self, "inventario_general_table"):
            self.inventario_general_table.setVisible(general_view)
        self.inventario_actual_table.setVisible(not general_view)

        if general_view and hasattr(self, "inventario_general_table"):
            productos = self.manager.db.get_productos(search=search_raw)
            filtered = []
            for prod in productos:
                try:
                    stock_val = float(prod.get("stock", 0) or 0)
                except (TypeError, ValueError):
                    stock_val = 0
                if stock_only and stock_val <= 0:
                    continue
                filtered.append((prod, stock_val))

            self.inventario_general_table.setRowCount(len(filtered))
            for row, (prod, stock_val) in enumerate(filtered):
                self.inventario_general_table.setItem(row, 0, QTableWidgetItem(prod.get("nombre", "")))
                self.inventario_general_table.setItem(row, 1, QTableWidgetItem(prod.get("codigo", "")))
                precio_minorista = prod.get("precio_venta_minorista", 0) or 0
                self.inventario_general_table.setItem(row, 2, QTableWidgetItem(f"${precio_minorista:.2f}"))
                stock_display = int(stock_val) if float(stock_val).is_integer() else stock_val
                self.inventario_general_table.setItem(row, 3, QTableWidgetItem(str(stock_display)))
                self.inventario_general_table.setRowHeight(row, 64)
            return

        catalogs = getattr(self.manager, "catalogs", None)
        compras = self.manager.db.get_compras()
        if catalogs and catalogs.products:
            productos_dict = catalogs.products
        else:
            productos_dict = {p["id"]: p for p in self.manager.db.get_productos()}

        detalles: list[dict] = []
        for compra in compras:
            compra_id = compra.get("id")
            detalles_compra = self.manager.db.get_detalles_compra(compra_id)
            _, distribuidor_nombre = resolve_party_names(compra, catalogs)
            for d in detalles_compra:
                prod = productos_dict.get(d["producto_id"])
                if not prod:
                    continue
                cantidad = int(d.get("cantidad", 0) or 0)
                if stock_only and cantidad <= 0:
                    continue
                detalles.append({
                    "producto": prod.get("nombre", ""),
                    "codigo": prod.get("codigo", ""),
                    "cantidad": cantidad,
                    "precio_compra": d.get("precio_unitario", 0),
                    "codigo_lote": d.get("codigo_lote") or "",
                    "registro_sanitario": d.get("registro_sanitario") or "",
                    "fecha_compra": compra.get("fecha", ""),
                    "fecha_vencimiento": d.get("fecha_vencimiento", ""),
                    "Distribuidor": distribuidor_nombre,
                    "detalle_id": d.get("id"),
                    "producto_id": d.get("producto_id"),
                    "compra_id": compra_id,
                })

        if search:
            detalles = [
                d for d in detalles
                if search in d["producto"].lower() or search in d["codigo"].lower()
            ]

        self.inventario_actual_table.setRowCount(len(detalles))
        for row, d in enumerate(detalles):
            item_producto = QTableWidgetItem(d["producto"])
            item_producto.setData(Qt.UserRole, d)
            self.inventario_actual_table.setItem(row, 0, item_producto)
            self.inventario_actual_table.setItem(row, 1, QTableWidgetItem(d["codigo"]))
            self.inventario_actual_table.setItem(row, 2, QTableWidgetItem(str(d["cantidad"])))
            self.inventario_actual_table.setItem(row, 3, QTableWidgetItem(f"${d['precio_compra']:.2f}"))
            self.inventario_actual_table.setItem(row, 4, QTableWidgetItem(d["codigo_lote"]))
            self.inventario_actual_table.setItem(row, 5, QTableWidgetItem(d["registro_sanitario"]))
            self.inventario_actual_table.setItem(row, 6, QTableWidgetItem(d["fecha_compra"]))
            self.inventario_actual_table.setItem(row, 7, QTableWidgetItem(d["fecha_vencimiento"]))
            self.inventario_actual_table.setItem(row, 8, QTableWidgetItem(d["Distribuidor"]))
            self._set_inventario_action_cell(row)
            self.inventario_actual_table.setRowHeight(row, 64)

    def _trigger_inventory_action(self, row: int, handler):
        if row >= 0:
            self.inventario_actual_table.selectRow(row)
            handler()

    def _set_inventario_action_cell(self, row: int):
        container = QWidget()
        container.setAttribute(Qt.WA_TranslucentBackground, True)
        container.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignCenter)

        btn_view = QPushButton("📄", container)
        btn_view.setProperty("class", "table-icon-btn")
        btn_view.setStyleSheet("color: #475569; font-size: 18px;")
        btn_view.setFixedSize(46, 42)
        btn_view.setToolTip("Ver información del lote")
        btn_view.clicked.connect(lambda _, r=row: self._trigger_inventory_action(r, self._ver_informacion_lote))

        btn_edit = QPushButton("✏️", container)
        btn_edit.setProperty("class", "table-icon-btn")
        btn_edit.setStyleSheet("color: #2563EB; font-size: 18px;")
        btn_edit.setFixedSize(46, 42)
        btn_edit.setToolTip("Editar lote")
        btn_edit.clicked.connect(lambda _, r=row: self._trigger_inventory_action(r, self._editar_lote_inventario_actual))

        btn_delete = QPushButton("🗑️", container)
        btn_delete.setProperty("class", "table-icon-btn")
        btn_delete.setStyleSheet("color: #DC2626; font-size: 18px;")
        btn_delete.setFixedSize(46, 42)
        btn_delete.setToolTip("Eliminar lote")
        btn_delete.clicked.connect(lambda _, r=row: self._trigger_inventory_action(r, self._eliminar_lote_inventario_actual))

        layout.addWidget(btn_view)
        layout.addWidget(btn_edit)
        layout.addWidget(btn_delete)
        self.inventario_actual_table.setCellWidget(row, 9, container)

    def _confirm_inventory_conflict(self, target: str) -> bool:
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Warning)
        dialog.setWindowTitle("Advertencia de inventario")
        dialog.setText(
            "Está a punto de editar el inventario.\n"
            "Esto puede ocasionar problemas de contabilidad; Vertex no se hace responsable "
            "por las consecuencias. La edición queda a discreción del usuario."
        )
        dialog.setInformativeText(
            "Si necesita reducir inventario, puede hacerlo mediante una factura de autoconsumo."
        )
        btn_autoconsumo = dialog.addButton(
            "Crear una venta de autoconsumo", QMessageBox.ActionRole
        )
        btn_proceed = dialog.addButton(
            "Proceder con la edición", QMessageBox.DestructiveRole
        )
        btn_cancel = dialog.addButton("Cancelar", QMessageBox.RejectRole)
        dialog.setDefaultButton(btn_cancel)
        dialog.exec_()

        clicked = dialog.clickedButton()
        if clicked == btn_autoconsumo:
            launcher = getattr(self, "registrar_venta", None)
            if callable(launcher):
                try:
                    launcher()
                except Exception:
                    logger.exception("No se pudo abrir la venta de autoconsumo")
            return False
        if clicked == btn_proceed:
            return True
        return False

    def _editar_lote_inventario_actual(self):
        row = self.inventario_actual_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Editar lote", "Seleccione un lote para editar.")
            return

        item_producto = self.inventario_actual_table.item(row, 0)
        if not item_producto:
            QMessageBox.warning(self, "Editar lote", "No se pudo obtener la información del lote seleccionado.")
            return

        data = item_producto.data(Qt.UserRole) or {}
        detalle_id = data.get("detalle_id")

        if not detalle_id:
            QMessageBox.warning(self, "Editar lote", "No se encontró el identificador del lote seleccionado.")
            return

        cantidad_actual = int(data.get("cantidad", 0) or 0)
        producto = data.get("producto", "")
        codigo = data.get("codigo", "")

        if not self._confirm_inventory_conflict("este lote"):
            return

        dialog = EditarLoteDialog(
            self,
            producto=producto,
            codigo=codigo,
            cantidad=cantidad_actual,
            codigo_lote=data.get("codigo_lote") or "",
            registro_sanitario=data.get("registro_sanitario") or "",
            fecha_vencimiento=data.get("fecha_vencimiento") or "",
        )

        if dialog.exec_() != QDialog.Accepted:
            return

        (
            nueva_cantidad,
            nuevo_codigo_lote,
            nuevo_registro_sanitario,
            nueva_fecha_vencimiento,
        ) = dialog.get_values()

        cambios: dict[str, object] = {}
        if nueva_cantidad != cantidad_actual:
            cambios["cantidad"] = nueva_cantidad

        codigo_lote_actual = data.get("codigo_lote") or ""
        if nuevo_codigo_lote != codigo_lote_actual:
            cambios["codigo_lote"] = nuevo_codigo_lote

        registro_sanitario_actual = data.get("registro_sanitario") or ""
        if nuevo_registro_sanitario != registro_sanitario_actual:
            cambios["registro_sanitario"] = nuevo_registro_sanitario

        fecha_actual = data.get("fecha_vencimiento") or ""
        if nueva_fecha_vencimiento != fecha_actual:
            cambios["fecha_vencimiento"] = nueva_fecha_vencimiento

        if not cambios:
            return

        try:
            self.manager.update_detalle_compra(detalle_id, **cambios)
        except ValueError as exc:
            QMessageBox.warning(self, "Editar lote", str(exc))
            return
        except Exception as exc:  # pragma: no cover - logging unexpected errors
            logger.exception("Error al actualizar el lote: %s", exc)
            QMessageBox.critical(
                self,
                "Editar lote",
                "Ocurrió un error al actualizar el lote.",
            )
            return

        QMessageBox.information(
            self,
            "Editar lote",
            "El lote se actualizó correctamente.",
        )

        self._actualizar_inventario_actual()
        self.filter_products()
        self.data_changed.emit()

    def _ver_informacion_lote(self):
        row = self.inventario_actual_table.currentRow()
        logger.info(
            "Inventario actual: solicitando detalle de lote en fila %s", row
        )
        if row < 0:
            QMessageBox.warning(
                self,
                "Ver información",
                "Seleccione un lote para consultar su información.",
            )
            return

        item_producto = self.inventario_actual_table.item(row, 0)
        if not item_producto:
            logger.warning(
                "Inventario actual: la fila %s no tiene item asociado", row
            )
            QMessageBox.warning(
                self,
                "Ver información",
                "No se pudo obtener la información del lote seleccionado.",
            )
            return

        data = item_producto.data(Qt.UserRole) or {}
        compra_id = data.get("compra_id")
        logger.info(
            "Inventario actual: lote con datos %s -> compra asociada %s",
            {k: data.get(k) for k in ("producto", "codigo", "detalle_id")},
            compra_id,
        )
        if not compra_id:
            QMessageBox.warning(
                self,
                "Ver información",
                "El lote seleccionado no tiene una compra asociada.",
            )
            return

        compra = self.manager.db.get_compra(compra_id)
        if compra:
            logger.info(
                "Inventario actual: compra %s recuperada desde base de datos",
                compra_id,
            )
        else:
            logger.warning(
                "Inventario actual: no se pudo recuperar la compra %s", compra_id
            )
        if not compra:
            QMessageBox.warning(
                self,
                "Ver información",
                "No fue posible cargar la compra asociada al lote seleccionado.",
            )
            return

        detalles = self.manager.db.get_detalles_compra(compra_id)
        logger.info(
            "Inventario actual: compra %s tiene %s partidas", compra_id, len(detalles)
        )
        catalogs = getattr(self.manager, "catalogs", None)
        dialog = CompraDetalleDialog(compra, detalles, self, catalogs=catalogs)
        dialog.exec_()

    def _eliminar_lote_inventario_actual(self):
        row = self.inventario_actual_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Eliminar lote", "Seleccione un lote para eliminar.")
            return

        item_producto = self.inventario_actual_table.item(row, 0)
        if not item_producto:
            QMessageBox.warning(
                self,
                "Eliminar lote",
                "No se pudo obtener la información del lote seleccionado.",
            )
            return

        data = item_producto.data(Qt.UserRole) or {}
        detalle_id = data.get("detalle_id")
        if not detalle_id:
            QMessageBox.warning(
                self,
                "Eliminar lote",
                "No se encontró el identificador del lote seleccionado.",
            )
            return

        producto = data.get("producto", "")
        codigo = data.get("codigo", "")
        cantidad = data.get("cantidad", 0)

        if not self._confirm_inventory_conflict("este lote"):
            return

        confirm = QMessageBox.question(
            self,
            "Eliminar lote",
            f"¿Eliminar el lote de {producto} (código {codigo}) con {cantidad} unidades?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        try:
            self.manager.delete_detalle_compra(detalle_id)
        except ValueError as exc:
            QMessageBox.warning(self, "Eliminar lote", str(exc))
            return
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.exception("Error al eliminar el lote %s", detalle_id)
            QMessageBox.critical(
                self,
                "Eliminar lote",
                "Ocurrió un error al eliminar el lote seleccionado.",
            )
            return

        QMessageBox.information(
            self,
            "Eliminar lote",
            "El lote se eliminó correctamente del inventario.",
        )

        self._actualizar_inventario_actual()
        if hasattr(self, "compras_tab") and hasattr(self.compras_tab, "load_purchases"):
            try:
                self.compras_tab.load_purchases()
            except Exception:  # pragma: no cover - keep UI responsive
                logger.exception("No se pudo refrescar la pestaña de compras tras eliminar el lote")
        self.filter_products()
        self.data_changed.emit()

    def _on_table_clicked(self, index):
        self.selected_row = index.row()

    def _get_selected_product(self):
        index = self.product_table.currentIndex()
        if not index.isValid():
            return None
        row = index.row()
        if row < 0 or row >= len(self.manager._products):
            return None
        return self.manager._products[row]
    
    def _abrir_datos_negocio(self):
        # Puedes guardar/cargar los datos en un archivo JSON local, por ejemplo:
        import os, json
        datos_path = DATOS_NEGOCIO_PATH
        config_path = CONFIG_NEGOCIO_PATH
        datos = {}
        config = {}
        if os.path.exists(datos_path):
            try:
                with open(datos_path, "r", encoding="utf-8") as f:
                    datos = json.load(f)
                    dir_info = datos.get("direccion") or {}
                    dir_info.setdefault("departamento", "")
                    dir_info.setdefault("municipio", "")
                    datos["direccion"] = dir_info
            except Exception:
                datos = {}
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
            except Exception:
                config = {}
        from dialogs import DatosNegocioDialog
        dlg = DatosNegocioDialog(datos, self)
        if dlg.exec_():
            datos_nuevos = dlg.get_data()
            datos.update(datos_nuevos)
            dir_info = datos.get("direccion") or {}
            dir_info.setdefault("departamento", "")
            dir_info.setdefault("municipio", "")
            datos["direccion"] = dir_info
            datos_changed, config_changed, tokens_reset = _sync_configs(
                datos,
                config,
                nit_hint=datos_nuevos.get("nit"),
                ambiente_hint=(datos.get("dte_api") or {}).get("ambiente"),
            )
            with open(datos_path, "w", encoding="utf-8") as f:
                json.dump(datos, f, ensure_ascii=False, indent=2)
            if config_changed:
                with open(config_path, "w", encoding="utf-8") as f:
                    json.dump(config, f, ensure_ascii=False, indent=2)
            if config_changed or datos_changed or tokens_reset:
                invalidate_token_cache()
            if tokens_reset:
                QMessageBox.information(
                    self,
                    "Tokens reiniciados",
                    "Los tokens almacenados se limpiaron porque cambiaste el NIT o el ambiente. "
                    "Vuelve a obtener un token en Configuración > Facturación Electrónica.",
                )
            QMessageBox.information(self, "Datos del negocio", "Datos guardados correctamente.")

    def _abrir_config_correo(self):
        import os, json
        datos_path = DATOS_NEGOCIO_PATH
        datos = {}
        if os.path.exists(datos_path):
            try:
                with open(datos_path, "r", encoding="utf-8") as f:
                    datos = json.load(f)
            except Exception:
                datos = {}
        from dialogs import EmailConfigDialog
        dlg = EmailConfigDialog(datos, self)
        if dlg.exec_():
            datos.update(dlg.get_data())
            with open(datos_path, "w", encoding="utf-8") as f:
                json.dump(datos, f, ensure_ascii=False, indent=2)
            QMessageBox.information(self, "Configuración de correo", "Datos guardados correctamente.")

    def _abrir_config_facturacion(self):
        import os, json
        datos_path = DATOS_NEGOCIO_PATH
        config_path = CONFIG_NEGOCIO_PATH
        datos = {}
        config = {}
        if os.path.exists(datos_path):
            try:
                with open(datos_path, "r", encoding="utf-8") as f:
                    datos = json.load(f)
            except Exception:
                datos = {}
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
            except Exception:
                config = {}
        from dialogs import DTEConfigDialog
        dte_api = datos.get("dte_api", {})
        ambiente = config.get("ambiente", "pruebas")
        env_conf = config.get(ambiente, {})
        fe_config = env_conf.get("firma_electronica", {})

        dialog_kwargs = {}
        try:
            import inspect

            params = inspect.signature(DTEConfigDialog.__init__).parameters
            if "db" in params:
                dialog_kwargs["db"] = self.manager.db
        except (AttributeError, ValueError, TypeError):  # pragma: no cover - defensive
            pass

        dlg = DTEConfigDialog(
            dte_api,
            fe_config,
            env_conf,
            self,
            datos_negocio=datos,
            **dialog_kwargs,
        )
        if dlg.exec_():
            new_dte_api, new_fe, new_urls = dlg.get_data()
            negocio_updates = getattr(dlg, "get_negocio_updates", lambda: {})()
            if isinstance(negocio_updates, Mapping):
                datos.update(negocio_updates)
            ambiente = new_dte_api["ambiente"]
            datos["dte_api"] = new_dte_api
            config["ambiente"] = ambiente
            config.setdefault(ambiente, {})
            config[ambiente]["firma_electronica"] = new_fe
            config[ambiente]["auth_url"] = new_urls.get("auth_url", "")
            config[ambiente]["recepcion_url"] = new_urls.get("recepcion_url", "")
            if "auth" in new_urls:
                config[ambiente]["auth"] = new_urls["auth"]
            datos_changed, config_changed_extra, tokens_reset = _sync_configs(
                datos,
                config,
                nit_hint=new_fe.get("nit"),
                ambiente_hint=new_dte_api.get("ambiente"),
            )
            with open(datos_path, "w", encoding="utf-8") as f:
                json.dump(datos, f, ensure_ascii=False, indent=2)
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            invalidate_token_cache()
            if tokens_reset:
                QMessageBox.information(
                    self,
                    "Tokens reiniciados",
                    "Los tokens almacenados se limpiaron porque cambiaste el NIT o el ambiente. "
                    "Obtén un token nuevo antes de volver a enviar DTE.",
                )
            QMessageBox.information(self, "Facturación electrónica", "Datos guardados correctamente.")

    def _abrir_config_usuarios(self):
        dlg = UserConfigDialog(self.manager.db, self)
        dlg.exec_()

    def _populate_estados_reportes_data(self):
        if not hasattr(self, "manager") or self.manager is None:
            return
        clientes = self.manager.db.get_clientes()
        vendedores = self.manager.db.get_trabajadores(solo_vendedores=True)
        self._clientes_estado = clientes
        self._vendedores_estado = vendedores

        if hasattr(self, "reportes_cliente_combo"):
            combo = self.reportes_cliente_combo
            current_id = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("Todos", None)
            for cli in clientes:
                display = f"{cli.get('codigo', '')} — {cli.get('nombre', '')}".strip(" —")
                combo.addItem(display, cli.get("id"))
            if current_id:
                idx = combo.findData(current_id)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
            combo.blockSignals(False)

        if hasattr(self, "reportes_vendedor_combo"):
            combo = self.reportes_vendedor_combo
            current_id = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("Todos", None)
            for vend in vendedores:
                display = f"{vend.get('codigo', '')} — {vend.get('nombre', '')}".strip(" —")
                combo.addItem(display, vend.get("id"))
            if current_id:
                idx = combo.findData(current_id)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
            combo.blockSignals(False)

    def _collect_report_params(self, mode: str):
        start_edit = self.reportes_cliente_desde if mode == "cliente" else self.reportes_vendedor_desde
        end_edit = self.reportes_cliente_hasta if mode == "cliente" else self.reportes_vendedor_hasta
        combo = self.reportes_cliente_combo if mode == "cliente" else self.reportes_vendedor_combo
        filtro_chk = self.reportes_cliente_filtro_fecha if mode == "cliente" else self.reportes_vendedor_filtro_fecha

        params = {
            "fecha_inicio": start_edit.date().toString("yyyy-MM-dd") if filtro_chk.isChecked() else "",
            "fecha_fin": end_edit.date().toString("yyyy-MM-dd") if filtro_chk.isChecked() else "",
        }
        selected_id = combo.currentData()
        if selected_id:
            if mode == "cliente":
                params["cliente_id"] = selected_id
            else:
                params["vendedor_id"] = selected_id
        return params

    def _generar_reporte_cliente(self):
        if not hasattr(self, "manager") or self.manager is None:
            return
        params = self._collect_report_params("cliente")
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Guardar estado de cuenta (cliente)",
            "estado_cuenta_cliente.pdf",
            "PDF Files (*.pdf)",
        )
        if not filename:
            return
        from estado_cuenta_pdf import generar_estado_cuenta_pdf
        try:
            generar_estado_cuenta_pdf(self.manager.db, modo="cliente", archivo=filename, **params)
            QMessageBox.information(self, "Estado de cuenta", f"Archivo generado en {filename}")
        except Exception as e:
            QMessageBox.warning(self, "Estado de cuenta", f"Error: {e}")

    def _generar_reporte_vendedor(self):
        if not hasattr(self, "manager") or self.manager is None:
            return
        params = self._collect_report_params("vendedor")
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Guardar estado de cuenta (vendedor)",
            "estado_cuenta_vendedor.pdf",
            "PDF Files (*.pdf)",
        )
        if not filename:
            return
        from estado_cuenta_pdf import generar_estado_cuenta_pdf
        try:
            mode = "vendedor"
            if "vendedor_id" not in params:
                mode = "todos"
            generar_estado_cuenta_pdf(self.manager.db, modo=mode, archivo=filename, **params)
            QMessageBox.information(self, "Estado de cuenta", f"Archivo generado en {filename}")
        except Exception as e:
            QMessageBox.warning(self, "Estado de cuenta", f"Error: {e}")

    def _actualizar_tabla_trabajadores(self):
        solo_vendedores = self.trabajadores_filtro_vendedor.isChecked() if hasattr(self, "trabajadores_filtro_vendedor") else False
        area = self.trabajadores_filtro_area.text() if hasattr(self, "trabajadores_filtro_area") else ""
        search = (self.trabajadores_search.text() or "").strip().lower() if hasattr(self, "trabajadores_search") else ""
        trabajadores = self.manager.db.get_trabajadores(
            solo_vendedores=solo_vendedores, area=area
        )
        filtered = []
        for t in trabajadores:
            haystack = " ".join(
                [
                    t.get("codigo", "") or "",
                    t.get("nombre", "") or "",
                    t.get("area", "") or "",
                    t.get("cargo", "") or "",
                    t.get("telefono", "") or "",
                    t.get("email", "") or "",
                ]
            ).lower()
            if search and search not in haystack:
                continue
            filtered.append(t)

        if hasattr(self, "trabajadores_list"):
            self.trabajadores_list.clear()
            for t in filtered:
                text = f"{t.get('codigo', '')} - {t.get('nombre', '')}".strip(" -")
                item = QListWidgetItem(text)
                item.setData(Qt.UserRole, t)
                self.trabajadores_list.addItem(item)

        table = getattr(self, "trabajadores_table", None)
        if table is not None:
            table.setRowCount(len(filtered))
            for row, t in enumerate(filtered):
                table.setItem(row, 0, QTableWidgetItem(t.get("codigo", "")))
                table.setItem(row, 1, QTableWidgetItem(t.get("nombre", "")))
                table.setItem(row, 2, QTableWidgetItem(t.get("dui", "")))
                table.setItem(row, 3, QTableWidgetItem(t.get("nit", "")))
                table.setItem(row, 4, QTableWidgetItem(t.get("fecha_nacimiento", "")))
                table.setItem(row, 5, QTableWidgetItem(t.get("cargo", "")))
                table.setItem(row, 6, QTableWidgetItem(t.get("area", "")))
                table.setItem(row, 7, QTableWidgetItem(t.get("telefono", "")))
                table.setItem(row, 8, QTableWidgetItem(t.get("email", "")))
                table.setItem(row, 9, QTableWidgetItem("Sí" if t.get("es_vendedor") else "No"))

    def _get_selected_trabajador(self):
        if hasattr(self, "trabajadores_list"):
            current = self.trabajadores_list.currentItem()
            if current:
                data = current.data(Qt.UserRole)
                if isinstance(data, dict):
                    return data
        table = getattr(self, "trabajadores_table", None)
        if table is None:
            return None
        row = table.currentRow()
        if row < 0:
            return None
        codigo = table.item(row, 0).text()
        trabajadores = self.manager.db.get_trabajadores()
        for t in trabajadores:
            if t.get("codigo", "") == codigo:
                return t
        return None

    def _agregar_trabajador(self):
        if self._is_guest():
            self._deny_guest()
            return
        from dialogs import TrabajadorDialog
        codigo = self.manager.db.get_next_trabajador_codigo()
        dialog = TrabajadorDialog(parent=self)
        dialog.codigo.setText(codigo)
        if dialog.exec_():
            data = dialog.get_data()
            self.manager.db.add_trabajador(data)
            self._actualizar_tabla_trabajadores()
            QMessageBox.information(self, "Trabajador", "Trabajador agregado correctamente.")

    def _editar_trabajador(self):
        if self._is_guest():
            self._deny_guest()
            return
        t = self._get_selected_trabajador()
        if not t:
            QMessageBox.warning(self, "Editar trabajador", "Seleccione un trabajador para editar.")
            return
        from dialogs import TrabajadorDialog
        dialog = TrabajadorDialog(trabajador=t, parent=self)
        if dialog.exec_():
            data = dialog.get_data()
            self.manager.db.update_trabajador(t["id"], data)
            self._actualizar_tabla_trabajadores()
            QMessageBox.information(self, "Trabajador", "Trabajador editado correctamente.")

    def _eliminar_trabajador(self):
        if self._is_guest():
            self._deny_guest()
            return
        t = self._get_selected_trabajador()
        if not t:
            QMessageBox.warning(self, "Eliminar trabajador", "Seleccione un trabajador para eliminar.")
            return
        confirm = QMessageBox.question(
            self,
            "Eliminar",
            f"¿Eliminar trabajador '{t['nombre']}'?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm == QMessageBox.Yes:
            count = self.manager.db.cursor.execute(
                "SELECT COUNT(*) FROM ventas WHERE vendedor_id=?",
                (t["id"],),
            ).fetchone()[0]
            if count > 0:
                QMessageBox.warning(
                    self,
                    "Eliminar trabajador",
                    "El trabajador tiene ventas asociadas y no puede eliminarse.",
                )
                return
            try:
                if t.get("es_vendedor"):
                    self.manager.db.delete_vendedor_completo(t["id"])
                else:
                    self.manager.db.delete_trabajador(t["id"])
            except ValueError:
                QMessageBox.warning(
                    self,
                    "Eliminar trabajador",
                    "El trabajador tiene registros asociados y no puede eliminarse.",
                )
                return
            except Exception as exc:
                logger.exception("No se pudo eliminar el trabajador")
                QMessageBox.critical(self, "Eliminar trabajador", f"No se pudo eliminar el trabajador: {exc}")
                return
            self._actualizar_tabla_trabajadores()
            QMessageBox.information(
                self,
                "Trabajador eliminado",
                f"El trabajador '{t['nombre']}' ha sido eliminado.",
            )


    def _toggle_estado_filtro_fechas(self, checked: bool):
        if not all(hasattr(self, attr) for attr in ("estado_quick_range", "estado_fecha_inicio", "estado_fecha_fin", "estado_filtrar_fechas")):
            return
        self.estado_quick_range.setEnabled(checked)
        custom = self.estado_quick_range.currentIndex() == 0
        self.estado_fecha_inicio.setEnabled(checked and custom)
        self.estado_fecha_fin.setEnabled(checked and custom)
        if checked:
            self._apply_estado_quick_range()

    def _apply_estado_quick_range(self):
        if not all(hasattr(self, attr) for attr in ("estado_filtrar_fechas", "estado_quick_range", "estado_fecha_inicio", "estado_fecha_fin")):
            return
        if not self.estado_filtrar_fechas.isChecked():
            return
        option = self.estado_quick_range.currentText()
        today = date.today()
        if option == "Hoy":
            self.estado_fecha_inicio.setDate(QDate(today))
            self.estado_fecha_fin.setDate(QDate(today))
            self.estado_fecha_inicio.setEnabled(False)
            self.estado_fecha_fin.setEnabled(False)
        elif option == "Esta semana":
            start = today - timedelta(days=today.weekday())
            end = start + timedelta(days=6)
            self.estado_fecha_inicio.setDate(QDate(start))
            self.estado_fecha_fin.setDate(QDate(end))
            self.estado_fecha_inicio.setEnabled(False)
            self.estado_fecha_fin.setEnabled(False)
        elif option == "Este mes":
            start = today.replace(day=1)
            if today.month == 12:
                end = date(today.year, 12, 31)
            else:
                end = date(today.year, today.month + 1, 1) - timedelta(days=1)
            self.estado_fecha_inicio.setDate(QDate(start))
            self.estado_fecha_fin.setDate(QDate(end))
            self.estado_fecha_inicio.setEnabled(False)
            self.estado_fecha_fin.setEnabled(False)
        elif option == "Este año":
            start = date(today.year, 1, 1)
            end = date(today.year, 12, 31)
            self.estado_fecha_inicio.setDate(QDate(start))
            self.estado_fecha_fin.setDate(QDate(end))
            self.estado_fecha_inicio.setEnabled(False)
            self.estado_fecha_fin.setEnabled(False)
        else:
            self.estado_fecha_inicio.setEnabled(True)
            self.estado_fecha_fin.setEnabled(True)

    def _abrir_generar_estado_dialog(self):
        """Abre la ventana de generación de estados de cuenta."""
        if not all(hasattr(self, attr) for attr in ("estado_tipo_combo", "estado_filtrar_fechas", "estado_fecha_inicio", "estado_fecha_fin")):
            return
        dialog = EstadoCuentaDialog(self.manager.db, self)
        tipo_idx = 0 if self.estado_tipo_combo.currentText() == "Cliente" else 1
        dialog.modo_combo.setCurrentIndex(tipo_idx)
        dialog.stack.setCurrentIndex(tipo_idx)
        if self.estado_filtrar_fechas.isChecked():
            dialog.filtrar_fechas_chk.setChecked(True)
            range_text = self.estado_quick_range.currentText()
            idx = dialog.quick_range.findText(range_text)
            if idx >= 0:
                dialog.quick_range.setCurrentIndex(idx)
            if idx == 0:
                dialog.fecha_inicio.setDate(self.estado_fecha_inicio.date())
                dialog.fecha_fin.setDate(self.estado_fecha_fin.date())
        else:
            dialog.filtrar_fechas_chk.setChecked(False)
        dialog.exec_()

    def _imprimir_estado_cuenta(self):
        dialog = EstadoCuentaDialog(self.manager.db, self)
        dialog.modo_combo.setCurrentIndex(1)
        dialog.stack.setCurrentIndex(1)
        if self.estado_filtrar_fechas.isChecked():
            dialog.filtrar_fechas_chk.setChecked(True)
            range_text = self.estado_quick_range.currentText()
            idx = dialog.quick_range.findText(range_text)
            if idx >= 0:
                dialog.quick_range.setCurrentIndex(idx)
            if idx == 0:
                dialog.fecha_inicio.setDate(self.estado_fecha_inicio.date())
                dialog.fecha_fin.setDate(self.estado_fecha_fin.date())
        else:
            dialog.filtrar_fechas_chk.setChecked(False)
        dialog.exec_()


    def _mostrar_historial_general(self):
        """Muestra el historial completo filtrando por cliente o vendedor."""
        required_attrs = [
            "estado_tipo_combo",
            "estado_filtrar_fechas",
            "estado_fecha_inicio",
            "estado_fecha_fin",
            "estado_search_bar",
            "estado_table",
        ]
        if any(not hasattr(self, attr) for attr in required_attrs):
            return
        tipo = "cliente" if self.estado_tipo_combo.currentText() == "Cliente" else "vendedor"

        if self.estado_filtrar_fechas.isChecked():
            inicio = self.estado_fecha_inicio.date().toPyDate()
            fin = self.estado_fecha_fin.date().toPyDate()
        else:
            inicio = None
            fin = None

        filtro = self.estado_search_bar.text().lower()
        ventas = self.manager.db.get_ventas()
        rows = []
        for v in ventas:
            fecha_str = v.get("fecha", "")
            try:
                fdate = datetime.strptime(fecha_str, "%Y-%m-%d %H:%M:%S").date()
            except ValueError:
                try:
                    fdate = datetime.strptime(fecha_str, "%Y-%m-%d").date()
                except ValueError:
                    fdate = None
            if inicio and fdate and fdate < inicio:
                continue
            if fin and fdate and fdate > fin:
                continue

            if tipo == "cliente" and not v.get("cliente_id"):
                continue
            if tipo == "vendedor" and not v.get("vendedor_id"):
                continue

            cli_nombre = ""
            vend_nombre = ""
            codigo = ""
            if v.get("cliente_id"):
                cli = self.manager.db.get_cliente(v["cliente_id"])
                if cli:
                    cli_nombre = cli.get("nombre", "")
                    codigo = cli.get("codigo", "")
            if v.get("vendedor_id"):
                trab = self.manager.db.get_trabajador(v["vendedor_id"])
                if trab:
                    vend_nombre = trab.get("nombre", "")
                    if tipo == "vendedor":
                        codigo = trab.get("codigo", "")

            if filtro and filtro not in cli_nombre.lower() and filtro not in vend_nombre.lower() and filtro not in codigo.lower():
                continue

            tipo_factura = "Crédito fiscal" if self.manager.db.get_venta_credito_fiscal(v.get("id")) else "Consumidor final"
            rows.append((fecha_str, v.get("id"), tipo_factura, cli_nombre, vend_nombre, v.get("total", 0)))

        self.estado_table.setColumnCount(6)
        self.estado_table.setHorizontalHeaderLabels([
            "Fecha",
            "Factura",
            "Tipo",
            "Cliente",
            "Vendedor",
            "Monto",
        ])
        self.estado_table.setRowCount(len(rows))
        for row, (fecha, fid, tipo, cli, vend, monto) in enumerate(rows):
            self.estado_table.setItem(row, 0, QTableWidgetItem(fecha))
            self.estado_table.setItem(row, 1, QTableWidgetItem(str(fid)))
            self.estado_table.setItem(row, 2, QTableWidgetItem(tipo))
            self.estado_table.setItem(row, 3, QTableWidgetItem(cli))
            self.estado_table.setItem(row, 4, QTableWidgetItem(vend))
            self.estado_table.setItem(row, 5, QTableWidgetItem(f"${float(monto):.2f}"))

    def _cargar_personas_estado(self):
        """Carga datos para la pestaña de estados de cuenta."""
        if hasattr(self, "reportes_cliente_combo") or hasattr(self, "reportes_vendedor_combo"):
            self._populate_estados_reportes_data()
        if hasattr(self, "estado_search_bar"):
            self._clientes_estado = self.manager.db.get_clientes()
            self._vendedores_estado = self.manager.db.get_trabajadores(solo_vendedores=True)
            self.estado_search_bar.clear()
            self._mostrar_historial_general()

    def get_tab_order(self):
        return [self.tabs.tabText(i) for i in range(self.tabs.count())]

    def set_tab_order(self, order):
        if not self._is_valid_tab_order(order):
            logger.info("Orden de pestañas ignorado por ser inválido: %s", order)
            return
        for desired_index, title in enumerate(order):
            index = self._find_tab_index(title)
            if index != -1 and index != desired_index:
                self.tabs.tabBar().moveTab(index, desired_index)

    def _find_tab_index(self, title):
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i) == title:
                return i
        return -1

    def _is_valid_tab_order(self, order):
        if not isinstance(order, (list, tuple)):
            return False
        current = [self.tabs.tabText(i) for i in range(self.tabs.count())]
        if len(order) != len(current):
            return False
        return set(order) == set(current)

    def _reset_tabs_to_default_order(self):
        canonical = [
            "Inicio",
            "Vendedores y Distribuidores",
            "Clientes",
            "Ventas",
            "Compras",
            "Inventario",
            "Facturacion",
            "Trabajadores",
            "Estados de cuenta",
        ]
        for desired_index, title in enumerate(canonical):
            idx = self._find_tab_index(title)
            if idx != -1 and idx != desired_index:
                self.tabs.tabBar().moveTab(idx, desired_index)

    # DEBUG: Método temporal para pruebas de Venta vs DTE
    def _debug_venta_vs_dte(self):  # pragma: no cover - debug helper
        """Compara cálculos de una venta con su DTE correspondiente."""
        row = self.sales_tab.sales_table.currentRow()
        venta_id = None
        if row >= 0:
            item = self.sales_tab.sales_table.item(row, 0)
            if item is not None:
                try:
                    venta_id = int(item.text())
                except ValueError:
                    venta_id = None
        else:
            text = self.sales_tab.search_bar.text().strip()
            if text.isdigit():
                venta_id = int(text)

        if venta_id is None:
            QMessageBox.warning(
                self,
                "Debug Venta vs DTE",
                "Seleccione una venta o ingrese un ID válido en el campo de búsqueda.",
            )
            return

        try:
            from utils.doc_generation import log_venta_vs_dte

            log_venta_vs_dte(self.manager, venta_id)

            db_path = self.manager.db.conn.execute("PRAGMA database_list").fetchone()[2]
            script = os.path.join(
                os.path.dirname(__file__), "tools", "venta_vs_dte_debug.py"
            )
            popen_kwargs = {}
            creationflag = getattr(subprocess, "CREATE_NEW_CONSOLE", None)
            if creationflag is not None:
                popen_kwargs["creationflags"] = creationflag
            else:
                popen_kwargs["start_new_session"] = True
            subprocess.Popen(
                [sys.executable, script, str(venta_id), "--db", db_path],
                **popen_kwargs,
            )
        except Exception as exc:  # pragma: no cover - debug helper
            QMessageBox.critical(self, "Error", str(exc))

    def _mark_saved(self):
        """Registra el estado actual de la base de datos como guardado.

        Se almacena el número total de cambios realizados en la conexión de
        SQLite para poder detectar posteriormente si el inventario ha sido
        modificado sin guardar.
        """
        self._db_change_counter = self.manager.db.conn.total_changes

    def _load_last_inventory_path(self):
        """Carga la última ruta usada para guardar el inventario.

        Permite que la opción "Guardar rápido" funcione al iniciar la
        aplicación reutilizando el mismo archivo utilizado previamente.
        """
        if not os.path.exists(LAST_INVENTORY_PATH):
            return
        try:
            with open(LAST_INVENTORY_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            logger.warning(
                "No se pudo leer %s para restaurar el último inventario",
                LAST_INVENTORY_PATH,
            )
            return

        ultimo = data.get("ultimo") if isinstance(data, dict) else None
        if ultimo:
            self.ultimo_archivo_json = ultimo

    def closeEvent(self, event):
        if self.manager.db.conn.total_changes == self._db_change_counter:
            detener_firmador()
            event.accept()
            return
        reply = QMessageBox.question(
            self,
            "Salir",
            "¿Desea guardar el inventario antes de salir?",
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
            QMessageBox.Yes,
        )
        if reply == QMessageBox.Yes:
            guardado = self.guardar_rapido(asincrono=False)
            if guardado:
                detener_firmador()
                event.accept()
            else:
                event.ignore()
        elif reply == QMessageBox.No:
            detener_firmador()
            event.accept()
        else:
            event.ignore()
