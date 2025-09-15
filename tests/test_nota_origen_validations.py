from decimal import Decimal
import pytest
from db import DB
from nota_credito_electronica import generar_nce_desde_dte
from nota_debito_electronica import generar_nde_desde_dte


def _insert_envio(db: DB, uuid: str, estado: str, sello: str = "SELLO"):
    db.ensure_column("dte_envios", "respuesta", "TEXT")
    db.cursor.execute(
        "INSERT INTO dte_envios (venta_id, estado, sello, respuesta) VALUES (?,?,?,?)",
        (None, estado, sello, uuid),
    )
    db.conn.commit()


def _build_dte_origen(uuid: str | None):
    ident = {
        "numeroControl": "NC",
        "tipoDte": "01",
        "fecEmi": "2024-01-01",
    }
    if uuid:
        ident["codigoGeneracion"] = uuid
    return {
        "identificacion": ident,
        "emisor": {},
        "receptor": {},
        "resumen": {},
        "selloRecibido": "SELLO",
    }


def test_nce_requires_sello():
    db = DB(":memory:")
    dte_origen = _build_dte_origen("UUID")
    dte_origen.pop("selloRecibido")
    with pytest.raises(ValueError):
        generar_nce_desde_dte(db, dte_origen, Decimal("1"))


def test_nce_requires_db_record():
    db = DB(":memory:")
    dte_origen = _build_dte_origen("UUID")
    with pytest.raises(ValueError):
        generar_nce_desde_dte(db, dte_origen, Decimal("1"))


def test_nce_requires_uuid():
    db = DB(":memory:")
    dte_origen = _build_dte_origen(None)
    with pytest.raises(ValueError):
        generar_nce_desde_dte(db, dte_origen, Decimal("1"))


def test_nce_requires_estado_aceptado():
    db = DB(":memory:")
    _insert_envio(db, "UUID", "Recibido")
    dte_origen = _build_dte_origen("UUID")
    with pytest.raises(ValueError):
        generar_nce_desde_dte(db, dte_origen, Decimal("1"))


def test_nde_requires_uuid():
    db = DB(":memory:")
    dte_origen = _build_dte_origen(None)
    detalles = [{"ventas_gravadas": 1, "precio_unitario": 1, "descripcion": "x"}]
    with pytest.raises(ValueError):
        generar_nde_desde_dte(db, dte_origen, detalles, None)


def test_nde_requires_estado_aceptado():
    db = DB(":memory:")
    _insert_envio(db, "UUID", "Recibido")
    dte_origen = _build_dte_origen("UUID")
    detalles = [{"ventas_gravadas": 1, "precio_unitario": 1, "descripcion": "x"}]
    with pytest.raises(ValueError):
        generar_nde_desde_dte(db, dte_origen, detalles, None)
