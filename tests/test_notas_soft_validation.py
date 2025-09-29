import json
import logging
from pathlib import Path
from types import SimpleNamespace

import dte
import nota_credito_electronica as nce
import nota_debito_electronica as nde


def _load_golden(name: str) -> dict:
    path = Path(__file__).resolve().parent / "goldens" / name
    return json.loads(path.read_text(encoding="utf-8"))


class _DummyCursor:
    def __init__(self, row):
        self._row = row

    def execute(self, *_args, **_kwargs):
        return self

    def fetchone(self):
        return self._row


class _DummyDB:
    def __init__(self, nota_row, snapshot, venta):
        self._nota_row = nota_row
        self._snapshot = snapshot
        self._venta = venta
        self.cursor = _DummyCursor(nota_row)

    def get_venta_by_id(self, _venta_id):
        return self._venta

    def get_venta_credito_fiscal(self, _venta_id):
        return None

    def get_snapshot_by_venta(self, _venta_id):
        return self._snapshot


def _patch_generics(monkeypatch):
    monkeypatch.setattr(
        dte,
        "generar_cabecera_dte_data",
        lambda *args, **_kwargs: {
            "codigo_generacion": "00000000-0000-4000-8000-000000000001",
            "numero_control": "DTE-00-S001P001-000000000000001",
            "correlativo": 1,
            "tipo_modelo": 1,
            "tipo_operacion": 1,
            "tipo_contingencia": None,
            "motivo_contin": None,
        },
    )
    monkeypatch.setattr(dte, "sanitize_dte_payload", lambda data, _schema=None: data)
    monkeypatch.setattr(nce.metrics, "inc", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(nde.metrics, "inc", lambda *_args, **_kwargs: None)


def _build_snapshot():
    payload = _load_golden("fc.json")
    ident = payload["identificacion"]
    ident["tipoDte"] = "01"
    ident["codigoGeneracion"] = "00000000-0000-4000-8000-000000000002"
    ident["numeroControl"] = "DTE-01-S001P001-000000000000999"
    ident["fecEmi"] = "2024-01-01"
    return SimpleNamespace(
        payload=payload,
        uuid="00000000-0000-4000-8000-000000000002",
        fecha_emision="2024-02-01",
    )


def _venta():
    return {"fecha": "2024-02-01"}


def test_nce_relacion_fecha_warning(monkeypatch, caplog):
    _patch_generics(monkeypatch)
    snapshot = _build_snapshot()
    nota_row = {
        "id": 7,
        "tipo": "credito",
        "venta_id": 11,
        "monto": "5",
        "detalles": None,
        "motivo": "ajuste",
    }
    db = _DummyDB(nota_row, snapshot, _venta())

    with caplog.at_level(logging.WARNING):
        result = nce.generar_nce_desde_nota(
            db,
            nota_row["id"],
            ambiente="00",
            strict_snapshot=True,
        )

    assert result
    assert (
        "documentoRelacionado.fechaEmision: valor no verificable localmente"
        in caplog.text
    )


def test_nde_relacion_fecha_warning(monkeypatch, caplog):
    _patch_generics(monkeypatch)
    snapshot = _build_snapshot()
    nota_row = {
        "id": 8,
        "tipo": "debito",
        "venta_id": 12,
        "monto": "5",
        "detalles": None,
        "motivo": "ajuste",
    }
    db = _DummyDB(nota_row, snapshot, _venta())

    with caplog.at_level(logging.WARNING):
        result = nde.generar_nde_desde_nota(
            db,
            nota_row["id"],
            ambiente="00",
            strict_snapshot=True,
        )

    assert result
    assert (
        "documentoRelacionado.fechaEmision: valor no verificable localmente"
        in caplog.text
    )
