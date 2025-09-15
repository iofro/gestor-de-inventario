from db import DB
from decimal import Decimal, ROUND_HALF_UP
import pytest
from nota_credito_electronica import generar_nce_desde_dte
from nota_debito_electronica import generar_nde_desde_dte
from dte import generar_dte_json

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


def test_generar_nce_detalles(monkeypatch):
    _prep(monkeypatch)
    db = create_db()
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None, vid, None, 0, 0, 0, 10)
    pid = db.cursor.lastrowid
    venta_id = db.add_venta("2024-01-01", 10)
    db.add_detalle_venta(venta_id, pid, 1, 10, vendedor_id=vid)
    detalles = [
        {
            "cantidad": 1,
            "descripcion": "Prod",
            "precio_unitario": 10,
            "ventas_gravadas": 10,
            "ventas_exentas": 0,
            "ventas_no_sujetas": 0,
        }
    ]
    dte_origen = generar_dte_json(db, venta_id, tipo_dte="01")
    data = generar_nce_desde_dte(db, dte_origen, Decimal("1"), detalles=detalles, motivo="Dev")
    assert (
        data["documentoRelacionado"][0]["numeroDocumento"]
        == dte_origen["identificacion"]["codigoGeneracion"]
    )
    item = data["cuerpoDocumento"][0]
    assert item["ventaGravada"] == 10
    assert data["resumen"]["totalGravada"] == 10


def test_generar_nce_detalles_tributos(monkeypatch):
    _prep(monkeypatch)
    db = create_db()
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None, vid, None, 0, 0, 0, 10)
    pid = db.cursor.lastrowid
    venta_id = db.add_venta("2024-01-01", 10)
    db.add_detalle_venta(venta_id, pid, 1, 10, vendedor_id=vid)
    detalles = [
        {
            "cantidad": 1,
            "descripcion": "Prod",
            "precio_unitario": 10,
            "ventas_gravadas": 10,
            "ventas_exentas": 0,
            "ventas_no_sujetas": 0,
        }
    ]
    dte_origen = generar_dte_json(db, venta_id, tipo_dte="01")
    data = generar_nce_desde_dte(db, dte_origen, Decimal("1"), detalles=detalles)
    assert (
        data["documentoRelacionado"][0]["numeroDocumento"]
        == dte_origen["identificacion"]["codigoGeneracion"]
    )
    expected_iva = Decimal("10") * Decimal("0.13")
    assert data["resumen"]["tributos"][0]["valor"] == expected_iva


def test_generar_nce_detalles_monto_total(monkeypatch):
    _prep(monkeypatch)
    db = create_db()
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None, vid, None, 0, 0, 0, 10)
    pid = db.cursor.lastrowid
    venta_id = db.add_venta("2024-01-01", 20)
    db.add_detalle_venta(venta_id, pid, 2, 10, vendedor_id=vid)
    detalles = [
        {
            "cantidad": 1,
            "descripcion": "Prod",
            "precio_unitario": 10,
            "ventas_gravadas": 10,
            "ventas_exentas": 0,
            "ventas_no_sujetas": 0,
        }
    ]
    dte_origen = generar_dte_json(db, venta_id, tipo_dte="01")
    nce = generar_nce_desde_dte(db, dte_origen, None, detalles=detalles)
    assert (
        nce["documentoRelacionado"][0]["numeroDocumento"]
        == dte_origen["identificacion"]["codigoGeneracion"]
    )
    resumen = nce["resumen"]
    expected_iva = Decimal("10") * Decimal("0.13")
    expected_total = Decimal("10") + expected_iva
    assert resumen["montoTotalOperacion"] == expected_total
    assert resumen["montoTotalOperacion"] < dte_origen["resumen"]["montoTotalOperacion"]


