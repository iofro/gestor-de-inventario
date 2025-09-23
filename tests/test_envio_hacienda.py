import json
import logging
from decimal import Decimal
import pytest
import requests
import auth
import dte

from db import DB
from dte import transmitir_dte
from svfe import config as svfe_config
from tests.conftest import make_jws


@pytest.fixture(autouse=True)
def _datos_negocio_default(monkeypatch, tmp_path):
    datos = {
        "nombre": "ACME",
        "nombreComercial": "ACME",
        "nit": "0614-123456-102-3",
        "nrc": "1234567",
        "codActividad": "0000",
        "descActividad": "Giro",
        "tipoContribuyente": "Persona Jurídica",
        "telefono": "",
        "correo": "",
        "direccion": {
            "departamento": "06",
            "municipio": "23",
            "complemento": "Calle 1",
        },
        "dte_api": {"url": dte.DEFAULT_RECEPCION_URL, "ambiente": "pruebas"},
    }
    datos_path = tmp_path / "datos_negocio.json"
    datos_path.write_text(json.dumps(datos))
    config_path = tmp_path / "config_negocio.json"
    config_path.write_text("{}")
    monkeypatch.setattr(dte, "DATOS_NEGOCIO_PATH", str(datos_path))
    monkeypatch.setattr(dte, "CONFIG_NEGOCIO_PATH", str(config_path))
    monkeypatch.setattr(svfe_config, "DATOS_NEGOCIO_PATH", str(datos_path))


def _datos_negocio(url):
    return {
        "nombre": "ACME",
        "nombreComercial": "ACME",
        "nit": "0614-123456-102-3",
        "nrc": "1234567",
        "codActividad": "0000",
        "descActividad": "Giro",
        "tipoContribuyente": "Persona Jurídica",
        "telefono": "",
        "correo": "",
        "direccion": {
            "departamento": "06",
            "municipio": "23",
            "complemento": "Calle 1",
        },
        "dte_api": {"url": url, "ambiente": "pruebas"},
    }


def _patch_datos_negocio(monkeypatch, url):
    monkeypatch.setattr("dte._load_datos_negocio", lambda: _datos_negocio(url))
    monkeypatch.setattr(svfe_config, "load_datos_negocio", lambda: _datos_negocio(url))


def create_sale(db):

    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("P1", "X", None,  vid, None, 0, 0, 0, 1)
    pid = db.cursor.lastrowid
    venta_id = db.add_venta("2024-01-01", 10)
    db.add_detalle_venta(venta_id, pid, 1, 10, vendedor_id=vid)
    return venta_id


