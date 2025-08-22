from copy import deepcopy
from pathlib import Path

from app.dte import NC_BASE, validate_dte


def test_base_envelope_fails_validation():
    env = deepcopy(NC_BASE)
    errors = validate_dte(env, "05")
    assert errors


def test_tipo_operacion_requires_contingencia():
    env = deepcopy(NC_BASE)
    env["identificacion"]["tipoOperacion"] = 2
    errors = validate_dte(env, "05")
    assert any("tipoContingencia" in e for e in errors)


def test_tipo_contingencia_requires_motivo():
    env = deepcopy(NC_BASE)
    env["identificacion"]["tipoContingencia"] = 5
    errors = validate_dte(env, "05")
    assert any("motivoContin" in e for e in errors)


def test_schema_dir_can_be_overridden(monkeypatch, tmp_path):
    src = Path(__file__).resolve().parents[1] / "svfe-json-schemas" / "fe-nc-v3.json"
    dest = tmp_path / "fe-nc-v3.json"
    dest.write_text(src.read_text(), encoding="utf-8")
    monkeypatch.setenv("DTE_SCHEMA_DIR", str(tmp_path))
    env = deepcopy(NC_BASE)
    errors = validate_dte(env, "05")
    assert errors

