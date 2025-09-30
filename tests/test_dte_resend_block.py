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
    db.registrar_envio_dte(
        venta,
        "normal",
        "PROCESADO",
        "S",
        codigo_generacion="ABC",
        numero_control="NC1",
    )
    db.registrar_envio_dte(venta, "normal", "Rechazado", "")

    called = {"sign": 0, "post": 0}

    monkeypatch.setattr(auth, "get_token", lambda: "T")
    monkeypatch.setattr(auth, "get_last_auth_host", lambda: None)
    monkeypatch.setattr(dte, "_load_dte_api_config", lambda: {"url": "http://example"})

    def fake_sign(data):  # pragma: no cover - should not be called
        called["sign"] += 1
        return "token"

    def fake_post(url, documento, dte_data, *args, **kwargs):  # pragma: no cover - should not be called
        called["post"] += 1
        return {"estado": "Procesado"}

    monkeypatch.setattr("utils.jws.sign_json", fake_sign)
    monkeypatch.setattr(dte, "_post_dte", fake_post)

    data = {
        "identificacion": {
            "tipoDte": "01",
            "codigoGeneracion": "abc",
            "numeroControl": "nc1",
        },
        "resumen": {"totalLetras": "X"},
    }
    with pytest.raises(ValueError):
        dte._enviar_documento(db, venta, data, "normal")

    assert called["sign"] == 0
    assert called["post"] == 0


def test_enviar_documento_reenvio_con_uuid_nuevo(monkeypatch):
    db = DB(":memory:")
    venta = create_sale(db)
    db.registrar_envio_dte(
        venta,
        "normal",
        "PROCESADO",
        "S",
        codigo_generacion="OLD-UUID",
        numero_control="NC-OLD",
    )

    called = {"sign": 0, "post": 0}

    monkeypatch.setattr(auth, "get_token", lambda: "T")
    monkeypatch.setattr(auth, "get_last_auth_host", lambda: None)
    monkeypatch.setattr(dte, "_load_dte_api_config", lambda: {"url": "http://example"})

    def fake_sign(data):
        called["sign"] += 1
        return "token"

    def fake_post(url, documento, dte_data, *args, **kwargs):
        called["post"] += 1
        return {"estado": "Procesado"}

    data = {
        "identificacion": {
            "tipoDte": "01",
            "codigoGeneracion": "NEW-uuid",
            "numeroControl": "NC-NEW",
        },
        "resumen": {"totalLetras": "X"},
    }

    monkeypatch.setattr("utils.jws.sign_json", fake_sign)
    monkeypatch.setattr(dte, "_decode_jws_payload", lambda token: {"identificacion": data["identificacion"]})
    monkeypatch.setattr(dte, "_post_dte", fake_post)
    monkeypatch.setattr(dte, "_save_signed_dte", lambda *args, **kwargs: None)

    resp = dte._enviar_documento(db, venta, data, "normal")

    assert resp["estado"] == "Procesado"
    assert called["sign"] == 1
    assert called["post"] == 1


def test_detectar_estado_factura_prioriza_exitosos(monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    facturacion_tab = pytest.importorskip(
        "facturacion_tab", reason="PyQt5 no disponible", exc_type=ImportError
    )
    FacturacionTab = facturacion_tab.FacturacionTab

    db = DB(":memory:")
    venta = create_sale(db)
    db.registrar_envio_dte(
        venta,
        "normal",
        "PROCESADO",
        "S",
        {"estado": "Procesado"},
        codigo_generacion="ABC",
        numero_control="NC1",
    )
    db.registrar_envio_dte(
        venta,
        "normal",
        "Rechazado",
        "",
        {"estado": "Rechazado"},
        codigo_generacion="ABC",
        numero_control="NC1",
    )

    _, envio = FacturacionTab._detectar_estado_factura(
        {},
        cur=db.cursor,
        venta_id=venta,
        codigo_generacion="ABC",
        numero_control="NC1",
    )
    assert envio == "Rechazado"


def test_detectar_estado_factura_muestra_observado(monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    facturacion_tab = pytest.importorskip(
        "facturacion_tab", reason="PyQt5 no disponible", exc_type=ImportError
    )
    FacturacionTab = facturacion_tab.FacturacionTab

    db = DB(":memory:")
    venta = create_sale(db)
    db.registrar_envio_dte(
        venta,
        "normal",
        "PROCESADO",
        "S",
        {
            "estado": "Procesado",
            "descripcionMsg": "RECIBIDO CON OBSERVACIONES",
            "observaciones": ["detalle"],
        },
        codigo_generacion="ABC-OBS",
    )

    _, envio = FacturacionTab._detectar_estado_factura(
        {},
        cur=db.cursor,
        venta_id=venta,
        codigo_generacion="ABC-OBS",
        numero_control=None,
    )

    assert envio == "Enviado (observado)"


def test_detectar_estado_factura_muestra_tag_rechazado(monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    facturacion_tab = pytest.importorskip(
        "facturacion_tab", reason="PyQt5 no disponible", exc_type=ImportError
    )
    FacturacionTab = facturacion_tab.FacturacionTab

    db = DB(":memory:")
    venta = create_sale(db)
    db.registrar_envio_dte(
        venta,
        "normal",
        "RECHAZADO",
        "S",
        {
            "estado": "Rechazado",
            "codigoMsg": "096",
            "descripcionMsg": "DOCUMENTO NO CUMPLE ESQUEMA JSON",
        },
        codigo_generacion="ABC-RECH",
    )

    _, envio = FacturacionTab._detectar_estado_factura(
        {},
        cur=db.cursor,
        venta_id=venta,
        codigo_generacion="ABC-RECH",
        numero_control=None,
    )

    assert envio == "Rechazado (schema)"


def test_detectar_estado_factura_nota_remision(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    facturacion_tab = pytest.importorskip(
        "facturacion_tab", reason="PyQt5 no disponible", exc_type=ImportError
    )
    FacturacionTab = facturacion_tab.FacturacionTab

    pdf = tmp_path / "DTE-09-S001P001-000000000000001.pdf"
    pdf.write_text("PDF")
    json_path = pdf.with_suffix(".json")
    json_path.write_text("{}")

    estado, envio = FacturacionTab._detectar_estado_factura(
        None,
        pdf_path=str(pdf),
        json_path=str(json_path),
        doc_tipo="Nota de remisión",
    )

    assert estado == "Completa"

