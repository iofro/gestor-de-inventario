import json
import pathlib

import pytest

from utils.docs import TRIBUTO_IVA, build_invoice_json, _remove_none


def _base_data():
    identificacion = {
        "ambiente": "00",
        "version": 1,
        "tipoDte": "01",
        "codigoGeneracion": "ABC",
        "numeroControl": "1",
    }
    emisor = {"nombre": "E", "direccion": {"departamento": "01", "municipio": "0101"}}
    receptor = {}
    items = [
        {
            "descripcion": "Prod",
            "cantidad": 1,
            "precioUnitario": 10,
            "tributos": [{"codigo": TRIBUTO_IVA, "monto": 1.3}],
        }
    ]
    return identificacion, emisor, receptor, items


def _contains_none(obj):
    if isinstance(obj, dict):
        return any(_contains_none(v) for v in obj.values())
    if isinstance(obj, list):
        return any(_contains_none(v) for v in obj)
    return obj is None


def test_item_and_resumen_tributos():
    ident, emi, rec, items = _base_data()
    dte = build_invoice_json(
        identificacion=ident,
        emisor=emi,
        receptor=rec,
        items=items,
    )
    assert dte["cuerpoDocumento"][0]["tributos"]
    assert dte["resumen"]["tributos"]
    assert dte["cuerpoDocumento"][0]["cantidad"] > 0
    assert dte["resumen"]["subTotalVentas"] + dte["resumen"]["tributos"][0]["monto"] == pytest.approx(
        dte["resumen"]["totalPagar"],
        rel=1e-6,
    )


def test_remove_null_keys():
    ident, emi, rec, items = _base_data()
    rec["nombre"] = None
    extras = {"documentoRelacionado": None}
    dte = build_invoice_json(
        identificacion=ident,
        emisor=emi,
        receptor=rec,
        items=items,
        extras=extras,
    )
    assert "documentoRelacionado" not in dte
    assert not _contains_none(dte)


def test_missing_blocks_raise():
    ident, emi, rec, items = _base_data()
    with pytest.raises(ValueError):
        build_invoice_json(identificacion=None, emisor=emi, receptor=rec, items=items)
    with pytest.raises(ValueError):
        build_invoice_json(identificacion=ident, emisor=None, receptor=rec, items=items)
    with pytest.raises(ValueError):
        build_invoice_json(identificacion=ident, emisor=emi, receptor=None, items=items)
    with pytest.raises(ValueError):
        build_invoice_json(identificacion=ident, emisor=emi, receptor=rec, items=[])


def test_matches_golden():
    ident, emi, rec, items = _base_data()
    dte = build_invoice_json(identificacion=ident, emisor=emi, receptor=rec, items=items)
    golden_path = pathlib.Path(__file__).with_name("goldens") / "invoice_basic.json"
    with open(golden_path) as fh:
        golden = json.load(fh)
    assert dte == _remove_none(golden)
