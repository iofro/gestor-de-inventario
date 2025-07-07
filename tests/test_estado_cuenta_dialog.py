import os
import pytest
from PyQt5.QtWidgets import QApplication

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
