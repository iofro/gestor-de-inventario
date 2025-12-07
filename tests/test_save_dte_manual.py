import pytest
from PyQt5.QtWidgets import QTableWidgetItem, QMessageBox

from sales_tab import SalesTab


class FakeDB:
    def __init__(self):
        self.estado_updates = []

    def get_venta_credito_fiscal(self, vid):
        return None

    def update_venta_estado(self, venta_id, estado):
        self.estado_updates.append((venta_id, estado))


class Manager:
    def __init__(self, db):
        self.db = db
        self._clientes = []
        self._Distribuidores = []
        self._vendedores = []


class FakeMainWindow:
    def __init__(self):
        self.calls = []

    def _generar_dte_sin_enviar(self, venta_id, tipo_dte):
        self.calls.append((venta_id, tipo_dte))
        return True, "ok"


def test_guardar_dte_manual_usa_helper_mainwindow(qt_app, monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)

    db = FakeDB()
    man = Manager(db)
    tab = SalesTab(man, check_smtp=False)

    tab.sales_table.setRowCount(1)
    tab.sales_table.setItem(0, 0, QTableWidgetItem("1"))
    tab.sales_table.selectRow(0)

    mw = FakeMainWindow()
    tab.main_window = mw

    tab._guardar_dte_manual()

    assert mw.calls == [(1, "01")]
    assert db.estado_updates == [(1, "Pendiente de Envío")]
