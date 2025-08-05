import os
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
import ticket_pdf


def test_with_falta():
    assert ticket_pdf._with_falta("") == "falta"
    assert ticket_pdf._with_falta("abc") == "abc"


def test_generar_ticket_pdf_creates_file(tmp_path):
    venta = {"fecha": "2020-01-01", "total": 10}
    detalles = [{"descripcion": "A", "cantidad": 1, "precio_unitario": 10}]
    out = tmp_path / "t.pdf"
    ticket_pdf.generar_ticket_pdf(venta, detalles, archivo=str(out), datos_negocio={"nombre_comercial": "X"})
    assert out.exists() and out.stat().st_size > 0
