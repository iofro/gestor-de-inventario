import uuid

import dte
from db import DB
from dialogs.anular_factura_dialog import AnularFacturaDialog
from dialogs.invoice_detail_dialog import InvoiceDetailDialog
from PyQt5.QtWidgets import QDialog


def test_anular_dialog_prefills_fields(qt_app):
    resp = {"nombre": "Negocio", "nit": "1234"}
    sol = {"nombre": "Cliente", "dui": "5678"}
    dlg = AnularFacturaDialog(responsable=resp, solicitante=sol)
    assert dlg.nom_resp.text() == "Negocio"
    assert dlg.ndoc_resp.text() == "1234"
    assert dlg.tdoc_resp.currentData() == "36"
    assert dlg.nom_sol.text() == "Cliente"
    assert dlg.ndoc_sol.text() == "5678"
    assert dlg.tdoc_sol.currentData() == "13"
    dlg.nom_resp.setText("Otro")
    assert dlg.nom_resp.text() == "Otro"


def test_invoice_detail_uses_negocio_and_cliente(monkeypatch, qt_app):
    negocio = {"nombre": "Dueño", "nit": "1111"}
    factura = {"receptor": {"nombre": "Comprador", "nit": "2222"}}
    monkeypatch.setattr(dte, "_load_datos_negocio", lambda: negocio)
    captured = {}

    class FakeDialog:
        def __init__(self, *args, **kwargs):
            captured["responsable"] = kwargs.get("responsable")
            captured["solicitante"] = kwargs.get("solicitante")
        def exec_(self):
            return QDialog.Rejected

    monkeypatch.setattr("dialogs.invoice_detail_dialog.AnularFacturaDialog", FakeDialog)
    dlg = InvoiceDetailDialog([], {}, venta_id=1, numero_control="1", factura=factura)
    dlg._anular()
    assert captured["responsable"]["nombre"] == "Dueño"
    assert captured["solicitante"]["nombre"] == "Comprador"


def test_anular_dialog_rejects_same_uuid(monkeypatch, qt_app):
    codigo = str(uuid.uuid4()).upper()
    factura = {"identificacion": {"tipoDte": "01", "codigoGeneracion": codigo}}
    dlg = AnularFacturaDialog(factura=factura)
    idx = dlg.tipo_cb.findData("1")
    dlg.tipo_cb.setCurrentIndex(idx)
    dlg.codigo_edit.setText(codigo)
    warnings = []

    def fake_warning(*args):
        warnings.append(args)

    monkeypatch.setattr("dialogs.anular_factura_dialog.QMessageBox.warning", fake_warning)
    assert not dlg._validate()
    assert warnings, "expected warning when selecting same UUID"


def test_usar_datos_negocio_button(monkeypatch, qt_app):
    negocio = {"nombre": "Dueño", "dui": "12345678-9"}
    monkeypatch.setattr(dte, "_load_datos_negocio", lambda: negocio)
    dlg = AnularFacturaDialog()
    dlg.negocio_btn.click()
    assert dlg.nom_resp.text() == "Dueño"
    assert dlg.ndoc_resp.text() == "12345678-9"
    assert dlg.tdoc_resp.currentData() == "13"


def test_buscar_empleado_autocompleta(tmp_path, qt_app):
    db = DB(tmp_path / "test.db")
    db.add_trabajador({"nombre": "Juan", "dui": "0001"})
    dlg = AnularFacturaDialog(db=db)
    dlg.emp_search.setText("Juan")
    dlg._buscar_empleado()
    item = dlg.emp_results.item(0)
    dlg._seleccionar_empleado(item)
    assert dlg.nom_resp.text() == "Juan"
    assert dlg.ndoc_resp.text() == "0001"
    assert dlg.tdoc_resp.currentData() == "13"
    db.conn.close()
