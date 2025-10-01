from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from evento_contingencia import (
    TZ_EL_SALVADOR,
    build_evento_contingencia,
    make_event_filename,
    save_evento_contingencia_json,
)
from utils.stable_json import stable_stringify


@pytest.fixture(autouse=True)
def _patch_datos_negocio(monkeypatch):
    monkeypatch.setattr(
        "evento_contingencia.dte._load_datos_negocio",
        lambda: {"dte_api": {"ambiente": "produccion"}},
    )


def _sample_datetime(hour: int) -> datetime:
    return datetime(2024, 1, 10, hour, 30, 15, tzinfo=TZ_EL_SALVADOR)


def test_build_v3_and_ambiente_ok(monkeypatch):
    uuid_val = "2933ad69-e11a-4f88-8fd7-0f9e3646c4ba"
    monkeypatch.setattr("evento_contingencia.uuid4", lambda: uuid_val)

    before = datetime.now(TZ_EL_SALVADOR)
    payload = build_evento_contingencia(
        tipo_contingencia=3,
        motivo=None,
        f_inicio=_sample_datetime(8),
        f_fin=_sample_datetime(12),
        dtes=[{"codigoGeneracion": "abc", "tipoDoc": "1"}],
    )
    after = datetime.now(TZ_EL_SALVADOR)

    ident = payload["identificacion"]
    assert ident["version"] == 3
    assert ident["ambiente"] == "01"
    assert ident["codigoGeneracion"] == uuid_val.upper()

    f_tx = datetime.strptime(ident["fTransmision"], "%Y-%m-%d").date()
    h_tx = datetime.strptime(ident["hTransmision"], "%H:%M:%S").time()
    tx_dt = datetime.combine(f_tx, h_tx, tzinfo=TZ_EL_SALVADOR)
    lower_bound = before - timedelta(seconds=1)
    upper_bound = after + timedelta(seconds=1)
    assert lower_bound <= tx_dt <= upper_bound


@pytest.mark.parametrize(
    "ambiente_value",
    [
        "01",
        1,
        "produccion",
        "producción",
        "prod",
        "production",
        "prod-01",
    ],
)
def test_ambiente_produccion_variants(monkeypatch, ambiente_value):
    monkeypatch.setattr(
        "evento_contingencia.dte._load_datos_negocio",
        lambda: {"dte_api": {"ambiente": ambiente_value}},
    )

    payload = build_evento_contingencia(
        tipo_contingencia=1,
        motivo=None,
        f_inicio=_sample_datetime(8),
        f_fin=_sample_datetime(9),
        dtes=[{"codigoGeneracion": "abc", "tipoDoc": "01"}],
    )

    assert payload["identificacion"]["ambiente"] == "01"


@pytest.mark.parametrize(
    "ambiente_value",
    ["00", 0, "pruebas", "test", "sandbox"],
)
def test_ambiente_pruebas_variants(monkeypatch, ambiente_value):
    monkeypatch.setattr(
        "evento_contingencia.dte._load_datos_negocio",
        lambda: {"dte_api": {"ambiente": ambiente_value}},
    )

    payload = build_evento_contingencia(
        tipo_contingencia=1,
        motivo=None,
        f_inicio=_sample_datetime(8),
        f_fin=_sample_datetime(9),
        dtes=[{"codigoGeneracion": "abc", "tipoDoc": "01"}],
    )

    assert payload["identificacion"]["ambiente"] == "00"


@pytest.mark.parametrize("ambiente_value", [None, "", "staging"])
def test_ambiente_unknown_defaults_to_pruebas(monkeypatch, ambiente_value):
    monkeypatch.setattr(
        "evento_contingencia.dte._load_datos_negocio",
        lambda: {"dte_api": {"ambiente": ambiente_value}},
    )

    payload = build_evento_contingencia(
        tipo_contingencia=1,
        motivo=None,
        f_inicio=_sample_datetime(8),
        f_fin=_sample_datetime(9),
        dtes=[{"codigoGeneracion": "abc", "tipoDoc": "01"}],
    )

    assert payload["identificacion"]["ambiente"] == "00"


