import json
import fitz
from ticket_pdf import generar_ticket_personalizado


def test_sample_ticket_generation(tmp_path):
    with open('tests/data/sample_ticket.json', encoding='utf-8') as f:
        data = json.load(f)

    out = tmp_path / 'ticket.pdf'
    generar_ticket_personalizado(
        data['venta'],
        data['detalles'],
        str(out),
        datos_negocio=data['datos_negocio'],
        dte_data=data['dte_data'],
    )

    assert out.exists()

    assert out.stat().st_size > 0

    with fitz.open(out) as generated:
        text = ''.join(p.get_text() for p in generated)

    assert "Farmacia San Nicolas" in text
    assert data["dte_data"]["selloRecibido"] in text

