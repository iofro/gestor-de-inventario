import pytest
from PyQt5.QtWidgets import QApplication

from user_picker_dialog import UserPickerDialog


@pytest.fixture
def qt_app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    return app


def test_single_selection(qt_app):
    users = [
        {"id": 1, "name": "Alice"},
        {"id": 2, "name": "Bob"},
        {"id": 3, "name": "Carol"},
    ]
    dlg = UserPickerDialog(users)
    # simulate click on first user
    list(dlg._buttons.values())[0].click()
    assert dlg.selected_user_ids() == 1
