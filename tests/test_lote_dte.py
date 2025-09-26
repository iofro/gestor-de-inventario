import dte
import auth
from utils import jws


def _make_dte(idx):
    return {
        "identificacion": {
            "version": 1,
            "ambiente": "00",
            "tipoDte": "01",
            "codigoGeneracion": f"COD{idx}",
        }
    }


def test_enviar_lote_dtes_envia_lote_y_registra_codigo(monkeypatch):
    pendientes = [(i + 1, _make_dte(i)) for i in range(3)]

    monkeypatch.setattr(jws, "sign_json", lambda data: f"signed-{data['identificacion']['codigoGeneracion']}")

    captured = {"posts": []}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["posts"].append((url, headers, json))

        class Resp:
            content = b"{}"

            def json(self):
                return {"codigoLote": "L123", "estado": "RECIBIDO"}

        return Resp()

    monkeypatch.setattr(dte.requests, "post", fake_post)
    monkeypatch.setattr(dte, "_load_dte_api_config", lambda: {"url": "http://example"})
    monkeypatch.setattr(auth, "get_token", lambda: "TOKEN")

    class DummyDB:
        def __init__(self):
            self.reg = []

        def registrar_envio_dte(
            self,
            venta_id,
            modo,
            estado,
            sello,
            respuesta_json="",
            codigo_lote=None,
            codigo_generacion=None,
            numero_control=None,
        ):
            self.reg.append((venta_id, modo, estado, codigo_lote))

    db = DummyDB()

    resp = dte.enviar_lote_dtes(pendientes, db=db)

    assert len(captured["posts"]) == 1
    url, headers, body = captured["posts"][0]
    assert url == "http://example/lote"
    assert headers["Authorization"] == "Bearer TOKEN"
    assert body["cantidadDocumentos"] == 3
    assert db.reg == [
        (1, "lote", "RECIBIDO", "L123"),
        (2, "lote", "RECIBIDO", "L123"),
        (3, "lote", "RECIBIDO", "L123"),
    ]
    assert resp[0]["codigoLote"] == "L123"


def test_enviar_lote_dtes_divide_batches(monkeypatch):
    pendientes = [(i, _make_dte(i)) for i in range(101)]
    monkeypatch.setattr(jws, "sign_json", lambda data: "x")
    posts = []

    def fake_post(url, headers=None, json=None, timeout=None):
        posts.append((headers, json))

        class Resp:
            content = b"{}"

            def json(self):
                return {"codigoLote": "L", "estado": "RECIBIDO"}

        return Resp()

    monkeypatch.setattr(dte.requests, "post", fake_post)
    monkeypatch.setattr(dte, "_load_dte_api_config", lambda: {"url": "http://example"})
    monkeypatch.setattr(auth, "get_token", lambda: "TOKEN")

    class DummyDB:
        def registrar_envio_dte(self, *a, **k):
            pass

    dte.enviar_lote_dtes(pendientes, db=DummyDB())

    assert len(posts) == 2
    assert posts[0][0]["Authorization"] == "Bearer TOKEN"
    assert posts[0][1]["cantidadDocumentos"] == 100
    assert posts[1][0]["Authorization"] == "Bearer TOKEN"
    assert posts[1][1]["cantidadDocumentos"] == 1


def test_consultar_estado_lote(monkeypatch):
    monkeypatch.setattr(dte, "_load_dte_api_config", lambda: {"url": "http://example"})
    monkeypatch.setattr(auth, "get_token", lambda: "TOKEN")
    captured = {}

    def fake_get(url, headers=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers

        class Resp:
            def json(self):
                return {"estado": "EN_PROCESO"}

        return Resp()

    monkeypatch.setattr(dte.requests, "get", fake_get)

    resp = dte.consultar_estado_lote("ABC")

    assert captured["url"] == "http://example/lote/ABC"
    assert captured["headers"]["Authorization"] == "Bearer TOKEN"
    assert resp["estado"] == "EN_PROCESO"


def test_enviar_lote_dtes_reuses_bearer_prefix(monkeypatch):
    pendientes = [(1, _make_dte(1))]

    monkeypatch.setattr(jws, "sign_json", lambda data: "signed")

    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["headers"] = headers

        class Resp:
            content = b"{}"

            def json(self):
                return {"codigoLote": "L1", "estado": "RECIBIDO"}

        return Resp()

    monkeypatch.setattr(dte.requests, "post", fake_post)
    monkeypatch.setattr(dte, "_load_dte_api_config", lambda: {"url": "http://example"})
    monkeypatch.setattr(auth, "get_token", lambda: "Bearer CLEAN")

    class DummyDB:
        def registrar_envio_dte(self, *a, **k):
            pass

    dte.enviar_lote_dtes(pendientes, db=DummyDB())

    assert captured["headers"]["Authorization"] == "Bearer CLEAN"


def test_consultar_estado_lote_reuses_bearer_prefix(monkeypatch):
    monkeypatch.setattr(dte, "_load_dte_api_config", lambda: {"url": "http://example"})
    monkeypatch.setattr(auth, "get_token", lambda: "Bearer CLEAN")

    captured = {}

    def fake_get(url, headers=None, timeout=None):
        captured["headers"] = headers

        class Resp:
            def json(self):
                return {"estado": "OK"}

        return Resp()

    monkeypatch.setattr(dte.requests, "get", fake_get)

    dte.consultar_estado_lote("XYZ")

    assert captured["headers"]["Authorization"] == "Bearer CLEAN"
