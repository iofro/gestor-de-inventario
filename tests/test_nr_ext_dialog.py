from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QListWidgetItem

import facturacion_tab
from facturacion_tab import NotaRemisionExtDialog
from utils.sanitize import solo_digitos


def test_nr_ext_dialog_autofill_and_sanitize(db_conn, qt_app):
    dialog = NotaRemisionExtDialog(db_conn)

    emp_item = QListWidgetItem("Emp")
    emp_item.setData(Qt.UserRole, {"nombre": "Juan", "dui": "0612-34567"})
    dialog._seleccionar_empleado(emp_item)
    assert dialog.nomb_entrega.text() == "Juan"
    assert dialog.docu_entrega.text() == "06123456-7"

    cli_item = QListWidgetItem("Cli")
    cli_item.setData(Qt.UserRole, {"nombre": "Ana", "dui": "0612 34567"})
    dialog._seleccionar_cliente(cli_item)
    assert dialog.nomb_recibe.text() == "Ana"
    assert dialog.docu_recibe.text() == "06123456-7"
    assert dialog.nrc_recibe.text() == ""

    dialog.ext_obs.setPlainText("Obs")
    data = dialog.get_data()
    assert data["docuEntrega"] == "061234567"
    assert data["docuRecibe"] == "061234567"
    assert data["nrcRecibe"] == ""
    assert data["tipoDocRecibe"] == "13"


def test_nr_ext_dialog_manual_selection_validation(db_conn, qt_app, monkeypatch):
    monkeypatch.setattr(facturacion_tab.QMessageBox, "warning", lambda *a, **k: None)
    dialog = NotaRemisionExtDialog(db_conn)
    w = dialog.panel
    w.nomb_entrega.setText("E")
    w.docu_entrega.setText("06123456-7")
    w.nomb_recibe.setText("R")

    # DUI manual selection
    w.tipo_recibe_cb.setCurrentIndex(0)
    w.tipo_recibe_cb.currentIndexChanged.emit(w.tipo_recibe_cb.currentIndex())
    w.docu_recibe.setText("1234567890")
    assert w.docu_recibe.text() == "12345678-9"
    assert len(solo_digitos(w.docu_recibe.text())) == 9
    assert not w.nrc_recibe.isEnabled()

    # NIT selection
    w.tipo_recibe_cb.setCurrentIndex(1)
    w.tipo_recibe_cb.currentIndexChanged.emit(w.tipo_recibe_cb.currentIndex())
    w.docu_recibe.setText("1" * 20)
    assert w.docu_recibe.text() == "1" * 14
    w.nrc_recibe.setText("123456")
    assert w.validate()

    # Invalid NIT length
    w.docu_recibe.setText("12345678")
    assert not w.validate()

    # Missing NRC
    w.docu_recibe.setText("12345678901234")
    w.nrc_recibe.clear()
    assert not w.validate()
