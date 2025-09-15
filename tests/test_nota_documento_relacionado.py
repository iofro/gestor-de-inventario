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
    monkeypatch.setattr(module, "_origen_aceptado_en_mh", lambda db, ident: True)
    monkeypatch.setattr(module, "sanitize_dte_payload", lambda data, schema: data)
    monkeypatch.setattr(module.catalogos, "get_dte_schema", lambda *a, **k: {})


def test_documento_relacionado_usa_uuid(monkeypatch):
    db = DB(":memory:")
    _patch_module(monkeypatch, nce_mod)
    _patch_module(monkeypatch, nde_mod)
    with open("tests/goldens/ccf.json") as f:
        dte_origen = json.load(f)
    dte_origen["selloRecibido"] = "SELLO"
    uuid = dte_origen["identificacion"]["codigoGeneracion"].upper()

    nce = generar_nce_desde_dte(db, dte_origen, Decimal("1"))
    assert nce["documentoRelacionado"][0]["numeroDocumento"] == uuid

    detalles = [{"descripcion": "Prod", "precio_unitario": 1, "ventas_gravadas": 1}]
    nde = generar_nde_desde_dte(db, dte_origen, detalles, None)
    assert nde["documentoRelacionado"][0]["numeroDocumento"] == uuid
