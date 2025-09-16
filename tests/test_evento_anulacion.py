import json
import uuid
from types import SimpleNamespace

import pytest
from PyQt5.QtWidgets import QDialog, QWidget

from dialogs.anular_factura_dialog import AnularFacturaDialog
from utils.catalogos import TRIBUTO_IVA
import facturacion_tab
import anulacion


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
        "nombre": "Cliente Demo",
        "nit": "06141404100016",
        "telefono": "50377778888",
        "correo": "cliente@example.com",
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


def test_generar_evento_anulacion(qt_app, monkeypatch):
    factura = _sample_factura()
    dlg = AnularFacturaDialog()
    dlg.tipo_cb.setCurrentIndex(dlg.tipo_cb.findData("2"))
    dlg.motivo_edit.setText("Error en factura")
    dlg.nom_resp.setText("Responsable Uno")
    dlg.tdoc_resp.setCurrentIndex(dlg.tdoc_resp.findData("36"))
    dlg.ndoc_resp.setText("123456789")
    dlg.nom_sol.setText("Solicita Dos")
    dlg.tdoc_sol.setCurrentIndex(dlg.tdoc_sol.findData("13"))
    dlg.ndoc_sol.setText("987654321")
    form = dlg.get_data()
    sello = "A" * 40

    monkeypatch.setattr(
        anulacion,
        "_load_datos_negocio",
        lambda: {
            "nit": "06141404100016",
            "nombre": "Empresa SA",
            "telefono": "22223333",
            "correo": "info@empresa.com",
            "tipoEstablecimiento": "01",
            "nombreComercial": "Empresa",
            "codEstableMH": "0001",
            "codEstable": "0001",
            "codPuntoVentaMH": "0001",
            "codPuntoVenta": "0001",
        },
    )
    evento = anulacion.build_invalidacion_json(
        {**factura, "selloRecibido": sello}, form, ambiente="00"
    )
    assert evento["motivo"]["nombreResponsable"] == "Responsable Uno"
    assert evento["motivo"]["numDocSolicita"] == "987654321"
    assert evento["documento"]["selloRecibido"] == sello
    assert (
        evento["documento"]["numeroControl"]
        == factura["identificacion"]["numeroControl"]
    )
    assert evento["documento"]["codigoGeneracionR"] is None
    assert evento["documento"]["telefono"] == "50377778888"
    assert evento["documento"]["correo"] == "cliente@example.com"
    assert evento["motivo"]["tipoAnulacion"] == 2


def test_invalidacion_tipo3_requiere_codigo(monkeypatch, db_conn, tmp_path):
    factura = _sample_factura()
    sello = "B" * 40

    codigo_reemplazo = str(uuid.uuid4()).upper()
    numero_control_reemplazo = "DTE-01-S001P001-000000000000777"
    reemplazo = {
        "identificacion": {
            "tipoDte": factura["identificacion"]["tipoDte"],
            "codigoGeneracion": codigo_reemplazo,
            "numeroControl": numero_control_reemplazo,
            "fecEmi": "2024-01-02",
        },
        "receptor": factura.get("receptor", {}),
    }
    json_path = tmp_path / "reemplazo.json"
    json_path.write_text(json.dumps(reemplazo), encoding="utf-8")

    extra = {
        "codigoGeneracion": codigo_reemplazo,
        "numeroControl": numero_control_reemplazo,
        "dteJsonPath": str(json_path),
        "selloRecibido": "Z" * 40,
    }
    venta_id = db_conn.add_venta("2024-01-02", 10, extra=extra)
    db_conn.registrar_envio_dte(
        venta_id,
        "test",
        "Aceptado",
        "Z" * 40,
        respuesta_json=json.dumps({"sello": "Z" * 40}),
        codigo_generacion=codigo_reemplazo,
        numero_control=numero_control_reemplazo,
    )

    monkeypatch.setattr(
        anulacion,
        "_load_datos_negocio",
        lambda: {
            "nit": "06141404100016",
            "nombre": "Empresa SA",
            "telefono": "22223333",
            "correo": "info@empresa.com",
            "tipoEstablecimiento": "01",
            "nombreComercial": "Empresa",
            "codEstableMH": "0001",
            "codEstable": "0001",
            "codPuntoVentaMH": "0001",
            "codPuntoVenta": "0001",
        },
    )

    form = {
        "tipoAnulacion": "3",
        "motivoAnulacion": "Cliente solicita anulación",
        "nombreResponsable": "Responsable Uno",
        "tipDocResponsable": "13",
        "numDocResponsable": "01234567-8",
        "nombreSolicita": "Solicita Dos",
        "tipDocSolicita": "36",
        "numDocSolicita": "06141404100016",
        "codigoGeneracionR": codigo_reemplazo,
    }

    evento = anulacion.build_invalidacion_json(
        {**factura, "selloRecibido": sello},
        form,
        ambiente="01",
        db=db_conn,
    )
    assert evento["documento"]["codigoGeneracionR"] == form["codigoGeneracionR"]
    assert evento["motivo"]["motivoAnulacion"] == "Cliente solicita anulación"

    sin_codigo = dict(form)
    sin_codigo.pop("codigoGeneracionR")
    with pytest.raises(ValueError):
        anulacion.build_invalidacion_json(
            {**factura, "selloRecibido": sello},
            sin_codigo,
            ambiente="01",
            db=db_conn,
        )

    sin_motivo = dict(form)
    sin_motivo["motivoAnulacion"] = "  "
    with pytest.raises(ValueError):
        anulacion.build_invalidacion_json(
            {**factura, "selloRecibido": sello},
            sin_motivo,
            ambiente="01",
            db=db_conn,
        )


