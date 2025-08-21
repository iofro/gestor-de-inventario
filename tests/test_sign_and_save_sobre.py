import json
import dte
from utils.jws import sign_and_save


def test_sign_and_save_creates_sobre(monkeypatch, tmp_path):
    payload = {
        "identificacion": {
            "version": 1,
            "tipoDte": "01",
            "codigoGeneracion": "ABC123",
            "ambiente": "00",
        }
    }
    # Simulate signature -> valid JWS (3 segments)
    monkeypatch.setattr("utils.jws.sign_json", lambda *a, **k: "a.b.c")

    # validate_dte_json should never be invoked for the sobre
    def explode(*a, **k):
        raise AssertionError("validate_dte_json llamado")

    monkeypatch.setattr(dte, "validate_dte_json", explode)

    json_path = tmp_path / "doc.json"
    sign_and_save(payload, str(json_path))

    sobre_path = json_path.with_name(json_path.stem + "-sobre.json")
    assert sobre_path.exists(), "sobre no guardado"
    data = json.loads(sobre_path.read_text(encoding="utf-8"))
    assert data["documento"] == "a.b.c"
    ident = payload["identificacion"]
    assert str(data["version"]) == str(ident["version"])
    assert str(data["tipoDte"]).zfill(2) == str(ident["tipoDte"]).zfill(2)
    assert data["codigoGeneracion"] == ident["codigoGeneracion"]
    assert data["ambiente"] == ident["ambiente"]
    assert data["idEnvio"] >= 1


def test_sign_and_save_overwrites_sobre(monkeypatch, tmp_path):
    payload = {
        "identificacion": {
            "version": 1,
            "tipoDte": "01",
            "codigoGeneracion": "ABC123",
            "ambiente": "00",
        }
    }
    json_path = tmp_path / "doc.json"

    monkeypatch.setattr("utils.jws.sign_json", lambda *a, **k: "a.b.c")
    sign_and_save(payload, str(json_path))

    monkeypatch.setattr("utils.jws.sign_json", lambda *a, **k: "d.e.f")
    sign_and_save(payload, str(json_path))

    sobre_path = json_path.with_name(json_path.stem + "-sobre.json")
    data = json.loads(sobre_path.read_text(encoding="utf-8"))
    assert data["documento"] == "d.e.f", "sobre no sobrescrito"


def test_sign_and_save_invalid_sobre(monkeypatch, tmp_path, caplog):
    payload = {
        "identificacion": {
            "version": 1,
            "tipoDte": "01",
            "codigoGeneracion": "ABC123",
            "ambiente": "00",
        }
    }

    monkeypatch.setattr("utils.jws.sign_json", lambda *a, **k: "a.b.c")

    def construir_invalid(jws, dte_full):
        return {
            "ambiente": "00",
            "idEnvio": 1,
            "version": 1,
            "tipoDte": "01",
            "codigoGeneracion": "ABC123",
            # documento mal formado (solo dos segmentos)
            "documento": "mal.formado",
        }

    monkeypatch.setattr(dte, "construir_sobre_recepcion", construir_invalid)

    json_path = tmp_path / "doc.json"
    with caplog.at_level("ERROR"):
        sign_and_save(payload, str(json_path))

    assert json_path.exists()
    assert json_path.with_suffix(".jws").exists()
    # sobre no debe crearse
    assert not json_path.with_name(json_path.stem + "-sobre.json").exists()
    assert "sobre" in caplog.text
