import pytest

from dte import DEFAULT_ADDRESS, _build_receptor_direccion
from utils.catalogos import GeoValidationError, validar_dep_muni_por_catalogo


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
def test_validar_dep_muni_rejects_invalid_combinations(departamento, municipio):
    with pytest.raises(GeoValidationError, match="no coincide por palabra"):
        validar_dep_muni_por_catalogo(departamento, municipio)


def test_validar_dep_muni_accepts_extranjeros():
    assert validar_dep_muni_por_catalogo("00", "00") == ("00", "00")


def test_norm_receptor_invalid_geo_raises():
    r = {"direccion": {"departamento": "05", "municipio": "20", "complemento": "abcdef"}}
    with pytest.raises(GeoValidationError):
        norm_receptor(r)


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
