from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QListWidgetItem

from facturacion_tab import NotaRemisionExtDialog


def test_nr_ext_dialog_autofill_and_sanitize(db_conn, qt_app):
    dialog = NotaRemisionExtDialog(db_conn)

    emp_item = QListWidgetItem("Emp")
    emp_item.setData(Qt.UserRole, {"nombre": "Juan", "dui": "0612-34567"})
    dialog._seleccionar_empleado(emp_item)
    assert dialog.nomb_entrega.text() == "Juan"
    assert dialog.docu_entrega.text() == "061234567"

    cli_item = QListWidgetItem("Cli")
    cli_item.setData(Qt.UserRole, {"nombre": "Ana", "nit": "0612 34567"})
    dialog._seleccionar_cliente(cli_item)
    assert dialog.nomb_recibe.text() == "Ana"
    assert dialog.docu_recibe.text() == "061234567"

    dialog.ext_obs.setText("Obs")
    data = dialog.get_data()
    assert data["docuEntrega"] == "061234567"
    assert data["docuRecibe"] == "061234567"
