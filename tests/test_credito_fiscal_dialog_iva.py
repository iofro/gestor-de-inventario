import pytest
from PyQt5.QtWidgets import QApplication, QLabel
from dialogs import RegisterCreditoFiscalDialog


@pytest.fixture
def qt_app(monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    return QApplication.instance() or QApplication([])


def test_iva_label_updates_with_items(qt_app):
    dialog = RegisterCreditoFiscalDialog.__new__(RegisterCreditoFiscalDialog)
    dialog.iva_label = QLabel()
    dialog.total_label = QLabel()
    dialog.venta_items = [{"iva": 13.0, "total": 113.0}]
    RegisterCreditoFiscalDialog._actualizar_resumen(dialog)
    assert dialog.iva_label.text() == "IVA: $13.00"
    assert dialog.total_label.text() == "TOTAL: $113.00"
