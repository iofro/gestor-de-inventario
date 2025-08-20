import xml.etree.ElementTree as ET

from dte import identificacion_a_xml


def test_identificacion_none_values_render_empty():
    ident = {
        "version": 1,
        "ambiente": "00",
        "tipoDte": "01",
        "numeroControl": "NC",
        "codigoGeneracion": "ABC",
        "tipoModelo": 1,
        "tipoOperacion": 1,
        "tipoContingencia": None,
        "motivoContin": None,
        "fecEmi": "2024-01-01",
        "horEmi": "12:00:00",
        "tipoMoneda": "USD",
    }
    elem = identificacion_a_xml(ident)
    assert elem.find("tipoContingencia").text == ""
    assert elem.find("motivoContin").text == ""
