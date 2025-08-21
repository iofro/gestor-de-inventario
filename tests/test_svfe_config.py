import json
import pytest

from svfe import config


def _write(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")


def test_load_datos_negocio_valid(monkeypatch, tmp_path):
    datos = tmp_path / "datos_negocio.json"
    _write(datos, {"direccion": {"departamento": "01", "municipio": "10", "complemento": "C"}})
    monkeypatch.setattr(config, "DATOS_NEGOCIO_PATH", datos)
    assert config.load_datos_negocio()["direccion"] == {
        "departamento": "01",
        "municipio": "10",
        "complemento": "C",
    }
    assert config.get_emisor_direccion() == {
        "departamento": "01",
        "municipio": "10",
        "complemento": "C",
    }


def test_load_datos_negocio_invalid(monkeypatch, tmp_path):
    datos = tmp_path / "datos_negocio.json"
    _write(datos, {"direccion": {"departamento": "99", "municipio": "10", "complemento": "C"}})
    monkeypatch.setattr(config, "DATOS_NEGOCIO_PATH", datos)
    with pytest.raises(ValueError):
        config.load_datos_negocio()


def test_load_datos_negocio_invalid_municipio(monkeypatch, tmp_path):
    datos = tmp_path / "datos_negocio.json"
    _write(datos, {"direccion": {"departamento": "01", "municipio": "99", "complemento": "C"}})
    monkeypatch.setattr(config, "DATOS_NEGOCIO_PATH", datos)
    with pytest.raises(ValueError):
        config.load_datos_negocio()
