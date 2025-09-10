import dte
from utils import catalogos


def _has_none(data):
    if data is None:
        return True
    if isinstance(data, dict):
        return any(_has_none(v) for v in data.values())
    if isinstance(data, list):
        return any(_has_none(v) for v in data)
    return False

REQUIRED_NULL_FIELDS = {
    "documentoRelacionado",
    "otrosDocumentos",
    "ventaTercero",
    "extension",
    "apendice",
}


def test_sanitize_dte_payload_removes_none_recursively(dte_metadata_factory):
    dte_payload = dte_metadata_factory()
    dte_payload["emisor"]["codActividad"] = None
    dte_payload["emisor"]["nombreComercial"] = None
    clean = dte.sanitize_dte_payload(dte_payload)
    assert "codActividad" not in clean["emisor"]
    assert clean["emisor"]["nombreComercial"] is None
    assert clean["identificacion"]["tipoContingencia"] is None
    assert clean["identificacion"]["motivoContin"] is None
    for key in REQUIRED_NULL_FIELDS:
        assert key in clean and clean[key] is None
    item0 = clean["cuerpoDocumento"][0]
    assert item0["codTributo"] is None
    assert item0["tributos"] is None
    assert clean["resumen"]["tributos"] is None
    clean_no_required = {k: v for k, v in clean.items() if k not in REQUIRED_NULL_FIELDS}
    for item in clean_no_required.get("cuerpoDocumento", []):
        item.pop("codTributo", None)
        item.pop("tributos", None)
    clean_no_required.get("resumen", {}).pop("tributos", None)
    clean_no_required.get("resumen", {}).pop("numPagoElectronico", None)
    clean_no_required.get("identificacion", {}).pop("tipoContingencia", None)
    clean_no_required.get("identificacion", {}).pop("motivoContin", None)
    clean_no_required.get("emisor", {}).pop("nombreComercial", None)
    assert not _has_none(clean_no_required)


def test_sanitize_dte_payload_adds_required_fields_and_cleans_docs(dte_metadata_factory):
    payload = dte_metadata_factory()
    payload.pop("ventaTercero", None)
    payload.pop("extension", None)
    payload.pop("apendice", None)
    payload["emisor"]["nit"] = "0614-123456-001-1"
    payload["emisor"]["dui"] = "01234567-8"
    payload["receptor"]["numDocumento"] = "01234567-8"
    clean = dte.sanitize_dte_payload(payload)
    assert clean["ventaTercero"] is None
    assert clean["extension"] is None
    assert clean["apendice"] is None
    assert clean["emisor"]["nit"] == "06141234560011"
    assert "dui" not in clean["emisor"]
    assert clean["receptor"]["numDocumento"] == "012345678"


def test_sanitize_skips_otros_documentos_for_notas():
    payload = {
        "identificacion": {},
        "emisor": {},
        "receptor": {},
        "cuerpoDocumento": [],
        "resumen": {},
    }

    for tipo in ("05", "06"):
        schema = catalogos.get_dte_schema(tipo)
        clean = dte.sanitize_dte_payload(payload, schema)
        assert "otrosDocumentos" not in clean


def test_emisor_dui_omitted_for_credito_fiscal(dte_metadata_factory):
    payload = dte_metadata_factory()
    payload["identificacion"]["tipoDte"] = "03"
    payload["emisor"]["dui"] = "01234567-8"
    clean = dte.sanitize_dte_payload(payload)
    assert "dui" not in clean["emisor"]
