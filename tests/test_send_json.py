import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import facturacion_tab
from db import DB


def test_send_json_success(monkeypatch, qt_app, tmp_path):
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

    tab.send_json()

    assert called["path"] == str(json_path)
    assert "called" in infos


def test_send_json_invalid(monkeypatch, qt_app, tmp_path):
    json_path = tmp_path / "doc.json"
    json_path.write_text("{ invalid")
    db = DB(":memory:")
    man = SimpleNamespace(db=db, _clientes=[], _Distribuidores=[])
    tab = facturacion_tab.FacturacionTab(man)

    monkeypatch.setattr(
        facturacion_tab.QFileDialog,
        "getOpenFileName",
        lambda *a, **k: (str(json_path), None),
    )

    called = {}
    monkeypatch.setattr(
        facturacion_tab.dte,
        "transmitir_dte_orphan",
        lambda *a, **k: called.setdefault("called", True),
    )
    crit = {}
    monkeypatch.setattr(
        facturacion_tab.QMessageBox,
        "critical",
        lambda *a, **k: crit.setdefault("called", True),
    )

    tab.send_json()

    assert "called" in crit
    assert "called" not in called
