import xml.etree.ElementTree as ET
from dte import identificacion_a_xml

def test_identificacion_xml_tags_and_optional_empty():
    ident = {
        "version": 1,
        "ambiente": "00",
        "tipoDte": "01",
        "numeroControl": "DTE-01-S001P001-123456789012345678",
        "codigoGeneracion": "00000000-0000-4000-8000-000000000001",
        "tipoModelo": 1,
        "tipoOperacion": 1,
        "tipoContingencia": None,   # opcional → debe salir vacío
        "motivoContin": None,       # opcional → debe salir vacío
        "fecEmi": "2025-01-01",
        "horEmi": "12:00:00",
        "tipoMoneda": "USD",
    }

    xml = identificacion_a_xml(ident)

    # 1) etiquetas obligatorias presentes (coinciden con la implementación actual)
    for tag in [
        "TipoDte",
        "NumeroControl",
        "CodigoGeneracion",
        "TipoModelo",
        "TipoOperacion",
        "FecEmi",
        "HorEmi",
        "Ambiente",
    ]:
        assert f"<{tag}>" in xml

    # 2) opcionales existen y están vacías cuando son None
    root = ET.fromstring(xml)
    tc = root.find("TipoContingencia")
    mc = root.find("MotivoContin")
    assert tc is not None and (tc.text in ("", None))
    assert mc is not None and (mc.text in ("", None))