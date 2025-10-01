import copy
from datetime import datetime

import auth
import dte
import pytest
from db import DB


def test_enviar_documento_preserva_fecemi_factura(monkeypatch):
    db = DB(":memory:")
    controlled_date = "2024-01-15"
    data = {
        "identificacion": {
            "tipoDte": "01",
            "codigoGeneracion": "UUID-123",
            "numeroControl": "DTE-01-ABC-000000000000001",
            "fecEmi": controlled_date,
        },
        "resumen": {"totalLetras": "DIEZ"},
    }

    calls = {"sign": 0, "post": 0}
    captured: dict[str, dict] = {}

    monkeypatch.setattr(auth, "get_last_auth_host", lambda: None)
    monkeypatch.setattr(
        dte,
        "_load_dte_api_config",
        lambda: {"url": "https://apitest.dtes.mh.gob.sv/fesv/recepciondte"},
    )
    monkeypatch.setattr(dte, "_save_signed_dte", lambda *args, **kwargs: None)
    monkeypatch.setattr(dte, "fecha_emision_hoy_str", lambda now=None: "2077-07-07")

    def fake_sign(payload):
        calls["sign"] += 1
        captured["payload"] = copy.deepcopy(payload)
        return "token"

    def fake_decode(token):
        assert token == "token"
        return copy.deepcopy(captured["payload"])

    def fake_post(url, documento, meta, **kwargs):
        calls["post"] += 1
        captured["meta"] = copy.deepcopy(meta)
        return {"estado": "Procesado"}

    monkeypatch.setattr("utils.jws.sign_json", fake_sign)
    monkeypatch.setattr(dte, "_decode_jws_payload", fake_decode)
    monkeypatch.setattr(dte, "_post_dte", fake_post)

    result = dte._enviar_documento(db, 1, data, "normal")

    assert result["estado"] == "Procesado"
    assert calls["sign"] == 1
    assert calls["post"] == 1
    assert captured["payload"]["identificacion"]["fecEmi"] == controlled_date
    assert data["identificacion"]["fecEmi"] == controlled_date


class _DummyCursor:
    def execute(self, *args, **kwargs):
        return self

    def fetchone(self):
        return None


class _DummyDB:
    def __init__(self):
        self.cursor = _DummyCursor()
        self.recorded: list[tuple] = []

    def ensure_column(self, *args, **kwargs):
        return None

    def registrar_envio_dte(self, *args, **kwargs):
        self.recorded.append((args, kwargs))


def _base_identificacion() -> dict:
    return {
        "tipoDte": "01",
        "codigoGeneracion": "UUID-123",
        "numeroControl": "DTE-01-S001P001-000000000000001",
        "fecEmi": "2024-01-15",
        "tipoModelo": 1,
        "tipoOperacion": 1,
        "tipoContingencia": None,
        "motivoContin": None,
    }


def _base_data() -> dict:
    return {"identificacion": _base_identificacion(), "resumen": {"totalLetras": "DIEZ"}}


class _FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2024, 1, 15, 12, 0, 0, tzinfo=tz)


def test_enviar_documento_contingencia_inyecta_configuracion(monkeypatch):
    db = _DummyDB()
    captured: dict[str, dict] = {}

    monkeypatch.setattr(auth, "get_last_auth_host", lambda: None)
    monkeypatch.setattr(dte, "_load_dte_api_config", lambda: {"url": "https://ejemplo"})
    monkeypatch.setattr(dte, "_load_datos_negocio", lambda: {"dte_api": {"tipo_contingencia": 3, "motivo_contin": "texto"}})
    monkeypatch.setattr(dte, "_save_signed_dte", lambda *a, **k: None)

    def fake_sign(payload):
        captured["payload"] = copy.deepcopy(payload)
        return "token"

    monkeypatch.setattr("utils.jws.sign_json", fake_sign)

    data = _base_data()
    result = dte._enviar_documento(db, 1, data, "contingencia")

    assert result == {"estado": "Pendiente"}
    ident = captured["payload"]["identificacion"]
    assert ident["tipoModelo"] == 2
    assert ident["tipoOperacion"] == 2
    assert ident["tipoContingencia"] == 3
    assert ident.get("motivoContin") is None
    assert db.recorded  # Se registró el envío local


