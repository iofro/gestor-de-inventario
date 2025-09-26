import fitz
from decimal import Decimal

from ticket_pdf import render_ticket_pdf


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
    pdf_bytes = render_ticket_pdf(payload, accepted=True, sello="SEAL-123")
    out = tmp_path / "ticket.pdf"
    out.write_bytes(pdf_bytes)

    with fitz.open(out) as doc:
        text = "\n".join(page.get_text() for page in doc)
    normalized = " ".join(text.split())

    assert "cuerpoDocumento" not in text
    assert "identificacion" not in text
    assert "DOCUMENTO TRIBUTARIO" in text
    assert "ELECTRÓNICO — CONSUMIDOR FINAL" in normalized
    assert "DETALLE DE FACTURA" in text
    assert "FORMA DE PAGO" in text or "Forma de pago" in text
    assert "Sello de Recepción: SEAL-123" in text
    assert "3.39" in text  # total


def test_render_ticket_pdf_credito_fiscal_title(tmp_path):
    payload = _sample_payload()
    payload["identificacion"]["tipoDte"] = "03"
    pdf_bytes = render_ticket_pdf(payload, accepted=True, sello="SEAL-123")
    out = tmp_path / "ticket.pdf"
    out.write_bytes(pdf_bytes)

    with fitz.open(out) as doc:
        text = "\n".join(page.get_text() for page in doc)
    normalized = " ".join(text.split())

    assert "ELECTRÓNICO — CRÉDITO FISCAL" in normalized
