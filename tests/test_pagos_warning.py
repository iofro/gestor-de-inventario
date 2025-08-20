import json
import logging
from pathlib import Path

import dte


def _load_fc():
    path = Path(__file__).resolve().parent / "goldens" / "fc.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_warns_on_payment_mismatch(monkeypatch, caplog):
    data = _load_fc()
    # Introduce discrepancy greater than one cent
    data["resumen"]["pagos"][0]["montoPago"] = "28.45"
    monkeypatch.setattr(
        dte,
        "normalizar_pagos",
        lambda pagos, total, **kwargs: pagos or [],
    )
    with caplog.at_level(logging.WARNING):
        dte.validate_dte_json(data)
    assert "Pagos no cuadran con totalPagar" in caplog.text
