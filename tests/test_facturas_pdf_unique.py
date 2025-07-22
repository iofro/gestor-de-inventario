from db import DB


def test_add_factura_pdf_deduplicates(tmp_path):
    db = DB(":memory:")
    venta_id = db.add_venta("2024-01-01", 10)
    pdf_path = tmp_path / "fact.pdf"
    pdf_path.write_text("pdf")

    first = db.add_factura_pdf(venta_id, "CF", str(pdf_path))
    second = db.add_factura_pdf(venta_id, "CF", str(pdf_path))

    assert first == second
    count = db.cursor.execute("SELECT COUNT(*) FROM facturas_pdf").fetchone()[0]
    assert count == 1

