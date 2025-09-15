import os

import pytest

import auth
import dte
from db import DB


def create_sale(db: DB) -> int:
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("P1", "X", None, vid, None, 0, 0, 0, 1)
    pid = db.cursor.lastrowid
    venta_id = db.add_venta("2024-01-01", 10)
    db.add_detalle_venta(venta_id, pid, 1, 10, vendedor_id=vid)
    return venta_id


def test_enviar_documento_rechaza_reenvio_exitoso(monkeypatch):
    db = DB(":memory:")
    venta = create_sale(db)
    db.registrar_envio_dte(venta, "normal", "Procesado", "S")

    called = {"sign": 0, "post": 0}

    monkeypatch.setattr(auth, "get_token", lambda: "T")
    monkeypatch.setattr(auth, "get_last_auth_host", lambda: None)
    monkeypatch.setattr(dte, "_load_dte_api_config", lambda: {"url": "http://example"})

    def fake_sign(data):  # pragma: no cover - should not be called
        called["sign"] += 1
        return "token"

    def fake_post(url, token, signed, meta):  # pragma: no cover - should not be called
        called["post"] += 1
        return {"estado": "Procesado"}

    monkeypatch.setattr("utils.jws.sign_json", fake_sign)
    monkeypatch.setattr(dte, "_post_dte", fake_post)

    data = {
        "identificacion": {"tipoDte": "01", "codigoGeneracion": "A"},
        "resumen": {"totalLetras": "X"},
    }
    with pytest.raises(ValueError):
        dte._enviar_documento(db, venta, data, "normal")

    assert called["sign"] == 0
    assert called["post"] == 0


def test_detectar_estado_factura_prioriza_exitosos(monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from facturacion_tab import FacturacionTab

    db = DB(":memory:")
    venta = create_sale(db)
    db.registrar_envio_dte(venta, "normal", "Transmitido", "S")
    db.registrar_envio_dte(venta, "normal", "Rechazado", "")

    _, envio = FacturacionTab._detectar_estado_factura(
        {}, cur=db.cursor, venta_id=venta
    )
    assert envio == "Enviado"