@pytest.mark.parametrize("tipo_dte", ["01", "04", "05", "06"])
@pytest.mark.parametrize("motivo", ["", "x" * 501])
def test_enviar_documento_contingencia_motivo_invalido(monkeypatch, motivo, tipo_dte):
    db = _DummyDB()

    monkeypatch.setattr(auth, "get_last_auth_host", lambda: None)
    monkeypatch.setattr(dte, "_load_dte_api_config", lambda: {"url": "https://ejemplo"})
    monkeypatch.setattr(
        dte,
        "_load_datos_negocio",
        lambda: {"dte_api": {"tipo_contingencia": 5, "motivo_contin": motivo}},
    )
    monkeypatch.setattr(dte, "_save_signed_dte", lambda *a, **k: None)

    data = _base_data()
    data["identificacion"]["tipoDte"] = tipo_dte

    with pytest.raises(ValueError):
        dte._enviar_documento(db, 1, data, "contingencia")


@pytest.mark.parametrize("tipo_dte", ["04", "05", "06"])
def test_enviar_documento_contingencia_notas_tipo5(monkeypatch, tipo_dte):
    db = _DummyDB()
    captured: dict[str, dict] = {}

    monkeypatch.setattr(auth, "get_last_auth_host", lambda: None)
    monkeypatch.setattr(dte, "_load_dte_api_config", lambda: {"url": "https://ejemplo"})
    monkeypatch.setattr(
        dte,
        "_load_datos_negocio",
        lambda: {"dte_api": {"tipo_contingencia": 5, "motivo_contin": "Motivo"}},
    )
    monkeypatch.setattr(dte, "_save_signed_dte", lambda *a, **k: None)

    def fake_sign(payload):
        captured["payload"] = copy.deepcopy(payload)
        return "token"

    monkeypatch.setattr("utils.jws.sign_json", fake_sign)

    data = _base_data()
    ident = data["identificacion"]
    ident["tipoDte"] = tipo_dte
    ident.pop("tipoModelo", None)
    ident.pop("tipoOperacion", None)
    ident["modeloFacturacion"] = 1
    ident["tipoTransmision"] = 1

    result = dte._enviar_documento(db, 99, data, "contingencia")

    assert result == {"estado": "Pendiente"}
    ident_signed = captured["payload"]["identificacion"]
    assert ident_signed["tipoModelo"] == 2
    assert ident_signed["tipoOperacion"] == 2
    assert ident_signed["tipoContingencia"] == 5
    assert ident_signed["motivoContin"] == "Motivo"
    assert "modeloFacturacion" not in ident_signed
    assert "tipoTransmision" not in ident_signed


def test_enviar_documento_contingencia_modo_derivado(monkeypatch):
    db = _DummyDB()
    captured: dict[str, dict] = {}

    monkeypatch.setattr(auth, "get_last_auth_host", lambda: None)
    monkeypatch.setattr(dte, "_load_dte_api_config", lambda: {"url": "https://ejemplo"})
    monkeypatch.setattr(dte, "_save_signed_dte", lambda *a, **k: None)
    monkeypatch.setattr(
        dte,
        "_load_datos_negocio",
        lambda: {"dte_api": {"tipo_contingencia": 2, "motivo_contin": None}},
    )
    monkeypatch.setattr(dte, "get_default_modo_transmision", lambda: "contingencia")

    def fake_sign(payload):
        captured["payload"] = copy.deepcopy(payload)
        return "token"

    monkeypatch.setattr("utils.jws.sign_json", fake_sign)

    data = _base_data()
    result = dte._enviar_documento(db, 1, data, None)

    assert result == {"estado": "Pendiente"}
    ident_signed = captured["payload"]["identificacion"]
    assert ident_signed["tipoModelo"] == 2
    assert ident_signed["tipoOperacion"] == 2
    assert ident_signed["tipoContingencia"] == 2
    assert ident_signed.get("motivoContin") is None


