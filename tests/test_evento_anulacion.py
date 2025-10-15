import json
import os
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from PyQt5.QtWidgets import QDialog, QWidget

from dialogs.anular_factura_dialog import AnularFacturaDialog
from dialogs.seleccionar_dte_dialog import SeleccionarDteDialog
from utils.catalogos import TRIBUTO_IVA
from tests.conftest import make_jws
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


def _basic_form(tipo: str = "2") -> dict:
    return {
        "tipoAnulacion": tipo,
        "motivoAnulacion": "Error en factura",
        "nombreResponsable": "Responsable Uno",
        "tipDocResponsable": "36",
        "numDocResponsable": "123456789",
        "nombreSolicita": "Solicita Dos",
        "tipDocSolicita": "13",
        "numDocSolicita": "987654321",
    }


def _evento_minimo() -> dict:
    codigo_evento = str(uuid.uuid4()).upper()
    codigo_dte = str(uuid.uuid4()).upper()
    return {
        "identificacion": {
            "version": 2,
            "ambiente": "00",
            "codigoGeneracion": codigo_evento,
            "fecAnula": "2024-01-05",
            "horAnula": "08:00:00",
        },
        "documento": {
            "tipoDte": "01",
            "codigoGeneracion": codigo_dte,
            "selloRecibido": SELLO_BASE36,
            "numeroControl": "DTE-01-S001P001-000000000000099",
            "fecEmi": "2024-01-01",
            "montoIva": 1.23,
            "codigoGeneracionR": None,
            "tipoDocumento": "36",
            "numDocumento": "123456789",
            "nombre": "Cliente Demo",
        },
        "motivo": {"tipoAnulacion": 2},
    }


def test_build_invalidacion_tributos_null_usa_totaliva(monkeypatch):
    factura = _sample_factura()
    factura["resumen"]["tributos"] = None
    factura["resumen"]["totalIva"] = "5.50"
    factura["selloRecibido"] = SELLO_BASE36
    form = _basic_form()

    _patch_negocio(monkeypatch)

    evento = anulacion.build_invalidacion_json(factura, form, ambiente="00")

    assert evento["documento"]["montoIva"] == pytest.approx(5.5)


def test_build_invalidacion_tributos_null_sin_totaliva(monkeypatch):
    factura = _sample_factura()
    factura["resumen"]["tributos"] = None
    factura["resumen"].pop("totalIva", None)
    factura["selloRecibido"] = SELLO_BASE36
    form = _basic_form()

    _patch_negocio(monkeypatch)

    evento = anulacion.build_invalidacion_json(factura, form, ambiente="00")

    assert evento["documento"]["montoIva"] is None


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


@pytest.mark.usefixtures("qt_app")
def test_seleccionar_dte_fecha_filter_respects_checkbox(
    db_conn, tmp_path, dte_metadata_factory
):
    factura = dte_metadata_factory()
    codigo = str(uuid.uuid4()).upper()
    numero = "DTE-01-S001P001-000000000000601"
    factura["identificacion"]["codigoGeneracion"] = codigo
    factura["identificacion"]["numeroControl"] = numero
    json_path = tmp_path / "dte_antiguo.json"
    json_path.write_text(json.dumps(factura), encoding="utf-8")

    extra = {
        "codigoGeneracion": codigo,
        "numeroControl": numero,
        "dteJsonPath": str(json_path),
        "selloRecibido": "S" * 40,
    }
    venta_id = db_conn.add_venta("2024-01-01", 10, extra=extra)
    db_conn.registrar_envio_dte(
        venta_id,
        "manual",
        "Aceptado",
        "S" * 40,
        respuesta_json=json.dumps({"documento": factura}),
        codigo_generacion=codigo,
        numero_control=numero,
    )
    row_id = db_conn.cursor.lastrowid
    antiguo = datetime.now() - timedelta(days=90)
    db_conn.ensure_column("dte_envios", "ambiente", "TEXT")
    db_conn.cursor.execute(
        "UPDATE dte_envios SET fecha_hora=?, ambiente=? WHERE id=?",
        (
            antiguo.isoformat(),
            factura["identificacion"].get("ambiente"),
            row_id,
        ),
    )
    db_conn.conn.commit()

    dialog = SeleccionarDteDialog(
        db_conn,
        tipo_dte=factura["identificacion"].get("tipoDte"),
        ambiente=factura["identificacion"].get("ambiente"),
        receptor_documentos=[factura["receptor"].get("numDocumento")],
    )

    assert not dialog.filtrar_fecha_cb.isChecked()
    assert dialog.fecha_inicio.date() == dialog.fecha_inicio.minimumDate()
    assert dialog.fecha_fin.date() == dialog.fecha_fin.minimumDate()

    codigos_sin_filtro = {c["codigo_generacion"] for c in dialog.candidates}
    assert codigo in codigos_sin_filtro

    dialog.filtrar_fecha_cb.setChecked(True)

    assert dialog.fecha_inicio.date() <= dialog.fecha_fin.date()
    codigos_con_filtro = {c["codigo_generacion"] for c in dialog.candidates}
    assert codigo not in codigos_con_filtro

    dialog.deleteLater()


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


