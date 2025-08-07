import json
import os
import main


def test_cargar_ultimo_archivo_prioriza_ultimo(tmp_path, monkeypatch):
    last = tmp_path / "ultimo.json"
    inv = tmp_path / "inv.json"
    inv.write_text("{}")
    last.write_text(json.dumps({"ultimo": str(inv)}))
    monkeypatch.setattr(main, "LAST_FILE_PATH", str(last))
    monkeypatch.setattr(main, "DEFAULT_INVENTORY", "def.json")
    assert main.cargar_ultimo_archivo() == str(inv)


def test_cargar_ultimo_archivo_default(tmp_path, monkeypatch):
    inv = tmp_path / "inv.json"
    inv.write_text("{}")
    monkeypatch.setattr(main, "LAST_FILE_PATH", str(tmp_path / "missing.json"))
    monkeypatch.setattr(main, "DEFAULT_INVENTORY", str(inv))
    assert main.cargar_ultimo_archivo() == str(inv)


def test_cargar_ultimo_archivo_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "LAST_FILE_PATH", str(tmp_path / "missing.json"))
    monkeypatch.setattr(main, "DEFAULT_INVENTORY", str(tmp_path / "missing.json"))
    assert main.cargar_ultimo_archivo() == ""