def test_anular_dte_uses_sello_from_db(qt_app, db_conn, monkeypatch):
    def _create_sale(db):
        db.add_vendedor("V1")
        vid = db.cursor.lastrowid
        db.add_producto("P1", "C1", None, vid, None, 0, 10, 10, 1)
        pid = db.cursor.lastrowid
        db.add_cliente("C", "", "", "", "", "", "c@x.com", "", "", "")
        cid = db.cursor.lastrowid
        venta_id = db.add_venta("2024-01-01", 10, cliente_id=cid, vendedor_id=vid)
        db.add_detalle_venta(venta_id, pid, 1, 10, vendedor_id=vid)
        return venta_id

    venta_id = _create_sale(db_conn)
    sello = "S" * 40
    db_conn.registrar_envio_dte(venta_id, "test", "aceptado", sello)

    factura = {"venta_id": venta_id}
    data = {
        "identificacion": {
            "codigoGeneracion": "CG123",
            "numeroControl": "NC123",
        },
        "receptor": {},
    }

    class DummyTab(QWidget):
        def __init__(self, db):
            super().__init__()
            self.manager = SimpleNamespace(db=db)

        def refresh_and_reload(self):
            pass

    dummy = DummyTab(db_conn)

    monkeypatch.setattr(
        facturacion_tab.dte,
        "_load_datos_negocio",
        lambda: {"nombre": "Empresa", "nit": "06141404100016"},
    )

    class DummyDialog:
        def __init__(self, *args, **kwargs):
            pass

        def exec_(self):
            return QDialog.Rejected

        def get_data(self):
            return {}

    monkeypatch.setattr(facturacion_tab, "AnularDteDialog", DummyDialog)

    called = []

    def fake_critical(*args, **kwargs):
        called.append((args, kwargs))

    monkeypatch.setattr(facturacion_tab.QMessageBox, "critical", fake_critical)

    facturacion_tab.FacturacionTab._anular_dte(dummy, factura, data)

    assert not called
    assert data["selloRecibido"] == sello


def test_anular_dte_uses_sello_from_respuesta(qt_app, db_conn, monkeypatch):
    def _create_sale(db):
        db.add_vendedor("V1")
        vid = db.cursor.lastrowid
        db.add_producto("P1", "C1", None, vid, None, 0, 10, 10, 1)
        pid = db.cursor.lastrowid
        db.add_cliente("C", "", "", "", "", "", "c@x.com", "", "", "")
        cid = db.cursor.lastrowid
        venta_id = db.add_venta("2024-01-01", 10, cliente_id=cid, vendedor_id=vid)
        db.add_detalle_venta(venta_id, pid, 1, 10, vendedor_id=vid)
        return venta_id

    venta_id = _create_sale(db_conn)
    sello = "R" * 40
    db_conn.registrar_envio_dte(
        venta_id,
        "test",
        "aceptado",
        "",
        json.dumps({"selloRecibido": sello}),
    )

    factura = {"venta_id": venta_id}
    data = {
        "identificacion": {
            "codigoGeneracion": "CG123",
            "numeroControl": "NC123",
        },
        "receptor": {},
    }

    class DummyTab(QWidget):
        def __init__(self, db):
            super().__init__()
            self.manager = SimpleNamespace(db=db)

        def refresh_and_reload(self):
            pass

    dummy = DummyTab(db_conn)

    monkeypatch.setattr(
        facturacion_tab.dte,
        "_load_datos_negocio",
        lambda: {"nombre": "Empresa", "nit": "06141404100016"},
    )

    class DummyDialog:
        def __init__(self, *args, **kwargs):
            pass

        def exec_(self):
            return QDialog.Rejected

        def get_data(self):
            return {}

    monkeypatch.setattr(facturacion_tab, "AnularDteDialog", DummyDialog)

    called = []

    def fake_critical(*args, **kwargs):
        called.append((args, kwargs))

    monkeypatch.setattr(facturacion_tab.QMessageBox, "critical", fake_critical)

    facturacion_tab.FacturacionTab._anular_dte(dummy, factura, data)

    assert not called
    assert data["selloRecibido"] == sello
