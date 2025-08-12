import os
import pytest
from PyQt5.QtWidgets import QApplication

os.environ["QT_QPA_PLATFORM"] = "offscreen"


@pytest.fixture
def qt_app():
    app = QApplication.instance() or QApplication([])
    return app


def test_fetch_token_uses_credentials_dialog(qt_app, monkeypatch):
    import dialogs

    captured = {}

    def fake_prompt(parent, user, password):
        captured["parent"] = parent
        return "nit", "pwd"

    monkeypatch.setattr(dialogs, "prompt_auth_credentials", fake_prompt)

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"status": "OK", "body": {"token": "tok123"}}

    def fake_post(url, data, timeout):
        captured["url"] = url
        captured["data"] = data
        return FakeResp()

    monkeypatch.setattr(dialogs.requests, "post", fake_post)

    dlg = dialogs.DTEConfigDialog()
    dlg.auth_url.setText("http://example.com")
    dlg._fetch_token()

    assert captured["parent"] is dlg
    assert captured["data"] == {"user": "nit", "pwd": "pwd"}
    assert dlg.token_hacienda.text() == "tok123"
