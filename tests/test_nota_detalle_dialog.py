import pytest

pytest.importorskip("PyQt5.QtWidgets", exc_type=ImportError)

from PyQt5.QtWidgets import QRadioButton, QCheckBox

from dialogs.nota_detalle_dialog import NotaDetalleDialog


def _make_detalle(**kwargs):
    detalle = {
        "id": 1,
        "producto_id": "P1",
        "descripcion": "Producto",
        "cantidad": 5.0,
        "precio_unitario": 10.0,
        "ventas_gravadas": 50.0,
        "ventas_exentas": 0.0,
        "ventas_no_sujetas": 0.0,
        "precio_unitario_iva": 0.0,
        "descuento_iva": 0.0,
        "total_linea": 50.0,
        "uniMedida": 59,
        "tipoItem": 1,
    }
    detalle.update(kwargs)
    return detalle


def _get_row_widgets(dialog, row=0):
    mode_widget = dialog.table.cellWidget(row, 5)
    qty_spin = dialog.table.cellWidget(row, 6)
    price_spin = dialog.table.cellWidget(row, 7)
    qty_radio = mode_widget.findChild(QRadioButton, f"mode-cantidad-{row}")
    price_radio = mode_widget.findChild(QRadioButton, f"mode-precio-{row}")
    iva_checkbox = dialog.table.cellWidget(row, 8)
    assert isinstance(iva_checkbox, QCheckBox)
    return qty_spin, price_spin, qty_radio, price_radio, iva_checkbox


def test_table_shows_ajuste_precio_label(qt_app):
    dialog = NotaDetalleDialog([_make_detalle()], "debito")

    headers = [dialog.table.horizontalHeaderItem(i).text() for i in range(dialog.table.columnCount())]

    assert "Ajuste total" in headers
    assert "Monto incluye IVA" in headers


def test_select_quantity_mode_disables_price_input(qt_app):
    dialog = NotaDetalleDialog([_make_detalle()], "debito")
    qty_spin, price_spin, qty_radio, price_radio, iva_checkbox = _get_row_widgets(dialog)

    assert qty_radio is not None and price_radio is not None
    qty_radio.setChecked(True)

    assert qty_spin.isEnabled()
    assert not price_spin.isEnabled()
    assert price_spin.value() == 0
    assert not iva_checkbox.isEnabled()
    assert not iva_checkbox.isChecked()

    price_spin.stepUp()
    assert price_spin.value() == 0


def test_select_price_mode_disables_quantity_input(qt_app):
    dialog = NotaDetalleDialog([_make_detalle()], "debito")
    qty_spin, price_spin, qty_radio, price_radio, iva_checkbox = _get_row_widgets(dialog)

    price_radio.setChecked(True)

    assert price_spin.isEnabled()
    assert not qty_spin.isEnabled()
    assert qty_spin.value() == 0
    assert iva_checkbox.isEnabled()
    assert iva_checkbox.isChecked()

    qty_spin.stepUp()
    assert qty_spin.value() == 0


def test_auto_selects_quantity_mode_on_input(qt_app):
    dialog = NotaDetalleDialog([_make_detalle()], "credito")
    qty_spin, price_spin, qty_radio, price_radio, iva_checkbox = _get_row_widgets(dialog)

    assert not qty_radio.isChecked()
    assert not price_radio.isChecked()
    
    qty_spin.setValue(2)

    assert qty_radio.isChecked()
    assert not price_spin.isEnabled()
    assert price_spin.value() == 0
    assert not iva_checkbox.isEnabled()

    qty_spin.setValue(0)
    assert qty_radio.isChecked()

    total, motivo, detalles_nota = dialog.get_data()
    assert motivo == ""
    assert pytest.approx(total, rel=1e-4) == 22.6
    assert len(detalles_nota) == 1
    detalle = detalles_nota[0]
    assert detalle["ajusteCantidad"] is True
    assert pytest.approx(detalle["cantidad"], rel=1e-4) == 2
    assert "modo" not in detalle


def test_auto_selects_price_mode_on_input(qt_app):
    dialog = NotaDetalleDialog([_make_detalle()], "debito")
    qty_spin, price_spin, qty_radio, price_radio, iva_checkbox = _get_row_widgets(dialog)

    price_spin.setValue(5)

    assert price_radio.isChecked()
    assert not qty_spin.isEnabled()
    assert qty_spin.value() == 0
    assert iva_checkbox.isChecked()

    total, _, detalles_nota = dialog.get_data()
    assert pytest.approx(total, rel=1e-4) == 5.0
    assert len(detalles_nota) == 1
    detalle = detalles_nota[0]
    assert "ajusteCantidad" not in detalle
    assert pytest.approx(detalle["ajuste"], rel=1e-4) == 5.0
    assert detalle["ajuste"] > 0
    assert detalle["monto_incluye_iva"] is True


def test_unchecking_mode_returns_inputs_to_free_state(qt_app):
    dialog = NotaDetalleDialog([_make_detalle()], "debito")
    qty_spin, price_spin, qty_radio, price_radio, iva_checkbox = _get_row_widgets(dialog)

    qty_radio.setChecked(True)
    assert qty_radio.isChecked()

    qty_radio.setChecked(False)

    assert not qty_radio.isChecked()
    assert qty_spin.isEnabled()
    assert price_spin.isEnabled()
    assert iva_checkbox.isEnabled()


def test_get_data_raises_when_both_modes_used(qt_app):
    dialog = NotaDetalleDialog([_make_detalle()], "debito")
    qty_spin, price_spin, _, _, _ = _get_row_widgets(dialog)
    qty_spin.blockSignals(True)
    price_spin.blockSignals(True)
    qty_spin.setValue(1)
    price_spin.setValue(1)
    qty_spin.blockSignals(False)
    price_spin.blockSignals(False)

    with pytest.raises(ValueError):
        dialog.get_data()
