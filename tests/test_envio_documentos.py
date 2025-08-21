import json
import logging
import pytest

from pathlib import Path
from db import DB
from dte import (
    enviar_factura,
    enviar_nota_credito,
    enviar_evento_contingencia,
    enviar_evento_anulacion,
    _post_dte,
    DTEValidationError,
)
import auth
from tests.conftest import make_jws


def create_sale(db):
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("P1", "X", vid, None, 0, 0, 0, 1)
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
    monkeypatch.setattr(auth, "get_token", lambda: "JWT")
    monkeypatch.setattr(auth, "get_last_auth_host", lambda: "example.com")
    monkeypatch.setattr("dte.validate_dte_json", lambda data: None)
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
                "totalIva": 0,
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

    def fake_post(url, data=None, headers=None, timeout=20):
        calls.append((url, headers, data))
        data = responses.pop(0)

        class R:
            status_code = 200

            def json(self):
                return data

            def raise_for_status(self):
                pass

        return R()

    monkeypatch.setattr("dte.requests.post", fake_post)

    config = {"ambiente": "pruebas", "pruebas": {"recepcion_url": "http://example.com"}}
    cfg_path = Path(__file__).resolve().parents[1] / "config_negocio.json"
    with open(cfg_path, "w", encoding="utf-8") as fh:
        json.dump(config, fh)

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
        assert url == "http://example.com"
        assert body in sign_calls["tokens"]
        assert headers["Authorization"] == "Bearer JWT"
        assert headers["Content-Type"] == "application/json"


def test_no_envia_si_validacion_falla(monkeypatch):
    db = DB(":memory:")
    venta = create_sale(db)

    sent = []

    def fake_post(url, data=None, headers=None, timeout=20):
        sent.append(True)

    monkeypatch.setattr("dte.requests.post", fake_post)
    monkeypatch.setattr(auth, "get_token", lambda: "JWT")

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
    monkeypatch.setattr(auth, "get_token", lambda: "JWT")
    monkeypatch.setattr(auth, "get_last_auth_host", lambda: "example.com")
    monkeypatch.setattr("dte.validate_dte_json", lambda data: None)
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
                "totalIva": 0,
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

    def fake_post(url, data=None, headers=None, timeout=20):
        calls.append((url, headers, data))

        class R:
            status_code = 200

            def json(self):
                return {"estado": "Transmitido", "sello": "XYZ"}

            def raise_for_status(self):
                pass

        return R()

    monkeypatch.setattr("dte.requests.post", fake_post)

    config = {"ambiente": "pruebas", "pruebas": {"recepcion_url": "http://example.com"}}
    cfg_path = Path(__file__).resolve().parents[1] / "config_negocio.json"
    with open(cfg_path, "w", encoding="utf-8") as fh:
        json.dump(config, fh)

    res = enviar_nota_credito(db, nota_id)
    assert res["estado"] == "Transmitido"
    row = db.cursor.execute("SELECT estado FROM dte_envios WHERE venta_id=?", (nota_id,)).fetchone()
    assert row["estado"] == "Transmitido"
    assert sign_calls["count"] == 1
    assert len(calls) == 1
    url, headers, body = calls[0]
    assert url == "http://example.com"
    assert body in sign_calls["tokens"]
    assert headers["Authorization"] == "Bearer JWT"
    assert headers["Content-Type"] == "application/json"


def test_post_dte_sends_raw_jws_body(monkeypatch):
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=20):
        captured["body"] = json["documento"]

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
    _post_dte("http://example.com", "TOKEN", token, meta)

    assert captured["body"] == token
    assert "\n" not in captured["body"]


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
    monkeypatch.setattr(auth, "get_token", lambda: "JWT")
    monkeypatch.setattr(auth, "get_last_auth_host", lambda: "example.com")

    calls = []

    def fake_post(url, data=None, headers=None, timeout=20):
        calls.append((url, headers, data))

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

    config = {"ambiente": "pruebas", "pruebas": {"recepcion_url": "http://example.com"}}
    cfg_path = Path(__file__).resolve().parents[1] / "config_negocio.json"
    with open(cfg_path, "w", encoding="utf-8") as fh:
        json.dump(config, fh)

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
    assert url == "http://example.com"
    assert body == sign_calls["token"]
    assert headers["Authorization"] == "Bearer JWT"
    assert headers["Content-Type"] == "application/json"


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
    monkeypatch.setattr(auth, "get_token", lambda: "JWT")
    monkeypatch.setattr(auth, "get_last_auth_host", lambda: "example.com")

    calls = []

    def fake_post(url, data=None, headers=None, timeout=20):
        calls.append((url, headers, data))

        class R:
            status_code = 200

            def json(self):
                return {"estado": "Transmitido", "sello": "SSS"}

            def raise_for_status(self):
                pass

        return R()

    monkeypatch.setattr("dte.requests.post", fake_post)

    config = {"ambiente": "pruebas", "pruebas": {"recepcion_url": "http://example.com"}}
    cfg_path = Path(__file__).resolve().parents[1] / "config_negocio.json"
    with open(cfg_path, "w", encoding="utf-8") as fh:
        json.dump(config, fh)

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
    assert url == "http://example.com"
    assert body == sign_calls["token"]
    assert headers["Authorization"] == "Bearer JWT"
    assert headers["Content-Type"] == "application/json"

