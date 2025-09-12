import json
import logging
import os
import pytest

from pathlib import Path
from db import DB
from dte import (
    enviar_factura,
    enviar_nota_credito,
    enviar_nota_debito,
    enviar_nota_remision,
    enviar_evento_contingencia,
    enviar_evento_anulacion,
    _post_dte,
    DTEValidationError,
)
import dte
import auth
from tests.conftest import make_jws
from utils import docs


def create_sale(db):
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("P1", "X", None,  vid, None, 0, 0, 0, 1)
    pid = db.cursor.lastrowid
    venta_id = db.add_venta("2024-01-01", 10)
    db.add_detalle_venta(venta_id, pid, 1, 10, vendedor_id=vid)
    return venta_id


def test_enviar_factura_rechazo_y_reenvio(monkeypatch, caplog, tmp_path):
    db = DB(":memory:")
    venta = create_sale(db)

    sign_calls = {"count": 0, "tokens": []}

    def fake_sign(data):
        sign_calls["count"] += 1
        token = make_jws(data)
        sign_calls["tokens"].append(token)
        return token

    monkeypatch.setattr("utils.jws.sign_json", fake_sign)
    monkeypatch.setattr(auth, "get_token", lambda: "Bearer JWT")
    monkeypatch.setattr(auth, "get_last_auth_host", lambda: "apitest.dtes.mh.gob.sv")
    monkeypatch.setattr("dte.validate_dte_json", lambda data, db=None: None)
    monkeypatch.setattr(
        "dte.generar_dte_json",
        lambda db_obj, vid: {
            "receptor": {"nombre": "Cliente"},
            "cuerpoDocumento": [{"cantidad": 1, "precioUni": 10}],
            "resumen": {
                "totalNoSuj": 0,
                "totalExenta": 0,
                "totalGravada": 10,
                "subTotalVentas": 10,
                "descuNoSuj": 0,
                "descuExenta": 0,
                "descuGravada": 0,
                "porcentajeDescuento": 0,
                "totalDescu": 0,
                "tributos": [],
                "subTotal": 10,
                "ivaRete1": 0,
                "reteRenta": 0,
                "montoTotalOperacion": 10,
                "totalNoGravado": 0,
                "totalPagar": 10,
                "totalLetras": "DIEZ",
                "saldoFavor": 0,
                "condicionOperacion": 1,
                "pagos": None,
                "numPagoElectronico": None,
            },
            "identificacion": {
                "tipoDte": "01",
                "version": 2,
                "ambiente": "00",
                "codigoGeneracion": "ABC",
            },
        },
    )

    responses = [
        {"estado": "Rechazado", "descripcionMsg": "Error", "observaciones": ["campo"]},
        {"estado": "Transmitido", "sello": "ABC"},
    ]

    calls = []

    def fake_post(url, json=None, headers=None, timeout=20):
        calls.append((url, headers, json))
        data = responses.pop(0)

        class R:
            status_code = 200

            def json(self):
                return data

            def raise_for_status(self):
                pass

        return R()

    monkeypatch.setattr("dte.requests.post", fake_post)

    orig_load = dte._load_datos_negocio

    def fake_load():
        data = orig_load()
        data.setdefault("dte_api", {})["url"] = dte.DEFAULT_RECEPCION_URL
        data["dte_api"]["ambiente"] = "pruebas"
        return data

    monkeypatch.setattr(dte, "_load_datos_negocio", fake_load)

    caplog.set_level(logging.ERROR)
    res = enviar_factura(db, venta)
    assert res["estado"] == "Rechazado"
    assert "Error" in caplog.text and "campo" in caplog.text
    row = db.cursor.execute("SELECT count(*) c FROM dte_envios WHERE venta_id=?", (venta,)).fetchone()
    assert row["c"] == 1

    caplog.clear()
    res = enviar_factura(db, venta)
    assert res["estado"] == "Transmitido"
    row = db.cursor.execute("SELECT count(*) c FROM dte_envios WHERE venta_id=?", (venta,)).fetchone()
    assert row["c"] == 2

    assert sign_calls["count"] == 2
    assert len(calls) == 2
    for url, headers, body in calls:
        assert url == dte.DEFAULT_RECEPCION_URL
        assert body["documento"] in sign_calls["tokens"]
        assert headers["Authorization"] == "Bearer JWT"
        assert headers["Content-Type"] == "application/json"
        assert headers["Accept"] == "application/json"
        assert headers["User-Agent"] == "Vertex-DTE/1.0"


