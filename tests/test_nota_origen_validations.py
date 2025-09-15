from decimal import Decimal
import pytest
from db import DB
from nota_credito_electronica import generar_nce_desde_dte


def test_nce_requires_sello():
    db = DB(":memory:")
    dte_origen = {
        "identificacion": {
            "codigoGeneracion": "UUID",
            "numeroControl": "NC",
            "tipoDte": "01",
            "fecEmi": "2024-01-01",
        }
    }
    with pytest.raises(ValueError):
        generar_nce_desde_dte(db, dte_origen, Decimal("1"))


def test_nce_requires_db_record():
    db = DB(":memory:")
    dte_origen = {
        "identificacion": {
            "codigoGeneracion": "UUID",
            "numeroControl": "NC",
            "tipoDte": "01",
            "fecEmi": "2024-01-01",
        },
        "selloRecibido": "SELLO",
    }
    with pytest.raises(ValueError):
        generar_nce_desde_dte(db, dte_origen, Decimal("1"))
