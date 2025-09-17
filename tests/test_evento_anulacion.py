import json
import os
import uuid
from types import SimpleNamespace

import pytest
from PyQt5.QtWidgets import QDialog, QWidget

from dialogs.anular_factura_dialog import AnularFacturaDialog
from utils.catalogos import TRIBUTO_IVA
import facturacion_tab
import anulacion


SELLO_BASE36 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZABCD"


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
    sello = SELLO_BASE36

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
    sello = "Z" * 40

    codigo_reemplazo = str(uuid.uuid4()).upper()
    numero_control_reemplazo = "DTE-01-S001P001-000000000000777"
    reemplazo = {
        "identificacion": {
            "tipoDte": factura["identificacion"]["tipoDte"],
            "codigoGeneracion": codigo_reemplazo,
            "numeroControl": numero_control_reemplazo,
            "fecEmi": "2024-01-02",
        },
        "emisor": factura.get("emisor", {}),
        "receptor": factura.get("receptor", {}),
    }
    json_path = tmp_path / "reemplazo.json"
    json_path.write_text(json.dumps(reemplazo), encoding="utf-8")

    extra = {
        "codigoGeneracion": codigo_reemplazo,
        "numeroControl": numero_control_reemplazo,
        "dteJsonPath": str(json_path),
        "selloRecibido": "Y" * 40,
    }
    venta_id = db_conn.add_venta("2024-01-02", 10, extra=extra)
    db_conn.registrar_envio_dte(
        venta_id,
        "test",
        "Aceptado",
        "E" * 40,
        respuesta_json=json.dumps({"sello": "E" * 40}),
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


def _patch_negocio(monkeypatch):
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


def _build_form(codigo):
    return {
        "tipoAnulacion": "3",
        "motivoAnulacion": "Cliente solicita anulación",
        "nombreResponsable": "Responsable Uno",
        "tipDocResponsable": "13",
        "numDocResponsable": "01234567-8",
        "nombreSolicita": "Solicita Dos",
        "tipDocSolicita": "36",
        "numDocSolicita": "06141404100016",
        "codigoGeneracionR": codigo,
    }


def test_invalidacion_rechaza_emisor_distinto(monkeypatch, db_conn, tmp_path):
    factura = _sample_factura()
    sello = "C" * 40
    codigo_reemplazo = str(uuid.uuid4()).upper()
    numero_control = "DTE-01-S001P001-000000000000888"
    reemplazo = {
        "identificacion": {
            "tipoDte": factura["identificacion"]["tipoDte"],
            "codigoGeneracion": codigo_reemplazo,
            "numeroControl": numero_control,
            "fecEmi": "2024-01-02",
        },
        "emisor": {
            "nit": "06141404100017",
            "nombre": "Otra Empresa",
        },
        "receptor": factura.get("receptor", {}),
    }
    json_path = tmp_path / "reemplazo_emisor.json"
    json_path.write_text(json.dumps(reemplazo), encoding="utf-8")

    extra = {
        "codigoGeneracion": codigo_reemplazo,
        "numeroControl": numero_control,
        "dteJsonPath": str(json_path),
        "selloRecibido": "E" * 40,
    }
    venta_id = db_conn.add_venta("2024-01-02", 10, extra=extra)
    db_conn.registrar_envio_dte(
        venta_id,
        "manual",
        "Aceptado",
        "E" * 40,
        respuesta_json=json.dumps({"documento": reemplazo}),
        codigo_generacion=codigo_reemplazo,
        numero_control=numero_control,
    )

    _patch_negocio(monkeypatch)
    form = _build_form(codigo_reemplazo)

    with pytest.raises(ValueError) as excinfo:
        anulacion.build_invalidacion_json(
            {**factura, "selloRecibido": sello},
            form,
            ambiente="00",
            db=db_conn,
        )
    assert str(excinfo.value) == anulacion.ERROR_REEMPLAZO_EMISOR


def test_invalidacion_rechaza_fecha_anterior(monkeypatch, db_conn, tmp_path):
    factura = _sample_factura()
    sello = "D" * 40
    codigo_reemplazo = str(uuid.uuid4()).upper()
    numero_control = "DTE-01-S001P001-000000000000889"
    reemplazo = {
        "identificacion": {
            "tipoDte": factura["identificacion"]["tipoDte"],
            "codigoGeneracion": codigo_reemplazo,
            "numeroControl": numero_control,
            "fecEmi": "2023-12-20",
        },
        "emisor": factura.get("emisor", {}),
        "receptor": factura.get("receptor", {}),
    }
    json_path = tmp_path / "reemplazo_fecha.json"
    json_path.write_text(json.dumps(reemplazo), encoding="utf-8")

    extra = {
        "codigoGeneracion": codigo_reemplazo,
        "numeroControl": numero_control,
        "dteJsonPath": str(json_path),
        "selloRecibido": "E" * 40,
    }
    venta_id = db_conn.add_venta("2023-12-20", 10, extra=extra)
    db_conn.registrar_envio_dte(
        venta_id,
        "manual",
        "Aceptado",
        "E" * 40,
        respuesta_json=json.dumps({"documento": reemplazo}),
        codigo_generacion=codigo_reemplazo,
        numero_control=numero_control,
    )

    _patch_negocio(monkeypatch)
    form = _build_form(codigo_reemplazo)

    with pytest.raises(ValueError) as excinfo:
        anulacion.build_invalidacion_json(
            {**factura, "selloRecibido": sello},
            form,
            ambiente="00",
            db=db_conn,
        )
    assert str(excinfo.value) == anulacion.ERROR_REEMPLAZO_FECHA


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
    sello = "1" * 40
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


def test_enviar_invalidacion_guarda_archivos(monkeypatch):
    codigo = "ABC123XYZ789"
    data = {
        "identificacion": {"codigoGeneracion": codigo},
        "documento": {"ejemplo": True},
    }

    monkeypatch.setattr(anulacion, "_load_dte_api_config", lambda: {"url": "https://mh.test"})
    monkeypatch.setattr(anulacion.jws, "sign_json", lambda payload: "TOKEN")
    monkeypatch.setattr(anulacion.auth, "get_token", lambda: "token")

    posted = []

    def fake_post(url, token, signed, payload):
        posted.append((url, token, signed, payload))
        return {"estado": "aceptado", "sello": "0" * 40}

    monkeypatch.setattr(anulacion, "_post_invalidacion", fake_post)

    created_dirs = []

    def fake_makedirs(path, exist_ok=False):
        created_dirs.append((path, exist_ok))

    monkeypatch.setattr(anulacion.os, "makedirs", fake_makedirs)

    saved = []

    def fake_save_file(path, content, add_final_newline=True):
        saved.append((path, content, add_final_newline))

    monkeypatch.setattr("utils.stable_json.save_file", fake_save_file)

    result = anulacion.enviar_invalidacion(None, data)

    expected_dir = os.path.join(
        os.path.dirname(anulacion.__file__),
        "dtes",
        "eventos",
        "anulacion",
        codigo,
    )
    assert created_dirs == [(expected_dir, True)]

    assert len(saved) == 2
    saved_dict = {
        path: (content, add_final_newline)
        for path, content, add_final_newline in saved
    }
    json_path = os.path.join(expected_dir, "documento.json")
    jws_path = os.path.join(expected_dir, "documento.jws")
    assert json_path in saved_dict
    assert saved_dict[json_path][1] is True
    assert jws_path in saved_dict
    assert saved_dict[jws_path][0] == "TOKEN"
    assert saved_dict[jws_path][1] is False
    assert posted and posted[0][2] == "TOKEN"
    assert result["sello"] == "0" * 40


def test_enviar_invalidacion_continua_si_falla_guardado(monkeypatch):
    codigo = "ERR123456789"
    data = {
        "identificacion": {"codigoGeneracion": codigo},
        "documento": {"ejemplo": True},
    }

    monkeypatch.setattr(anulacion, "_load_dte_api_config", lambda: {"url": "https://mh.test"})
    monkeypatch.setattr(anulacion.jws, "sign_json", lambda payload: "TOKEN")
    monkeypatch.setattr(anulacion.auth, "get_token", lambda: "token")

    posted = []

    def fake_post(url, token, signed, payload):
        posted.append((url, token, signed, payload))
        return {"estado": "procesado", "sello": "2" * 40}

    monkeypatch.setattr(anulacion, "_post_invalidacion", fake_post)

    monkeypatch.setattr(anulacion.os, "makedirs", lambda *args, **kwargs: None)

    def failing_save_file(*args, **kwargs):
        raise OSError("permiso denegado")

    monkeypatch.setattr("utils.stable_json.save_file", failing_save_file)

    class DummyLogger:
        def __init__(self):
            self.calls = []

        def exception(self, msg, *args, **kwargs):
            self.calls.append((msg, args, kwargs))

    dummy_logger = DummyLogger()
    monkeypatch.setattr(anulacion, "logger", dummy_logger)

    result = anulacion.enviar_invalidacion(None, data)

    assert posted and posted[0][2] == "TOKEN"
    assert result["estado"] == "procesado"
    assert dummy_logger.calls


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
    sello = "3" * 40
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
