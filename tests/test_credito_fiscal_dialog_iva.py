import pytest
from PyQt5.QtWidgets import (
    QApplication,
    QLabel,
    QSpinBox,
    QDoubleSpinBox,
    QComboBox,
    QCheckBox,
    QRadioButton,
    QListWidget,
    QTableWidget,
    QLineEdit,
    QDateEdit,
)
from PyQt5.QtCore import QDate
from dialogs import RegisterCreditoFiscalDialog


@pytest.fixture
def qt_app(monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    return QApplication.instance() or QApplication([])


def build_dialog(qty=5, price=1.00):
    dialog = RegisterCreditoFiscalDialog.__new__(RegisterCreditoFiscalDialog)
    dialog.cantidad_spin = QSpinBox()
    dialog.cantidad_spin.setMaximum(100000)
    dialog.cantidad_spin.setValue(qty)
    dialog.precio_spin = QDoubleSpinBox()
    dialog.precio_spin.setDecimals(2)
    dialog.precio_spin.setValue(price)
    dialog.precio_total_spin = QDoubleSpinBox()
    dialog.precio_total_spin.setDecimals(2)
    dialog.precio_total_spin.setValue(qty * price)
    dialog.tipo_minorista = QRadioButton()
    dialog.tipo_minorista.setChecked(True)
    dialog.tipo_mayorista_unit = QRadioButton()
    dialog.tipo_mayorista_unit.setChecked(False)
    dialog.tipo_mayorista_total = QRadioButton()
    dialog.tipo_mayorista_total.setChecked(False)
    dialog.descuento_spin = QDoubleSpinBox()
    dialog.descuento_spin.setDecimals(2)
    dialog.descuento_spin.setValue(0)
    dialog.descuento_tipo_combo = QComboBox()
    dialog.descuento_tipo_combo.addItems(["%", "$"])
    dialog.descuento_tipo_combo.setCurrentIndex(0)
    dialog.comision_chk = QCheckBox()
    dialog.comision_pct_spin = QDoubleSpinBox()
    dialog.comision_pct_spin.setDecimals(2)
    dialog.comision_tipo_combo = QComboBox()
    dialog.comision_tipo_combo.addItems(["Añadida al total", "Desglosada (incluida en el precio)"])
    dialog.item_precio_label = QLabel()
    dialog.item_sumas_label = QLabel()
    dialog.item_total_sin_desc_label = QLabel()
    dialog.item_descuento_label = QLabel()
    dialog.item_subtotal_label = QLabel()
    dialog.comision_label = QLabel()
    dialog.tipo_fiscal_combo = QComboBox()
    dialog.tipo_fiscal_combo.addItems(["Venta gravada", "Venta exenta", "Venta no sujeta"])
    dialog.product_list = QListWidget()
    dialog.product_list.addItem("Producto X")
    dialog.product_list.setCurrentRow(0)
    dialog.productos = [{"lote_id": 1, "producto_id": 1, "nombre": "Producto X", "Distribuidor_id": 1}]
    dialog.venta_items = []
    dialog.table = QTableWidget(0, 6)
    dialog.total_label = QLabel()
    dialog.vendedor_combo = QComboBox()
    dialog.vendedor_combo.addItem("Sin vendedor")
    dialog.vendedores_trabajadores = []
    dialog.selected_cliente = {"id": 1, "nombre": "Cliente"}
    dialog.iva_agregado_radio = QRadioButton()
    dialog.nrc_edit = QLineEdit()
    dialog.nit_edit = QLineEdit()
    dialog.giro_edit = QLineEdit()
    dialog.email_edit = QLineEdit()
    dialog.no_remision_edit = QLineEdit()
    dialog.orden_no_edit = QLineEdit()
    dialog.condicion_pago_combo = QComboBox()
    dialog.venta_a_cuenta_de_edit = QLineEdit()
    dialog.venta_documento_edit = QLineEdit()
    dialog.fecha_remision_anterior = QDateEdit(QDate.currentDate())
    dialog.fecha_remision = QDateEdit(QDate.currentDate())
    dialog.Distribuidor_combo = QComboBox()
    return dialog


def test_total_label_updates_with_items(qt_app):
    dialog = RegisterCreditoFiscalDialog.__new__(RegisterCreditoFiscalDialog)
    dialog.total_label = QLabel()
    dialog.venta_items = [{"total": 113.0}]
    RegisterCreditoFiscalDialog._actualizar_resumen(dialog)
    assert dialog.total_label.text() == "Total venta (con IVA): $113.00"


def test_product_summary_recalculates_iva(qt_app):
    dialog = build_dialog()
    dialog.descuento_spin.setValue(10)
    RegisterCreditoFiscalDialog._recalcular_totales(dialog)

    assert dialog.item_precio_label.text() == "Precio U. sin IVA: $0.88"
    assert dialog.item_sumas_label.text() == "Sumas sin IVA: $4.40"
    assert dialog.item_total_sin_desc_label.text() == "Total con IVA sin descuento: $5.00"
    assert dialog.item_descuento_label.text() == "Descuento: -$0.50"
    assert dialog.item_subtotal_label.text() == "Subtotal final (con IVA): $4.50"


def test_descuento_tipo_limita_rango(qt_app):
    dialog = build_dialog()
    dialog.descuento_tipo_combo.setCurrentIndex(0)  # %
    RegisterCreditoFiscalDialog._on_descuento_tipo_changed(dialog)
    assert dialog.descuento_spin.maximum() == 100
    dialog.descuento_tipo_combo.setCurrentIndex(1)  # $
    RegisterCreditoFiscalDialog._on_descuento_tipo_changed(dialog)
    assert dialog.descuento_spin.maximum() == 1000000


def test_descuento_monto_clamped(qt_app):
    dialog = build_dialog()
    dialog.descuento_tipo_combo.setCurrentIndex(1)  # $
    dialog.descuento_spin.setValue(10)
    RegisterCreditoFiscalDialog._recalcular_totales(dialog)
    assert dialog.item_subtotal_label.text() == "Subtotal final (con IVA): $0.00"
    RegisterCreditoFiscalDialog._agregar_a_venta(dialog)
    item = dialog.venta_items[0]
    assert item["descuento_monto"] == 5.0
    assert item["total"] == 0.0


@pytest.mark.parametrize("tipo_index", [1, 2])
def test_tipo_fiscal_exenta_no_sujeta(qt_app, tipo_index):
    dialog = build_dialog()
    dialog.descuento_spin.setValue(10)
    dialog.tipo_fiscal_combo.setCurrentIndex(tipo_index)
    RegisterCreditoFiscalDialog._recalcular_totales(dialog)
    RegisterCreditoFiscalDialog._agregar_a_venta(dialog)
    item = dialog.venta_items[0]
    assert item["iva"] == 0.0
    assert item["subtotal_con_descuento"] == 4.5
    assert item["total"] == 4.5
    assert dialog.item_precio_label.text() == "Precio U. sin IVA: $1.00"


def test_mayorista_total_recalculates_unit_price(qt_app):
    dialog = build_dialog()
    dialog.tipo_mayorista_total.setChecked(True)
    dialog.precio_total_spin.setValue(5.00)
    dialog.descuento_spin.setValue(10)
    RegisterCreditoFiscalDialog._recalcular_totales(dialog)
    assert dialog.item_precio_label.text() == "Precio U. sin IVA: $0.88"
    assert dialog.item_subtotal_label.text() == "Subtotal final (con IVA): $4.50"


@pytest.mark.parametrize(
    "qty, price, expected",
    [
        (1, 0.01, 0.01),
        (100000, 0.99, 99000.0),
    ],
)
def test_totals_precision_edge_cases(qt_app, qty, price, expected):
    dialog = build_dialog(qty, price)
    RegisterCreditoFiscalDialog._agregar_a_venta(dialog)
    item = dialog.venta_items[0]
    assert pytest.approx(item["total"], rel=1e-6) == expected


def test_get_data_credito_fiscal_discount_total(qt_app):
    dialog = build_dialog(qty=1, price=15.00)
    dialog.descuento_spin.setValue(10)
    dialog.descuento_tipo_combo.setCurrentIndex(0)
    RegisterCreditoFiscalDialog._recalcular_totales(dialog)
    RegisterCreditoFiscalDialog._agregar_a_venta(dialog)

    data = RegisterCreditoFiscalDialog.get_data(dialog)

    assert len(dialog.venta_items) == 1
    assert data["total"] == pytest.approx(13.5)
    assert f"{data['total']:.2f}" == "13.50"
    assert data["descuentos"] == pytest.approx(1.32743363)