def test_no_envia_si_validacion_falla(monkeypatch):
    db = DB(":memory:")
    venta = create_sale(db)

    sent = []

    def fake_post(url, json=None, headers=None, timeout=20):
        sent.append(True)

    monkeypatch.setattr("dte.requests.post", fake_post)
    monkeypatch.setattr(auth, "get_token", lambda: "Bearer JWT")

    sign_calls = {"count": 0}

    def fake_sign(data):
        sign_calls["count"] += 1
        return "TOKEN"

    monkeypatch.setattr("utils.jws.sign_json", fake_sign)

    monkeypatch.setattr(
        "dte.generar_dte_json",
        lambda db_obj, vid: {"identificacion": {"tipoDte": "01"}},
    )

    with pytest.raises(DTEValidationError):
        enviar_factura(db, venta)

    assert sent == []
    assert sign_calls["count"] == 0


def test_enviar_nota_credito(monkeypatch, tmp_path):
    db = DB(":memory:")
    venta = create_sale(db)
    nota_id = db.add_nota(venta, "credito", "2024-01-02", 10, "motivo")

    sign_calls = {"count": 0, "tokens": []}

    def fake_sign(data):
        sign_calls["count"] += 1
        token = make_jws(data)
        sign_calls["tokens"].append(token)
        return token

    monkeypatch.setattr("utils.jws.sign_json", fake_sign)
    monkeypatch.setattr(auth, "get_token", lambda: "Bearer JWT")
    monkeypatch.setattr(auth, "get_last_auth_host", lambda: "apitest.dtes.mh.gob.sv")
    monkeypatch.setattr("dte.validate_dte_json", lambda data, db=None: None)
    monkeypatch.setattr(
        "dte.generar_nota_credito_json",
        lambda db_obj, nid: {
            "receptor": {"nombre": "Cliente"},
            "cuerpoDocumento": [{"cantidad": 1, "precioUni": 10}],
            "resumen": {
                "totalNoSuj": 0,
                "totalExenta": 0,
                "totalGravada": 10,
                "subTotalVentas": 10,
                "descuNoSuj": 0,
                "descuExenta": 0,
                "descuGravada": 0,
                "porcentajeDescuento": 0,
                "totalDescu": 0,
                "tributos": [],
                "subTotal": 10,
                "ivaRete1": 0,
                "reteRenta": 0,
                "montoTotalOperacion": 10,
                "totalNoGravado": 0,
                "totalPagar": 10,
                "totalLetras": "DIEZ",
                "saldoFavor": 0,
                "condicionOperacion": 1,
                "pagos": None,
                "numPagoElectronico": None,
            },
            "identificacion": {
                "tipoDte": "01",
                "version": 2,
                "ambiente": "00",
                "codigoGeneracion": "NC1",
            },
        },
    )

    calls = []

    def fake_post(url, json=None, headers=None, timeout=20):
        calls.append((url, headers, json))

        class R:
            status_code = 200

            def json(self):
                return {"estado": "Transmitido", "sello": "XYZ"}

            def raise_for_status(self):
                pass

        return R()

    monkeypatch.setattr("dte.requests.post", fake_post)

    orig_load = dte._load_datos_negocio

    def fake_load():
        data = orig_load()
        data.setdefault("dte_api", {})["url"] = dte.DEFAULT_RECEPCION_URL
        data["dte_api"]["ambiente"] = "pruebas"
        return data

    monkeypatch.setattr(dte, "_load_datos_negocio", fake_load)

    res = enviar_nota_credito(db, nota_id)
    assert res["estado"] == "Transmitido"
    row = db.cursor.execute("SELECT estado FROM dte_envios WHERE venta_id=?", (nota_id,)).fetchone()
    assert row["estado"] == "Transmitido"
    assert sign_calls["count"] == 1
    assert len(calls) == 1
    url, headers, body = calls[0]
    assert url == dte.DEFAULT_RECEPCION_URL
    assert body["documento"] in sign_calls["tokens"]
    assert headers["Authorization"] == "Bearer JWT"
    assert headers["Content-Type"] == "application/json"
    assert headers["Accept"] == "application/json"
    assert headers["User-Agent"] == "Vertex-DTE/1.0"


