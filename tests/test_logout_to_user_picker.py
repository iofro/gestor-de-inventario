import os
import pytest
from PyQt5.QtWidgets import QApplication, QMessageBox, QDialog

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import ui_mainwindow
import db
import user_picker_dialog


@pytest.fixture
def qt_app():
    return QApplication.instance() or QApplication([])


def test_logout_opens_user_picker(qt_app, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)

    class DummyDB:
        def get_users(self):
            return [{"id": 1, "username": "user", "role": "guest"}]
        def get_user(self, user_id):
            return {"id": 1, "username": "user", "role": "guest"}
        def authenticate(self, username, password):
            return True
    monkeypatch.setattr(db, "DB", lambda: DummyDB())

    class DummyPicker:
        def __init__(self, *args, **kwargs):
            self.exec_called = False
        def exec_(self):
            self.exec_called = True
            return QDialog.Rejected
        def selected_user_ids(self):
            return []
    picker = DummyPicker()
    monkeypatch.setattr(user_picker_dialog, "UserPickerDialog", lambda *a, **k: picker)

    monkeypatch.setattr(QApplication, "quit", lambda *a, **k: None)

    win = ui_mainwindow.MainWindow({"username": "admin", "role": "admin"})
    win.cerrar_sesion()

    assert picker.exec_called
