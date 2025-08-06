import os
import pytest
from PyQt5.QtWidgets import QApplication, QWidget, QMessageBox

from dialogs import TrabajadorDialog


class DummyDB:
    def __init__(self, trabajadores=None):
        self._trabajadores = trabajadores or []

    def get_trabajadores(self, solo_vendedores=False, area=None, search=""):
        return self._trabajadores


class DummyParent(QWidget):
    def __init__(self, db):
        super().__init__()
        self.manager = type('M', (), {'db': db})()


def make_dialog(db, trabajador=None):
    parent = DummyParent(db)
    dialog = TrabajadorDialog(trabajador=trabajador, parent=parent)
    dialog._parent_ref = parent
    return dialog


@pytest.fixture
def qt_app(monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    app = QApplication.instance() or QApplication([])
    return app


def test_missing_fields(monkeypatch, qt_app):
    db = DummyDB()
    dialog = make_dialog(db)
    dialog.codigo.setText('')
    dialog.nombre.setText('Nombre')
    dialog.nit.setText('1234-123456-123-1')
    dialog.email.setText('test@example.com')

    accepted = {}
    dialog.accept = lambda: accepted.setdefault('called', True)
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a, **k: None)

    dialog._validar_y_accept()
    assert not accepted.get('called')


def test_invalid_nit_email(monkeypatch, qt_app):
    db = DummyDB()
    dialog = make_dialog(db)
    dialog.codigo.setText('T001')
    dialog.nombre.setText('Nombre')
    dialog.nit.setText('invalid')
    dialog.email.setText('bademail')

    accepted = {}
    dialog.accept = lambda: accepted.setdefault('called', True)
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a, **k: None)

    dialog._validar_y_accept()
    assert not accepted.get('called')


def test_duplicate_codigo(monkeypatch, qt_app):
    existing = {'id': 1, 'codigo': 'T001'}
    db = DummyDB([existing])
    dialog = make_dialog(db)
    dialog.codigo.setText('T001')
    dialog.nombre.setText('Nombre')
    dialog.nit.setText('1234-123456-123-1')
    dialog.email.setText('test@example.com')

    accepted = {}
    dialog.accept = lambda: accepted.setdefault('called', True)
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a, **k: None)

    dialog._validar_y_accept()
    assert not accepted.get('called')
