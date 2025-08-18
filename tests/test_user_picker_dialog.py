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
    assert not dlg.ok_btn.isEnabled()
    cards = list(dlg._cards.values())
    cards[0].click()
    assert dlg.selected_user_ids() == 1
    assert dlg.ok_btn.isEnabled()
    cards[1].click()
    assert dlg.selected_user_ids() == 2
    assert dlg.ok_btn.isEnabled()
    cards[1].click()
    assert dlg.selected_user_ids() is None
    assert not dlg.ok_btn.isEnabled()


def test_multi_selection(qt_app):
    users = [
        {"id": 1, "name": "Alice"},
        {"id": 2, "name": "Bob"},
        {"id": 3, "name": "Carol"},
    ]
    dlg = UserPickerDialog(users, multi_select=True)
    cards = list(dlg._cards.values())
    cards[0].click()
    cards[1].click()
    assert set(dlg.selected_user_ids()) == {1, 2}
    assert dlg.ok_btn.isEnabled()