def test_transmision_exitosa(monkeypatch, tmp_path):
    db = DB(":memory:")
    recepcion_url = dte.DEFAULT_RECEPCION_URL
    _patch_datos_negocio(monkeypatch, recepcion_url)
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("P1", "X", None,  vid, None, 0, 0, 0, 1)
    pid = db.cursor.lastrowid
    db.add_cliente("Cliente", "", "0614-987654-321-0", "", "Giro", "", "", "Dir", "", "")
    cid = db.cursor.lastrowid
    venta = db.add_venta("2024-01-01", 10, cliente_id=cid)
    db.add_detalle_venta(venta, pid, 1, 10, vendedor_id=vid)

    captured = {}

    def fake_sign(data):
        captured["data"] = data
        captured["count"] = captured.get("count", 0) + 1
        return make_jws(data)

    monkeypatch.setattr("utils.jws.sign_json", fake_sign)
    
    tokens = {"count": 0}

    def fake_token():
        tokens["count"] += 1
        return "Bearer JWT"

    monkeypatch.setattr(auth, "get_token", fake_token)
    monkeypatch.setattr(auth, "get_last_auth_host", lambda: "apitest.dtes.mh.gob.sv")
    monkeypatch.setattr("dte.validate_dte_json", lambda d, db=None: None)
    monkeypatch.setattr(
        "dte.generar_dte_json",
        lambda db_obj, vid, **kwargs: {
            "receptor": {
                "nombre": "Cliente",
                "tipoDocumento": "36",
                "numDocumento": "06149876543210",
                "nrc": None,
                "codActividad": None,
                "descActividad": None,
                "direccion": None,
                "telefono": None,
                "correo": None,
            },
            "cuerpoDocumento": [{"cantidad": 1, "precioUni": 10}],
            "resumen": {
                "totalNoSuj": 0,
                "totalExenta": 0,
                "totalGravada": 10,
                "subTotalVentas": 10,
                "descuNoSuj": 0,
                "descuExenta": 0,
                "descuGravada": 0,
                "porcentajeDescuento": 0,
                "totalDescu": 0,
                "tributos": [],
                "subTotal": 10,
                "ivaRete1": 0,
                "reteRenta": 0,
                "montoTotalOperacion": 10,
                "totalNoGravado": 0,
                "totalPagar": 10,
                "totalLetras": "diez",
                "saldoFavor": 0,
                "condicionOperacion": 1,
                "pagos": None,
                "numPagoElectronico": None,
            },
                "identificacion": {
                    "tipoDte": "01",
                    "codigoGeneracion": "00000000-0000-4000-8000-000000000001",
                    "version": 1,
                    "ambiente": "00",
                },
        },
    )

    auth_url = "http://auth.test"
    calls = []

    class Resp:
        def __init__(self, data):
            self.data = data
            self.status_code = 200
            self.text = json.dumps(data)

        def json(self):
            return self.data

        def raise_for_status(self):
            pass

    def fake_post(url, *a, **k):
        headers = k.get("headers", {})
        calls.append((url, headers, k.get("data")))
        if url == auth_url:
            return Resp(
                {
                    "status": "OK",
                    "body": {
                        "token": "Bearer JWT",
                        "tokenType": "bearer",
                        "expiresIn": 3600,
                    },
                }
            )
        if url == recepcion_url:
            return Resp({"estado": "Transmitido", "sello": "ABC123"})
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr("requests.post", fake_post)

    transmitir_dte(db, venta)

    assert len(calls) == 1
    assert captured.get("count") == 1
    payload = captured["data"]
    assert payload["receptor"]["nombre"] == "Cliente"
    assert payload["receptor"]["numDocumento"] == "06149876543210"
    assert payload["cuerpoDocumento"][0]["cantidad"] == 1

    items_total = sum(
        i["cantidad"] * i.get("precioUni", 0)
        for i in payload["cuerpoDocumento"]
    )
    assert payload["resumen"]["subTotalVentas"] == pytest.approx(items_total)
    assert payload["resumen"]["totalPagar"] == pytest.approx(items_total)
    expected_iva = (Decimal(str(items_total)) * Decimal("0.13") / Decimal("1.13")).quantize(Decimal("0.01"))
    assert Decimal(str(payload["resumen"]["totalIva"])) == expected_iva
    assert payload["identificacion"]["tipoDte"] == "01"

    assert tokens["count"] == 1
    recep = [c for c in calls if c[0] == recepcion_url]
    assert recep[0][1]["Authorization"] == "Bearer JWT"

    row = db.cursor.execute(
        "SELECT estado, sello FROM dte_envios WHERE venta_id=?", (venta,)
    ).fetchone()
    assert row["estado"] == "Transmitido"
    assert row["sello"] == "ABC123"


@pytest.mark.parametrize("status", [401, 500])
def test_http_error_negativo(monkeypatch, tmp_path, status):
    """Token 401 and response 500 should mark envio as Rechazado."""
    db = DB(":memory:")
    venta = create_sale(db)

    monkeypatch.setattr("utils.jws.sign_json", lambda d: make_jws(d))
    monkeypatch.setattr(auth, "get_token", lambda: "Bearer JWT")
    monkeypatch.setattr(auth, "get_last_auth_host", lambda: "example.com")
    monkeypatch.setattr("dte.validate_dte_json", lambda d, db=None: None)

    class Resp:
        status_code = status
        text = f"error {status}"

        def json(self):
            return {"estado": "Rechazado", "descripcionMsg": self.text}

        def raise_for_status(self):
            raise requests.HTTPError(self.text)

    monkeypatch.setattr("dte.requests.post", lambda *a, **k: Resp())
    _patch_datos_negocio(monkeypatch, dte.DEFAULT_RECEPCION_URL)
    monkeypatch.setattr("dte.generar_dte_json", lambda *a, **k: _make_minimal_dte())
    monkeypatch.setattr(auth, "get_last_auth_host", lambda: "apitest.dtes.mh.gob.sv")

    resp = transmitir_dte(db, venta)
    assert resp["estado"] == "Rechazado"
    detalle_text = str(resp.get("detalle"))
    assert detalle_text
    row = db.cursor.execute(
        "SELECT estado, count(*) c FROM dte_envios WHERE venta_id=?", (venta,)
    ).fetchone()
    assert row["estado"] == "Rechazado"
    assert row["c"] == 1


