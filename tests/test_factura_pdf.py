import pytest
import fitz
from factura_sv import generar_factura_electronica_pdf, build_qr_value


def _sample_data(tipo):
    venta = {
        'sumas': 10,
        'descuentos': 0,
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


def test_header_boxes_and_qr(tmp_path):
    out = _generate(tmp_path, 'Crédito Fiscal')
    assert out.exists()
    with fitz.open(out) as doc:
        text = ''.join(p.get_text() for p in doc)

    # Verificamos que todos los textos de cabecera estén presentes
    assert 'Código Generación:' in text
    assert 'Número Control:' in text
    assert 'Sello Recepción:' in text
    assert 'Modelo Facturación:' in text
    assert 'Tipo Transmisión:' in text
    assert 'Fecha Generación:' in text


def test_values_are_rounded(tmp_path):
    out = _generate(tmp_path, 'Crédito Fiscal')
    with fitz.open(out) as doc:
        text = ''.join(p.get_text() for p in doc)
    # IVA should be shown with two decimal places
    assert '1.30' in text
    # Precio unitario is shown with four decimals
    assert '10.0000' in text


def test_qr_value_contains_params():
    url = build_qr_value('ABC', 'NC-1', nit_emisor='0614', ambiente='01')
    assert 'codGen=ABC' in url
    assert 'numeroControl=NC-1' in url
    assert 'nitEmisor=0614' in url


def test_contingencia_draws_message(tmp_path):
    venta, detalles = _sample_data('Consumidor Final')
    out = tmp_path / 'cont.pdf'
    generar_factura_electronica_pdf(
        venta,
        detalles,
        {},
        {},
        'Consumidor Final',
        archivo=str(out),
        datos_negocio={},
        tipo_transmision='2 - Contingencia',
    )
    with fitz.open(out) as doc:
        text = ''.join(p.get_text() for p in doc)
    assert 'TRANSMISIÓN DIFERIDA' in text

