from decimal import Decimal, ROUND_HALF_UP

import pytest
from db import DB
from dte import generar_dte_json
from nota_credito_electronica import generar_nce_desde_dte


def create_db():
    return DB(":memory:")


@pytest.fixture(autouse=True)
def _mock_geo(monkeypatch):
    monkeypatch.setattr(
        "dte.validar_dep_muni_por_catalogo",
        lambda d, m, strict=True: (str(d).zfill(2), str(m).zfill(2)),
    )


def _prep(monkeypatch):
    monkeypatch.setattr(
        "svfe.config.load_datos_negocio",
        lambda: {"direccion": {"departamento": "05", "municipio": "24", "complemento": "Dir"}},
    )
    monkeypatch.setattr("dte.validate_dte_json", lambda *a, **k: None)
    monkeypatch.setattr(
        "dte._build_receptor_direccion",
        lambda src: {"departamento": "05", "municipio": "24", "complemento": "Dir"},
    )


def test_nce_monto_total_por_detalles(monkeypatch):
    """La NCE debe calcular el monto total únicamente con los detalles indicados."""
    _prep(monkeypatch)
    db = create_db()
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None, vid, None, 0, 0, 0, 10)
    pid = db.cursor.lastrowid
    venta_id = db.add_venta("2024-01-01", 20)
    db.add_detalle_venta(venta_id, pid, 2, 10, vendedor_id=vid)
    dte_origen = generar_dte_json(db, venta_id, tipo_dte="01")
    codigo = dte_origen["cuerpoDocumento"][0]["codigo"]
    detalles = [
        {
            "cantidad": 1,
            "descripcion": "Prod",
            "codigo": codigo,
            "ventas_gravadas": Decimal("10"),
            "ventas_exentas": 0,
            "ventas_no_sujetas": 0,
        }
    ]
    nce = generar_nce_desde_dte(db, dte_origen, None, detalles=detalles)
    assert (
        nce["documentoRelacionado"][0]["numeroDocumento"]
        == dte_origen["identificacion"]["codigoGeneracion"]
    )
    resumen = nce["resumen"]
    expected_iva = (Decimal("10") * Decimal("0.13")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    expected_total = Decimal("10") + expected_iva
    assert resumen["montoTotalOperacion"] == expected_total
    assert resumen["montoTotalOperacion"] < dte_origen["resumen"]["montoTotalOperacion"]


def test_nce_detalles_monto_un_dolar(monkeypatch):
    _prep(monkeypatch)
    db = create_db()
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None, vid, None, 0, 0, 0, 1)
    pid = db.cursor.lastrowid
    venta_id = db.add_venta("2024-01-01", 1)
    db.add_detalle_venta(venta_id, pid, 1, 1, vendedor_id=vid)
    dte_origen = generar_dte_json(db, venta_id, tipo_dte="01")
    codigo = dte_origen["cuerpoDocumento"][0]["codigo"]
    detalles = [
        {
            "cantidad": 1,
            "descripcion": "Prod",
            "codigo": codigo,
            "ventas_gravadas": dte_origen["cuerpoDocumento"][0]["ventaGravada"],
            "ventas_exentas": 0,
            "ventas_no_sujetas": 0,
        }
    ]
    nce = generar_nce_desde_dte(db, dte_origen, None, detalles=detalles, monto=Decimal("1"))
    assert (
        nce["documentoRelacionado"][0]["numeroDocumento"]
        == dte_origen["identificacion"]["codigoGeneracion"]
    )
    resumen = nce["resumen"]
    iva = resumen["tributos"][0]["valor"] if resumen["tributos"] else Decimal("0")
    assert resumen["montoTotalOperacion"] == Decimal("1.00")
    assert resumen["totalGravada"] + iva == Decimal("1.00")

