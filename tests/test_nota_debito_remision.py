import fitz
from db import DB
from dte import generar_nota_debito_json, generar_nota_remision_json, generar_dte_json
from factura_sv import generar_nota_debito_pdf, generar_nota_remision_pdf


def create_db():
    return DB(":memory:")


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


def test_generar_nota_debito_json_ticket(tmp_path, monkeypatch):
    datos = {
        "nit": "0614-140710-001-2",
        "nrc": "1234567",
        "nombre": "Emisor",
        "nombreComercial": "Emisor",
        "codActividad": "111111",
        "descActividad": "Giro",
        "telefono": "22223456",
        "correo": "test@example.com",
        "direccion": {"departamento": "05", "municipio": "24", "complemento": "Dir"},
    }
    monkeypatch.setattr("svfe.config.load_datos_negocio", lambda: datos)
    monkeypatch.setattr("dte._load_datos_negocio", lambda: datos)
    monkeypatch.setattr(
        "dte._build_receptor_direccion",
        lambda src: {"departamento": "05", "municipio": "24", "complemento": "Dir"},
    )
    db = create_db()
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None,  vid, None, 0, 0, 0, 10)
    pid = db.cursor.lastrowid
    db.add_cliente("Cliente", "1234567", "06141407100012", "", "giro", "", "", "", "", "")
    cliente_id = db.cursor.lastrowid
    venta_id = db.add_venta_credito_fiscal(cliente_id, "2024-01-01", 10, "1234567", "06141407100012", "giro", descuentos=0)
    db.add_detalle_venta(venta_id, pid, 1, 10, vendedor_id=vid)
    db.cursor.execute(
        "INSERT INTO notas (venta_id, tipo, fecha, monto, motivo) VALUES (?,?,?,?,?)",
        (venta_id, "debito", "2024-01-02", 10, "Ajuste"),
    )
    nota_id = db.cursor.lastrowid
    db.conn.commit()

    data = generar_nota_debito_json(db, nota_id)
    assert data["identificacion"]["tipoDte"] == "06"
    assert data["resumen"]["montoTotalOperacion"] > 0
    doc_rel = data["documentoRelacionado"][0]
    assert doc_rel["tipoDocumento"] == "01"
    assert doc_rel["tipoGeneracion"] == 2
    assert doc_rel["fechaEmision"]
    assert doc_rel["numeroDocumento"] != data["identificacion"].get("numeroControl")
    assert "-" not in data["emisor"].get("nit", "")


def test_generar_nota_remision_json_factura(tmp_path):
    db = create_db()
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None,  vid, None, 0, 0, 0, 10)
    pid = db.cursor.lastrowid
    db.add_cliente("Cliente", "123", "nit1", "", "giro", "", "", "", "", "")
    cliente_id = db.cursor.lastrowid
    venta_id = db.add_venta_credito_fiscal(cliente_id, "2024-01-01", 10, "123", "nit1", "giro", descuentos=0)
    db.add_detalle_venta(venta_id, pid, 1, 10, vendedor_id=vid)
    db.cursor.execute(
        "INSERT INTO notas (venta_id, tipo, fecha, monto, motivo) VALUES (?,?,?,?,?)",
        (venta_id, "remision", "2024-01-02", 0, "Envio"),
    )
    nota_id = db.cursor.lastrowid
    db.conn.commit()

    data = generar_nota_remision_json(db, nota_id)
    assert data["identificacion"]["tipoDte"] == "04"
    assert data["documentoRelacionado"]["tipoDoc"] == "01"


def test_nota_debito_pdf(tmp_path):
    venta, detalles = _sample_data()
    out = tmp_path / "nota.pdf"
    generar_nota_debito_pdf(venta, detalles, {}, {}, archivo=str(out), datos_negocio={})
    assert out.exists()
    with fitz.open(out) as doc:
        text = "".join(p.get_text() for p in doc)
    assert "DOCUMENTO TRIBUTARIO ELECTRÓNICO" in text
    assert "NOTA DE DÉBITO" in text
    assert "Código Generación:" in text
    assert "Número Control:" in text
    assert "Sello Recepción:" in text
    assert "Tipo Modelo:" in text
    assert "Tipo Operación:" in text
    assert "Fecha Generación:" in text


def test_nota_remision_pdf(tmp_path):
    venta, detalles = _sample_data()
    out = tmp_path / "nota.pdf"
    generar_nota_remision_pdf(venta, detalles, {}, {}, archivo=str(out), datos_negocio={})
    assert out.exists()
    with fitz.open(out) as doc:
        text = "".join(p.get_text() for p in doc)
    assert "NOTA DE REMISI" in text
