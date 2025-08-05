import json
import logging

from db import DB
from dte import (
    enviar_factura,
    enviar_nota_credito,
    enviar_evento_contingencia,
    enviar_evento_anulacion,
)


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

    monkeypatch.setattr("utils.jws.get_cert_config", lambda: (None, None, None))
    monkeypatch.setattr("utils.jws.sign_json", lambda data, c, p, k: "SIGNED")
    monkeypatch.setattr("auth.get_token", lambda: "JWT")
    monkeypatch.setattr("dte.validate_dte_json", lambda data: None)

    responses = [
        {"estado": "Rechazado", "descripcionMsg": "Error", "observaciones": ["campo"]},
        {"estado": "Transmitido", "sello": "ABC"},
    ]

    def fake_post(url, json=None, headers=None, timeout=20):
        data = responses.pop(0)
        class R:
            status_code = 200
            def json(self):
                return data
            def raise_for_status(self):
                pass
        return R()

    monkeypatch.setattr("dte.requests.post", fake_post)

    config = {"ambiente": "pruebas", "recepcion_url": {"pruebas": "http://example.com"}}
    with open("config_negocio.json", "w", encoding="utf-8") as fh:
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


def test_enviar_nota_credito(monkeypatch, tmp_path):
    db = DB(":memory:")
    venta = create_sale(db)
    nota_id = db.add_nota(venta, "credito", "2024-01-02", 10, "motivo")

    monkeypatch.setattr("utils.jws.get_cert_config", lambda: (None, None, None))
    monkeypatch.setattr("utils.jws.sign_json", lambda data, c, p, k: "SIGNED")
    monkeypatch.setattr("auth.get_token", lambda: "JWT")
    monkeypatch.setattr("dte.validate_dte_json", lambda data: None)

    def fake_post(url, json=None, headers=None, timeout=20):
        class R:
            status_code = 200
            def json(self):
                return {"estado": "Transmitido", "sello": "XYZ"}
            def raise_for_status(self):
                pass
        return R()

    monkeypatch.setattr("dte.requests.post", fake_post)

    config = {"ambiente": "pruebas", "recepcion_url": {"pruebas": "http://example.com"}}
    with open("config_negocio.json", "w", encoding="utf-8") as fh:
        json.dump(config, fh)

    res = enviar_nota_credito(db, nota_id)
    assert res["estado"] == "Transmitido"
    row = db.cursor.execute("SELECT estado FROM dte_envios WHERE venta_id=?", (nota_id,)).fetchone()
    assert row["estado"] == "Transmitido"


def test_enviar_evento_contingencia(monkeypatch, caplog, tmp_path):
    db = DB(":memory:")
    venta_id = create_sale(db)

    monkeypatch.setattr("utils.jws.get_cert_config", lambda: (None, None, None))
    monkeypatch.setattr("utils.jws.sign_json", lambda data, c, p, k: "SIGNED")
    monkeypatch.setattr("auth.get_token", lambda: "JWT")

    def fake_post(url, json=None, headers=None, timeout=20):
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

    config = {"ambiente": "pruebas", "recepcion_url": {"pruebas": "http://example.com"}}
    with open("config_negocio.json", "w", encoding="utf-8") as fh:
        json.dump(config, fh)

    caplog.set_level(logging.ERROR)
    res = enviar_evento_contingencia(db, venta_id, {"id": venta_id})
    assert res["estado"] == "Rechazado"
    assert "Fallo" in caplog.text and "campo: invalido" in caplog.text
    row = db.cursor.execute("SELECT estado FROM dte_envios WHERE venta_id=?", (venta_id,)).fetchone()
    assert row["estado"] == "Rechazado"


def test_enviar_evento_anulacion(monkeypatch, tmp_path):
    db = DB(":memory:")
    venta_id = create_sale(db)

    monkeypatch.setattr("utils.jws.get_cert_config", lambda: (None, None, None))
    monkeypatch.setattr("utils.jws.sign_json", lambda data, c, p, k: "SIGNED")
    monkeypatch.setattr("auth.get_token", lambda: "JWT")

    def fake_post(url, json=None, headers=None, timeout=20):
        class R:
            status_code = 200
            def json(self):
                return {"estado": "Transmitido", "sello": "SSS"}
            def raise_for_status(self):
                pass
        return R()

    monkeypatch.setattr("dte.requests.post", fake_post)

    config = {"ambiente": "pruebas", "recepcion_url": {"pruebas": "http://example.com"}}
    with open("config_negocio.json", "w", encoding="utf-8") as fh:
        json.dump(config, fh)

    res = enviar_evento_anulacion(db, venta_id, {"id": venta_id})
    assert res["estado"] == "Transmitido"
    row = db.cursor.execute("SELECT estado FROM dte_envios WHERE venta_id=?", (venta_id,)).fetchone()
    assert row["estado"] == "Transmitido"

