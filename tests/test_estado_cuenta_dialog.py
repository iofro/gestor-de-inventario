import os
import pytest
from PyQt5.QtWidgets import QApplication, QAbstractItemView, QMessageBox

from dialogs import EstadoCuentaDialog
from db import DB

@pytest.fixture(scope="module")
def qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    return app

def test_dialog_uses_trabajadores_for_vendedores(qt_app):
    db = DB(":memory:")
    db.add_trabajador({"nombre": "Vend1", "codigo": "T1", "es_vendedor": True})
    db.add_trabajador({"nombre": "Vend2", "codigo": "T2", "es_vendedor": True})

    dialog = EstadoCuentaDialog(db)

    assert dialog.vendedor_table.rowCount() == 2
    codes = [dialog.vendedor_table.item(i, 0).text() for i in range(2)]
    assert "T1" in codes and "T2" in codes


def test_dialog_requires_vendedor_selection(qt_app, monkeypatch):
    db = DB(":memory:")
    db.add_trabajador({"nombre": "Vend1", "codigo": "V1", "es_vendedor": True})
    dialog = EstadoCuentaDialog(db)
    dialog.modo_combo.setCurrentIndex(1)
    warnings = {}

    def fake_warning(parent, title, msg):
        warnings["msg"] = msg

    monkeypatch.setattr(QMessageBox, "warning", fake_warning)
    params = dialog._collect_params()
    assert params is None
    assert "ningún vendedor" in warnings.get("msg", "")


def test_dialog_requires_cliente_selection(qt_app, monkeypatch):
    db = DB(":memory:")
    db.add_cliente("Cli", "", "", "", "", "", "", "", "", "")
    dialog = EstadoCuentaDialog(db)
    dialog.modo_combo.setCurrentIndex(0)
    warnings = {}

    def fake_warning(parent, title, msg):
        warnings["msg"] = msg

    monkeypatch.setattr(QMessageBox, "warning", fake_warning)
    params = dialog._collect_params()
    assert params is None
    assert "ningún cliente" in warnings.get("msg", "")


def test_vendedor_table_all_no_selection(qt_app):
    db = DB(":memory:")
    db.add_trabajador({"nombre": "Vend", "codigo": "V1", "es_vendedor": True})
    dialog = EstadoCuentaDialog(db)
    assert dialog.vendedor_table_all.selectionMode() == QAbstractItemView.NoSelection
