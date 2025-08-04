from db import DB
from dte import transmitir_dte, _post_dte
import json


def create_sale(db):
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("P1", "X", vid, None, 0, 0, 0, 1)
    pid = db.cursor.lastrowid
    venta_id = db.add_venta("2024-01-01", 10)
    db.add_detalle_venta(venta_id, pid, 1, 10, vendedor_id=vid)
    return venta_id


def test_transmitir_dte_contingencia(tmp_path):
    db = DB(":memory:")
    venta = create_sale(db)
    res = transmitir_dte(db, venta, modo="contingencia")
    assert res["estado"] == "Pendiente"
    row = db.cursor.execute(
        "SELECT estado FROM dte_envios WHERE venta_id=?", (venta,)
    ).fetchone()
    assert row["estado"] == "Pendiente"


def test_transmitir_dte_normal(monkeypatch, tmp_path):
    db = DB(":memory:")
    venta = create_sale(db)

    monkeypatch.setattr("utils.jws.get_cert_config", lambda: (None, None, None))
    monkeypatch.setattr("utils.jws.sign_json", lambda data, cert, p, key: "SIGNED")
    monkeypatch.setattr("auth.get_token", lambda: "JWT")
    monkeypatch.setattr("dte.validate_dte_json", lambda data: None)

    def fake_post(url, json=None, headers=None, timeout=20):
        class R:
            status_code = 200
            def json(self):
                return {"estado": "Transmitido", "sello": "ABC123"}
            def raise_for_status(self):
                pass
        return R()

    monkeypatch.setattr("dte.requests.post", fake_post)

    config = {"ambiente": "pruebas", "recepcion_url": {"pruebas": "http://example.com"}}
    with open("config_negocio.json", "w", encoding="utf-8") as fh:
        json.dump(config, fh)

    res = transmitir_dte(db, venta)
    assert res["estado"] == "Transmitido"
    row = db.cursor.execute(
        "SELECT estado, sello FROM dte_envios WHERE venta_id=?", (venta,)
    ).fetchone()
    assert row["estado"] == "Transmitido"
    assert row["sello"] == "ABC123"


def test_post_dte_uses_bearer(monkeypatch):
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=20):
        captured["headers"] = headers
        class R:
            status_code = 200
            def json(self):
                return {}
            def raise_for_status(self):
                pass
        return R()

    monkeypatch.setattr("dte.requests.post", fake_post)
    _post_dte("http://example.com", "TOKEN", "SIGNED")
    assert captured["headers"]["Authorization"] == "Bearer TOKEN"


def test_consultar_envio_dte():
    db = DB(":memory:")
    venta = create_sale(db)
    db.registrar_envio_dte(venta, "normal", "Transmitido", "S", '{"ok": true}')
    assert db.consultar_envio_dte(venta) == {"ok": True}
