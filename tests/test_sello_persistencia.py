import json
from db import DB
from dte import (
    transmitir_dte,
    enviar_factura,
    enviar_nota_credito,
    enviar_nota_debito,
    enviar_nota_remision,
)
import dte
import nota_remision
import utils.docs
import utils.jws
from tests.conftest import make_jws


def create_sale(db: DB):
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("P1", "X", None, vid, None, 0, 0, 0, 1)
    pid = db.cursor.lastrowid
    venta_id = db.add_venta("2024-01-01", 10)
    db.add_detalle_venta(venta_id, pid, 1, 10, vendedor_id=vid)
    return venta_id


def _stub_enviar_documento(db_obj, doc_id, data, modo, jws_token=None):
    return {"estado": "Transmitido", "sello": "SELLO"}


def _assert_sello_guardado(db: DB, venta_id: int):
    row = db.cursor.execute("SELECT extra FROM ventas WHERE id=?", (venta_id,)).fetchone()
    assert row and row["extra"]
    extra = json.loads(row["extra"])
    assert extra["selloRecibido"] == "SELLO"


def test_transmitir_dte_guarda_sello(monkeypatch):
    db = DB(":memory:")
    venta_id = create_sale(db)
    monkeypatch.setattr(
        dte,
        "generar_dte_json",
        lambda db_obj, vid, **kwargs: {"identificacion": {"tipoDte": "01"}},
    )
    monkeypatch.setattr(dte, "apply_schema_patch", lambda d: d)
    monkeypatch.setattr(dte.catalogos, "get_dte_schema", lambda t: {})
    monkeypatch.setattr(dte, "_enviar_documento", _stub_enviar_documento)
    res = transmitir_dte(db, venta_id)
    assert res["sello"] == "SELLO"
    _assert_sello_guardado(db, venta_id)


def test_enviar_factura_guarda_sello(monkeypatch):
    db = DB(":memory:")
    venta_id = create_sale(db)
    monkeypatch.setattr(
        dte,
        "generar_dte_json",
        lambda db_obj, vid, **kwargs: {"identificacion": {"tipoDte": "01"}},
    )
    monkeypatch.setattr(dte, "apply_schema_patch", lambda d: d)
    monkeypatch.setattr(dte.catalogos, "get_dte_schema", lambda t: {})
    monkeypatch.setattr(dte, "_enviar_documento", _stub_enviar_documento)
    res = enviar_factura(db, venta_id)
    assert res["sello"] == "SELLO"
    _assert_sello_guardado(db, venta_id)


def test_enviar_nota_credito_guarda_sello(monkeypatch, tmp_path):
    db = DB(":memory:")
    venta_id = create_sale(db)
    nota_id = db.add_nota(venta_id, "credito", "2024-01-02", 10, "motivo")
    monkeypatch.setattr(dte, "generar_nota_credito_json", lambda db_obj, nid: {"identificacion": {"fecEmi": "2024-01-02", "numeroControl": "1"}, "receptor": {"nombre": "Cliente"}, "resumen": {"totalLetras": "X"}})
    monkeypatch.setattr(dte, "apply_schema_patch", lambda d: d)
    monkeypatch.setattr(dte.catalogos, "get_dte_schema", lambda t: {})
    monkeypatch.setattr(utils.docs, "get_dte_document_paths", lambda *a, **k: (None, tmp_path / "nc.json"))
    monkeypatch.setattr(utils.jws, "sign_json", lambda data: "TOKEN")
    monkeypatch.setattr(dte, "save_file", lambda *a, **k: None)
    monkeypatch.setattr(dte, "stable_stringify", lambda data, indent=2: json.dumps(data))
    monkeypatch.setattr(dte.os.path, "exists", lambda p: False)
    monkeypatch.setattr(dte, "_enviar_documento", _stub_enviar_documento)
    res = enviar_nota_credito(db, nota_id)
    assert res["sello"] == "SELLO"
    _assert_sello_guardado(db, nota_id)


