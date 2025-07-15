import pytest
import fitz
from factura_sv import generar_factura_electronica_pdf


def _sample_data(tipo):
    venta = {
        'sumas': 10,
        'descuentos_globales': 0,
        'subtotal': 10,
        'iva': 1.3,
        'total': 11.3,
        'ventas_exentas': 0,
        'ventas_no_sujetas': 0,
        'total_letras': 'ONCE CON 30/100 DOLARES',
    }
    detalles = [
        {
            'cantidad': 1,
            'descripcion': 'Prod',
            'precio_unitario': 10,
            'ventas_no_sujetas': 0,
            'ventas_exentas': 0,
            'ventas_gravadas': 10,
        }
    ]
    return venta, detalles


def _generate(tmp_path, tipo):
    venta, detalles = _sample_data(tipo)
    out = tmp_path / 'fact.pdf'
    generar_factura_electronica_pdf(
        venta,
        detalles,
        {},
        {},
        tipo,
        archivo=str(out),
        datos_negocio={},
    )
    return out


@pytest.mark.parametrize('tipo', ['Crédito Fiscal', 'Consumidor Final'])
def test_factura_header_contains_doc_type(tmp_path, tipo):
    out = _generate(tmp_path, tipo)
    assert out.exists()
    with fitz.open(out) as doc:
        text = ''.join(p.get_text() for p in doc)
    assert 'DOCUMENTO TRIBUTARIO ELECTRÓNICO' in text
    assert tipo.upper() in text


def test_qr_position_and_boxes_spacing(tmp_path):
    out = _generate(tmp_path, 'Crédito Fiscal')
    with fitz.open(out) as doc:
        page = doc[0]
        numero = page.search_for('Número Control')[0]
        emisor = page.search_for('EMISOR:')[0]

    # QR position computed using same constants as in factura_sv
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import mm

    width, height = letter
    x_margin = 30
    qr_col_w = 30 * mm
    col_margin = 15
    available_w = width - 2 * x_margin - qr_col_w - 2 * col_margin
    left_col_w = available_w / 2
    size = 30 * mm
    qr_x = x_margin + left_col_w + col_margin + 5
    qr_y = (height - 50 - 40) - size - 23
    qr_top = height - (qr_y + size)
    qr_bottom = height - qr_y

    # QR should align vertically with the header lines
    assert abs(qr_top - numero.y0) < 5

    # Boxes should sit close to the QR code
    gap = qr_bottom - emisor.y0
    assert gap < 45

