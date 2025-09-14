from utils.jws import sign_and_save


def test_sign_and_save_returns_token_without_creating_jws(monkeypatch, tmp_path):
    """`sign_and_save` should not create a `.jws` file on disk."""
    payload = {"identificacion": {"version": 1, "tipoDte": "01"}}

    def fake_sign_json(*args, **kwargs):
        return "TOKEN\n"

    monkeypatch.setattr("utils.jws.sign_json", fake_sign_json)

    json_path = tmp_path / "payload.json"
    path, token = sign_and_save(payload, str(json_path), return_token=True)

    assert token == "TOKEN"
    assert path == str(json_path)
    assert not (tmp_path / "payload.jws").exists()
