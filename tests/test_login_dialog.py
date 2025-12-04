import os

import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QLineEdit

from login_dialog import LoginDialog

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def dialog(qtbot):
    dlg = LoginDialog()
    qtbot.addWidget(dlg)
    return dlg


def test_initialization_ui(dialog):
    assert dialog is not None
    assert hasattr(dialog, "brand_label")
    assert hasattr(dialog, "title_label")
    assert hasattr(dialog, "user_combo")
    assert hasattr(dialog, "password_input")
    assert hasattr(dialog, "btn_login")
    assert dialog.brand_label.text() == "INVENTARIO PRO"
    assert dialog.title_label.text() == "Iniciar Sesión"


def test_user_selection(dialog):
    expected_users = ["admin", "usuario"]
    assert [dialog.user_combo.itemText(i) for i in range(dialog.user_combo.count())] == expected_users
    index = dialog.user_combo.findText("admin")
    dialog.user_combo.setCurrentIndex(index)
    assert dialog.user_combo.currentText() == "admin"


def test_password_visibility_toggle(dialog, qtbot):
    dialog.password_input.setText("secreto")
    assert dialog.password_input.echoMode() == QLineEdit.Password

    qtbot.mouseClick(dialog.toggle_password_btn, Qt.LeftButton)
    assert dialog.password_input.echoMode() == QLineEdit.Normal
    assert dialog.toggle_password_btn.text() == "Ocultar"

    qtbot.mouseClick(dialog.toggle_password_btn, Qt.LeftButton)
    assert dialog.password_input.echoMode() == QLineEdit.Password
    assert dialog.toggle_password_btn.text() == "Mostrar"


def test_login_button_emits_accepted(dialog, qtbot):
    with qtbot.waitSignal(dialog.accepted, timeout=1000):
        qtbot.mouseClick(dialog.btn_login, Qt.LeftButton)
