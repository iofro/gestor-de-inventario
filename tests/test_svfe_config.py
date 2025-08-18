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
