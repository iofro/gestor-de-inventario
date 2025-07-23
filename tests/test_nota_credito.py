import fitz
from db import DB
from dte import generar_nota_credito_json
from factura_sv import generar_nota_credito_pdf


def create_db():
    return DB(":memory:")


def test_generar_nota_credito_json_basic(tmp_path):
    db = create_db()
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("Prod", "P1", vid, None, 0, 0, 0, 10)
    pid = db.cursor.lastrowid
    venta_id = db.add_venta("2024-01-01", 10)
    db.add_detalle_venta(venta_id, pid, 1, 10, vendedor_id=vid)
    db.cursor.execute(
        "INSERT INTO notas (venta_id, tipo, fecha, monto, motivo) VALUES (?,?,?,?,?)",
        (venta_id, "credito", "2024-01-02", 10, "Dev"),
    )
    nota_id = db.cursor.lastrowid
    db.conn.commit()

    data = generar_nota_credito_json(db, nota_id)
    assert data["identificacion"]["tipoDte"] == "05"
    assert data.get("documentoRelacionado")
    assert data["cuerpoDocumento"][0]["precioUnitario"] < 0
    assert data["resumen"]["totalPagar"] < 0


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
    assert "NOTA DE CR\xc9DITO" in text
