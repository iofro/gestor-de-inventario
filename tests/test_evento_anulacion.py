import uuid

from dialogs.anular_factura_dialog import AnularFacturaDialog
from dte import generar_evento_anulacion
from utils.catalogos import TRIBUTO_IVA


def _sample_factura():
    ident = {
        "ambiente": "00",
        "tipoDte": "01",
        "codigoGeneracion": str(uuid.uuid4()).upper(),
        "numeroControl": "DTE-01-S001P001-000000000000001",
        "fecEmi": "2024-01-01",
    }
    emisor = {
        "nit": "06141404100016",
        "nombre": "Empresa SA",
        "tipoEstablecimiento": "01",
        "telefono": "22223333",
        "correo": "info@empresa.com",
        "codEstable": "0001",
        "codPuntoVenta": "0001",
        "nombreComercial": "Empresa",
    }
    receptor = {
        "nombre": "Cliente",
        "nit": "06141404100016",
    }
    resumen = {
        "tributos": [{"codigo": TRIBUTO_IVA, "valor": "1.30"}]
    }
    return {
        "identificacion": ident,
        "emisor": emisor,
        "receptor": receptor,
        "resumen": resumen,
    }


def test_generar_evento_anulacion(qt_app):
    factura = _sample_factura()
    dlg = AnularFacturaDialog()
    dlg.tipo_cb.setCurrentIndex(1)
    dlg.motivo_edit.setText("Error en factura")
    dlg.nom_resp.setText("Responsable Uno")
    dlg.tdoc_resp.setCurrentIndex(0)
    dlg.ndoc_resp.setText("123456789")
    dlg.nom_sol.setText("Solicita Dos")
    dlg.tdoc_sol.setCurrentIndex(1)
    dlg.ndoc_sol.setText("987654321")
    form = dlg.get_data()
    sello = "A" * 40
    evento = generar_evento_anulacion(factura, form, sello)
    assert evento["motivo"]["nombreResponsable"] == "Responsable Uno"
    assert evento["motivo"]["numDocSolicita"] == "987654321"
    assert evento["documento"]["selloRecibido"] == sello
    assert evento["documento"]["numeroControl"] == factura["identificacion"]["numeroControl"]