def test_firma_fallida_negativo(monkeypatch, tmp_path):
    db = DB(":memory:")
    venta = create_sale(db)

    monkeypatch.setattr(auth, "get_token", lambda: "Bearer JWT")
    monkeypatch.setattr(auth, "get_last_auth_host", lambda: "example.com")
    monkeypatch.setattr("dte.validate_dte_json", lambda d, db=None: None)

    def fail(*a, **k):
        raise RuntimeError("firma")

    monkeypatch.setattr("utils.jws.sign_json", fail)

    called = {}

    def fake_post(*a, **k):
        called["called"] = True
        raise AssertionError("should not post")

    monkeypatch.setattr("dte.requests.post", fake_post)

    _patch_datos_negocio(monkeypatch, dte.DEFAULT_RECEPCION_URL)
    monkeypatch.setattr("dte.generar_dte_json", lambda *a, **k: _make_minimal_dte())
    monkeypatch.setattr(auth, "get_last_auth_host", lambda: "apitest.dtes.mh.gob.sv")

    with pytest.raises(RuntimeError):
        transmitir_dte(db, venta)

    row = db.cursor.execute(
        "SELECT count(*) c FROM dte_envios WHERE venta_id=?", (venta,)
    ).fetchone()
    assert row["c"] == 0
    assert "called" not in called

def test_transmision_token_401_en_recepcion(monkeypatch, tmp_path):
    db = DB(":memory:")
    venta = create_sale(db)

    monkeypatch.setattr("utils.jws.sign_json", lambda d: make_jws(d))
    monkeypatch.setattr("dte.validate_dte_json", lambda d: None)

    token_calls = []

    def fake_get_token(refresh: bool = False):
        token_calls.append(refresh)
        return "Bearer JWT_VALIDO"

    monkeypatch.setattr(auth, "get_token", fake_get_token)
    monkeypatch.setattr(auth, "get_last_auth_host", lambda: "example.com")

    calls = {"auth": 0, "recepcion": 0}

    class RespAuth:
        status_code = 200

        def json(self):
            return {
                "status": "OK",
                "body": {
                    "token": "Bearer JWT_VALIDO",
                    "tokenType": "bearer",
                    "expiresIn": 3600,
                },
            }

        def raise_for_status(self):
            pass

    class Resp401:
        status_code = 401
        text = "TOKEN_INVALIDO"

        def json(self):
            return {"estado": "Rechazado", "descripcionMsg": self.text}

        def raise_for_status(self):
            raise requests.HTTPError(self.text)

    def fake_post(url, *a, **k):
        if "auth" in url:
            calls["auth"] += 1
            return RespAuth()
        calls["recepcion"] += 1
        return Resp401()

    monkeypatch.setattr("dte.requests.post", fake_post)
    monkeypatch.setattr("auth.requests.post", fake_post)

    _patch_datos_negocio(monkeypatch, dte.DEFAULT_RECEPCION_URL)
    monkeypatch.setattr("dte.generar_dte_json", lambda *a, **k: _make_minimal_dte())
    monkeypatch.setattr(auth, "get_last_auth_host", lambda: "apitest.dtes.mh.gob.sv")

    resp = transmitir_dte(db, venta)

    assert resp["estado"] == "Rechazado"
    assert "TOKEN" in str(resp.get("detalle", "")).upper()
    assert calls["recepcion"] <= 2
    assert len(token_calls) <= 2

    row = db.cursor.execute(
        "SELECT estado, count(*) c FROM dte_envios WHERE venta_id=?", (venta,),
    ).fetchone()
    assert row["estado"] == "Rechazado"
    assert row["c"] == 1


def test_timeout_no_modifica_extra(monkeypatch, tmp_path):
    db = DB(":memory:")
    venta = create_sale(db)

    monkeypatch.setattr("utils.jws.sign_json", lambda d: make_jws(d))
    monkeypatch.setattr(auth, "get_token", lambda: "Bearer JWT")
    monkeypatch.setattr(auth, "get_last_auth_host", lambda: "example.com")
    monkeypatch.setattr("dte.validate_dte_json", lambda d: None)

    def fake_post(*a, **k):
        raise requests.Timeout("timeout")

    monkeypatch.setattr("dte.requests.post", fake_post)

    _patch_datos_negocio(monkeypatch, dte.DEFAULT_RECEPCION_URL)
    monkeypatch.setattr("dte.generar_dte_json", lambda *a, **k: _make_minimal_dte())
    monkeypatch.setattr(auth, "get_last_auth_host", lambda: "apitest.dtes.mh.gob.sv")

    resp = transmitir_dte(db, venta)
    assert resp["estado"] == "Error"

    row = db.cursor.execute(
        "SELECT estado, sello FROM dte_envios WHERE venta_id=?", (venta,)
    ).fetchone()
    assert row["estado"] == "Error"
    assert row["sello"] == ""
    extra = db.cursor.execute("SELECT extra FROM ventas WHERE id=?", (venta,)).fetchone()["extra"]
    assert not extra


