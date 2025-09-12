import dte
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
        def __init__(self, parent=None, responsable=None, solicitante=None):
            captured["responsable"] = responsable
            captured["solicitante"] = solicitante
        def exec_(self):
            return QDialog.Rejected

    monkeypatch.setattr("dialogs.invoice_detail_dialog.AnularFacturaDialog", FakeDialog)
    dlg = InvoiceDetailDialog([], {}, venta_id=1, numero_control="1", factura=factura)
    dlg._anular()
    assert captured["responsable"]["nombre"] == "Dueño"
    assert captured["solicitante"]["nombre"] == "Comprador"
