import os
from pathlib import Path

import paths


def _force_windows(monkeypatch):
    monkeypatch.setattr(paths, "_is_windows", lambda: True)
    paths._get_store_package_dirs.cache_clear()


def test_resolve_user_visible_path_prefers_physical_location(tmp_path, monkeypatch):
    base = tmp_path / "AppData" / "Local"
    package_dir = (
        base
        / "Packages"
        / "PythonSoftwareFoundation.Python.3.11_qbz5n2kfra8p0"
    )
    physical_root = package_dir / "LocalCache" / "Local"
    physical_file = physical_root / "VertexDTE" / "facturas" / "venta.pdf"
    physical_file.parent.mkdir(parents=True, exist_ok=True)
    physical_file.write_bytes(b"pdf")

    virtual_file = base / "VertexDTE" / "facturas" / "venta.pdf"
    virtual_file.parent.mkdir(parents=True, exist_ok=True)
    virtual_file.write_bytes(b"pdf")

    monkeypatch.setenv("LOCALAPPDATA", str(base))
    _force_windows(monkeypatch)

    resolved = paths.resolve_user_visible_path(str(virtual_file))
    assert resolved == str(physical_file)


def test_resolve_user_visible_path_falls_back_when_missing(tmp_path, monkeypatch):
    base = tmp_path / "AppData" / "Local"
    package_dir = (
        base
        / "Packages"
        / "PythonSoftwareFoundation.Python.3.11_qbz5n2kfra8p0"
    )
    package_dir.mkdir(parents=True, exist_ok=True)

    virtual_file = base / "VertexDTE" / "facturas" / "venta.pdf"

    monkeypatch.setenv("LOCALAPPDATA", str(base))
    _force_windows(monkeypatch)

    resolved = paths.resolve_user_visible_path(str(virtual_file))
    assert resolved == str(virtual_file)