def test_cat005_motivo_rules(monkeypatch):
    uuid_val = "11111111-1111-4111-8111-111111111111"
    monkeypatch.setattr("evento_contingencia.uuid4", lambda: uuid_val)

    payload = build_evento_contingencia(
        tipo_contingencia=5,
        motivo="  prueba  ",
        f_inicio=_sample_datetime(9),
        f_fin=_sample_datetime(11),
        dtes=[],
    )
    assert payload["motivo"]["tipo"] == 5
    assert payload["motivo"]["motivo"] == "prueba"

    with pytest.raises(ValueError):
        build_evento_contingencia(
            tipo_contingencia=5,
            motivo=None,
            f_inicio=_sample_datetime(9),
            f_fin=_sample_datetime(10),
            dtes=[],
        )

    payload_tipo3 = build_evento_contingencia(
        tipo_contingencia=3,
        motivo="debe ir null",
        f_inicio=_sample_datetime(9),
        f_fin=_sample_datetime(10),
        dtes=[],
    )
    assert payload_tipo3["motivo"]["motivo"] is None


def test_range_formats_and_inverted_range_ok(monkeypatch):
    uuid_val = "22222222-2222-4222-8222-222222222222"
    monkeypatch.setattr("evento_contingencia.uuid4", lambda: uuid_val)

    inicio = _sample_datetime(14)
    fin = _sample_datetime(10)

    payload = build_evento_contingencia(
        tipo_contingencia=1,
        motivo=None,
        f_inicio=inicio,
        f_fin=fin,
        dtes=[],
    )

    motivo = payload["motivo"]
    assert motivo["fInicio"] == "2024-01-10"
    assert motivo["hInicio"] == "10:30:15"
    assert motivo["fFin"] == "2024-01-10"
    assert motivo["hFin"] == "14:30:15"


def test_detalle_numbering_cap_and_typodoc_normalization(monkeypatch):
    uuid_val = "33333333-3333-4333-8333-333333333333"
    monkeypatch.setattr("evento_contingencia.uuid4", lambda: uuid_val)

    dtes = []
    for idx in range(1002):
        dtes.append(
            {
                "codigoGeneracion": f"abc-{idx}",
                "tipoDoc": 1 if idx % 2 == 0 else "03",
            }
        )

    payload = build_evento_contingencia(
        tipo_contingencia=2,
        motivo=None,
        f_inicio=_sample_datetime(8),
        f_fin=_sample_datetime(9),
        dtes=dtes,
    )

    detalle = payload["detalleDTE"]
    assert len(detalle) == 1000
    assert detalle[0]["noItem"] == 1
    assert detalle[-1]["noItem"] == 1000
    assert detalle[0]["codigoGeneracion"] == "ABC-0"
    assert all(item["tipoDoc"] in {"01", "03"} for item in detalle)


def test_make_event_filename_valid_and_errors():
    payload = {
        "identificacion": {
            "fTransmision": "2024-02-01",
            "codigoGeneracion": "ABC",
        }
    }
    assert (
        make_event_filename(payload)
        == "evento_contingencia_2024-02-01_ABC.json"
    )

    with pytest.raises(ValueError):
        make_event_filename({})

    with pytest.raises(ValueError):
        make_event_filename({"identificacion": {"fTransmision": ""}})


def test_save_evento_creates_dirs_and_is_stable(tmp_path):
    payload = {
        "identificacion": {
            "version": 3,
            "ambiente": "00",
            "codigoGeneracion": "ABC",
            "fTransmision": "2024-02-01",
            "hTransmision": "12:00:00",
        },
        "motivo": {
            "tipo": 1,
            "motivo": None,
            "fInicio": "2024-02-01",
            "hInicio": "08:00:00",
            "fFin": "2024-02-01",
            "hFin": "10:00:00",
        },
        "detalleDTE": [
            {"noItem": 1, "codigoGeneracion": "ABC", "tipoDoc": "01", "monto": Decimal("1.23")}
        ],
    }

    target = tmp_path / "nested" / "evento.json"
    saved_path = save_evento_contingencia_json(payload, str(target))
    assert Path(saved_path).exists()

    with Path(saved_path).open("r", encoding="utf-8") as fh:
        content = fh.read()

    expected = stable_stringify(payload, indent=2)
    assert content == expected + "\n"
