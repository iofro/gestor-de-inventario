import pytest
from PyQt5.QtWidgets import QApplication
from dialogs import RegisterSaleDialog

@pytest.fixture
def qt_app(monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    app = QApplication.instance() or QApplication([])
    return app


def test_iva_desglosado_con_descuento(qt_app):
    productos = [{
        "lote_id": 1,
        "producto_id": 1,
        "nombre": "Prod",
        "codigo": "P1",
        "stock": 1,
        "Distribuidor_id": None,
        "vendedor_id": None,
    }]
    dialog = RegisterSaleDialog(productos, [], [])
    dialog.product_list.setCurrentRow(0)
    dialog.cantidad_spin.setValue(1)
    dialog.precio_spin.setValue(113)
    dialog.descuento_spin.setValue(10)
    dialog.descuento_tipo_combo.setCurrentText("%")
    dialog.iva_checkbox.setChecked(True)
    dialog.iva_desglosado_radio.setChecked(True)

    dialog._agregar_a_venta()
    assert len(dialog.venta_items) == 1
    item = dialog.venta_items[0]
    assert item["subtotal"] == pytest.approx(100.0)
    assert item["descuento_monto"] == pytest.approx(10.0)
    assert item["subtotal_con_descuento"] == pytest.approx(90.0)
    assert item["iva"] == pytest.approx(11.7)
    assert item["total"] == pytest.approx(101.7)

    data = dialog.get_data()
    assert data["sumas"] == pytest.approx(100.0)
    assert data["descuentos"] == pytest.approx(10.0)
    assert data["iva"] == pytest.approx(11.7)
    assert data["total"] == pytest.approx(101.7)
    assert data["sumas"] - data["descuentos"] + data["iva"] == pytest.approx(data["total"])
