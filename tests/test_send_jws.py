from types import SimpleNamespace

import facturacion_tab
from db import DB


def test_send_jws_token(monkeypatch, qt_app, tmp_path):
    jws_path = tmp_path / "doc.jws"
    token = "header.payload.signature"
    jws_path.write_text(token)
    db = DB(":memory:")
    man = SimpleNamespace(db=db, _clientes=[], _Distribuidores=[])
    tab = facturacion_tab.FacturacionTab(man)

    monkeypatch.setattr(
        facturacion_tab.QFileDialog,
        "getOpenFileName",
        lambda *a, **k: (str(jws_path), None),
    )

    called = {}

    def fake_send(token_):
        called["token"] = token_
        return {"estado": "Transmitido"}

    monkeypatch.setattr(facturacion_tab.dte, "enviar_dte_a_hacienda", fake_send)
    infos = {}
    monkeypatch.setattr(
        facturacion_tab.QMessageBox,
        "information",
        lambda *a, **k: infos.setdefault("called", True),
    )
    monkeypatch.setattr(facturacion_tab.QMessageBox, "critical", lambda *a, **k: None)

    tab.send_jws()

    assert called["token"] == token
    assert "called" in infos


def test_send_jws_json(monkeypatch, qt_app, tmp_path):
    json_path = tmp_path / "doc.json"
    json_path.write_text("{}")
    db = DB(":memory:")
    man = SimpleNamespace(db=db, _clientes=[], _Distribuidores=[])
    tab = facturacion_tab.FacturacionTab(man)

    monkeypatch.setattr(
        facturacion_tab.QFileDialog,
        "getOpenFileName",
        lambda *a, **k: (str(json_path), None),
    )

    called = {}

    def fake_transmit(db_, path):
        called["path"] = path
        return {"estado": "Transmitido"}

    monkeypatch.setattr(facturacion_tab.dte, "transmitir_dte_orphan", fake_transmit)
    infos = {}
    monkeypatch.setattr(
        facturacion_tab.QMessageBox,
        "information",
        lambda *a, **k: infos.setdefault("called", True),
    )
    monkeypatch.setattr(facturacion_tab.QMessageBox, "critical", lambda *a, **k: None)

    tab.send_jws()

    assert called["path"] == str(json_path)
    assert "called" in infos

