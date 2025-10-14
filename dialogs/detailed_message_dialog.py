"""Utility dialog with expandable error details."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon, QTextOption
from PyQt5.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QLabel,
    QPushButton,
    QPlainTextEdit,
)
from typing import Optional


class DetailedMessageDialog(QDialog):
    """Message dialog that exposes an expandable details panel."""

    def __init__(
        self,
        *,
        title: str,
        text: str,
        details: str | None = None,
        icon: QIcon | None = None,
        parent=None,
        buttons: QDialogButtonBox.StandardButtons = QDialogButtonBox.Ok,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self._toggle_button: Optional[QPushButton] = None
        self._details_widget: Optional[QPlainTextEdit] = None

        layout = QGridLayout(self)
        row = 0

        if icon is not None:
            icon_label = QLabel(self)
            icon_label.setPixmap(icon.pixmap(48, 48))
            icon_label.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
            layout.addWidget(icon_label, row, 0, 1, 1)
        else:
            layout.setColumnStretch(0, 0)

        text_label = QLabel(text, self)
        text_label.setWordWrap(True)
        text_label.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        layout.addWidget(text_label, row, 1, 1, 2)
        row += 1

        if details:
            self._toggle_button = QPushButton("Ver detalles", self)
            self._toggle_button.setCheckable(True)
            self._toggle_button.setChecked(False)
            self._toggle_button.toggled.connect(self._on_toggle)
            layout.addWidget(self._toggle_button, row, 1, 1, 2, alignment=Qt.AlignLeft)
            row += 1

            self._details_widget = QPlainTextEdit(self)
            self._details_widget.setReadOnly(True)
            self._details_widget.setPlainText(details)
            self._details_widget.hide()
            self._details_widget.setMinimumHeight(180)
            self._details_widget.setLineWrapMode(QPlainTextEdit.NoWrap)
            self._details_widget.setWordWrapMode(QTextOption.NoWrap)
            layout.addWidget(self._details_widget, row, 0, 1, 3)
            row += 1

        button_box = QDialogButtonBox(buttons, parent=self)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box, row, 0, 1, 3)

        self.resize(self.sizeHint())

    def _on_toggle(self, checked: bool) -> None:
        if not self._details_widget or not self._toggle_button:
            return
        if checked:
            self._toggle_button.setText("Ocultar detalles")
            self._details_widget.show()
        else:
            self._toggle_button.setText("Ver detalles")
            self._details_widget.hide()


__all__ = ["DetailedMessageDialog"]
