import pytest

from db import DB
import dte
from dte import transmitir_dte
import auth
from utils import jws


@pytest.fixture
def db_venta():
    db = DB(":memory:")
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("P1", "X", vid, None, 0, 0, 0, 1)
    pid = db.cursor.lastrowid
    venta = db.add_venta("2024-01-01", 10)
    db.add_detalle_venta(venta, pid, 1, 10, vendedor_id=vid)
    return db, venta


def test_envio_hacienda(monkeypatch, db_venta):
    db, venta_id = db_venta

    captured_payload = {}

    def fake_sign_json(payload, cert, phrase, key):
        captured_payload["data"] = payload
        return "FAKE_SIGNATURE"

    monkeypatch.setattr(jws, "sign_json", fake_sign_json)
    monkeypatch.setattr(dte, "validate_dte_json", lambda data: None)

    token_calls = {"count": 0}
    original_get_token = auth.get_token

    def tracking_get_token():
        token_calls["count"] += 1
        return original_get_token()

    monkeypatch.setattr(auth, "get_token", tracking_get_token)
    monkeypatch.setattr(auth, "_get_credentials", lambda: ("NIT", "PWD"))
    auth._access_token = None
    auth._expires_at = 0

    def fake_post(url, data=None, json=None, headers=None, timeout=20):
        class Resp:
            status_code = 200

            def __init__(self, payload):
                self._payload = payload

            def json(self):
                return self._payload

            def raise_for_status(self):
                pass

        if url.endswith("/auth"):
            return Resp({"access_token": "TOK", "expires_in": 300})
        if url.endswith("/recepciondte"):
            return Resp({"estado": "RECIBIDO", "sello": "XYZ"})
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr("requests.post", fake_post)

    transmitir_dte(db, venta_id)

    assert "data" in captured_payload
    assert token_calls["count"] == 1
    row = db.cursor.execute(
        "SELECT estado, sello, fecha_hora FROM dte_envios WHERE venta_id=?", (venta_id,)
    ).fetchone()
    assert row["estado"] == "RECIBIDO"
    assert row["sello"] == "XYZ"
    assert row["fecha_hora"]