def test_enviar_nota_debito_guarda_sello(monkeypatch, tmp_path):
    db = DB(":memory:")
    venta_id = create_sale(db)
    nota_id = db.add_nota(venta_id, "debito", "2024-01-02", 10, "motivo")
    monkeypatch.setattr(dte, "generar_nota_debito_json", lambda db_obj, nid: {"identificacion": {"fecEmi": "2024-01-02", "numeroControl": "1"}, "receptor": {"nombre": "Cliente"}, "resumen": {"totalLetras": "X"}})
    monkeypatch.setattr(dte, "apply_schema_patch", lambda d: d)
    monkeypatch.setattr(dte.catalogos, "get_dte_schema", lambda t: {})
    monkeypatch.setattr(utils.docs, "get_dte_document_paths", lambda *a, **k: (None, tmp_path / "nd.json"))
    monkeypatch.setattr(utils.jws, "sign_json", lambda data: "TOKEN")
    monkeypatch.setattr(dte, "save_file", lambda *a, **k: None)
    monkeypatch.setattr(dte, "stable_stringify", lambda data, indent=2: json.dumps(data))
    monkeypatch.setattr(dte.os.path, "exists", lambda p: False)
    monkeypatch.setattr(dte, "_enviar_documento", _stub_enviar_documento)
    res = enviar_nota_debito(db, nota_id)
    assert res["sello"] == "SELLO"
    _assert_sello_guardado(db, nota_id)


def test_enviar_nota_remision_guarda_sello(monkeypatch):
    db = DB(":memory:")
    venta_id = create_sale(db)
    nota_id = db.add_nota(venta_id, "remision", "2024-01-02", 10, "motivo")
    monkeypatch.setattr(nota_remision, "generar_nota_remision_desde_db", lambda db_obj, nid: {"resumen": {"totalLetras": "X"}})
    monkeypatch.setattr(dte, "apply_schema_patch", lambda d: d)
    monkeypatch.setattr(dte.catalogos, "get_dte_schema", lambda t: {})
    monkeypatch.setattr(dte, "_enviar_documento", _stub_enviar_documento)
    res = enviar_nota_remision(db, nota_id)
    assert res["sello"] == "SELLO"
    _assert_sello_guardado(db, nota_id)


def test_sello_recibido_actualiza_envio_y_extra(monkeypatch):
    db = DB(":memory:")
    venta_id = create_sale(db)

    minimo = {
        "identificacion": {
            "tipoDte": "01",
            "version": 1,
            "ambiente": "00",
            "codigoGeneracion": "ABC",
        },
        "resumen": {"totalLetras": "X"},
    }

    monkeypatch.setattr(dte, "generar_dte_json", lambda db_obj, vid, **kwargs: minimo)
    monkeypatch.setattr(dte, "apply_schema_patch", lambda d: d)
    monkeypatch.setattr(dte.catalogos, "get_dte_schema", lambda t: {})
    monkeypatch.setattr(dte.jws, "sign_json", lambda data: make_jws(data))
    monkeypatch.setattr(dte.auth, "get_token", lambda: "TKN")
    monkeypatch.setattr(dte.auth, "get_last_auth_host", lambda: "apitest.dtes.mh.gob.sv")
    monkeypatch.setattr(
        dte, "_load_dte_api_config", lambda: {"url": "https://apitest.dtes.mh.gob.sv/fesv/recepciondte"}
    )
    monkeypatch.setattr(
        dte, "_post_dte", lambda *a, **k: {"estado": "Transmitido", "selloRecibido": "SR"}
    )
    monkeypatch.setattr(dte, "_save_signed_dte", lambda *a, **k: None)

    resp = enviar_factura(db, venta_id)
    assert resp["sello"] == "SR"

    row = db.cursor.execute(
        "SELECT estado, sello FROM dte_envios WHERE venta_id=?", (venta_id,)
    ).fetchone()
    assert row["sello"] == "SR"

    extra_row = db.cursor.execute(
        "SELECT extra FROM ventas WHERE id=?", (venta_id,)
    ).fetchone()
    extra = json.loads(extra_row["extra"])
    assert extra["selloRecibido"] == "SR"


def test_generar_dte_json_exposes_sello(monkeypatch):
    db = DB(":memory:")
    venta_id = create_sale(db)
    db.update_venta_extra(venta_id, {"selloRecibido": "ABC", "es_ticket": True})
    datos = {
        "nombre": "X",
        "nit": "06140010912506",
        "nrc": "123456-7",
        "cod_giro": "123456",
        "dte_api": {"prefijo_control": "DTE-01-S001P001"},
    }
    monkeypatch.setattr(dte, "_load_datos_negocio", lambda: datos)
    monkeypatch.setattr(
        dte.svfe_config,
        "load_datos_negocio",
        lambda: {
            "direccion": {
                "departamento": "01",
                "municipio": "001",
                "complemento": "X",
            }
        },
    )
    monkeypatch.setattr(dte, "validate_dte_json", lambda *a, **k: None)
    data = dte.generar_dte_json(db, venta_id, tipo_dte="01")
    assert data["selloRecibido"] == "ABC"

