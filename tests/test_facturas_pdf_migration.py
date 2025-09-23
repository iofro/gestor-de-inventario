import json
import os
from pathlib import Path

import pytest

import db
import paths


def _override_user_data(monkeypatch: pytest.MonkeyPatch, base_dir: Path) -> None:
    user_dir = base_dir / "user-data"
    user_dir.mkdir(parents=True, exist_ok=True)

    def _user_data_path(*parts: str) -> Path:
        if not parts:
            return user_dir
        path = user_dir.joinpath(*parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _ensure_user_dir(*parts: str) -> Path:
        path = user_dir.joinpath(*parts)
        path.mkdir(parents=True, exist_ok=True)
        return path

    monkeypatch.setattr(paths, "USER_DATA_DIR", user_dir)
    monkeypatch.setattr(paths, "user_data_path", _user_data_path)
    monkeypatch.setattr(paths, "ensure_user_dir", _ensure_user_dir)

    # Rebind helpers imported in db.py so they use the patched paths module.
    monkeypatch.setattr(db, "user_data_path", _user_data_path)
    monkeypatch.setattr(db, "get_canonical_dte_dir", paths.get_canonical_dte_dir)

    for attr, tipo in [
        ("FACTURAS_CONSUMIDOR_FINAL_DIR", "ConsumidorFinal"),
        ("FACTURAS_CREDITO_FISCAL_DIR", "CreditoFiscal"),
        ("NOTAS_CREDITO_DIR", "NotaCredito"),
        ("NOTAS_DEBITO_DIR", "NotaDebito"),
        ("NOTAS_REMISION_DIR", "NotaRemision"),
    ]:
        if hasattr(paths, attr):
            monkeypatch.setattr(paths, attr, str(paths.get_canonical_dte_dir(tipo)), raising=False)


def _create_db(tmp_path: Path) -> db.DB:
    database = db.DB(str(tmp_path / "inventario.sqlite"))
    # Ensure migration runs only on the records created inside each test.
    return database


def test_migrate_facturas_pdf_paths_moves_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _override_user_data(monkeypatch, tmp_path)
    database = _create_db(tmp_path)

    legacy_dir = tmp_path / "legacy"
    legacy_dir.mkdir()
    legacy_pdf = legacy_dir / "venta.pdf"
    legacy_json = legacy_dir / "venta.json"
    legacy_pdf.write_bytes(b"PDF")
    legacy_json.write_text(json.dumps({"venta": 1}), encoding="utf-8")

    database.cursor.execute(
        "INSERT INTO facturas_pdf (venta_id, tipo, ruta, fecha_creacion) VALUES (?, ?, ?, ?)",
        (None, "consumidor final", os.fspath(legacy_pdf), "2024-01-01 00:00:00"),
    )
    record_id = database.cursor.lastrowid
    database.conn.commit()

    database.migrate_facturas_pdf_paths()

    canonical_pdf = paths.get_canonical_dte_dir("ConsumidorFinal") / legacy_pdf.name
    canonical_json = canonical_pdf.with_suffix(".json")

    assert canonical_pdf.exists()
    assert canonical_pdf.read_bytes() == b"PDF"
    assert canonical_json.exists()
    assert json.loads(canonical_json.read_text(encoding="utf-8")) == {"venta": 1}
    # Legacy files remain in place until the user chooses to clean them up.
    assert legacy_pdf.exists()
    assert legacy_json.exists()

    row = database.cursor.execute(
        "SELECT ruta FROM facturas_pdf WHERE id=?",
        (record_id,),
    ).fetchone()
    assert row is not None
    assert os.path.abspath(row["ruta"]) == os.path.abspath(os.fspath(canonical_pdf))


def test_migrate_facturas_pdf_paths_updates_existing_canonical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _override_user_data(monkeypatch, tmp_path)
    database = _create_db(tmp_path)

    canonical_pdf = paths.get_canonical_dte_dir("ConsumidorFinal") / "venta.pdf"
    canonical_pdf.parent.mkdir(parents=True, exist_ok=True)
    canonical_pdf.write_bytes(b"CANONICAL")
    canonical_json = canonical_pdf.with_suffix(".json")
    canonical_json.write_text(json.dumps({"venta": 2}), encoding="utf-8")

    missing_legacy = tmp_path / "legacy" / "venta.pdf"

    database.cursor.execute(
        "INSERT INTO facturas_pdf (venta_id, tipo, ruta, fecha_creacion) VALUES (?, ?, ?, ?)",
        (None, "CF", os.fspath(missing_legacy), "2024-01-02 00:00:00"),
    )
    record_id = database.cursor.lastrowid
    database.conn.commit()

    database.migrate_facturas_pdf_paths()

    assert canonical_pdf.exists()
    assert canonical_pdf.read_bytes() == b"CANONICAL"
    assert canonical_json.exists()
    assert json.loads(canonical_json.read_text(encoding="utf-8")) == {"venta": 2}

    row = database.cursor.execute(
        "SELECT ruta FROM facturas_pdf WHERE id=?",
        (record_id,),
    ).fetchone()
    assert row is not None
    assert os.path.abspath(row["ruta"]) == os.path.abspath(os.fspath(canonical_pdf))

    # No legacy file was ever present, migration simply updated the stored path.
    assert not missing_legacy.exists()
