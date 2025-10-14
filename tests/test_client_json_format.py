import json
from pathlib import Path

from utils.docs import (
    build_client_json_payload,
    persist_client_json,
    sync_client_json_with_canonical,
)
from utils import versioned_dte
from utils.stable_json import stable_stringify


def test_persist_client_json_creates_backup(tmp_path):
    target_dir = tmp_path / "documentos"
    target_dir.mkdir()
    json_path = target_dir / "sample.json"

    dte_payload = {
        "identificacion": {"numeroControl": "DTE-01-00000001"},
        "resumen": {},
    }

    persist_client_json(json_path, dte_payload, firma="FIRMA", sello="SELLO-123")

    written = json.loads(json_path.read_text(encoding="utf-8"))
    assert written["firmaElectronica"] == "FIRMA"
    assert written["selloRecibido"] == "SELLO-123"
    assert written["dteJson"]["identificacion"]["numeroControl"] == "DTE-01-00000001"
    assert "firmaElectronica" not in written["dteJson"]
    assert "selloRecibido" not in written["dteJson"]

    backup_path = target_dir / "copia de seguridad" / "sample.json"
    assert backup_path.exists()
    backup = json.loads(backup_path.read_text(encoding="utf-8"))
    assert backup == written


def test_build_client_json_payload_preserves_existing_values():
    existing = {
        "dteJson": {"identificacion": {"codigoGeneracion": "OLD"}},
        "firmaElectronica": "TOKEN-OLD",
        "selloRecibido": "EXISTENTE",
    }

    updated = build_client_json_payload(
        existing["dteJson"], existing_payload=existing, firma=None, sello=None
    )

    assert updated["firmaElectronica"] == "TOKEN-OLD"
    assert updated["selloRecibido"] == "EXISTENTE"


def test_sync_client_json_with_canonical(tmp_path):
    codigo = "0aa8b0a4-05f4-4f1a-9c40-5f9a5f84a1d9"
    version_dir_path = Path(versioned_dte.resolve_version_dir(tmp_path, codigo))
    version_dir_path.mkdir(parents=True, exist_ok=True)
    canonical_payload = {
        "identificacion": {
            "codigoGeneracion": codigo.upper(),
            "numeroControl": "DTE-01-S001P001-00000001",
        },
        "resumen": {"totalPagar": 10},
    }
    canonical_path = version_dir_path / "documento.json"
    canonical_path.write_text(stable_stringify(canonical_payload, indent=2), encoding="utf-8")

    json_path = tmp_path / "factura.json"
    persist_client_json(
        json_path,
        {"identificacion": {"codigoGeneracion": "DIFF"}},
        firma="FIRMA-123",
        sello="SELLO-999",
    )

    sync_code, sync_sello = sync_client_json_with_canonical(
        json_path,
        codigo=codigo,
        sello="SELLO-ABC",
        base_dir=tmp_path,
    )

    assert sync_code == codigo.upper()
    assert sync_sello == "SELLO-ABC"

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["dteJson"]["identificacion"]["codigoGeneracion"] == codigo.upper()
    assert payload["firmaElectronica"] == "FIRMA-123"
    assert payload["selloRecibido"] == "SELLO-ABC"