def test_enviar_nota_credito_reuses_jws(monkeypatch, tmp_path):
    db = DB(":memory:")
    venta = create_sale(db)
    nota_id = db.add_nota(venta, "credito", "2024-01-02", 10, "motivo")

    data = {
        "receptor": {"nombre": "Cliente"},
        "cuerpoDocumento": [{"cantidad": 1, "precioUni": 10}],
        "resumen": {
            "totalNoSuj": 0,
            "totalExenta": 0,
            "totalGravada": 10,
            "subTotalVentas": 10,
            "descuNoSuj": 0,
            "descuExenta": 0,
            "descuGravada": 0,
            "porcentajeDescuento": 0,
            "totalDescu": 0,
            "tributos": [],
            "subTotal": 10,
            "ivaRete1": 0,
            "reteRenta": 0,
            "montoTotalOperacion": 10,
            "totalNoGravado": 0,
            "totalPagar": 10,
            "totalLetras": "DIEZ",
            "saldoFavor": 0,
            "condicionOperacion": 1,
            "pagos": None,
            "numPagoElectronico": None,
        },
        "identificacion": {
            "tipoDte": "01",
            "version": 2,
            "ambiente": "00",
            "codigoGeneracion": "NC1",
            "numeroControl": "1",
            "fecEmi": "2024-01-02",
        },
    }

    monkeypatch.setattr(
        "dte.generar_nota_credito_json",
        lambda db_obj, nid: data,
    )

    sign_calls = {"count": 0}

    def fake_sign(payload):
        sign_calls["count"] += 1
        return "SIGNED"

    monkeypatch.setattr("utils.jws.sign_json", fake_sign)

    orig_paths = docs.get_dte_document_paths

    def fake_paths(fecha, empresa, numero_control, doc_type, root=None):
        return orig_paths(fecha, empresa, numero_control, doc_type, root=tmp_path)

    monkeypatch.setattr(docs, "get_dte_document_paths", fake_paths)

    _, json_path = fake_paths(
        data["identificacion"]["fecEmi"],
        data["receptor"]["nombre"],
        data["identificacion"]["numeroControl"],
        "NotaCredito",
    )
    jws_path = os.path.splitext(json_path)[0] + ".jws"
    token = make_jws(data)
    with open(jws_path, "w", encoding="utf-8") as fh:
        fh.write(token)

    captured = {}

    def fake_post(url, json=None, headers=None, timeout=20):
        captured["token"] = json["documento"]

        class R:
            status_code = 200

            def json(self):
                return {"estado": "Transmitido", "sello": "XYZ"}

            def raise_for_status(self):
                pass

        return R()

    monkeypatch.setattr("dte.requests.post", fake_post)

    monkeypatch.setattr(auth, "get_token", lambda: "Bearer JWT")
    monkeypatch.setattr(auth, "get_last_auth_host", lambda: "apitest.dtes.mh.gob.sv")

    orig_load = dte._load_datos_negocio

    def fake_load():
        cfg = orig_load()
        cfg.setdefault("dte_api", {})["url"] = dte.DEFAULT_RECEPCION_URL
        cfg["dte_api"]["ambiente"] = "pruebas"
        return cfg

    monkeypatch.setattr(dte, "_load_datos_negocio", fake_load)

    res = enviar_nota_credito(db, nota_id)
    assert res["estado"] == "Transmitido"
    assert captured["token"] == token
    assert sign_calls["count"] == 0


