from pathlib import Path

from db import DB
from utils.facturacion_records import get_facturacion_rows


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("pdf", encoding="utf-8")


def test_remision_note_does_not_get_grouped_with_base_invoice(tmp_path):
    db = DB(":memory:")
    venta_id = db.add_venta("2024-01-01", 100)

    invoice_pdf = tmp_path / "20240101_0001_ConsumidorFinal.pdf"
    note_pdf = tmp_path / "20240101_0001_NotaRemision.pdf"
    _touch(invoice_pdf)
    _touch(note_pdf)

    db.add_factura_pdf(venta_id, "Consumidor Final", str(invoice_pdf))
    db.add_factura_pdf(venta_id, "Nota de remisión", str(note_pdf))

    rows = get_facturacion_rows(db)

    tipos = [row.get("tipo") for row in rows]
    assert "Consumidor final" in tipos
    assert "Nota de remisión" in tipos

    nota_rows = [row for row in rows if row.get("tipo") == "Nota de remisión"]
    assert len(nota_rows) == 1
    assert nota_rows[0].get("venta_id") == venta_id


def test_remision_label_without_nota_still_shows_note_entry(tmp_path):
    db = DB(":memory:")
    venta_id = db.add_venta("2024-01-01", 100)

    invoice_pdf = tmp_path / "20240101_0002_ConsumidorFinal.pdf"
    note_pdf = tmp_path / "20240101_0002_NotaRemision.pdf"
    _touch(invoice_pdf)
    _touch(note_pdf)

    db.add_factura_pdf(venta_id, "Consumidor Final", str(invoice_pdf))
    note_id = db.add_factura_pdf(venta_id, "Nota de remisión", str(note_pdf))
    db.cursor.execute(
        "UPDATE facturas_pdf SET tipo=? WHERE id=?", ("Remision", note_id)
    )
    db.conn.commit()

    rows = get_facturacion_rows(db)

    nota_rows = [row for row in rows if row.get("tipo") == "Nota de remisión"]
    assert len(nota_rows) == 1
    assert nota_rows[0].get("venta_id") == venta_id
