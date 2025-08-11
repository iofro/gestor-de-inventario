from typing import List, Dict, Optional, Union
import os

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QPixmap, QColor, QPainter
from PyQt5.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QGridLayout,
    QLabel,
    QWidget,
    QHBoxLayout,
    QApplication,
    QGraphicsDropShadowEffect,
    QFrame,
    QPushButton,
)

BRAND_COLOR = "#0EA5E9"
BACKGROUND_COLOR = "#F7FAFC"
TEXT_COLOR = "#1F2937"

DEFAULT_AVATAR = os.path.join(os.path.dirname(__file__), "avatar.jpg")


def square_avatar(path: str, size: int) -> QPixmap:
    """Load an image, crop it to a square and scale to ``size`` pixels."""

    pix = QPixmap()
    if path and os.path.exists(path):
        pix.load(path)

    if pix.isNull():
        pix = QPixmap(size, size)
        pix.fill(QColor("#E5E7EB"))
        painter = QPainter(pix)
        painter.setPen(QColor("#374151"))
        font = painter.font()
        font.setBold(True)
        font.setPointSize(int(size * 0.5))
        painter.setFont(font)
        painter.drawText(pix.rect(), Qt.AlignCenter, "?")
        painter.end()
        return pix

    if pix.width() != pix.height():
        side = min(pix.width(), pix.height())
        x = (pix.width() - side) // 2
        y = (pix.height() - side) // 2
        pix = pix.copy(x, y, side, side)

    return pix.scaled(size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)


class UserCard(QFrame):
    clicked = pyqtSignal(bool)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._checked = False
        self.setProperty("class", "user-card")
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)

    def mousePressEvent(self, event):  # type: ignore[override]
        self.setChecked(not self._checked)
        self.clicked.emit(self._checked)
        if event is not None:
            super().mousePressEvent(event)

    def setChecked(self, checked: bool):
        self._checked = checked
        self.setProperty("checked", checked)
        self.style().unpolish(self)
        self.style().polish(self)

    def isChecked(self) -> bool:
        return self._checked

    def click(self):
        self.mousePressEvent(None)  # type: ignore[arg-type]


class UserPickerDialog(QDialog):
    def __init__(self, users: List[Dict], multi_select: bool = False, parent: Optional[QWidget] = None):
        QApplication.setStyle("Fusion")
        super().__init__(parent)
        self.users = users
        self.multi_select = multi_select
        self._cards: Dict[Union[int, str], UserCard] = {}
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
            QFrame.user-card {{
                background-color: {BACKGROUND_COLOR};
                color: {TEXT_COLOR};
                border: 1px solid {BRAND_COLOR};
                border-radius: 16px;
                padding: 24px;
            }}
            QFrame.user-card:hover {{
                background-color: #E0F2FE;
                border: 2px solid #7DD3FC;
            }}
            QFrame.user-card[checked="true"] {{
                border: 2px solid {BRAND_COLOR};
                background-color: #BAE6FD;
            }}
            QLabel.user-name {{
                font-weight: bold;
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

        grid = QGridLayout()
        grid.setSpacing(24)
        columns = max(1, min(len(self.users), 3))

        for index, user in enumerate(self.users):
            card = self._create_user_card(user)
            shadow = QGraphicsDropShadowEffect(card)
            shadow.setBlurRadius(15)
            shadow.setOffset(0, 3)
            shadow.setColor(QColor(0, 0, 0, 80))
            card.setGraphicsEffect(shadow)
            self._cards[user.get("id")] = card
            row = index // columns
            col = index % columns
            grid.addWidget(card, row, col)

        main_layout.addLayout(grid)

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

    def _create_user_card(self, user: Dict) -> UserCard:
        card = UserCard()

        layout = QVBoxLayout(card)
        layout.setAlignment(Qt.AlignCenter)

        path = (
            user.get("avatar")
            or user.get("photo")
            or user.get("image")
            or user.get("avatar_path")
            or DEFAULT_AVATAR
        )
        avatar = QLabel()
        pix = square_avatar(path, 96)
        avatar.setPixmap(pix)
        avatar.setFixedSize(pix.size())
        avatar.setAlignment(Qt.AlignCenter)

        name = QLabel(user.get("name", ""))
        name.setProperty("class", "user-name")
        name.setAlignment(Qt.AlignCenter)

        subtitle_text = user.get("subtitle")
        layout.addWidget(avatar)
        layout.addWidget(name)
        if subtitle_text:
            subtitle = QLabel(str(subtitle_text))
            subtitle.setAlignment(Qt.AlignCenter)
            layout.addWidget(subtitle)

        card.clicked.connect(lambda checked, c=card: self._on_card_clicked(c))
        return card

    # --------------------------- BEHAVIOR ----------------------------------
    def _on_card_clicked(self, card: UserCard):
        if not self.multi_select and card.isChecked():
            for other in self._cards.values():
                if other is not card:
                    other.setChecked(False)

    def selected_user_ids(self):
        if self.multi_select:
            return [uid for uid, card in self._cards.items() if card.isChecked()]
        for uid, card in self._cards.items():
            if card.isChecked():
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