def test_ccf_contingencia_injection_ok(monkeypatch):
    db = _DummyDB()
    captured: dict[str, dict] = {}

    monkeypatch.setattr(auth, "get_last_auth_host", lambda: None)
    monkeypatch.setattr(dte, "_load_dte_api_config", lambda: {"url": "https://ejemplo"})
    monkeypatch.setattr(
        dte,
        "_load_datos_negocio",
        lambda: {"dte_api": {"tipo_contingencia": 2, "motivo_contin": None}},
    )
    monkeypatch.setattr(dte, "_save_signed_dte", lambda *a, **k: None)

    def fake_sign(payload):
        captured["payload"] = copy.deepcopy(payload)
        return "token"

    monkeypatch.setattr("utils.jws.sign_json", fake_sign)

    data = _base_data()
    data["identificacion"]["tipoDte"] = "03"

    result = dte._enviar_documento(db, 1, data, "contingencia")

    assert result == {"estado": "Pendiente"}
    ident_signed = captured["payload"]["identificacion"]
    assert ident_signed["tipoModelo"] == 2
    assert ident_signed["tipoOperacion"] == 2
    assert ident_signed["tipoContingencia"] == 2
    assert ident_signed.get("motivoContin") is None


def test_ccf_contingencia_tipo5_motivo_requerido(monkeypatch):
    db = _DummyDB()

    monkeypatch.setattr(auth, "get_last_auth_host", lambda: None)
    monkeypatch.setattr(dte, "_load_dte_api_config", lambda: {"url": "https://ejemplo"})
    monkeypatch.setattr(dte, "_save_signed_dte", lambda *a, **k: None)

    data = _base_data()
    data["identificacion"]["tipoDte"] = "03"

    monkeypatch.setattr(
        dte,
        "_load_datos_negocio",
        lambda: {"dte_api": {"tipo_contingencia": 5, "motivo_contin": ""}},
    )

    with pytest.raises(ValueError):
        dte._enviar_documento(db, 1, data, "contingencia")

    captured: dict[str, dict] = {}

    monkeypatch.setattr(
        dte,
        "_load_datos_negocio",
        lambda: {"dte_api": {"tipo_contingencia": 5, "motivo_contin": "Motivo"}},
    )

    def fake_sign(payload):
        captured["payload"] = copy.deepcopy(payload)
        return "token"

    monkeypatch.setattr("utils.jws.sign_json", fake_sign)

    result = dte._enviar_documento(db, 1, data, "contingencia")

    assert result == {"estado": "Pendiente"}
    ident_signed = captured["payload"]["identificacion"]
    assert ident_signed["tipoModelo"] == 2
    assert ident_signed["tipoOperacion"] == 2
    assert ident_signed["tipoContingencia"] == 5
    assert ident_signed.get("motivoContin") == "Motivo"


def test_enviar_documento_refirma_token_normal_al_cambiar_a_contingencia(monkeypatch):
    db = _DummyDB()
    captured: dict[str, dict] = {"sign": 0}

    monkeypatch.setattr(auth, "get_last_auth_host", lambda: None)
    monkeypatch.setattr(dte, "_load_dte_api_config", lambda: {"url": "https://ejemplo"})
    monkeypatch.setattr(
        dte,
        "_load_datos_negocio",
        lambda: {"dte_api": {"tipo_contingencia": 2, "motivo_contin": None}},
    )

    monkeypatch.setattr(dte, "_save_signed_dte", lambda *a, **k: None)
    monkeypatch.setattr(dte, "datetime", _FixedDateTime)

    def fake_sign(payload):
        captured["sign"] += 1
        captured["payload"] = copy.deepcopy(payload)
        return "nuevo-token"

    monkeypatch.setattr("utils.jws.sign_json", fake_sign)

    token_ident = _base_identificacion()
    token_ident.update({
        "tipoModelo": 1,
        "tipoOperacion": 1,
        "tipoContingencia": None,
        "motivoContin": None,
        "horEmi": "08:00:00",
    })

    monkeypatch.setattr(
        dte,
        "_decode_jws_payload",
        lambda token: {"identificacion": copy.deepcopy(token_ident)},
    )

    data = _base_data()

    result = dte._enviar_documento(db, 1, data, "contingencia", jws_token="token-previo")

    assert result == {"estado": "Pendiente"}
    assert captured["sign"] == 1
    ident_signed = captured["payload"]["identificacion"]
    assert ident_signed["tipoModelo"] == 2
    assert ident_signed["tipoOperacion"] == 2
    assert ident_signed["tipoContingencia"] == 2