def test_generar_nota_debito_detalles(monkeypatch):
    _prep(monkeypatch)
    db = create_db()
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None, vid, None, 0, 0, 0, 10)
    pid = db.cursor.lastrowid
    venta_id = db.add_venta("2024-01-01", 10)
    db.add_detalle_venta(venta_id, pid, 1, 10, vendedor_id=vid)
    detalles = [
        {
            "cantidad": 1,
            "descripcion": "Ajuste",
            "precio_unitario": 2,
            "ventas_gravadas": 2,
            "ventas_exentas": 0,
            "ventas_no_sujetas": 0,
        }
    ]
    dte_origen = generar_dte_json(db, venta_id, tipo_dte="01")
    data = generar_nde_desde_dte(db, dte_origen, detalles, Decimal("2.26"), "Ajuste")
    item = data["cuerpoDocumento"][0]
    assert item["ventaGravada"] == 2
    assert data["resumen"]["totalGravada"] == 2
    expected_iva = Decimal("2") * Decimal("0.13")
    assert data["resumen"]["tributos"][0]["valor"] == expected_iva
    assert data["resumen"]["montoTotalOperacion"] == Decimal("2") + expected_iva
    doc_rel = data["documentoRelacionado"][0]
    assert doc_rel["tipoDocumento"] == "01"
    assert (
        doc_rel["numeroDocumento"]
        == dte_origen["identificacion"]["codigoGeneracion"]
    )


def test_generar_nde_respeta_total(monkeypatch):
    _prep(monkeypatch)
    db = create_db()
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None, vid, None, 0, 0, 0, 10)
    pid = db.cursor.lastrowid
    venta_id = db.add_venta("2024-01-01", 9)
    db.add_detalle_venta(venta_id, pid, 1, 7.96, vendedor_id=vid)
    dte_origen = generar_dte_json(db, venta_id, tipo_dte="01")
    detalles = [
        {
            "cantidad": 1,
            "descripcion": "Prod",
            "precio_unitario": Decimal("7.96"),
            "ventas_gravadas": Decimal("7.96"),
            "ventas_exentas": 0,
            "ventas_no_sujetas": 0,
        }
    ]
    data = generar_nde_desde_dte(db, dte_origen, detalles, Decimal("9"), "Ajuste")
    resumen = data["resumen"]
    assert resumen["montoTotalOperacion"] == Decimal("9.00")
    assert resumen["totalGravada"] == Decimal("7.96")
    assert resumen["tributos"][0]["valor"] == Decimal("1.04")


def test_generar_nota_debito_precio_4_decimales(monkeypatch):
    _prep(monkeypatch)
    db = create_db()
    dte_origen = {
        "identificacion": {
            "tipoDte": "01",
            "codigoGeneracion": "UUID",
            "fecEmi": "2024-01-01",
        },
        "emisor": {},
        "receptor": {},
        "resumen": {
            "montoTotalOperacion": Decimal("1.23"),
            "totalGravada": Decimal("0"),
            "totalExenta": Decimal("1.23"),
            "totalNoSuj": Decimal("0"),
        },
    }
    detalles = [
        {
            "cantidad": 1,
            "descripcion": "Prod",
            "ventas_gravadas": 0,
            "ventas_exentas": Decimal("1.2345"),
            "ventas_no_sujetas": 0,
        }
    ]
    data = generar_nde_desde_dte(db, dte_origen, detalles, 1.23, "Ajuste")
    item = data["cuerpoDocumento"][0]
    assert item["precioUni"] == Decimal("1.2345")
    assert item["ventaExenta"] == Decimal("1.2345")
    subtotal = Decimal("1.2345")
    expected_total = subtotal.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    assert data["resumen"]["montoTotalOperacion"] == expected_total


def test_iva_no_excesivo_en_nota(monkeypatch):
    _prep(monkeypatch)
    db = create_db()
    dte_origen = {
        "identificacion": {
            "tipoDte": "01",
            "codigoGeneracion": "UUID",
            "fecEmi": "2024-01-01",
        },
        "emisor": {},
        "receptor": {},
        "resumen": {
            "montoTotalOperacion": Decimal("104.92"),
            "totalGravada": Decimal("92.85"),
            "totalExenta": Decimal("0"),
            "totalNoSuj": Decimal("0"),
        },
    }
    detalles = [
        {
            "cantidad": 1,
            "descripcion": "Prod",
            "precio_unitario": Decimal("4.42"),
            "ventas_gravadas": Decimal("4.42"),
            "ventas_exentas": 0,
            "ventas_no_sujetas": 0,
        }
    ]
    nde = generar_nde_desde_dte(db, dte_origen, detalles, None, "Ajuste")
    iva = Decimal("4.42") * Decimal("0.13")
    iva = iva.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    assert nde["resumen"]["tributos"][0]["valor"] == iva
    assert nde["resumen"]["montoTotalOperacion"] == Decimal("4.42") + iva
    assert nde["resumen"]["tributos"][0]["valor"] != Decimal("12.07")
