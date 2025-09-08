import pytest
from PyQt5.QtWidgets import QApplication, QWidget, QMessageBox

from dialogs import ClienteDialog


class DummyDB:
    def __init__(self, existing_nits=None):
        self._existing = set(existing_nits or [])

    def nit_exists(self, nit, exclude_id=None):
        return nit in self._existing


class DummyParent(QWidget):
    def __init__(self, db):
        super().__init__()
        self.manager = type('M', (), {'db': db})()


def make_dialog(db):
    parent = DummyParent(db)
    dialog = ClienteDialog(parent=parent)
    dialog._parent_ref = parent
    return dialog


@pytest.fixture
def qt_app(monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    app = QApplication.instance() or QApplication([])
    return app


@pytest.mark.parametrize(
    'field,value', [
        ('nrc_edit', ''),
        ('nrc_edit', 'bad'),
        ('nit_edit', ''),
        ('nit_edit', 'bad'),
        ('telefono_edit', ''),
        ('telefono_edit', '12345'),
        ('email_edit', ''),
        ('email_edit', 'bademail'),
    ],
)
def test_invalid_fields(monkeypatch, qt_app, field, value):
    db = DummyDB()
    dialog = make_dialog(db)

    dialog.nombre_edit.setText('Nombre')
    dialog.nombre_comercial_edit.setText('Comercial')
    dialog.nrc_edit.setText('1234567')
    dialog.nit_edit.setText('1234-123456-123-1')
    dialog.telefono_edit.setText('1234-5678')
    dialog.email_edit.setText('test@example.com')

    getattr(dialog, field).setText(value)

    warnings = {}
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a, **k: warnings.setdefault('called', True))

    accepted = {}
    dialog.accept = lambda: accepted.setdefault('called', True)

    dialog._validar_y_accept()

    assert warnings.get('called')
    assert not accepted.get('called')


def test_duplicate_nit(monkeypatch, qt_app):
    db = DummyDB(existing_nits={'1234-123456-123-1'})
    dialog = make_dialog(db)

    dialog.nombre_edit.setText('Nombre')
    dialog.nombre_comercial_edit.setText('Comercial')
    dialog.nrc_edit.setText('1234567')
    dialog.nit_edit.setText('1234-123456-123-1')
    dialog.telefono_edit.setText('1234-5678')
    dialog.email_edit.setText('test@example.com')

    warnings = {}
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a, **k: warnings.setdefault('called', True))

    accepted = {}
    dialog.accept = lambda: accepted.setdefault('called', True)

    dialog._validar_y_accept()

    assert warnings.get('called')
    assert not accepted.get('called')


def test_nombre_comercial_included(monkeypatch, qt_app):
    db = DummyDB()
    dialog = make_dialog(db)

    dialog.nombre_edit.setText('Nombre')
    dialog.nombre_comercial_edit.setText('Comercial')
    dialog.nrc_edit.setText('1234567')
    dialog.nit_edit.setText('1234-123456-123-1')
    dialog.telefono_edit.setText('1234-5678')
    dialog.email_edit.setText('test@example.com')

    warnings = {}
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a, **k: warnings.setdefault('called', True))

    accepted = {}
    dialog.accept = lambda: accepted.setdefault('called', True)

    dialog._validar_y_accept()

    assert not warnings.get('called')
    assert accepted.get('called')
    data = dialog.get_data()
    assert data['nombreComercial'] == 'Comercial'
