import fitz
from decimal import Decimal
from db import DB
from dte import generar_dte_json
from nota_credito_electronica import generar_nce_desde_dte
from factura_sv import generar_nota_credito_pdf


def create_db():
    return DB(":memory:")


def test_generar_nota_credito_json_ticket(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "svfe.config.load_datos_negocio",
        lambda: {"direccion": {"departamento": "05", "municipio": "24", "complemento": "Dir"}},
    )
    monkeypatch.setattr("dte.validate_dte_json", lambda *a, **k: None)
    monkeypatch.setattr(
        "dte._build_receptor_direccion",
        lambda src: {"departamento": "05", "municipio": "24", "complemento": "Dir"},
    )
    db = create_db()
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None,  vid, None, 0, 0, 0, 10)
    pid = db.cursor.lastrowid
    venta_id = db.add_venta("2024-01-01", 10)
    db.add_detalle_venta(venta_id, pid, 1, 10, vendedor_id=vid)
    dte_origen = generar_dte_json(db, venta_id, tipo_dte="03")
    data = generar_nce_desde_dte(db, dte_origen, Decimal("1"), motivo="Dev")
    assert data["identificacion"]["tipoDte"] == "05"
    assert data.get("documentoRelacionado")
    assert data["documentoRelacionado"][0]["tipoDocumento"] == "03"
    assert data["cuerpoDocumento"][0]["precioUni"] > 0
    assert "totalPagar" not in data["resumen"]
    assert data["resumen"]["montoTotalOperacion"] > 0
    for k in ("ivaRete1", "reteRenta", "ivaPerci1", "condicionOperacion"):
        assert k in data["resumen"]
    assert data["resumen"]["ivaPerci1"] == 0.0
    assert data["resumen"]["ivaRete1"] == 0.0
    assert data["resumen"]["reteRenta"] == 0.0
    assert data["resumen"]["condicionOperacion"] == 1


def test_generar_nota_credito_json_factura(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "svfe.config.load_datos_negocio",
        lambda: {"direccion": {"departamento": "05", "municipio": "24", "complemento": "Dir"}},
    )
    monkeypatch.setattr("dte.validate_dte_json", lambda *a, **k: None)
    monkeypatch.setattr(
        "dte._build_receptor_direccion",
        lambda src: {"departamento": "05", "municipio": "24", "complemento": "Dir"},
    )
    db = create_db()
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None,  vid, None, 0, 0, 0, 10)
    pid = db.cursor.lastrowid
    db.add_cliente("Cliente", "123", "0614-140710-001-2", "", "giro", "", "", "", "", "")
    cliente_id = db.cursor.lastrowid
    venta_id = db.add_venta_credito_fiscal(
        cliente_id, "2024-01-01", 10, "123", "06141407100012", "giro", descuentos=0
    )
    db.add_detalle_venta(venta_id, pid, 1, 10, vendedor_id=vid)
    dte_origen = generar_dte_json(db, venta_id, tipo_dte="01")
    data = generar_nce_desde_dte(db, dte_origen, Decimal("1"), motivo="Dev")
    assert data["documentoRelacionado"][0]["tipoDocumento"] == "01"
    assert "-" not in data["receptor"].get("nit", "")


def _sample_data():
    venta = {
        "sumas": 10,
        "descuentos": 0,
        "subtotal": 10,
        "iva": 1.3,
        "total": 11.3,
        "ventas_exentas": 0,
        "ventas_no_sujetas": 0,
        "total_letras": "ONCE CON 30/100 DOLARES",
    }
    detalles = [
        {
            "cantidad": 1,
            "descripcion": "Prod",
            "precio_unitario": 10,
            "ventas_no_sujetas": 0,
            "ventas_exentas": 0,
            "ventas_gravadas": 10,
        }
    ]
    return venta, detalles


def test_nota_credito_pdf(tmp_path):
    venta, detalles = _sample_data()
    out = tmp_path / "nota.pdf"
    generar_nota_credito_pdf(venta, detalles, {}, {}, archivo=str(out), datos_negocio={})
    assert out.exists()
    with fitz.open(out) as doc:
        text = "".join(p.get_text() for p in doc)
    assert "DOCUMENTO TRIBUTARIO ELECTRÓNICO" in text
    assert "NOTA DE CRÉDITO" in text
    assert "Código Generación:" in text
    assert "Número Control:" in text
    assert "Sello Recepción:" in text
    assert "Tipo Modelo:" in text
    assert "Tipo Operación:" in text
    assert "Fecha Generación:" in text