def test_post_dte_packs_jws_in_json_body(monkeypatch):
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=20):
        captured["body"] = json

        class R:
            status_code = 200
            text = ""

            def json(self):
                return {}

            def raise_for_status(self):
                pass

        return R()

    monkeypatch.setattr("dte.requests.post", fake_post)

    meta = {
        "ambiente": "00",
        "version": 2,
        "tipoDte": "01",
        "codigoGeneracion": "ABC",
    }
    token = make_jws({"identificacion": meta})
    _post_dte(dte.DEFAULT_RECEPCION_URL, "Bearer TOKEN", token, meta)

    body_json = captured["body"]
    assert body_json["documento"] == token


def test_enviar_evento_contingencia(monkeypatch, caplog, tmp_path):
    db = DB(":memory:")
    venta_id = create_sale(db)

    sign_calls = {"count": 0, "token": ""}

    def fake_sign(data):
        sign_calls["count"] += 1
        token = make_jws(data)
        sign_calls["token"] = token
        return token

    monkeypatch.setattr("utils.jws.sign_json", fake_sign)
    monkeypatch.setattr(auth, "get_token", lambda: "Bearer JWT")
    monkeypatch.setattr(auth, "get_last_auth_host", lambda: "apitest.dtes.mh.gob.sv")

    calls = []

    def fake_post(url, json=None, headers=None, timeout=20):
        calls.append((url, headers, json))

        class R:
            status_code = 200

            def json(self):
                return {
                    "estado": "Rechazado",
                    "descripcionMsg": "Fallo",
                    "observaciones": {"campo": "invalido"},
                }

            def raise_for_status(self):
                pass

        return R()

    monkeypatch.setattr("dte.requests.post", fake_post)

    orig_load = dte._load_datos_negocio

    def fake_load():
        data = orig_load()
        data.setdefault("dte_api", {})["url"] = dte.DEFAULT_RECEPCION_URL
        data["dte_api"]["ambiente"] = "pruebas"
        return data

    monkeypatch.setattr(dte, "_load_datos_negocio", fake_load)

    caplog.set_level(logging.ERROR)
    data = {
        "identificacion": {
            "version": 2,
            "ambiente": "00",
            "tipoDte": "CON",
            "codigoGeneracion": "EV1",
        },
        "id": venta_id,
    }
    res = enviar_evento_contingencia(db, venta_id, data)
    assert res["estado"] == "Rechazado"
    assert "Fallo" in caplog.text and "campo: invalido" in caplog.text
    row = db.cursor.execute("SELECT estado FROM dte_envios WHERE venta_id=?", (venta_id,)).fetchone()
    assert row["estado"] == "Rechazado"
    assert sign_calls["count"] == 1
    assert len(calls) == 1
    url, headers, body = calls[0]
    assert url == dte.DEFAULT_EVENTO_URL
    assert body["documento"] == sign_calls["token"]
    assert headers["Authorization"] == "Bearer JWT"
    assert headers["Content-Type"] == "application/json"
    assert headers["Accept"] == "application/json"
    assert headers["User-Agent"] == "Vertex-DTE/1.0"


