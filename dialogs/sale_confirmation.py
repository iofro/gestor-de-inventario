from PyQt5.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
)
from PyQt5.QtCore import Qt


class SaleConfirmationDialog(QDialog):
    RESULT_SEND_DTE = 10
    RESULT_SAVE_DTE = 20
    RESULT_SAVE_LOCAL = 30

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Finalizar Venta")
        self.setModal(True)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 16)
        layout.setSpacing(12)

        title = QLabel("Finalizar Venta", self)
        title.setStyleSheet("font-size: 18px; font-weight: 700; color: #0f172a;")
        layout.addWidget(title)

        subtitle = QLabel(
            "Elige cómo deseas finalizar: generar y enviar el DTE, guardarlo sin enviar o solo registrar la venta.",
            self,
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: #475569;")
        layout.addWidget(subtitle)

        btn_send = QPushButton("✅ Guardar y Enviar DTE (Recomendado)", self)
        btn_send.setStyleSheet(
            """
            QPushButton {
                background-color: #16a34a;
                color: white;
                padding: 12px;
                border-radius: 8px;
                font-weight: 600;
                font-size: 14px;
            }
            QPushButton:hover { background-color: #15803d; }
            """
        )
        btn_send.clicked.connect(lambda: self.done(self.RESULT_SEND_DTE))
        layout.addWidget(btn_send)

        separator = QFrame(self)
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        layout.addWidget(separator)

        extra_label = QLabel("Opciones Adicionales", self)
        extra_label.setStyleSheet("color: #6b7280; font-weight: 600;")
        layout.addWidget(extra_label)

        secondary = QHBoxLayout()
        secondary.setSpacing(10)

        btn_save_dte = QPushButton("📄 Guardar sin Enviar\n(Se genera DTE)", self)
        btn_save_dte.setStyleSheet(
            """
            QPushButton {
                border: 1px solid #2563eb;
                color: #2563eb;
                background: transparent;
                padding: 10px;
                border-radius: 8px;
                font-weight: 600;
            }
            QPushButton:hover { background-color: rgba(37,99,235,0.08); }
            """
        )
        btn_save_dte.clicked.connect(lambda: self.done(self.RESULT_SAVE_DTE))
        secondary.addWidget(btn_save_dte)

        btn_save_local = QPushButton("💾 Solo Registrar Venta Local\n(Sin DTE)", self)
        btn_save_local.setStyleSheet(
            """
            QPushButton {
                border: 1px solid #f97316;
                color: #f97316;
                background: transparent;
                padding: 10px;
                border-radius: 8px;
                font-weight: 600;
            }
            QPushButton:hover { background-color: rgba(249,115,22,0.08); }
            """
        )
        btn_save_local.clicked.connect(lambda: self.done(self.RESULT_SAVE_LOCAL))
        secondary.addWidget(btn_save_local)

        layout.addLayout(secondary)

        cancel = QPushButton("Cancelar", self)
        cancel.setFlat(True)
        cancel.setStyleSheet("color: #6b7280; font-weight: 500;")
        cancel.clicked.connect(self.reject)
        layout.addWidget(cancel, alignment=Qt.AlignRight)
