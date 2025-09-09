import dte

def test_enviar_lote_dtes_divide_and_assign(monkeypatch):
    pendientes = [{"dte_json": {"n": i}} for i in range(150)]

    monkeypatch.setattr(dte.jws, "sign_json", lambda data: f"tok{data['n']}")
    monkeypatch.setattr(dte.auth, "get_token", lambda: "TOKEN")
    monkeypatch.setattr(dte, "_load_dte_api_config", lambda: {"url": "https://api.example/fesv/recepciondte"})

    calls = []

    def fake_post_lote(url, token, documentos):
        calls.append((url, token, documentos))
        return {"codigoLote": f"L{len(calls)}"}

    monkeypatch.setattr(dte, "_post_lote", fake_post_lote)

    responses = dte.enviar_lote_dtes(pendientes)

    assert len(responses) == 2
    assert len(calls) == 2
    assert calls[0][0].endswith("/recepcionlote")
    assert len(calls[0][2]) == 100
    assert len(calls[1][2]) == 50
    assert all(p["codigoLote"] == "L1" for p in pendientes[:100])
    assert all(p["codigoLote"] == "L2" for p in pendientes[100:])


def test_consultar_estado_lote(monkeypatch):
    monkeypatch.setattr(dte, "_load_dte_api_config", lambda: {"url": "https://api.example/fesv/recepciondte"})
    monkeypatch.setattr(dte.auth, "get_token", lambda: "TOKEN")

    captured = {}

    def fake_get(url, headers=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers

        class R:
            status_code = 200
            text = ""

            def json(self):
                return {"estado": "OK"}

        return R()

    monkeypatch.setattr(dte.requests, "get", fake_get)

    res = dte.consultar_estado_lote("ABC123")

    assert captured["url"] == "https://api.example/fesv/consultalote/ABC123"
    assert captured["headers"]["Authorization"] == "Bearer TOKEN"
    assert res == {"estado": "OK"}
