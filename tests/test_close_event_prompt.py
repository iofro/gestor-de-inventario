import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest

import inventory_manager as im
import ui_mainwindow
from PyQt5.QtWidgets import QApplication, QMessageBox


class MemoryDB(im.DB):
    def __init__(self):
        super().__init__(db_name=":memory:")


@pytest.fixture(scope="module")
def qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    return app


def test_close_without_changes_does_not_prompt(qt_app, monkeypatch):
    monkeypatch.setattr(im, "DB", MemoryDB)
    window = ui_mainwindow.MainWindow()
    called = False

    def fake_question(*a, **k):
        nonlocal called
        called = True
        return QMessageBox.Yes

    monkeypatch.setattr(ui_mainwindow.QMessageBox, "question", fake_question)
    window.close()
    assert not called


def test_close_with_changes_prompts(qt_app, monkeypatch):
    monkeypatch.setattr(im, "DB", MemoryDB)
    window = ui_mainwindow.MainWindow()
    window.manager.db.add_producto("P1", "C1", None, None, None, 1, 2, 3, 5)
    called = False

    def fake_question(*a, **k):
        nonlocal called
        called = True
        return QMessageBox.No

    monkeypatch.setattr(ui_mainwindow.QMessageBox, "question", fake_question)
    window.close()
    assert called


def test_close_after_save_does_not_prompt(qt_app, monkeypatch):
    monkeypatch.setattr(im, "DB", MemoryDB)
    window = ui_mainwindow.MainWindow()
    window.manager.db.add_producto("P1", "C1", None, None, None, 1, 2, 3, 5)
    window._mark_saved()
    called = False

    def fake_question(*a, **k):
        nonlocal called
        called = True
        return QMessageBox.Yes

    monkeypatch.setattr(ui_mainwindow.QMessageBox, "question", fake_question)
    window.close()
    assert not called