def test_recepcion_url_host_mismatch(monkeypatch, tmp_path, caplog):
    db = DB(":memory:")
    venta = create_sale(db)
    monkeypatch.setattr("utils.jws.sign_json", lambda d: make_jws(d))
    monkeypatch.setattr(auth, "get_token", lambda: "Bearer JWT")
    monkeypatch.setattr(auth, "get_last_auth_host", lambda: "auth.example")
    monkeypatch.setattr("dte.validate_dte_json", lambda d, db=None: None)
    _patch_datos_negocio(monkeypatch, dte.DEFAULT_RECEPCION_URL)
    monkeypatch.setattr(
        dte,
        "generar_dte_json",
        lambda db, vid, **kwargs: {
            "identificacion": {
                "ambiente": "00",
                "version": "1",
                "tipoDte": "01",
                "codigoGeneracion": "ABC",
            },
            "resumen": {"totalLetras": "X"},
        },
    )
    called = {}

    def fake_post(url, token, jws_token, meta):
        called["url"] = url
        return {"estado": "Transmitido", "sello": "S"}

    monkeypatch.setattr(dte, "_post_dte", fake_post)
    with caplog.at_level(logging.WARNING):
        transmitir_dte(db, venta)
    assert "Auth host auth.example ≠ recepción apitest.dtes.mh.gob.sv" in caplog.text
    assert called["url"].endswith("/fesv/recepciondte")


def _make_minimal_dte():
    return {
        "identificacion": {
            "tipoDte": "01",
            "codigoGeneracion": "00000000-0000-4000-8000-000000000123",
            "version": 1,
            "ambiente": "00",
        },
        "resumen": {
            "totalLetras": "cero",
            "condicionOperacion": 1,
            "totalPagar": 0,
            "montoTotalOperacion": 0,
            "totalGravada": 0,
            "totalNoSuj": 0,
            "totalExenta": 0,
        },
    }


def test_enviar_documento_prefiere_token_manual(monkeypatch):
    db = DB(":memory:")
    data = _make_minimal_dte()
    manual_token = "Manual TOKEN"
    url = dte.DEFAULT_RECEPCION_URL

    monkeypatch.setattr(
        dte,
        "_load_dte_api_config",
        lambda: {"url": url, "ambiente": "pruebas", "token": manual_token},
    )
    monkeypatch.setattr(dte.jws, "sign_json", lambda payload: make_jws(payload))
    monkeypatch.setattr(dte, "_save_signed_dte", lambda *a, **k: None)
    monkeypatch.setattr(auth, "get_token", lambda: (_ for _ in ()).throw(AssertionError))
    monkeypatch.setattr(auth, "get_last_auth_host", lambda: None)

    usados = []

    def fake_post(url, token, signed, meta):
        usados.append(token)
        return {"estado": "Transmitido", "sello": "S"}

    monkeypatch.setattr(dte, "_post_dte", fake_post)

    resp = dte._enviar_documento(db, None, data, modo="normal")

    assert resp["estado"] == "Transmitido"
    assert usados == [manual_token]


def test_transmitir_orphan_fallback_a_token_auto(monkeypatch, tmp_path):
    db = DB(":memory:")
    data = _make_minimal_dte()
    json_path = tmp_path / "doc.json"
    json_path.write_text(json.dumps(data), encoding="utf-8")
    manual_token = "Manual TOKEN"
    url = dte.DEFAULT_RECEPCION_URL

    monkeypatch.setattr(
        dte,
        "_load_dte_api_config",
        lambda: {"url": url, "ambiente": "pruebas", "token": manual_token},
    )
    monkeypatch.setattr(dte, "apply_schema_patch", lambda raw: raw)
    monkeypatch.setattr(dte, "recalcular_totales", lambda *a, **k: None)
    monkeypatch.setattr(dte.catalogos, "get_dte_schema", lambda *a, **k: {})
    monkeypatch.setattr(dte.jws, "sign_json", lambda payload: make_jws(payload))

    tokens = []
    responses = [
        {"estado": "Rechazado", "http_status": 401, "detalle": "Token inválido"},
        {"estado": "Transmitido", "sello": "S"},
    ]

    def fake_post(url, token, signed, meta):
        tokens.append(token)
        return responses.pop(0)

    monkeypatch.setattr(dte, "_post_dte", fake_post)

    auto_tokens = iter(["Bearer AUTO"])

    def fake_get_token():
        try:
            return next(auto_tokens)
        except StopIteration:
            raise AssertionError("get_token llamado más veces de lo esperado")

    monkeypatch.setattr(auth, "get_token", fake_get_token)
    monkeypatch.setattr(auth, "get_last_auth_host", lambda: "apitest.dtes.mh.gob.sv")
    monkeypatch.setattr("dte.generar_dte_json", lambda *a, **k: _make_minimal_dte())

    resp = dte.transmitir_dte_orphan(db, str(json_path))

    assert resp["estado"] == "Transmitido"
    assert tokens == [manual_token, "Bearer AUTO"]
