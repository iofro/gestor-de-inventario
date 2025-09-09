import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QListWidgetItem

from facturacion_tab import NotaRemisionDialog, QMessageBox
from nota_remision_electronica import generar_nota_remision_independiente


def _sample_emisor():
    return {"nit": "0614-140710-001-2", "nrc": "1234567"}


def _sample_cliente(complemento="Calle 1"):
    return {
        "nombre": "Ana",
        "nit": "0614-123456-102-3",
        "nrc": "1234567",
        "codActividad": "6201",
        "giro": "Servicios de software",
        "telefono": "70000001",
        "email": "ana@example.com",
        "departamento": "05",
        "municipio": "24",
        "direccion": complemento,
    }


def _build_dialog(db_conn):
    dialog = NotaRemisionDialog(db_conn, productos=[{"codigo": "P1", "nombre": "Prod"}])
    dialog.prod_cb.setCurrentIndex(0)
    dialog._add_item()
    dialog.ext_widget.nomb_entrega.setText("Juan")
    dialog.ext_widget.docu_entrega.setText("061234567")
    dialog.ext_widget.ext_obs.setPlainText("Obs")
    return dialog


def test_nr_dialog_receptor_fields(db_conn, qt_app):
    dialog = _build_dialog(db_conn)
    cli_item = QListWidgetItem("Cli")
    cli_item.setData(Qt.UserRole, _sample_cliente())
    dialog.ext_widget._seleccionar_cliente(cli_item)
    data = dialog.get_data()
    assert data is not None
    detalles, extension, receptor = data
    nr = generar_nota_remision_independiente(
        db_conn,
        emisor=_sample_emisor(),
        receptor=receptor,
        detalles=detalles,
        extension=extension,
        documento_relacionado=[
            {
                "tipoDocumento": "03",
                "tipoGeneracion": 1,
                "numeroDocumento": "XYZ",
                "fechaEmision": "2024-01-01",
            }
        ],
    )
    rec = nr["receptor"]
    assert rec["codActividad"] == "6201"
    assert rec["descActividad"] == "Servicios de software"
    assert rec["telefono"] == "70000001"
    assert rec["correo"] == "ana@example.com"
    assert rec["direccion"]["complemento"] == "Calle 1"


def test_nr_dialog_requires_address(monkeypatch, db_conn, qt_app):
    dialog = _build_dialog(db_conn)
    cli_item = QListWidgetItem("Cli")
    cli_item.setData(Qt.UserRole, _sample_cliente(complemento=""))
    dialog.ext_widget._seleccionar_cliente(cli_item)
    called = {}
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: called.setdefault("warn", True))
    assert dialog.get_data() is None
    assert called.get("warn")
