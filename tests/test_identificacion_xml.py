import re
from dte import identificacion_a_xml


def test_identificacion_xml_tags():
    ident = {
        "tipoDte": "01",
        "numeroControl": "DTE-01-S001P001-123456789012345",
        "codigoGeneracion": "00000000-0000-4000-8000-000000000001",
        "tipoModelo": 1,
        "tipoOperacion": 1,
        "fecEmi": "2025-01-01",
        "horEmi": "12:00:00",
        "ambiente": "00",
    }
    xml = identificacion_a_xml(ident)
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
