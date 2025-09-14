import fitz
from ticket_pdf import generar_ticket_fe_pdf


def test_ticket_fe_pdf_clean(tmp_path):
    venta = {"fecha": "2025-01-01", "total": 2.0}
    detalles = [{"descripcion": "Acetaminofen 500mg", "cantidad": 1, "precio_unitario": 2.0}]
    dte_json = {
        "identificacion": {
            "tipoDte": "01",
            "codigoGeneracion": "12345678-1234-1234-1234-123456789012",
            "numeroControl": "DTE-01-0001",
            "tipoModelo": 1,
            "tipoOperacion": 1,
            "fecEmi": "2025-01-01",
            "horEmi": "12:00:00",
        },
        "emisor": {
            "nombreComercial": "Farmacia X",
            "nit": "0614-290389-102-1",
            "nrc": "123456-7",
            "descActividad": "Farmacia",
            "direccion": {"complemento": "Av. Siempre Viva"},
        },
        "receptor": {"tipoDocumento": "37", "direccion": {"complemento": "Calle 1"}},
        "cuerpoDocumento": [
            {
                "cantidad": 1,
                "uniMedida": "59",
                "descripcion": "Acetaminofen 500mg",
                "precioUni": 2.0,
                "montoTotal": 2.0,
            }
        ],
        "resumen": {
            "totalGravada": 2.0,
            "montoTotalOperacion": 2.0,
            "totalPagar": 2.0,
            "condicionOperacion": 1,
            "pagos": [{"codigo": "01", "montoPago": 2.0}],
        },
    }
    dte_data = {"dteJson": dte_json}
    out = tmp_path / "ticket.pdf"
    generar_ticket_fe_pdf(venta, detalles, archivo=str(out), dte_data=dte_data)

    with fitz.open(out) as doc:
        text = "\n".join(page.get_text() for page in doc)

    for bad in ("apendice", "cuerpoDocumento", "falta", "None"):
        assert bad not in text

    for good in (
        "DOCUMENTO TRIBUTARIO ELECTRÓNICO",
        "FACTURA (Ticket)",
        "Pago:",
    ):
        assert good in text