def test_post_invalidacion_envia_sobre_con_jws(monkeypatch):
    evento = _evento_minimo()
    firmado = make_jws(evento)

    monkeypatch.setattr(anulacion, "sign_json", lambda data: firmado)

    captured = {}

    class DummyResp:
        status_code = 200
        text = ""
        headers = {}
        content = b""

    def fake_auth_headers(extra=None, *, ambiente=None):
        headers = {"Authorization": "Bearer token123"}
        if isinstance(extra, dict):
            headers.update(extra)
        return headers

    monkeypatch.setattr(anulacion, "auth_headers", fake_auth_headers)
    monkeypatch.setattr(anulacion, "detect_user_agent", lambda *a, **k: "UA")

    def fake_post_json(url, headers, body, *, tag):
        captured["url"] = url
        captured["headers"] = headers
        captured["body"] = body
        captured["tag"] = tag
        return DummyResp(), {"estado": "aceptado", "sello": "S" * 40}, ""

    monkeypatch.setattr(anulacion, "_post_json", fake_post_json)

    result = anulacion._post_invalidacion(
        "https://apitest.dtes.mh.gob.sv/fesv/anulardte",
        evento,
        ambiente_config="00",
    )

    assert captured["url"] == "https://apitest.dtes.mh.gob.sv/fesv/anulardte"
    assert captured["body"]["documento"] == firmado
    assert isinstance(captured["body"]["documento"], str)
    assert captured["body"]["ambiente"] == "00"
    assert captured["body"]["idEnvio"] == 1
    assert captured["body"]["version"] == 2
    assert captured["headers"]["Authorization"] == "Bearer token123"
    assert result["estado"] == "aceptado"


def test_post_invalidacion_reporta_detalle_error(monkeypatch):
    evento = _evento_minimo()
    firmado = make_jws(evento)

    monkeypatch.setattr(anulacion, "sign_json", lambda data: firmado)

    class DummyResp:
        status_code = 400
        text = "Bad Request"
        headers = {}
        content = b""

    def fake_auth_headers(extra=None, *, ambiente=None):
        headers = {"Authorization": "Bearer token456"}
        if isinstance(extra, dict):
            headers.update(extra)
        return headers

    monkeypatch.setattr(anulacion, "auth_headers", fake_auth_headers)
    monkeypatch.setattr(anulacion, "detect_user_agent", lambda *a, **k: "UA")

    def fake_post_json(url, headers, body, *, tag):
        data = {
            "detalle": {
                "descripcionMsg": "Formato inválido",
                "observaciones": ["Falta campo"],
            }
        }
        return DummyResp(), data, json.dumps(data)

    monkeypatch.setattr(anulacion, "_post_json", fake_post_json)

    result = anulacion._post_invalidacion(
        "https://apitest.dtes.mh.gob.sv/fesv/anulardte",
        evento,
    )

    assert result["estado"] == "Rechazado"
    assert result["http_status"] == 400
    assert result["descripcionMsg"] == "Formato inválido"
    assert result["observaciones"] == ["Falta campo"]


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

    monkeypatch.setattr(facturacion_tab, "AnularFacturaDialog", DummyDialog)

    called = []

    def fake_critical(*args, **kwargs):
        called.append((args, kwargs))

    monkeypatch.setattr(facturacion_tab.QMessageBox, "critical", fake_critical)

    facturacion_tab.FacturacionTab._anular_dte(dummy, factura, data)

    assert not called
    assert data["selloRecibido"] == sello


