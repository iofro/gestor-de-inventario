import json
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
