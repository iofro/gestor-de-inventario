import pytest

pytest.importorskip("PyQt5.QtWidgets", exc_type=ImportError)

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


def test_dialog_quantity_adjustment_populates_payload(qt_app):
    detalles = [_make_detalle()]
    dialog = NotaDetalleDialog(detalles, "credito")

    qty_spin = dialog.table.cellWidget(0, 5)
    assert qty_spin is not None
    qty_spin.setValue(2)
    dialog._update_total()

    assert pytest.approx(dialog._totals["gravada"], rel=1e-4) == 20.0
    assert pytest.approx(dialog._totals["iva"], rel=1e-4) == 2.6

    total, motivo, detalles_nota = dialog.get_data()
    assert motivo == ""
    assert pytest.approx(total, rel=1e-4) == 22.6
    assert len(detalles_nota) == 1
    detalle = detalles_nota[0]
    assert detalle["ajusteCantidad"] is True
    assert pytest.approx(detalle["cantidad"], rel=1e-4) == 2
    assert pytest.approx(detalle["precio_unitario"], rel=1e-4) == 10
    assert "ajuste" not in detalle


def test_dialog_combined_adjustments_single_payload(qt_app):
    detalles = [_make_detalle()]
    dialog = NotaDetalleDialog(detalles, "debito")

    qty_spin = dialog.table.cellWidget(0, 5)
    monto_spin = dialog.table.cellWidget(0, 6)
    assert qty_spin is not None and monto_spin is not None

    qty_spin.setValue(1)
    monto_spin.setValue(5)
    dialog._update_total()

    total, _, detalles_nota = dialog.get_data()
    assert pytest.approx(total, rel=1e-4) == 16.3
    assert len(detalles_nota) == 1
    detalle = detalles_nota[0]
    assert detalle["ajusteCantidad"] is True
    assert pytest.approx(detalle["cantidad"], rel=1e-4) == 1
    assert pytest.approx(detalle["precio_unitario"], rel=1e-4) == 10
    assert pytest.approx(detalle["ajuste"], rel=1e-4) == 5
    assert detalle["ajuste"] > 0
