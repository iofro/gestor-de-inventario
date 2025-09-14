import fitz
from decimal import Decimal

from print.ticket_renderer import render_ticket_pdf


def _sample_payload():
    return {
        "identificacion": {
            "tipoDte": "01",
            "codigoGeneracion": "12345678-1234-1234-1234-123456789012",
            "numeroControl": "DTE-01-0001",
            "fecEmi": "2025-01-01",
            "horEmi": "12:00:00",
            "ambiente": "00",
        },
        "emisor": {
            "nombreComercial": "Farmacia X",
            "nit": "0614-290389-102-1",
            "nrc": "123456-7",
            "descActividad": "Farmacia",
            "direccion": {"complemento": "Av. Siempre Viva"},
        },
        "cuerpoDocumento": [
            {
                "descripcion": "Acetaminofen 500mg",
                "cantidad": Decimal("2"),
                "precioUni": Decimal("1.50"),
                "montoTotal": Decimal("3.00"),
            }
        ],
        "resumen": {
            "subTotal": Decimal("3.00"),
            "totalIva": Decimal("0.39"),
            "montoTotalOperacion": Decimal("3.39"),
            "pagos": [{"codigo": "01", "montoPago": Decimal("3.39")}],
        },
        "extra": {"es_ticket": True},
    }


def test_render_ticket_pdf_clean(tmp_path):
    payload = _sample_payload()
    pdf_bytes = render_ticket_pdf(payload, accepted=True)
    out = tmp_path / "ticket.pdf"
    out.write_bytes(pdf_bytes)

    with fitz.open(out) as doc:
        text = "\n".join(page.get_text() for page in doc)

    assert "cuerpoDocumento" not in text
    assert "identificacion" not in text
    assert "DOCUMENTO TRIBUTARIO ELECTRÓNICO" in text
    assert "FACTURA (Ticket)" in text
    assert "Pago: Efectivo" in text
    assert "3.39" in text  # total
