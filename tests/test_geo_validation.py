import pytest

from dte import DEFAULT_ADDRESS, _build_receptor_direccion
from utils.catalogos import (
    CAT_MUNI44,
    CAT_MUNI44_BY_DEPTO,
    GeoValidationError,
    _municipality_name_candidates,
    validar_dep_muni_por_catalogo,
)


def norm_receptor(data: dict, es_ticket: bool = False) -> dict:
    direccion_src = (data or {}).get("direccion") or {}
    direccion_norm = _build_receptor_direccion(direccion_src)
    complemento = direccion_norm.get("complemento")
    dep_norm = direccion_norm.get("departamento")
    muni_norm = direccion_norm.get("municipio")
    try:
        dep, muni = validar_dep_muni_por_catalogo(dep_norm, muni_norm)
    except GeoValidationError:
        if dep_norm is None and muni_norm is None:
            dep = DEFAULT_ADDRESS["departamento"]
            muni = DEFAULT_ADDRESS["municipio"]
        elif es_ticket:
            dep = DEFAULT_ADDRESS["departamento"]
            muni = DEFAULT_ADDRESS["municipio"]
        else:
            raise
    comp_text = (str(complemento or "").strip())
    if len(comp_text) < 5:
        complemento = DEFAULT_ADDRESS["complemento"]
    return {
        "direccion": {
            "departamento": dep,
            "municipio": muni,
            "complemento": complemento,
        }
    }


@pytest.mark.parametrize(
    "departamento, municipio",
    [
        ("05", "24"),  # La Libertad Centro
        ("06", "24"),  # San Salvador Sur
        ("08", "24"),  # La Paz Centro
        ("11", "24"),  # Usulután Norte
        ("05", "28"),  # La Libertad Sur
        ("06", "21"),  # San Salvador Oeste
        ("07", "18"),  # Cuscatlán Sur
    ],
)
def test_validar_dep_muni_accepts_by_word(departamento, municipio):
    assert validar_dep_muni_por_catalogo(departamento, municipio) == (
        departamento,
        municipio,
    )


def test_validar_dep_muni_normaliza_codigos():
    dep, muni = validar_dep_muni_por_catalogo(6, "21")
    assert dep == "06"
    assert muni == "21"


@pytest.mark.parametrize(
    "departamento, municipio",
    [
        ("06", "25"),  # Ningún nombre contiene "San Salvador"
        ("06", "14"),  # Evita coincidencias parciales con "San"
        ("03", "24"),
    ],
)
def test_validar_dep_muni_invalid_combinations_use_default(departamento, municipio):
    with pytest.warns(UserWarning):
        dep, muni = validar_dep_muni_por_catalogo(departamento, municipio)
    assert dep == DEFAULT_ADDRESS["departamento"]
    assert muni == DEFAULT_ADDRESS["municipio"]


def test_validar_dep_muni_accepts_extranjeros():
    assert validar_dep_muni_por_catalogo("00", "00") == ("00", "00")


def test_muni44_candidates_prioritize_department():
    candidates = _municipality_name_candidates("24", "05")
    assert candidates[0] == ("05", CAT_MUNI44_BY_DEPTO["05"]["24"])
    assert ("06", CAT_MUNI44_BY_DEPTO["06"]["24"]) in candidates


def test_validar_dep_muni_shared_code_relies_on_name(monkeypatch):
    original = CAT_MUNI44["24"].copy()
    try:
        # Simula una tabla en la que solo queda el municipio de San Salvador.
        monkeypatch.setitem(CAT_MUNI44, "24", {"06": original["06"], "08": original["08"]})
        dep, muni = validar_dep_muni_por_catalogo("05", "24")
        assert (dep, muni) == ("05", "24")
    finally:
        monkeypatch.setitem(CAT_MUNI44, "24", original)


def test_norm_receptor_invalid_geo_uses_default():
    r = {"direccion": {"departamento": "05", "municipio": "20", "complemento": "abcdef"}}
    res = norm_receptor(r)
    assert res["direccion"]["departamento"] == DEFAULT_ADDRESS["departamento"]
    assert res["direccion"]["municipio"] == DEFAULT_ADDRESS["municipio"]
    assert res["direccion"]["complemento"] == "abcdef"


def test_norm_receptor_ticket_fallback():
    r = {"direccion": {"departamento": "05", "municipio": "20", "complemento": "abcdef"}}
    res = norm_receptor(r, es_ticket=True)
    assert res["direccion"]["departamento"] == DEFAULT_ADDRESS["departamento"]
    assert res["direccion"]["municipio"] == DEFAULT_ADDRESS["municipio"]
    assert res["direccion"]["complemento"] == "abcdef"


def test_norm_receptor_cf_missing_geo_uses_default():
    r = {"direccion": {"complemento": "abc"}}
    res = norm_receptor(r)
    assert res["direccion"] == {
        "departamento": DEFAULT_ADDRESS["departamento"],
        "municipio": DEFAULT_ADDRESS["municipio"],
        "complemento": DEFAULT_ADDRESS["complemento"],
    }


def test_norm_receptor_missing_geo_uses_default():
    r = {"nit": "06142501751015", "direccion": {"complemento": "abc"}}
    res = norm_receptor(r)
    assert res["direccion"] == {
        "departamento": DEFAULT_ADDRESS["departamento"],
        "municipio": DEFAULT_ADDRESS["municipio"],
        "complemento": DEFAULT_ADDRESS["complemento"],
    }