def test_anular_dte_accepts_client_json_payload(qt_app, monkeypatch):
    sello = "A" * 40
    client_payload = {
        "dteJson": {
            "identificacion": {
                "codigoGeneracion": "11111111-2222-3333-4444-555555555555",
                "numeroControl": "DTE-01-S001P001-000000000000123",
                "fecEmi": "2024-01-02",
                "tipoDte": "01",
            },
            "receptor": {"nombre": "Cliente Demo"},
        },
        "selloRecibido": sello,
        "firmaElectronica": "TOKEN",
    }

    class DummyTab(QWidget):
        def __init__(self):
            super().__init__()
            self.manager = SimpleNamespace(db=None)

        def refresh_and_reload(self):
            pass

    dummy = DummyTab()
    factura = {"venta_id": None}

    monkeypatch.setattr(
        facturacion_tab.dte,
        "_load_datos_negocio",
        lambda: {"nombre": "Empresa", "nit": "06141404100016"},
    )

    captured = {}

    class DummyDialog:
        def __init__(self, *args, **kwargs):
            pass

        def exec_(self):
            return QDialog.Accepted

        def get_data(self):
            return {}

    monkeypatch.setattr(facturacion_tab, "AnularFacturaDialog", DummyDialog)

    def fake_build(factura_arg, ui_data, *, ambiente, db):
        captured["factura"] = factura_arg
        captured["ambiente"] = ambiente
        captured["ui"] = ui_data
        return {"ok": True}

    monkeypatch.setattr(anulacion, "build_invalidacion_json", fake_build)

    monkeypatch.setattr(
        anulacion,
        "enviar_invalidacion",
        lambda db, payload: {"estado": "rechazado", "detalle": "error"},
    )

    critical_calls = []

    monkeypatch.setattr(facturacion_tab.QMessageBox, "critical", lambda *a, **k: critical_calls.append((a, k)))
    monkeypatch.setattr(facturacion_tab.QMessageBox, "warning", lambda *a, **k: None)

    facturacion_tab.FacturacionTab._anular_dte(dummy, factura, client_payload)

    assert not critical_calls
    factura_used = captured["factura"]
    assert factura_used["selloRecibido"] == sello
    ident = factura_used.get("identificacion", {})
    assert ident.get("codigoGeneracion") == "11111111-2222-3333-4444-555555555555"
    assert ident.get("numeroControl") == "DTE-01-S001P001-000000000000123"


