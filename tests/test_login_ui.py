import os
import pytest
from PyQt5.QtWidgets import QApplication

os.environ["QT_QPA_PLATFORM"] = "offscreen"


@pytest.fixture
def qt_app():
    app = QApplication.instance() or QApplication([])
    return app


def test_only_new_user_picker_is_used(qt_app):
    import dialogs
    if hasattr(dialogs, "LoginDialog"):
        with pytest.raises(Exception):
            dialogs.LoginDialog()

    from user_picker_dialog import UserPickerDialog
    users = [{"id": 1, "name": "Invitado"}]
    dlg = UserPickerDialog(users)
    assert not dlg.selected_user_ids()
