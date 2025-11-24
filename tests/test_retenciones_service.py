from __future__ import annotations

import json

import pytest

from retenciones.builder import serialize_cr
from retenciones.catalogos_retencion import CatalogosRetencion
from retenciones.service import RetencionCRService

from tests.helpers.retenciones import load_ccf_sample


def _insert_sale(db, venta_id: int = 1, total: float = 26.95) -> None:
    db.cursor.execute(
        "INSERT INTO ventas (id, fecha, total) VALUES (?, ?, ?)",
        (venta_id, "2024-01-01", total),
    )
    db.conn.commit()


def _fixed_ident() -> dict:
    return {
        "numeroControl": "DTE-07-TEST2024-000000000000001",
        "codigoGeneracion": "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE",
    }


def test_prepare_cr_persists_payload_and_blocks_duplicates(db_conn) -> None:
    _insert_sale(db_conn, venta_id=1)
    service = RetencionCRService(db_conn, catalogos=CatalogosRetencion())
    factura = load_ccf_sample()
    payload = service.prepare_cr(1, factura=factura, identificacion_override=_fixed_ident())

    stored = db_conn.get_retencion_cr(1)
    assert stored is not None
    assert stored["payload_json"] == serialize_cr(payload, indent=None)

    with pytest.raises(ValueError):
        service.prepare_cr(1, factura=factura, identificacion_override=_fixed_ident())


def test_prepare_cr_rejects_non_ccf(db_conn) -> None:
    _insert_sale(db_conn, venta_id=2)
    service = RetencionCRService(db_conn, catalogos=CatalogosRetencion())
    factura = load_ccf_sample()
    factura["identificacion"]["tipoDte"] = "01"

    with pytest.raises(ValueError, match="CR-07 solo para DTE 03"):
        service.prepare_cr(2, factura=factura, identificacion_override=_fixed_ident())


def test_sign_cr_uses_persisted_json(monkeypatch, db_conn) -> None:
    _insert_sale(db_conn, venta_id=3)
    service = RetencionCRService(db_conn, catalogos=CatalogosRetencion())
    factura = load_ccf_sample()
    payload = service.prepare_cr(3, factura=factura, identificacion_override=_fixed_ident())

    stored_json = db_conn.get_retencion_cr(3)["payload_json"]
    monkeypatch.setattr("retenciones.service.sign_cr_payload", lambda payload, **_: "JWS-TOKEN")

    token = service.sign_cr(3, payload=payload)
    assert token == "JWS-TOKEN"

    with pytest.raises(ValueError, match="no coincide con el CR persistido"):
        service.sign_cr(3, payload="{}")


def test_sign_and_send_cr_updates_db(monkeypatch, db_conn) -> None:
    _insert_sale(db_conn, venta_id=10)
    service = RetencionCRService(db_conn, catalogos=CatalogosRetencion())
    factura = load_ccf_sample()
    service.prepare_cr(10, factura=factura, identificacion_override=_fixed_ident())

    monkeypatch.setattr("retenciones.service.sign_cr_payload", lambda payload, **_: "JWS-TOKEN")
    monkeypatch.setattr(
        "retenciones.service._load_dte_api_config",
        lambda: {
            "url": "https://apitest.dtes.mh.gob.sv/fesv/recepciondte",
            "ambiente": "pruebas",
        },
    )

    posted: dict = {}

    def fake_post(url, documento, dte_data, config, **kwargs):
        posted.update(
            {
                "url": url,
                "documento": documento,
                "dte": dte_data,
            }
        )
        return {
            "estado": "ACEPTADO",
            "codigoGeneracion": dte_data["identificacion"]["codigoGeneracion"],
            "selloRecibido": "A" * 40,
            "detalle": "Procesado",
            "fhProcesamiento": "2024-01-01T12:00:00",
        }

    monkeypatch.setattr("retenciones.service._post_dte_with_config", fake_post)

    response = service.send_cr(10)
    assert response["estado"] == "ACEPTADO"

    stored = db_conn.get_retencion_cr(10)
    assert stored["jws"] == "JWS-TOKEN"
    assert stored["estado"] == "ACEPTADO"
    assert stored["sello"] == "A" * 40

    respuesta = json.loads(stored["respuesta"])
    assert respuesta["estado"] == "ACEPTADO"

    assert posted["documento"] == "JWS-TOKEN"
    assert posted["url"].endswith("/fesv/recepciondte")
