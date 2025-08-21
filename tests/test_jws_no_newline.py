from pathlib import Path
from utils.jws import sign_and_save


def test_sign_and_save_writes_jws_without_newline(monkeypatch, tmp_path):
    """Ensure sign_and_save writes JWS files without a trailing newline."""
    payload = {"identificacion": {"version": 1, "tipoDte": "01"}}

    def fake_sign_json(*args, **kwargs):
        return "TOKEN\n"

    monkeypatch.setattr("utils.jws.sign_json", fake_sign_json)

    json_path = tmp_path / "payload.json"
    jws_path = Path(sign_and_save(payload, str(json_path)))

    content = jws_path.read_bytes()
    assert content == b"TOKEN"
    assert not content.endswith(b"\n"), "JWS file should not end with a newline"
