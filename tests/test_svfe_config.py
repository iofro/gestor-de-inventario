import pytest

from svfe import config


def test_get_emisor_direccion_valid(monkeypatch, tmp_path):
    cfg = tmp_path / "company.json"
    cfg.write_text(
        '{"emisor":{"departamento":"12","municipio":"34","complemento":"C"}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "CONFIG_PATH", cfg)
    assert config.get_emisor_direccion() == {
        "departamento": "12",
        "municipio": "34",
        "complemento": "C",
    }


def test_get_emisor_direccion_invalid(monkeypatch, tmp_path):
    cfg = tmp_path / "company.json"
    cfg.write_text(
        '{"emisor":{"departamento":"1","municipio":"34","complemento":"C"}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "CONFIG_PATH", cfg)
    with pytest.raises(ValueError):
        config.get_emisor_direccion()


def test_get_emisor_direccion_invalid_municipio(monkeypatch, tmp_path):
    cfg = tmp_path / "company.json"
    cfg.write_text(
        '{"emisor":{"departamento":"05","municipio":"99","complemento":"C"}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "CONFIG_PATH", cfg)
    with pytest.raises(ValueError):
        config.get_emisor_direccion()


def test_catalogo_muni_por_depto():
    assert config.MUNICIPIO_RANGES["05"] == ("01", "22")
    assert config.MUNICIPIO_RANGES["06"] == ("01", "19")
