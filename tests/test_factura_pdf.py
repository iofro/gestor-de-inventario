import uuid
import pytest
import fitz
from urllib.parse import urlparse, parse_qs
import factura_sv
from factura_sv import (
    generar_factura_electronica_pdf,
    build_qr_url,
    generar_nota_credito_pdf,
    generar_nota_debito_pdf,
    generar_nota_remision_pdf,
)
import utils.catalogos as catalogos


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
        codigo_generacion=str(uuid.uuid4()),
        numero_control=uuid.uuid4().hex[:8].upper(),
        fecha_generacion="01/01/2024",
        sello_recepcion="0" * 40,
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
    assert 'Tipo Modelo:' in text
    assert 'Tipo Operación:' in text
    assert 'Fecha Generación:' in text


def test_values_are_rounded(tmp_path):
    out = _generate(tmp_path, 'Crédito Fiscal')
    with fitz.open(out) as doc:
        text = ''.join(p.get_text() for p in doc)
    # IVA should be shown with two decimal places
    assert '1.30' in text
    # Precio unitario is shown with four decimals
    assert '10.0000' in text


def test_consumidor_final_pdf_omits_iva_column(tmp_path):
    venta = {
        'sumas': 5.65,
        'descuentos': 0,
        'subtotal': 5.65,
        'total': 5.65,
        'ventas_exentas': 0,
        'ventas_no_sujetas': 0,
        'total_letras': '',
        'iva': 0.65,
    }
    detalles = [
        {
            'cantidad': 1,
            'descripcion': 'Prod CF',
            'precio_unitario': 5.65,
            'ventas_no_sujetas': 0,
            'ventas_exentas': 0,
            'ventas_gravadas': 5.0,
            'iva': 0.65,
        }
    ]
    out = tmp_path / 'fact_cf.pdf'
    generar_factura_electronica_pdf(
        venta,
        detalles,
        {},
        {},
        'Consumidor Final',
        archivo=str(out),
        datos_negocio={},
        codigo_generacion=str(uuid.uuid4()),
        numero_control=uuid.uuid4().hex[:8].upper(),
        fecha_generacion="01/01/2024",
        sello_recepcion='0' * 40,
    )
    with fitz.open(out) as doc:
        text = ''.join(p.get_text() for p in doc)

    assert 'Precio Unitario IVA' not in text
    assert 'IVA 13%' not in text
    assert '0.65' not in text


def test_credito_fiscal_pdf_shows_venta_a_cuenta(tmp_path):
    venta, detalles = _sample_data('Crédito Fiscal')
    venta['venta_a_cuenta_de'] = 'Tercero Ejemplo'
    venta['documento_venta_a_cuenta'] = '0614-1990-0110-19'
    out = tmp_path / 'fact_cf_venta_cta.pdf'
    generar_factura_electronica_pdf(
        venta,
        detalles,
        {},
        {},
        'Crédito Fiscal',
        archivo=str(out),
        datos_negocio={},
        codigo_generacion=str(uuid.uuid4()),
        numero_control=uuid.uuid4().hex[:8].upper(),
        fecha_generacion="01/01/2024",
        sello_recepcion='0' * 40,
    )
    with fitz.open(out) as doc:
        text = ''.join(p.get_text() for p in doc)

    assert 'Venta a cta de: Tercero Ejemplo' in text
    assert 'DUI/NIT: 0614-1990-0110-19' in text


def test_consumidor_final_pdf_shows_venta_a_cuenta_from_extra(tmp_path):
    venta, detalles = _sample_data('Consumidor Final')
    venta['extra'] = {
        'venta_a_cuenta_de': 'Cliente CF',
        'documento_venta_a_cuenta': '0614-2000-1111-19',
    }
    out = tmp_path / 'fact_cf_extra.pdf'
    generar_factura_electronica_pdf(
        venta,
        detalles,
        {},
        {},
        'Consumidor Final',
        archivo=str(out),
        datos_negocio={},
        codigo_generacion=str(uuid.uuid4()),
        numero_control=uuid.uuid4().hex[:8].upper(),
        fecha_generacion="01/01/2024",
        sello_recepcion='0' * 40,
    )
    with fitz.open(out) as doc:
        text = ''.join(p.get_text() for p in doc)

    assert 'Venta a cta de: Cliente CF' in text
    assert 'DUI/NIT: 0614-2000-1111-19' in text


def test_total_letras_is_wrapped(tmp_path):
    venta = {
        'sumas': 0,
        'descuentos': 0,
        'subtotal': 0,
        'iva': 0,
        'total': 0,
        'ventas_exentas': 0,
        'ventas_no_sujetas': 0,
        'total_letras': 'TRESCIENTOS SESENTA Y SIETE 71/100 DÓLARES',
    }
    detalles = [
        {
            'cantidad': 1,
            'descripcion': 'Prod',
            'precio_unitario': 0,
            'ventas_no_sujetas': 0,
            'ventas_exentas': 0,
            'ventas_gravadas': 0,
        }
    ]
    out = tmp_path / 'fact.pdf'
    generar_factura_electronica_pdf(
        venta,
        detalles,
        {},
        {},
        'Crédito Fiscal',
        archivo=str(out),
        datos_negocio={},
        codigo_generacion=str(uuid.uuid4()),
        numero_control=uuid.uuid4().hex[:8].upper(),
        fecha_generacion="01/01/2024",
        sello_recepcion="0" * 40,
    )
    with fitz.open(out) as doc:
        text = ''.join(p.get_text() for p in doc)
    lines = text.splitlines()
    assert any('TRESCIENTOS SESENTA Y SIETE' in ln for ln in lines)
    assert any('71/100 DÓLARES' in ln for ln in lines)


