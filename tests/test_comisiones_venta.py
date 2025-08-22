import fitz
from db import DB
from estado_cuenta_pdf import generar_estado_cuenta_pdf


def create_db():
    return DB(":memory:")


def test_detalle_venta_con_comision(tmp_path):
    db = create_db()
    db.add_vendedor("Vend")
    vid = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None,  vid, None, 0, 0, 0, 10)
    pid = db.cursor.lastrowid

    venta_id = db.add_venta("2024-01-01", 10, vendedor_id=vid)
    db.add_detalle_venta(venta_id, pid, 1, 10, comision=2, vendedor_id=vid)

    detalles = db.get_detalles_venta(venta_id)
    assert detalles[0]["comision"] == 2

    pdf_file = tmp_path / "estado.pdf"
    generar_estado_cuenta_pdf(
        db,
        modo="vendedor",
        archivo=str(pdf_file),
        vendedor_id=vid,
        datos_negocio={},
    )
    assert pdf_file.exists()

    with fitz.open(pdf_file) as doc:
        text = "\n".join(p.get_text() for p in doc)
    assert "2.00" in text