def test_enviar_evento_anulacion(monkeypatch, tmp_path):
    db = DB(":memory:")
    venta_id = create_sale(db)

    sign_calls = {"count": 0, "token": ""}

    def fake_sign(data):
        sign_calls["count"] += 1
        token = make_jws(data)
        sign_calls["token"] = token
        return token

    monkeypatch.setattr("utils.jws.sign_json", fake_sign)
    monkeypatch.setattr(auth, "get_token", lambda: "Bearer JWT")
    monkeypatch.setattr(auth, "get_last_auth_host", lambda: "apitest.dtes.mh.gob.sv")

    calls = []

    def fake_post(url, json=None, headers=None, timeout=20):
        calls.append((url, headers, json))

        class R:
            status_code = 200

            def json(self):
                return {"estado": "Transmitido", "sello": "SSS"}

            def raise_for_status(self):
                pass

        return R()

    monkeypatch.setattr("dte.requests.post", fake_post)

    orig_load = dte._load_datos_negocio

    def fake_load():
        data = orig_load()
        data.setdefault("dte_api", {})["url"] = dte.DEFAULT_RECEPCION_URL
        data["dte_api"]["ambiente"] = "pruebas"
        return data

    monkeypatch.setattr(dte, "_load_datos_negocio", fake_load)

    data = {
        "identificacion": {
            "version": 2,
            "ambiente": "00",
            "tipoDte": "ANU",
            "codigoGeneracion": "EV2",
        },
        "id": venta_id,
    }
    res = enviar_evento_anulacion(db, venta_id, data)
    assert res["estado"] == "Transmitido"
    row = db.cursor.execute("SELECT estado FROM dte_envios WHERE venta_id=?", (venta_id,)).fetchone()
    assert row["estado"] == "Transmitido"
    assert sign_calls["count"] == 1
    assert len(calls) == 1
    url, headers, body = calls[0]
    assert url == dte.DEFAULT_EVENTO_URL
    assert body["documento"] == sign_calls["token"]
    assert headers["Authorization"] == "Bearer JWT"
    assert headers["Content-Type"] == "application/json"
    assert headers["Accept"] == "application/json"
    assert headers["User-Agent"] == "Vertex-DTE/1.0"


def test_enviar_factura_default_contingencia(monkeypatch):
    db = DB(":memory:")
    venta_id = create_sale(db)

    monkeypatch.setattr(dte, "get_default_modo_transmision", lambda: "contingencia")
    monkeypatch.setattr(dte, "_load_dte_api_config", lambda: {"url": "http://example"})
    monkeypatch.setattr(
        "dte.generar_dte_json",
        lambda db_obj, vid: {"resumen": {"totalLetras": "X"}},
    )
    monkeypatch.setattr("dte.apply_schema_patch", lambda data: data)
    monkeypatch.setattr("dte.catalogos.get_dte_schema", lambda t: {})
    monkeypatch.setattr(auth, "get_token", lambda: "T")
    monkeypatch.setattr(auth, "get_last_auth_host", lambda: None)
    monkeypatch.setattr("dte._save_signed_dte", lambda *a, **k: None)
    monkeypatch.setattr("utils.jws.sign_json", lambda data: "TOKEN")
    monkeypatch.setattr(
        "dte.requests.post",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not post")),
    )

    res = enviar_factura(db, venta_id)
    assert res["estado"] == "Pendiente"
    row = db.cursor.execute(
        "SELECT estado, modo FROM dte_envios WHERE venta_id=?", (venta_id,)
    ).fetchone()
    assert row["estado"] == "Pendiente"
    assert row["modo"] == "contingencia"


def test_enviar_nota_credito_default_contingencia(monkeypatch, tmp_path):
    db = DB(":memory:")
    venta_id = create_sale(db)
    nota_id = db.add_nota(venta_id, "credito", "2024-01-02", 10, "motivo")

    monkeypatch.setattr(dte, "get_default_modo_transmision", lambda: "contingencia")
    monkeypatch.setattr(dte, "_load_dte_api_config", lambda: {"url": "http://example"})
    monkeypatch.setattr(
        "dte.generar_nota_credito_json",
        lambda db_obj, nid: {
            "identificacion": {"fecEmi": "2024-01-02", "numeroControl": "1"},
            "receptor": {"nombre": "C"},
            "resumen": {"totalLetras": "X"},
        },
    )
    monkeypatch.setattr("dte.apply_schema_patch", lambda data: data)
    monkeypatch.setattr("dte.catalogos.get_dte_schema", lambda t: {})
    monkeypatch.setattr(auth, "get_token", lambda: "T")
    monkeypatch.setattr(auth, "get_last_auth_host", lambda: None)
    monkeypatch.setattr("dte._save_signed_dte", lambda *a, **k: None)
    monkeypatch.setattr(
        "utils.docs.get_dte_document_paths",
        lambda *a, **k: (tmp_path / "x.pdf", tmp_path / "x.json"),
    )
    monkeypatch.setattr("utils.jws.sign_json", lambda data: "TOKEN")
    monkeypatch.setattr("utils.stable_json.save_file", lambda *a, **k: None)
    monkeypatch.setattr("utils.stable_json.stable_stringify", lambda d, indent=2: "{}")
    monkeypatch.setattr(
        "dte.requests.post",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not post")),
    )

    res = enviar_nota_credito(db, nota_id)
    assert res["estado"] == "Pendiente"
    row = db.cursor.execute(
        "SELECT estado, modo FROM dte_envios WHERE venta_id=?", (nota_id,)
    ).fetchone()
    assert row["estado"] == "Pendiente"
    assert row["modo"] == "contingencia"