def test_qr_url_contains_params():
    url = build_qr_url(
        {
            'identificacion': {
                'ambiente': '00',
                'codigoGeneracion': 'ABC',
                'fecEmi': '2025-01-01',
            }
        }
    )
    assert url.startswith('https://admin.factura.gob.sv/consultaPublica?')
    assert 'codGen=ABC' in url
    assert 'fechaEmi=2025-01-01' in url
    assert 'ambiente=00' in url


def test_qr_url_matches_environment(tmp_path, monkeypatch):
    venta, detalles = _sample_data('Crédito Fiscal')
    captured = []

    def fake_build_qr_url(dte):
        url = build_qr_url(dte)
        captured.append(url)
        return url

    monkeypatch.setattr(factura_sv, 'build_qr_url', fake_build_qr_url)

    scenarios = [
        ('01', '01'),
        ('00', '00'),
    ]

    for env, expected_param in scenarios:
        captured.clear()
        out = tmp_path / f'fact_{env}.pdf'
        generar_factura_electronica_pdf(
            venta,
            detalles,
            {},
            {},
            'Crédito Fiscal',
            archivo=str(out),
            datos_negocio={},
            ambiente=env,
            codigo_generacion=str(uuid.uuid4()),
            numero_control=uuid.uuid4().hex[:8].upper(),
            fecha_generacion="01/01/2024",
            sello_recepcion="0" * 40,
        )
        assert captured, 'QR value not generated'
        url = captured[0]
        assert url.startswith('https://admin.factura.gob.sv/consultaPublica')
        qs = parse_qs(urlparse(url).query)
        assert qs.get('ambiente') == [expected_param]


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
        tipo_operacion=2,
        codigo_generacion=str(uuid.uuid4()),
        numero_control=uuid.uuid4().hex[:8].upper(),
        fecha_generacion="01/01/2024",
        sello_recepcion="0" * 40,
    )
    with fitz.open(out) as doc:
        text = ''.join(p.get_text() for p in doc)
    assert 'TRANSMISIÓN DIFERIDA' in text


def test_direccion_includes_municipio(tmp_path, monkeypatch):
    monkeypatch.setattr(
        catalogos,
        "get_value",
        lambda cat, code, default=None: "La Libertad Centro" if code == "0524" else default,
    )
    venta, detalles = _sample_data('Crédito Fiscal')
    cliente = {
        'nombre': 'Ana',
        'departamento': '05',
        'municipio': '24',
        'direccion': 'Colonia El Centro con una avenida realmente muy larga para pruebas',
    }
    datos_negocio = {
        'nombre': 'Neg',
        'nit': '',
        'nrc': '',
        'descActividad': '',
        'direccion': {
            'departamento': '05',
            'municipio': '24',
            'complemento': 'Colonia El Centro con una avenida realmente muy larga para pruebas',
        },
    }
    out = tmp_path / 'dir.pdf'
    generar_factura_electronica_pdf(
        venta,
        detalles,
        cliente,
        {},
        'Crédito Fiscal',
        archivo=str(out),
        datos_negocio=datos_negocio,
        codigo_generacion=str(uuid.uuid4()),
        numero_control=uuid.uuid4().hex[:8].upper(),
        fecha_generacion="01/01/2024",
        sello_recepcion="0" * 40,
    )
    with fitz.open(out) as doc:
        lines = ''.join(p.get_text() for p in doc).splitlines()
    idx = next(i for i, ln in enumerate(lines) if ln.startswith('Dirección:'))
    assert 'La Libertad Centro' in lines[idx]
    assert 'realmente muy larga para pruebas' in lines[idx + 1]


def test_direccion_as_text(tmp_path):
    venta, detalles = _sample_data('Crédito Fiscal')
    cliente = {'nombre': 'Ana', 'direccion': 'Colonia Escalón, calle 1'}
    out = tmp_path / 'dir_text.pdf'
    generar_factura_electronica_pdf(
        venta,
        detalles,
        cliente,
        {},
        'Crédito Fiscal',
        archivo=str(out),
        datos_negocio={},
        codigo_generacion=str(uuid.uuid4()),
        numero_control=uuid.uuid4().hex[:8].upper(),
        fecha_generacion="01/01/2024",
        sello_recepcion="0" * 40,
    )
    assert out.exists()


@pytest.mark.parametrize(
    "generator",
    [
        generar_nota_credito_pdf,
        generar_nota_debito_pdf,
        generar_nota_remision_pdf,
    ],
)
def test_notas_pdf_includes_full_receptor_info(tmp_path, generator):
    venta, detalles = _sample_data('Crédito Fiscal')
    venta.update(
        {
            'no_remision': '12345',
            'orden_no': 'A-1',
            'condicion_pago': 'Contado',
        }
    )
    cliente = {
        'nombre': 'Cliente Nota',
        'dui': '01234567-8',
        'nrc': '123456-7',
        'nit': '0614-290190-102-2',
        'giro': 'Comercio',
        'direccion': {
            'departamento': '05',
            'municipio': '24',
            'complemento': 'Colonia Centro',
        },
    }
    out = tmp_path / 'nota.pdf'
    generator(
        venta,
        detalles,
        cliente,
        {},
        archivo=str(out),
        datos_negocio={},
        codigo_generacion=str(uuid.uuid4()),
        numero_control=uuid.uuid4().hex[:8].upper(),
        fecha_generacion="01/01/2024",
        sello_recepcion="0" * 40,
    )
    with fitz.open(out) as doc:
        text = ''.join(p.get_text() for p in doc)

    assert f"NRC: {cliente['nrc']}" in text
    assert f"No. Remisión: {venta['no_remision']}" in text
    assert f"Giro: {cliente['giro']}" in text
    assert f"Condición pago: {venta['condicion_pago']}" in text

