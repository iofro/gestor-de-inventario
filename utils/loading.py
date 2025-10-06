from __future__ import annotations

"""Utility widgets to display a lightweight loading indicator."""

from contextlib import contextmanager

from PyQt5.QtCore import QPointF, QTimer, Qt, QSize
from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import QApplication, QDialog, QVBoxLayout, QLabel, QSizePolicy, QWidget


class _SpinnerWidget(QWidget):
    """Simple circular spinner drawn with a ``QPainter``."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._line_count = 12
        self._line_length = 12
        self._line_width = 4
        self._inner_radius = 10
        self._counter = 0

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._rotate)
        self._timer.start(80)

        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def sizeHint(self):  # noqa: D401 - Qt API compatibility
        diameter = (self._inner_radius + self._line_length + self._line_width) * 2
        return QSize(diameter, diameter)

    def minimumSizeHint(self):  # noqa: D401 - Qt API compatibility
        return self.sizeHint()

    def _rotate(self) -> None:
        self._counter = (self._counter + 1) % self._line_count
        self.update()

    def stop(self) -> None:
        self._timer.stop()

    def paintEvent(self, event):  # noqa: D401 - Qt API compatibility
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        painter.translate(self.rect().center())

        color = QColor(33, 150, 243)
        for i in range(self._line_count):
            painter.save()
            rotate_angle = 360 * (i + self._counter) / self._line_count
            painter.rotate(rotate_angle)
            painter.translate(self._inner_radius, 0)
            alpha = int(255 * (i + 1) / self._line_count)
            color.setAlpha(alpha)
            pen = QPen(color, self._line_width, Qt.SolidLine, Qt.RoundCap)
            painter.setPen(pen)
            painter.drawLine(QPointF(0, 0), QPointF(self._line_length, 0))
            painter.restore()

        painter.end()


class LoadingDialog(QDialog):
    """Small frameless dialog with a spinner and status message."""

    def __init__(self, message: str, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.Dialog | Qt.FramelessWindowHint)
        self.setModal(True)
        self.setWindowModality(Qt.ApplicationModal)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setObjectName("LoadingDialog")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        self._spinner = _SpinnerWidget(self)
        layout.addWidget(self._spinner, 0, Qt.AlignCenter)

        self._label = QLabel(message, self)
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setStyleSheet("color: #1a1a1a; font-weight: 500;")
        self._label.setWordWrap(True)
        layout.addWidget(self._label, 0, Qt.AlignCenter)

        self.setStyleSheet(
            "#LoadingDialog {"
            "  background: rgba(255, 255, 255, 235);"
            "  border: 1px solid rgba(0, 0, 0, 40);"
            "  border-radius: 12px;"
            "}"
        )

        self.adjustSize()

    def set_message(self, message: str) -> None:
        self._label.setText(message)
        self.adjustSize()

    def finish(self) -> None:
        self.close()
        self.deleteLater()

    def closeEvent(self, event):  # noqa: D401 - Qt API compatibility
        self._spinner.stop()
        super().closeEvent(event)

    def showEvent(self, event):  # noqa: D401 - Qt API compatibility
        super().showEvent(event)
        parent = self.parentWidget()
        window = parent.window() if parent else None
        target = window or parent
        if target:
            rect = target.frameGeometry()
            self.move(
                rect.center().x() - self.width() // 2,
                rect.center().y() - self.height() // 2,
            )


def create_loading_dialog(parent: QWidget | None, message: str) -> LoadingDialog:
    """Create and display a loading dialog with the provided message."""

    dialog = LoadingDialog(message, parent)
    dialog.show()
    QApplication.processEvents()
    return dialog


@contextmanager
def loading_dialog(parent: QWidget | None, message: str):
    """Context manager that displays a loading dialog while running a block."""

    dialog = create_loading_dialog(parent, message)
    try:
        yield dialog
    finally:
        dialog.finish()
