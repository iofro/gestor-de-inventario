from decimal import Decimal

from db import DB
from nota_credito_electronica import generar_nce_desde_dte
from dte import generar_nde_desde_dte


def _datos_negocio():
    return {
        "nit": "0614-140710-001-2",
        "nrc": "1234567",
        "nombre": "Emisor",
        "nombreComercial": "Emisor",
        "codActividad": "111111",
        "descActividad": "Giro",
        "telefono": "22223456",
        "correo": "test@example.com",
        "direccion": {
            "departamento": "05",
            "municipio": "24",
            "complemento": "Dir",
        },
    }


def _dte_origen():
    return {
        "identificacion": {
            "tipoDte": "03",
            "codigoGeneracion": "UUID",
            "fecEmi": "2024-01-01",
        },
        "emisor": {},
        "receptor": {},
        "resumen": {
            "montoTotalOperacion": 1.88,
            "totalGravada": 1.66,
            "totalExenta": 0,
            "totalNoSuj": 0,
            "condicionOperacion": 1,
        },
    }


def _detalles():
    return [
        {
            "cantidad": 1,
            "descripcion": "Item1",
            "precio_unitario": Decimal("1.2345"),
            "ventaGravada": Decimal("1.23"),
            "ventaExenta": 0,
            "ventaNoSuj": 0,
        },
        {
            "cantidad": 1,
            "descripcion": "Item2",
            "precio_unitario": Decimal("0.4321"),
            "ventaGravada": Decimal("0.43"),
            "ventaExenta": 0,
            "ventaNoSuj": 0,
        },
    ]


def test_notas_precio_uni_cuatro_decimales(monkeypatch):
    datos = _datos_negocio()
    monkeypatch.setattr("svfe.config.load_datos_negocio", lambda: datos)
    monkeypatch.setattr("dte._load_datos_negocio", lambda: datos)

    db = DB(":memory:")
    dte_origen = _dte_origen()
    detalles = _detalles()
    precios = [Decimal("1.2345"), Decimal("0.4321")]

    nce = generar_nce_desde_dte(db, dte_origen, None, detalles=detalles)
    nde = generar_nde_desde_dte(db, dte_origen, detalles, None, "Ajuste")

    total_original = Decimal(str(dte_origen["resumen"]["montoTotalOperacion"]))
    for nota in (nce, nde):
        for det, esperado in zip(nota["cuerpoDocumento"], precios):
            dec = Decimal(str(det["precioUni"]))
            assert dec == esperado
            assert dec.as_tuple().exponent == -4
        assert (
            Decimal(str(nota["resumen"]["montoTotalOperacion"])) == total_original
        )
