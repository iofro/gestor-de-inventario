import uuid
from PyPDF2 import PdfReader
from factura_sv import generar_factura_electronica_pdf


def test_factura_pdf_includes_iva_column(tmp_path):
    venta = {
        "sumas": 9.47,
        "descuentos": 0,
        "iva": 1.23,
        "ventas_exentas": 0,
        "ventas_no_sujetas": 0,
        "subtotal": 10.7,
        "total": 10.7,
        "total_letras": "",
    }
    detalles = [
        {
            "cantidad": 1,
            "descripcion": "Prod",
            "precio_unitario": 9.47,
            "iva": 1.23,
            "ventas_gravadas": 9.47,
            "ventas_exentas": 0,
            "ventas_no_sujetas": 0,
        }
    ]
    pdf = tmp_path / "f.pdf"
    generar_factura_electronica_pdf(
        venta,
        detalles,
        {},
        {},
        archivo=str(pdf),
        codigo_generacion=str(uuid.uuid4()),
        numero_control=uuid.uuid4().hex[:8].upper(),
        sello_recepcion="SELLO",
        fecha_generacion="01/01/2024",
    )
    reader = PdfReader(str(pdf))
    text = "".join(page.extract_text() or "" for page in reader.pages)
    assert text.count("IVA") >= 2
    assert text.count("1.23") >= 2
