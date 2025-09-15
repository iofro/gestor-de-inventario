from decimal import Decimal

from db import DB
from nota_credito_electronica import generar_nce_desde_dte


def _base_dte() -> dict:
    return {
        "identificacion": {
            "codigoGeneracion": "UUID",
            "numeroControl": "NC",
            "tipoDte": "01",
            "fecEmi": "2024-01-01",
        },
        "emisor": {},
        "receptor": {},
        "resumen": {},
    }


def test_nce_allows_missing_sello():
    db = DB(":memory:")
    dte_origen = _base_dte()
    data = generar_nce_desde_dte(db, dte_origen, Decimal("1"))
    assert data["documentoRelacionado"][0]["numeroDocumento"] == "UUID"


def test_nce_without_mh_record():
    db = DB(":memory:")
    dte_origen = _base_dte()
    dte_origen["selloRecibido"] = "SELLO"
    data = generar_nce_desde_dte(db, dte_origen, Decimal("1"))
    assert data["documentoRelacionado"][0]["numeroDocumento"] == "UUID"
