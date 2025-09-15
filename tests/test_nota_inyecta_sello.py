from decimal import Decimal

from db import DB
from nota_credito_electronica import generar_nce_desde_dte
from nota_debito_electronica import generar_nde_desde_dte


def _insert_envio(db: DB, uuid: str, numc: str, sello: str):
    db.ensure_column("dte_envios", "respuesta", "TEXT")
    db.cursor.execute(
        "INSERT INTO dte_envios (venta_id, estado, sello, respuesta) VALUES (?,?,?,?)",
        (None, "Procesado", sello, f"{uuid} {numc}"),
    )
    db.conn.commit()


def test_nce_inyecta_sello_desde_envio():
    db = DB(":memory:")
    _insert_envio(db, "UUID", "NC", "SELLO")
    dte_origen = {
        "identificacion": {
            "codigoGeneracion": "uuid",
            "numeroControl": "NC",
            "tipoDte": "01",
            "fecEmi": "2024-01-01",
        },
        "emisor": {},
        "receptor": {},
        "resumen": {},
    }
    generar_nce_desde_dte(db, dte_origen, Decimal("1"))
    assert dte_origen["selloRecibido"] == "SELLO"


def test_nde_inyecta_sello_desde_envio():
    db = DB(":memory:")
    _insert_envio(db, "UUID", "NC", "SELLO")
    dte_origen = {
        "identificacion": {
            "codigoGeneracion": "uuid",
            "numeroControl": "NC",
            "tipoDte": "01",
            "fecEmi": "2024-01-01",
        },
        "emisor": {},
        "receptor": {},
        "resumen": {},
    }
    detalles = [{"ventas_gravadas": 1, "precio_unitario": 1, "descripcion": "x"}]
    generar_nde_desde_dte(db, dte_origen, detalles, None)
    assert dte_origen["selloRecibido"] == "SELLO"
