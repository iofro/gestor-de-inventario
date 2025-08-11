from typing import List, Dict, Optional, Union
import os

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap, QIcon, QPainter, QPainterPath, QColor
from PyQt5.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QGridLayout,
    QPushButton,
    QLabel,
    QWidget,
    QHBoxLayout,
    QApplication,
    QStyle,
    QGraphicsDropShadowEffect,
)

BRAND_COLOR = "#0EA5E9"
BACKGROUND_COLOR = "#F7FAFC"
TEXT_COLOR = "#1F2937"

DEFAULT_AVATAR = os.path.join(os.path.dirname(__file__), "avatar.jpg")


def _load_avatar(user: Dict, size: int = 96) -> QPixmap:
    """Return a pixmap for the user avatar or the default avatar image."""
    path = (
        user.get("avatar")
        or user.get("photo")
        or user.get("image")
        or user.get("avatar_path")
        or DEFAULT_AVATAR
    )
    pix = QPixmap()
    if path:
        pix.load(path)
    if pix.isNull():
        # Fallback to a themed icon that resembles a person
        icon = QIcon.fromTheme("user")
        if icon.isNull():
            icon = QApplication.style().standardIcon(QStyle.SP_FileIcon)
        pix = icon.pixmap(size, size)

    pix = pix.scaled(size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    # make circular
    result = QPixmap(size, size)
    result.fill(Qt.transparent)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.Antialiasing, True)
    path = QPainterPath()
    path.addEllipse(0, 0, size, size)
    painter.setClipPath(path)
    painter.drawPixmap(0, 0, pix)
    painter.end()
    return result


class UserPickerDialog(QDialog):
    def __init__(self, users: List[Dict], multi_select: bool = False, parent: Optional[QWidget] = None):
        QApplication.setStyle("Fusion")
        super().__init__(parent)
        self.users = users
        self.multi_select = multi_select
        self._buttons: Dict[Union[int, str], QPushButton] = {}
        self.setWindowTitle("Seleccionar Usuario")
        self._build_ui()
        # Make the dialog a bit larger for easier interaction
        self.setMinimumSize(600, 400)

    # ---------------------------- UI SETUP ---------------------------------
    def _build_ui(self):
        self.setStyleSheet(
            f"""
            QDialog {{
                background-color: {BACKGROUND_COLOR};
                color: {TEXT_COLOR};
            }}
            QPushButton#CardButton {{
                background-color: {BACKGROUND_COLOR};
                color: {TEXT_COLOR};
                border: 1px solid {BRAND_COLOR};
                border-radius: 16px;
                padding: 24px;
            }}
            QPushButton#CardButton:hover {{
                background-color: #E0F2FE;
            }}
            QPushButton#CardButton:checked {{
                border: 2px solid {BRAND_COLOR};
                background-color: #BAE6FD;
            }}
            QPushButton#PrimaryButton {{
                background-color: {BRAND_COLOR};
                color: white;
                border: none;
                padding: 6px 12px;
                border-radius: 6px;
            }}
            QPushButton#PrimaryButton:hover {{
                background-color: #0284C7;
            }}
            QPushButton#PrimaryButton:pressed {{
                background-color: #0369A1;
            }}
            QPushButton#SecondaryButton {{
                background-color: transparent;
                color: {TEXT_COLOR};
                border: 1px solid #E2E8F0;
                padding: 6px 12px;
                border-radius: 6px;
            }}
            QPushButton#SecondaryButton:hover {{
                background-color: #EDF2F7;
            }}
            """
        )

        main_layout = QVBoxLayout(self)

        grid_widget = QWidget(self)
        grid = QGridLayout(grid_widget)
        grid.setSpacing(24)
        columns = max(1, min(len(self.users), 3))

        for index, user in enumerate(self.users):
            btn = self._create_user_button(user)
            shadow = QGraphicsDropShadowEffect(btn)
            shadow.setBlurRadius(15)
            shadow.setOffset(0, 3)
            shadow.setColor(QColor(0, 0, 0, 80))
            btn.setGraphicsEffect(shadow)
            self._buttons[user.get("id")] = btn
            row = index // columns
            col = index % columns
            grid.addWidget(btn, row, col)

        main_layout.addWidget(grid_widget)

        # Bottom buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        cancel_btn = QPushButton("Cancelar")
        cancel_btn.setObjectName("SecondaryButton")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        ok_btn = QPushButton("Aceptar")
        ok_btn.setObjectName("PrimaryButton")
        ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(ok_btn)
        main_layout.addLayout(btn_layout)

    def _create_user_button(self, user: Dict) -> QPushButton:
        btn = QPushButton()
        btn.setObjectName("CardButton")
        btn.setCheckable(True)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFocusPolicy(Qt.StrongFocus)

        layout = QVBoxLayout(btn)
        layout.setAlignment(Qt.AlignCenter)

        avatar = QLabel()
        pix = _load_avatar(user)
        avatar.setPixmap(pix)
        avatar.setFixedSize(pix.size())
        avatar.setStyleSheet(f"border-radius: {pix.width() // 2}px;")
        avatar.setAlignment(Qt.AlignCenter)

        name = QLabel(user.get("name", ""))
        name.setStyleSheet("font-weight: bold;")
        name.setAlignment(Qt.AlignCenter)

        subtitle_text = user.get("subtitle")
        if subtitle_text:
            subtitle = QLabel(str(subtitle_text))
            subtitle.setAlignment(Qt.AlignCenter)
            layout.addWidget(avatar)
            layout.addWidget(name)
            layout.addWidget(subtitle)
        else:
            layout.addWidget(avatar)
            layout.addWidget(name)

        btn.clicked.connect(lambda checked, b=btn: self._on_card_clicked(b))
        return btn

    # --------------------------- BEHAVIOR ----------------------------------
    def _on_card_clicked(self, button: QPushButton):
        if not self.multi_select and button.isChecked():
            for other in self._buttons.values():
                if other is not button:
                    other.setChecked(False)

    def selected_user_ids(self):
        if self.multi_select:
            return [uid for uid, btn in self._buttons.items() if btn.isChecked()]
        for uid, btn in self._buttons.items():
            if btn.isChecked():
                return uid
        return None


# ----------------------------- Helper API ---------------------------------

def pick_user(parent: QWidget, users: List[Dict], multi_select: bool = False):
    QApplication.setStyle("Fusion")
    dialog = UserPickerDialog(users, multi_select=multi_select, parent=parent)
    result = dialog.exec_()
    if result == QDialog.Accepted:
        return dialog.selected_user_ids()
    return [] if multi_select else None
