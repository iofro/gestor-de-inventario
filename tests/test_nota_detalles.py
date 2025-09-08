from db import DB
from decimal import Decimal, ROUND_HALF_UP
from nota_credito_electronica import generar_nce_desde_dte
from nota_debito_electronica import generar_nde_desde_dte
from dte import generar_dte_json, d4
from utils.monto import to_base_iva, d2

def create_db():
    return DB(":memory:")


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
    dte_origen = generar_dte_json(db, venta_id, tipo_dte="03")
    data = generar_nce_desde_dte(db, dte_origen, Decimal("1"), detalles=detalles, motivo="Dev")
    item = data["cuerpoDocumento"][0]
    assert item["ventaGravada"] == 10
    assert data["resumen"]["totalGravada"] == 10


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
            "precio_unitario": Decimal("9"),
        }
    ]
    dte_origen = generar_dte_json(db, venta_id, tipo_dte="03")
    data = generar_nde_desde_dte(db, dte_origen, detalles, 9, "Ajuste")
    base, iva = to_base_iva(Decimal("9"))
    item = data["cuerpoDocumento"][0]
    assert item["ventaGravada"] == d4(base)
    assert data["resumen"]["totalGravada"] == d2(base)
    assert data["resumen"]["tributos"][0]["valor"] == d2(iva)
    assert data["resumen"]["montoTotalOperacion"] == Decimal("9")
    doc_rel = data["documentoRelacionado"][0]
    assert doc_rel["tipoDocumento"] == "03"


def test_generar_nota_debito_precio_4_decimales(monkeypatch):
    _prep(monkeypatch)
    db = create_db()
    dte_origen = {
        "identificacion": {
            "tipoDte": "03",
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
            "tipoDte": "03",
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
        }
    ]
    nde = generar_nde_desde_dte(db, dte_origen, detalles, None, "Ajuste")
    base, iva = to_base_iva(Decimal("4.42"))
    iva = d2(iva)
    assert nde["resumen"]["tributos"][0]["valor"] == iva
    assert nde["resumen"]["montoTotalOperacion"] == Decimal("4.42")
    assert nde["resumen"]["tributos"][0]["valor"] != Decimal("12.07")