def test_enviar_nota_debito_default_contingencia(monkeypatch, tmp_path):
    db = DB(":memory:")
    venta_id = create_sale(db)
    nota_id = db.add_nota(venta_id, "debito", "2024-01-02", 10, "motivo")

    monkeypatch.setattr(dte, "get_default_modo_transmision", lambda: "contingencia")
    monkeypatch.setattr(dte, "_load_dte_api_config", lambda: {"url": "http://example"})
    monkeypatch.setattr(
        "dte.generar_nota_debito_json",
        lambda db_obj, nid: {
            "identificacion": {"fecEmi": "2024-01-02", "numeroControl": "1"},
            "receptor": {"nombre": "C"},
            "resumen": {"totalLetras": "X"},
        },
    )
    monkeypatch.setattr("dte.apply_schema_patch", lambda data: data)
    monkeypatch.setattr("dte.catalogos.get_dte_schema", lambda t: {})
    monkeypatch.setattr(auth, "get_token", lambda: "T")
    monkeypatch.setattr(auth, "get_last_auth_host", lambda: None)
    monkeypatch.setattr(
        "utils.docs.get_dte_document_paths",
        lambda *a, **k: (tmp_path / "x.pdf", tmp_path / "x.json"),
    )
    monkeypatch.setattr("utils.jws.sign_json", lambda data: "TOKEN")
    monkeypatch.setattr("utils.stable_json.save_file", lambda *a, **k: None)
    monkeypatch.setattr("utils.stable_json.stable_stringify", lambda d, indent=2: "{}")
    monkeypatch.setattr(
        "dte.requests.post",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not post")),
    )

    res = enviar_nota_debito(db, nota_id)
    assert res["estado"] == "Pendiente"
    row = db.cursor.execute(
        "SELECT estado, modo FROM dte_envios WHERE venta_id=?", (nota_id,)
    ).fetchone()
    assert row["estado"] == "Pendiente"
    assert row["modo"] == "contingencia"


def test_enviar_nota_remision_default_contingencia(monkeypatch):
    db = DB(":memory:")
    venta_id = create_sale(db)
    nota_id = db.add_nota(venta_id, "remision", "2024-01-02", 10, "motivo")

    monkeypatch.setattr(dte, "get_default_modo_transmision", lambda: "contingencia")
    monkeypatch.setattr(dte, "_load_dte_api_config", lambda: {"url": "http://example"})
    monkeypatch.setattr(
        "nota_remision.generar_nota_remision_desde_db",
        lambda db_obj, nid: {"resumen": {"totalLetras": "X"}},
    )
    monkeypatch.setattr("dte.apply_schema_patch", lambda data: data)
    monkeypatch.setattr("dte.catalogos.get_dte_schema", lambda t: {})
    monkeypatch.setattr(auth, "get_token", lambda: "T")
    monkeypatch.setattr(auth, "get_last_auth_host", lambda: None)
    monkeypatch.setattr("dte._save_signed_dte", lambda *a, **k: None)
    monkeypatch.setattr("utils.jws.sign_json", lambda data: "TOKEN")
    monkeypatch.setattr(
        "dte.requests.post",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not post")),
    )

    res = enviar_nota_remision(db, nota_id)
    assert res["estado"] == "Pendiente"
    row = db.cursor.execute(
        "SELECT estado, modo FROM dte_envios WHERE venta_id=?", (nota_id,)
    ).fetchone()
    assert row["estado"] == "Pendiente"
    assert row["modo"] == "contingencia"

