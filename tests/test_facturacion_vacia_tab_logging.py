import os
import logging
import pytest
from PyQt5.QtWidgets import QApplication, QWidget

from facturacion_vacia_tab import FacturacionVaciaTab


@pytest.fixture(scope="module")
def qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def test_obtener_notas_exception_logged(qt_app, caplog):
    class DummyDB:
        def get_ventas(self):
            return []

        def obtener_notas(self):
            raise RuntimeError("boom")

    class DummyManager:
        def __init__(self):
            self.db = DummyDB()
            self._clientes = []

    parent = QWidget()
    parent.manager = DummyManager()

    with caplog.at_level(logging.ERROR):
        FacturacionVaciaTab(parent)

    assert "Error obteniendo notas" in caplog.text


def test_invalid_date_logged(qt_app, caplog):
    class DummyDB:
        def get_ventas(self):
            return [{"id": 1, "fecha": "bad-date", "cliente_id": 0, "total": 0, "estado": ""}]

        def obtener_notas(self):
            return []

    class DummyManager:
        def __init__(self):
            self.db = DummyDB()
            self._clientes = []

    parent = QWidget()
    parent.manager = DummyManager()

    with caplog.at_level(logging.ERROR):
        FacturacionVaciaTab(parent)

    assert "Fecha inválida" in caplog.text
