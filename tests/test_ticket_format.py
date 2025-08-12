import json
import fitz
from pathlib import Path
from ticket_pdf import generar_ticket_personalizado


def test_custom_ticket_matches_example(tmp_path):
    fixture = Path(__file__).resolve().parent / 'fixtures' / 'ticket_fixture.json'
    with open(fixture, 'r', encoding='utf-8') as fh:
        data = json.load(fh)

    out_file = tmp_path / 'ticket.pdf'
    generar_ticket_personalizado(
        data['venta'],
        data['detalles'],
        archivo=str(out_file),
        datos_negocio=data['datos_negocio'],
        dte_data=data['dte_data'],
    )

    with fitz.open(out_file) as doc:
        generated_text = "\n".join(p.get_text() for p in doc)
    example_path = Path(__file__).resolve().parents[1] / 'ticket_example.pdf'
    with fitz.open(example_path) as doc:
        example_text = "\n".join(p.get_text() for p in doc)

    subset = [
        data['datos_negocio']['nombreComercial'],
        'Bencobal',
        '21.08',
    ]
    for fragment in subset:
        assert fragment in generated_text
        assert fragment in example_text
