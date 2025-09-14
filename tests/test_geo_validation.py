import pytest
from utils.catalogos import validar_dep_muni_por_catalogo, GeoValidationError
from dte import norm_receptor, DEFAULT_ADDRESS


def test_ll_sur_con_ll_dep_ok():
    assert validar_dep_muni_por_catalogo("05", "28") == ("05", "28")


def test_ss_norte_con_ll_dep_falla():
    with pytest.raises(GeoValidationError):
        validar_dep_muni_por_catalogo("05", "20")


def test_extranjeros_ok():
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

