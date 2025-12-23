from utils.certificates import copy_certificate_to_signer_dir, resolve_signer_cert_dir


def test_copy_certificate_from_signer_dir(monkeypatch, tmp_path):
    cert_dir = tmp_path / "certs"
    monkeypatch.setenv("FIRMADOR_CERT_DIR", str(cert_dir))
    cert_dir.mkdir()

    existing = cert_dir / "0614.crt"
    existing.write_bytes(b"contenido-anterior")

    extra = cert_dir / "otro.crt"
    extra.write_bytes(b"viejo")

    selected = cert_dir / "seleccionado.crt"
    selected.write_bytes(b"nuevo")

    dest = copy_certificate_to_signer_dir(selected, "0614")

    signer_dir = resolve_signer_cert_dir()
    canonical = signer_dir / "0614.crt"
    assert dest == canonical
    assert dest.read_bytes() == b"nuevo"
    assert not selected.exists(), "El archivo seleccionado debe reemplazarse por el canónico"
    assert not extra.exists(), "Otros certificados deben limpiarse"
    assert list(sorted(p.name for p in cert_dir.glob("*.crt"))) == ["0614.crt"]
