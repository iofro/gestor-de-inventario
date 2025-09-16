import fitz
from dte_header_pdf import generar_cabecera_dte


def test_generar_cabecera_consumidor_final(tmp_path):
    archivo = tmp_path / "cf.pdf"
    generar_cabecera_dte(
        codigo_generacion="1234567890ABCDEF",
        numero_control="DTE-123",
        sello_recepcion="ABCDEF0123456789ABCDEF0123456789ABCDEF01",
        tipo_modelo=1,
        tipo_operacion=1,
        fecha_generacion="01/07/2025, 11:15 AM",
        tipo_documento="CONSUMIDOR FINAL",
        archivo=str(archivo),
    )
    assert archivo.exists()
    with fitz.open(archivo) as doc:
        text = "".join(p.get_text() for p in doc)
    assert "DOCUMENTO TRIBUTARIO ELECTRÓNICO" in text
    assert "CONSUMIDOR FINAL" in text
    assert "DTE-123" in text


def test_generar_cabecera_credito_fiscal(tmp_path):
    archivo = tmp_path / "cfis.pdf"
    generar_cabecera_dte(
        codigo_generacion="1234567890ABCDEF",
        numero_control="DTE-987",
        sello_recepcion="1234567890ABCDEF1234567890ABCDEF12345678",
        tipo_modelo=1,
        tipo_operacion=1,
        fecha_generacion="01/07/2025, 11:15 AM",
        tipo_documento="CREDITO FISCAL",
        archivo=str(archivo),
    )
    with fitz.open(archivo) as doc:
        text = "".join(p.get_text() for p in doc)
    assert "CREDITO FISCAL" in text
    assert "DTE-987" in text
