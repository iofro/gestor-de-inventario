import json
from decimal import Decimal

from db import DB
import nota_credito_electronica as nce_mod
import nota_debito_electronica as nde_mod
from nota_credito_electronica import generar_nce_desde_dte
from nota_debito_electronica import generar_nde_desde_dte


def _patch_module(monkeypatch, module):
    dummy_header = {
        "numero_control": "NC",
        "codigo_generacion": "12345678-1234-4234-8234-1234567890AB",
        "tipo_modelo": 1,
        "tipo_operacion": 1,
        "tipo_contingencia": None,
        "motivo_contin": None,
    }
    monkeypatch.setattr(module, "generar_cabecera_dte_data", lambda *a, **k: dummy_header)
    monkeypatch.setattr(module, "sanitize_dte_payload", lambda data, schema: data)
    monkeypatch.setattr(module.catalogos, "get_dte_schema", lambda *a, **k: {})
    if hasattr(module, "_origen_aceptado_en_mh"):
        monkeypatch.setattr(module, "_origen_aceptado_en_mh", lambda db, ident: True)


def _load_golden(name: str) -> dict:
    with open(f"tests/goldens/{name}.json", "r", encoding="utf-8") as fh:
        return json.load(fh)


def test_nce_docrel_ccf_usa_control(monkeypatch):
    db = DB(":memory:")
    _patch_module(monkeypatch, nce_mod)
    ccf = _load_golden("ccf")
    expected_control = ccf["identificacion"]["numeroControl"].upper()

    resultado = generar_nce_desde_dte(db, ccf, Decimal("1"))

    doc_rel = resultado["documentoRelacionado"][0]
    assert doc_rel["tipoDocumento"] == "03"
    assert doc_rel["numeroDocumento"] == expected_control
    assert doc_rel["tipoGeneracion"] == 2
    for item in resultado["cuerpoDocumento"]:
        assert item["numeroDocumento"] == expected_control


def test_nce_docrel_factura_usa_control(monkeypatch):
    db = DB(":memory:")
    _patch_module(monkeypatch, nce_mod)
    factura = _load_golden("fc")
    expected_control = factura["identificacion"]["numeroControl"].upper()

    resultado = generar_nce_desde_dte(db, factura, Decimal("1"))

    doc_rel = resultado["documentoRelacionado"][0]
    assert doc_rel["tipoDocumento"] == "01"
    assert doc_rel["numeroDocumento"] == expected_control
    assert doc_rel["tipoGeneracion"] == 2
    for item in resultado["cuerpoDocumento"]:
        assert item["numeroDocumento"] == expected_control


def test_nde_docrel_usa_uuid(monkeypatch):
    db = DB(":memory:")
    _patch_module(monkeypatch, nde_mod)
    ccf = _load_golden("ccf")
    uuid = ccf["identificacion"]["codigoGeneracion"]

    detalles = [{"descripcion": "Prod", "precio_unitario": 1, "ventas_gravadas": 1}]
    nde = generar_nde_desde_dte(db, ccf, detalles, None)
    assert nde["documentoRelacionado"][0]["numeroDocumento"] == uuid
