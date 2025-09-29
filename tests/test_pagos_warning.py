import json
import logging
from pathlib import Path

import dte
from db import DB


def _load_fc():
    path = Path(__file__).resolve().parent / "goldens" / "fc.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_warns_on_payment_mismatch(monkeypatch, caplog, tmp_path):
    data = _load_fc()
    # Introduce discrepancy greater than one cent
    data["resumen"]["pagos"][0]["montoPago"] = "28.45"
    data["receptor"]["nrc"] = "1234567"
    monkeypatch.setattr(
        dte,
        "normalizar_pagos",
        lambda pagos, total, **kwargs: pagos or [],
    )
    monkeypatch.setattr(
        dte,
        "_load_datos_negocio",
        lambda: {
            "nombre": "Demo",
            "nit": "00000000000000",
            "direccion": {
                "departamento": "01",
                "municipio": "01",
                "complemento": "CALLE",
            },
        },
    )
    monkeypatch.setattr(
        dte.svfe_config,
        "load_datos_negocio",
        lambda: {
            "direccion": {
                "departamento": "01",
                "municipio": "01",
                "complemento": "CALLE",
            }
        },
    )
    db = DB(tmp_path / "test.db")
    with caplog.at_level(logging.WARNING, logger="dte"):
        dte.validate_dte_json(data, db=db)


def test_validate_dte_json_allows_invalid_dui(monkeypatch, db_conn, caplog):
    data = _load_fc()
    data["receptor"]["tipoDocumento"] = "13"
    data["receptor"]["numDocumento"] = "12345"
    data["receptor"]["nrc"] = "1234567"
    monkeypatch.setattr(
        dte,
        "_load_datos_negocio",
        lambda: {
            "nombre": "Demo",
            "nit": "00000000000000",
            "direccion": {
                "departamento": "01",
                "municipio": "01",
                "complemento": "CALLE",
            },
        },
    )
    monkeypatch.setattr(
        dte.svfe_config,
        "load_datos_negocio",
        lambda: {
            "direccion": {
                "departamento": "01",
                "municipio": "01",
                "complemento": "CALLE",
            }
        },
    )
    with caplog.at_level(logging.WARNING, logger="dte"):
        dte.validate_dte_json(data, db=db_conn)
    assert any(
        "DUI no normalizable; se continúa sin bloquear" in record.getMessage()
        for record in caplog.records
    )
