import json
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


def test_credit_and_debit_notes_include_sign_and_total(tmp_path):
    db = DB(":memory:")
    venta_id = db.add_venta("2024-02-01", 150)

    credit_base = "20240201_Test_NotaCredito"
    debit_base = "20240202_Test_NotaDebito"

    credit_pdf = tmp_path / f"{credit_base}.pdf"
    debit_pdf = tmp_path / f"{debit_base}.pdf"
    credit_pdf.write_text("pdf", encoding="utf-8")
    debit_pdf.write_text("pdf", encoding="utf-8")

    credit_json = tmp_path / f"{credit_base}.json"
    debit_json = tmp_path / f"{debit_base}.json"

    credit_payload = {
        "identificacion": {
            "numeroControl": credit_base,
            "codigoGeneracion": "CRED-001",
            "tipoDte": "05",
        },
        "receptor": {"nombre": "Cliente"},
        "resumen": {"montoTotalOperacion": 25},
    }
    debit_payload = {
        "identificacion": {
            "numeroControl": debit_base,
            "codigoGeneracion": "DEB-001",
            "tipoDte": "06",
        },
        "receptor": {"nombre": "Cliente"},
        "resumen": {"montoTotalOperacion": 10},
    }

    credit_json.write_text(json.dumps(credit_payload), encoding="utf-8")
    debit_json.write_text(json.dumps(debit_payload), encoding="utf-8")

    credit_note_id = db.agregar_nota("credito", venta_id, "2024-02-02", 25, "Ajuste")
    debit_note_id = db.agregar_nota("debito", venta_id, "2024-02-03", 10, "Recargo")

    db.update_nota_detalles(
        credit_note_id,
        {
            "json_path": str(credit_json),
            "numeroControl": credit_base,
            "codigoGeneracion": "CRED-001",
        },
    )
    db.update_nota_detalles(
        debit_note_id,
        {
            "json_path": str(debit_json),
            "numeroControl": debit_base,
            "codigoGeneracion": "DEB-001",
        },
    )

    db.add_factura_pdf(venta_id, "Nota de crédito", str(credit_pdf))
    db.add_factura_pdf(venta_id, "Nota de débito", str(debit_pdf))

    rows = get_facturacion_rows(db)
    rows_by_numero = {
        row.get("numero_control"): row for row in rows if row.get("numero_control")
    }

    credit_row = rows_by_numero.get(credit_base)
    debit_row = rows_by_numero.get(debit_base)

    assert credit_row is not None
    assert debit_row is not None

    assert credit_row.get("sign") == -1
    assert credit_row.get("total") == 25.0

    assert debit_row.get("sign") == 1
    assert debit_row.get("total") == 10.0