def test_enviar_invalidacion_guarda_archivos(monkeypatch, tmp_path):
    codigo = "12345678-1234-1234-1234-1234567890AB"
    data = {
        "identificacion": {
            "codigoGeneracion": codigo,
            "version": 2,
            "ambiente": "00",
        },
        "documento": {
            "codigoGeneracion": codigo,
            "tipoDte": "01",
            "numeroControl": "DTE-01-ABCDEFGH-000000000000001",
            "selloRecibido": "0" * 40,
            "montoIva": 1.23,
        },
        "motivo": {"tipoAnulacion": 2},
    }

    monkeypatch.setattr(anulacion, "_load_dte_api_config", lambda: {"url": "https://mh.test"})
    monkeypatch.setattr(anulacion.auth, "get_token", lambda: "token")

    posted = []

    base_root = tmp_path / "userdata"

    def fake_ensure_user_dir(*parts):
        path = base_root.joinpath(*parts)
        path.mkdir(parents=True, exist_ok=True)
        return path

    monkeypatch.setattr(anulacion, "ensure_user_dir", fake_ensure_user_dir)

    def fake_post(url, payload, *, ambiente_config=None, **kwargs):
        posted.append((url, payload, ambiente_config, kwargs))
        return {"estado": "aceptado", "sello": "0" * 40}

    monkeypatch.setattr(anulacion, "_post_invalidacion", fake_post)

    def fake_resolve(base_dir, codigo_generacion):
        target = base_root / "dtes" / codigo_generacion
        target.mkdir(parents=True, exist_ok=True)
        return os.fspath(target)

    monkeypatch.setattr(anulacion, "resolve_version_dir", fake_resolve)

    created_dirs = []

    def fake_makedirs(path, exist_ok=False):
        created_dirs.append((path, exist_ok))

    monkeypatch.setattr(anulacion.os, "makedirs", fake_makedirs)

    saved = []

    def fake_save_file(path, content, add_final_newline=True):
        saved.append((path, content, add_final_newline))

    monkeypatch.setattr("utils.stable_json.save_file", fake_save_file)

    result = anulacion.enviar_invalidacion(None, data)

    base_dir = fake_ensure_user_dir("dtes", "actualizaciones", "anulacion")
    expected_dir = os.path.join(os.fspath(base_dir), codigo)
    assert created_dirs == [(expected_dir, True)]

    assert len(saved) == 3
    json_path = os.path.join(expected_dir, "documento.json")
    assert saved[0][0] == json_path
    assert saved[0][2] is True
    metadata_paths = [entry[0] for entry in saved if entry[0].endswith("metadata.json")]
    assert metadata_paths == [os.path.join(expected_dir, "metadata.json"), os.path.join(expected_dir, "metadata.json")]
    final_metadata = json.loads(saved[-1][1])
    assert final_metadata["documento"]["codigoGeneracion"] == codigo
    assert final_metadata["documento"]["numeroControl"] == "DTE-01-ABCDEFGH-000000000000001"
    assert final_metadata["respuesta"]["estado"].lower() == "aceptado"
    assert posted
    assert posted[0][0] == "https://mh.test/fesv/anulardte"
    assert posted[0][1] is data
    assert posted[0][2] is None
    assert posted[0][3] == {}
    assert result["sello"] == "0" * 40


def test_enviar_invalidacion_continua_si_falla_guardado(monkeypatch):
    codigo = "ABCDEF12-3456-7890-ABCD-EF1234567890"
    data = {
        "identificacion": {
            "codigoGeneracion": codigo,
            "version": 2,
            "ambiente": "01",
        },
        "documento": {
            "codigoGeneracion": codigo,
            "tipoDte": "01",
            "numeroControl": "DTE-01-IJKLMN12-000000000000002",
            "selloRecibido": "2" * 40,
            "montoIva": 0.0,
        },
        "motivo": {"tipoAnulacion": 2},
    }

    monkeypatch.setattr(anulacion, "_load_dte_api_config", lambda: {"url": "https://mh.test"})
    monkeypatch.setattr(anulacion.auth, "get_token", lambda: "token")

    posted = []

    def fake_post(url, payload, *, ambiente_config=None, **kwargs):
        posted.append((url, payload, ambiente_config, kwargs))
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

    assert posted and posted[0][1] is data
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

    monkeypatch.setattr(facturacion_tab, "AnularFacturaDialog", DummyDialog)

    called = []

    def fake_critical(*args, **kwargs):
        called.append((args, kwargs))

    monkeypatch.setattr(facturacion_tab.QMessageBox, "critical", fake_critical)

    facturacion_tab.FacturacionTab._anular_dte(dummy, factura, data)

    assert not called
    assert data["selloRecibido"] == sello
