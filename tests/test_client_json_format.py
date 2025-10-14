import json

from utils.docs import build_client_json_payload, persist_client_json


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
