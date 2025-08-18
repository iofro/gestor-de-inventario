import json
from pathlib import Path

import dte


def test_apply_schema_patch(tmp_path, monkeypatch):
    data = {"identificacion": {"tipoDte": "01"}}
    patch_ops = [{"op": "add", "path": "/identificacion/version", "value": "1"}]
    patch_file = tmp_path / "01.json"
    patch_file.write_text(json.dumps(patch_ops), encoding="utf-8")
    monkeypatch.setattr(dte, "PATCHES_DIR", tmp_path)
    patched = dte.apply_schema_patch(data)
    assert patched["identificacion"]["version"] == "1"
