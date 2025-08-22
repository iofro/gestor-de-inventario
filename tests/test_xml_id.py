from copy import deepcopy

from app.dte import NC_BASE, build_dte_id_xml


def test_build_dte_id_xml_injects_uuid_and_prolog():
    env = deepcopy(NC_BASE)
    xml = build_dte_id_xml(env)
    # Must start with XML declaration and use DTEId root tag
    assert xml.startswith("<?xml")
    assert "<DTEId>" in xml
    # CodigoGeneracion should be generated in envelope and appear in XML
    cg = env["identificacion"]["codigoGeneracion"]
    assert cg and cg in xml
    # Fields with None should be omitted
    assert "<Ambiente>" not in xml

