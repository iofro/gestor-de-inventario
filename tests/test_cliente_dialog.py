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
    "field,value",
    [
        ("nrc_edit", "bad"),
        ("nit_edit", "bad"),
        ("nit_edit", "1234-123456-123-1"),
        ("dui_edit", "bad"),
        ("telefono_edit", "12345"),
        ("email_edit", "bademail"),
    ],
)
def test_invalid_fields(monkeypatch, qt_app, field, value):
    db = DummyDB()
    dialog = make_dialog(db)

    getattr(dialog, field).setText(value)

    warnings = {}
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a, **k: warnings.setdefault('called', True))

    accepted = {}
    dialog.accept = lambda: accepted.setdefault('called', True)

    dialog._validar_y_accept()

    assert warnings.get('called')
    assert not accepted.get('called')


def test_nit_max_length(qt_app):
    db = DummyDB()
    dialog = make_dialog(db)
    dialog.nit_edit.setText("1" * 15)
    assert dialog.nit_edit.text() == "1" * 14


def test_dui_max_length(qt_app):
    db = DummyDB()
    dialog = make_dialog(db)
    dialog.dui_edit.insert("1" * 10)
    assert dialog.dui_edit.text() == "1" * 9


def test_dui_only_digits(qt_app):
    db = DummyDB()
    dialog = make_dialog(db)
    dialog.dui_edit.insert("abcd")
    assert dialog.dui_edit.text() == ""


def test_optional_fields(monkeypatch, qt_app):
    db = DummyDB()
    dialog = make_dialog(db)

    warnings = {}
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a, **k: warnings.setdefault('called', True))

    accepted = {}
    dialog.accept = lambda: accepted.setdefault('called', True)

    dialog._validar_y_accept()

    assert not warnings.get('called')
    assert accepted.get('called')


def test_duplicate_nit(monkeypatch, qt_app):
    db = DummyDB(existing_nits={"12341234561234"})
    dialog = make_dialog(db)

    dialog.nit_edit.setText("12341234561234")

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

    dialog.nombre_comercial_edit.setText('Comercial')

    warnings = {}
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a, **k: warnings.setdefault('called', True))

    accepted = {}
    dialog.accept = lambda: accepted.setdefault('called', True)

    dialog._validar_y_accept()

    assert not warnings.get('called')
    assert accepted.get('called')
    data = dialog.get_data()
    assert data['nombreComercial'] == 'Comercial'
