from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from utils.doc_generation import _maybe_generate_cr

from tests.helpers.retenciones import load_ccf_sample


def _insert_sale(db, venta_id: int, total: float = 100.0) -> None:
    db.cursor.execute(
        "INSERT INTO ventas (id, fecha, total) VALUES (?, ?, ?)",
        (venta_id, "2024-01-01", total),
    )
    db.conn.commit()


def _retencion_block(base: str = "100.00") -> dict:
    return {
        "enabled": True,
        "base": base,
        "tasa": "1",
        "codigoRetencionMH": "22",
    }


def test_ccf_generates_cr_with_control_reference(monkeypatch, db_conn, tmp_path) -> None:
    monkeypatch.setattr("utils.doc_generation.RETENCIONES_DIR", str(tmp_path / "retenciones"))
    _insert_sale(db_conn, venta_id=55)
    factura = load_ccf_sample()

    manager = SimpleNamespace(db=db_conn)
    result = _maybe_generate_cr(manager, 55, factura, _retencion_block(), ambiente="00")

    assert result and result["status"] == "created"
    payload = result["payload"]
    rel = payload["cuerpoDocumento"][0]
    assert rel["tipoDoc"] == 1
    assert rel["numDocumento"] == factura["identificacion"]["numeroControl"]
    assert payload["resumen"]["totalSujetoRetencion"] == Decimal("100.00")
    assert payload["resumen"]["totalIVAretenido"] == Decimal("1.00")
    assert "codGeneracion" not in rel
    assert Path(result["path"]).exists()


def test_non_ccf_retencion_is_skipped(monkeypatch, db_conn, tmp_path) -> None:
    monkeypatch.setattr("utils.doc_generation.RETENCIONES_DIR", str(tmp_path / "retenciones"))
    _insert_sale(db_conn, venta_id=56)
    factura = load_ccf_sample()
    factura["identificacion"]["tipoDte"] = "01"

    manager = SimpleNamespace(db=db_conn)
    result = _maybe_generate_cr(manager, 56, factura, _retencion_block(), ambiente="00")

    assert result and result["status"] == "skipped"
    assert "CR-07 solo para DTE 03" in result.get("reason", "")
    assert db_conn.get_retencion_cr(56) is None