def test_enviar_documento_refirma_cuando_motivo_contingencia_cambia(monkeypatch):
    db = _DummyDB()
    captured: dict[str, dict] = {"sign": 0}

    monkeypatch.setattr(auth, "get_last_auth_host", lambda: None)
    monkeypatch.setattr(dte, "_load_dte_api_config", lambda: {"url": "https://ejemplo"})
    monkeypatch.setattr(
        dte,
        "_load_datos_negocio",
        lambda: {"dte_api": {"tipo_contingencia": 5, "motivo_contin": "Motivo B"}},
    )

    monkeypatch.setattr(dte, "_save_signed_dte", lambda *a, **k: None)
    monkeypatch.setattr(dte, "datetime", _FixedDateTime)

    def fake_sign(payload):
        captured["sign"] += 1
        captured["payload"] = copy.deepcopy(payload)
        return "nuevo-token"

    monkeypatch.setattr("utils.jws.sign_json", fake_sign)

    token_ident = _base_identificacion()
    token_ident.update(
        {
            "tipoModelo": 2,
            "tipoOperacion": 2,
            "tipoContingencia": 5,
            "motivoContin": "Motivo A",
            "horEmi": "12:00:00",
        }
    )

    monkeypatch.setattr(
        dte,
        "_decode_jws_payload",
        lambda token: {"identificacion": copy.deepcopy(token_ident)},
    )

    data = _base_data()

    result = dte._enviar_documento(db, 1, data, "contingencia", jws_token="token-previo")

    assert result == {"estado": "Pendiente"}
    assert captured["sign"] == 1
    ident_signed = captured["payload"]["identificacion"]
    assert ident_signed["motivoContin"] == "Motivo B"


def test_enviar_documento_reutiliza_token_si_identificacion_igual(monkeypatch):
    db = _DummyDB()
    captured: dict[str, dict] = {"sign": 0, "saved": None}

    monkeypatch.setattr(auth, "get_last_auth_host", lambda: None)
    monkeypatch.setattr(dte, "_load_dte_api_config", lambda: {"url": "https://ejemplo"})
    monkeypatch.setattr(
        dte,
        "_load_datos_negocio",
        lambda: {"dte_api": {"tipo_contingencia": 2, "motivo_contin": None}},
    )

    def fake_save(data_obj, token, fallido=False):
        captured["saved"] = token

    monkeypatch.setattr(dte, "_save_signed_dte", fake_save)
    monkeypatch.setattr(dte, "datetime", _FixedDateTime)

    def fake_sign(payload):
        captured["sign"] += 1
        captured["payload"] = copy.deepcopy(payload)
        return "nuevo-token"

    monkeypatch.setattr("utils.jws.sign_json", fake_sign)

    expected_ident = _base_identificacion()
    expected_ident.update(
        {
            "tipoModelo": 2,
            "tipoOperacion": 2,
            "tipoContingencia": 2,
            "motivoContin": None,
            "horEmi": "12:00:00",
        }
    )

    monkeypatch.setattr(
        dte,
        "_decode_jws_payload",
        lambda token: {"identificacion": copy.deepcopy(expected_ident)},
    )

    data = _base_data()

    result = dte._enviar_documento(db, 1, data, "contingencia", jws_token="token-previo")

    assert result == {"estado": "Pendiente"}
    assert captured["sign"] == 0
    assert captured["saved"] == "token-previo"
