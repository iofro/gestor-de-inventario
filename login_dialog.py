from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QComboBox,
    QPushButton,
    QToolButton,
    QWidget,
)


class LoginDialog(QDialog):
    """Pantalla de inicio de sesión moderna y centrada."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setModal(True)
        self.setFixedSize(500, 650)

        self._build_ui()
        self._apply_styles()

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.background_frame = QFrame()
        self.background_frame.setObjectName("LoginBackground")

        background_layout = QGridLayout(self.background_frame)
        background_layout.setContentsMargins(24, 24, 24, 24)
        background_layout.setSpacing(0)
        background_layout.setRowStretch(0, 1)
        background_layout.setRowStretch(2, 1)
        background_layout.setColumnStretch(0, 1)
        background_layout.setColumnStretch(2, 1)

        card = QFrame()
        card.setObjectName("LoginCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(40, 36, 40, 36)
        card_layout.setSpacing(16)

        close_row = QHBoxLayout()
        close_row.setContentsMargins(0, 0, 0, 0)
        close_row.setSpacing(0)
        close_row.addStretch(1)
        self.btn_close = QToolButton()
        self.btn_close.setObjectName("CloseButton")
        self.btn_close.setText("✕")
        self.btn_close.setCursor(Qt.PointingHandCursor)
        self.btn_close.clicked.connect(self.reject)
        close_row.addWidget(self.btn_close, 0, Qt.AlignRight)
        card_layout.addLayout(close_row)

        self.brand_label = QLabel("INVENTARIO PRO")
        self.brand_label.setObjectName("BrandLabel")
        self.brand_label.setAlignment(Qt.AlignCenter)

        self.title_label = QLabel("Iniciar Sesión")
        self.title_label.setObjectName("LoginTitle")
        self.title_label.setAlignment(Qt.AlignCenter)

        card_layout.addWidget(self.brand_label)
        card_layout.addWidget(self.title_label)
        card_layout.addSpacing(12)

        user_label = QLabel("Usuario")
        self.user_combo = QComboBox()
        self.user_combo.addItems(["admin", "usuario"])
        self.user_combo.setMinimumHeight(44)

        card_layout.addWidget(user_label)
        card_layout.addWidget(self.user_combo)
        card_layout.addSpacing(12)

        password_label = QLabel("Contraseña")
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setPlaceholderText("********")
        self.password_input.setMinimumHeight(44)

        self.toggle_password_btn = QToolButton()
        self.toggle_password_btn.setObjectName("PasswordToggle")
        self.toggle_password_btn.setCheckable(True)
        self.toggle_password_btn.setCursor(Qt.PointingHandCursor)
        self.toggle_password_btn.setText("Mostrar")
        self.toggle_password_btn.clicked.connect(self._toggle_password_visibility)

        password_row = QWidget()
        password_layout = QHBoxLayout(password_row)
        password_layout.setContentsMargins(0, 0, 0, 0)
        password_layout.setSpacing(8)
        password_layout.addWidget(self.password_input)
        password_layout.addWidget(self.toggle_password_btn)

        card_layout.addWidget(password_label)
        card_layout.addWidget(password_row)
        card_layout.addSpacing(20)

        buttons_row = QHBoxLayout()
        buttons_row.setSpacing(10)
        self.btn_cancel = QPushButton("Cancelar")
        self.btn_cancel.setObjectName("SecondaryButton")
        self.btn_cancel.setMinimumHeight(48)
        self.btn_cancel.setCursor(Qt.PointingHandCursor)
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_login = QPushButton("Entrar")
        self.btn_login.setObjectName("PrimaryButton")
        self.btn_login.setMinimumHeight(50)
        self.btn_login.setCursor(Qt.PointingHandCursor)
        self.btn_login.clicked.connect(self.accept)
        buttons_row.addWidget(self.btn_cancel)
        buttons_row.addWidget(self.btn_login)
        card_layout.addLayout(buttons_row)

        card_layout.addSpacing(10)

        self.forgot_password_label = QLabel('<a href="#">Olvidé mi contraseña</a>')
        self.forgot_password_label.setObjectName("ForgotPassword")
        self.forgot_password_label.setAlignment(Qt.AlignCenter)
        self.forgot_password_label.setOpenExternalLinks(False)
        card_layout.addWidget(self.forgot_password_label)

        background_layout.addWidget(card, 1, 1, Qt.AlignCenter)
        main_layout.addWidget(self.background_frame)

    def _toggle_password_visibility(self, checked: bool) -> None:
        self.password_input.setEchoMode(
            QLineEdit.Normal if checked else QLineEdit.Password
        )
        self.toggle_password_btn.setText("Ocultar" if checked else "Mostrar")

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
/* Fondo Degradado Suave */
QFrame#LoginBackground {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #E0F2FE, stop:1 #F0F9FF);
    border-radius: 12px;
}

/* Tarjeta Blanca Central con Sombra */
QFrame#LoginCard {
    background-color: #FFFFFF;
    border-radius: 16px;
    border: 1px solid #F1F5F9;
    border-bottom: 3px solid #E2E8F0;
    border-right: 1px solid #E2E8F0;
}

/* Etiquetas */
QLabel {
    color: #475569;
    font-size: 14px;
}
QLabel#BrandLabel {
    color: #2563EB;
    font-weight: 700;
    letter-spacing: 1px;
    font-size: 13px;
}
QLabel#LoginTitle {
    color: #0F172A;
    font-size: 24px;
    font-weight: bold;
}
QLabel#ForgotPassword {
    color: #2563EB;
    font-size: 12px;
}
QLabel#ForgotPassword:hover {
    text-decoration: underline;
}

/* Inputs y Combobox Modernos */
QComboBox, QLineEdit {
    background-color: #F8FAFC;
    border: 1px solid #CBD5E1;
    border-radius: 8px;
    padding: 12px;
    font-size: 14px;
    color: #1E293B;
}
QComboBox::drop-down {
    border: none;
}
QLineEdit:focus, QComboBox:focus {
    border: 2px solid #3B82F6;
    background-color: #FFFFFF;
}

/* Botón Primario Grande */
QPushButton#PrimaryButton {
    background-color: #2563EB;
    color: white;
    border: none;
    border-radius: 8px;
    padding: 14px;
    font-size: 16px;
    font-weight: bold;
}
QPushButton#PrimaryButton:hover {
    background-color: #1D4ED8;
}
QPushButton#PrimaryButton:pressed {
    background-color: #1E40AF;
}
QPushButton#SecondaryButton {
    background-color: #FFFFFF;
    color: #0F172A;
    border: 1px solid #CBD5E1;
    border-radius: 8px;
    padding: 14px;
    font-size: 15px;
    font-weight: 600;
}
QPushButton#SecondaryButton:hover {
    background-color: #F8FAFC;
    border: 1px solid #94A3B8;
}

QToolButton#CloseButton {
    background: transparent;
    border: none;
    color: #9CA3AF;
    font-size: 16px;
    font-weight: 700;
    padding: 4px;
}
QToolButton#CloseButton:hover {
    color: #EF4444;
}

/* Botón de mostrar contraseña */
QToolButton#PasswordToggle {
    background: #E2E8F0;
    border: 1px solid #CBD5E1;
    border-radius: 8px;
    padding: 10px 12px;
    font-size: 12px;
    color: #0F172A;
}
QToolButton#PasswordToggle:checked {
    background: #DBEAFE;
    border: 1px solid #2563EB;
    color: #1E3A8A;
}
"""
        )
