import json
import uuid
import pytest
import re

import dte
from dte import sanitize_dte_payload, validate_dte_json
from jsonschema import ValidationError
from utils.catalogos import TRIBUTO_IVA
from db import DB
from utils.monto import D

UUID4_RE = r"^[0-9A-F]{8}-[0-9A-F]{4}-4[0-9A-F]{3}-[89AB][0-9A-F]{3}-[0-9A-F]{12}$"


def _patch_datos_negocio(tmp_path, monkeypatch):
    datos = {
        "nit": "06141404100016",
        "nrc": "1234567",
        "nombre": "Empresa SA",
        "nombreComercial": "Empresa",
        "codActividad": "12345",
        "descActividad": "Venta de productos",
        "tipoContribuyente": "Persona Natural",
        "telefono": "22223333",
        "correo": "info@empresa.com",
        "direccion": {
            "departamento": "01",
            "municipio": "13",
            "complemento": "Calle 1",
        },
    }
    path = tmp_path / "datos_negocio.json"
    path.write_text(json.dumps(datos), encoding="utf-8")
    monkeypatch.setattr(dte, "DATOS_NEGOCIO_PATH", str(path))


@pytest.fixture
def db_fixture(tmp_path, monkeypatch):
    _patch_datos_negocio(tmp_path, monkeypatch)
    monkeypatch.setenv("HOME", str(tmp_path))
    db = DB()
    yield db

def test_dte_valido_pasa(dte_metadata_factory, db_fixture):
    dte = dte_metadata_factory()
    validate_dte_json(dte, db=db_fixture)


def test_codigo_invalido_rechazado(dte_metadata_factory, db_fixture):
    dte = dte_metadata_factory()
    dte["identificacion"]["tipoDte"] = "99"
    with pytest.raises(ValueError):
        validate_dte_json(dte, db=db_fixture)


def test_longitud_nit_invalida(dte_metadata_factory, db_fixture):
    dte = dte_metadata_factory()
    dte["emisor"]["nit"] = "123"
    dte["resumen"].pop("pagos", None)
    with pytest.raises(ValueError):
        validate_dte_json(dte, db=db_fixture)


def test_longitud_num_documento_invalida(dte_metadata_factory, db_fixture):
    dte = dte_metadata_factory()
    dte["receptor"]["numDocumento"] = "123"
    with pytest.raises(ValueError):
        validate_dte_json(dte, db=db_fixture)


def test_codigo_generacion_debe_ser_uuid_v4(dte_metadata_factory, db_fixture):
    dte = dte_metadata_factory()
    dte["identificacion"]["codigoGeneracion"] = "not-a-uuid"
    with pytest.raises(ValueError):
        validate_dte_json(dte, db=db_fixture)
    dte["identificacion"]["codigoGeneracion"] = "12345678-1234-1234-1234-1234567890AB"
    with pytest.raises(ValueError):
        validate_dte_json(dte, db=db_fixture)


def test_codigo_generacion_rechaza_uuids_no_v4(dte_metadata_factory, db_fixture):
    dte = dte_metadata_factory()
    dte["identificacion"]["codigoGeneracion"] = str(uuid.uuid1()).upper()
    with pytest.raises(ValueError):
        validate_dte_json(dte, db=db_fixture)
    dte["identificacion"]["codigoGeneracion"] = str(uuid.uuid3(uuid.NAMESPACE_DNS, "test")).upper()
    with pytest.raises(ValueError):
        validate_dte_json(dte, db=db_fixture)


def test_estructura_invalida(dte_metadata_factory, monkeypatch, db_fixture):
    dte = dte_metadata_factory()
    del dte["emisor"]["nit"]
    monkeypatch.setattr("dte._load_datos_negocio", lambda: {})
    with pytest.raises(ValueError) as exc:
        validate_dte_json(dte, db=db_fixture)
    assert "nit" in str(exc.value)


def test_strips_additional_properties(dte_metadata_factory, db_fixture):
    dte = dte_metadata_factory()
    dte["firmaElectronica"] = "XYZ"
    dte["selloRecibido"] = "ABC"
    dte["identificacion"]["firmaElectronica"] = "XYZ"
    clean = sanitize_dte_payload(dte)
    assert "firmaElectronica" not in clean
    assert "selloRecibido" not in clean
    assert "firmaElectronica" not in clean["identificacion"]
    clean["resumen"].pop("pagos", None)
    validate_dte_json(clean, db=db_fixture)


def test_missing_top_level_fields_listed(db_fixture):
    with pytest.raises(ValueError) as exc:
        validate_dte_json({}, db=db_fixture)
    msg = str(exc.value)
    for key in [
        "identificacion",
        "emisor",
        "receptor",
        "cuerpoDocumento",
        "resumen",
    ]:
        assert key in msg


def test_missing_emisor_fields_listed(dte_metadata_factory, monkeypatch, db_fixture):
    dte = dte_metadata_factory()
    dte["emisor"] = {}
    monkeypatch.setattr("dte._load_datos_negocio", lambda: {})
    monkeypatch.setattr(
        "svfe.config.get_emisor_direccion", lambda: (_ for _ in ()).throw(ValueError())
    )
    with pytest.raises(ValueError) as exc:
        validate_dte_json(dte, db=db_fixture)
    msg = str(exc.value)
    for key in [
        "nit",
        "nrc",
        "nombre",
        "nombreComercial",
        "codActividad",
        "descActividad",
        "direccion.complemento",
        "telefono",
        "correo",
    ]:
        assert key in msg



def test_recalcula_totales(dte_metadata_factory, db_fixture):
    dte = dte_metadata_factory()
    # Manipulamos totales para que sean incorrectos
    dte["resumen"]["totalGravada"] = 20.0
    dte["resumen"]["subTotalVentas"] = 20.0
    dte["resumen"]["montoTotalOperacion"] = 20.0
    dte["resumen"]["totalPagar"] = 20.0

    validate_dte_json(dte, db=db_fixture)

    assert dte["resumen"]["totalGravada"] == pytest.approx(10.0)
    assert dte["resumen"]["subTotalVentas"] == pytest.approx(10.0)
    assert dte["resumen"]["montoTotalOperacion"] == pytest.approx(10.0)
    assert dte["resumen"]["totalPagar"] == pytest.approx(10.0)


def test_no_iva_en_items(dte_metadata_factory, db_fixture):
    dte = dte_metadata_factory()
    item = dte["cuerpoDocumento"][0]
    item.pop("tributos", None)
    item.pop("codTributo", None)
    validate_dte_json(dte, db=db_fixture)
    item = dte["cuerpoDocumento"][0]
    assert item["tributos"] is None
    assert item["codTributo"] is None


def test_iva_en_items_se_normaliza(dte_metadata_factory, db_fixture):
    dte = dte_metadata_factory()
    dte["cuerpoDocumento"][0]["codTributo"] = TRIBUTO_IVA
    validate_dte_json(dte, db=db_fixture)
    item = dte["cuerpoDocumento"][0]
    assert item["tributos"] is None and item["codTributo"] is None
    dte = dte_metadata_factory()
    dte["cuerpoDocumento"][0]["tributos"] = [TRIBUTO_IVA]
    validate_dte_json(dte, db=db_fixture)
    item = dte["cuerpoDocumento"][0]
    assert item["tributos"] is None and item["codTributo"] is None


def test_tributos_invalidos_rechazados(dte_metadata_factory, db_fixture):
    dte = dte_metadata_factory()
    dte["identificacion"]["tipoDte"] = "03"
    dte["cuerpoDocumento"][0]["tributos"] = ["ZZ"]
    with pytest.raises(ValueError):
        validate_dte_json(dte, db=db_fixture)

    dte = dte_metadata_factory()
    dte["identificacion"]["tipoDte"] = "03"
    dte["cuerpoDocumento"][0]["codTributo"] = "ZZ"
    with pytest.raises(ValueError):
        validate_dte_json(dte, db=db_fixture)


def test_clamp_uni_medida(dte_metadata_factory, db_fixture):
    dte = dte_metadata_factory()
    dte["cuerpoDocumento"][0]["uniMedida"] = 1  # valor fuera del catálogo permitido
    validate_dte_json(dte, db=db_fixture)
    assert dte["cuerpoDocumento"][0]["uniMedida"] == 59


def test_numero_control_regex(dte_metadata_factory, tmp_path, monkeypatch, db_fixture):
    _patch_datos_negocio(tmp_path, monkeypatch)
    dte = dte_metadata_factory()
    dte["identificacion"]["numeroControl"] = "INVALID"
    validate_dte_json(dte, db=db_fixture)
    assert re.fullmatch(
        r"^DTE-(\d{2})-S(\d{3})P(\d{3})-(\d{15})$",
        dte["identificacion"]["numeroControl"],
    )


@pytest.mark.parametrize(
    "numero",
    [
        "DTE-01-S123P456-123456789012345",
        "DTE-01-S001P001-000000000000000",
    ],
)
def test_numero_control_validos(dte_metadata_factory, numero, tmp_path, monkeypatch, db_fixture):
    dte = dte_metadata_factory()
    dte["identificacion"]["numeroControl"] = numero
    _patch_datos_negocio(tmp_path, monkeypatch)
    validate_dte_json(dte, db=db_fixture)


@pytest.mark.parametrize(
    "numero",
    [
        "DTE-01-S01P001-123456789012345",
        "DTE-01-S001P001-12345",
        "dte-01-S001P001-123456789012345",
    ],
)
def test_numero_control_invalidos(dte_metadata_factory, numero, tmp_path, monkeypatch, db_fixture):
    dte = dte_metadata_factory()
    dte["identificacion"]["numeroControl"] = numero
    _patch_datos_negocio(tmp_path, monkeypatch)
    validate_dte_json(dte, db=db_fixture)
    assert re.fullmatch(
        r"^DTE-(\d{2})-S(\d{3})P(\d{3})-(\d{15})$",
        dte["identificacion"]["numeroControl"],
    )


def test_numero_control_regenerates_from_emisor_codes(dte_metadata_factory, tmp_path, monkeypatch, db_fixture):
    _patch_datos_negocio(tmp_path, monkeypatch)
    dte = dte_metadata_factory()
    dte["emisor"]["codEstable"] = "123"
    dte["emisor"]["codEstableMH"] = "123"
    dte["emisor"]["codPuntoVenta"] = "456"
    dte["emisor"]["codPuntoVentaMH"] = "456"
    dte["identificacion"]["numeroControl"] = "BAD"
    validate_dte_json(dte, db=db_fixture)
    ident = dte["identificacion"]
    emisor = dte["emisor"]
    assert emisor["codEstable"] == "0123"
    assert emisor["codPuntoVenta"] == "0456"
    assert ident["numeroControl"].startswith("DTE-01-S123P456")


def test_numero_control_fallback_default(dte_metadata_factory, tmp_path, monkeypatch, db_fixture):
    _patch_datos_negocio(tmp_path, monkeypatch)
    monkeypatch.setenv("HOME", str(tmp_path))
    dte = dte_metadata_factory()
    for key in ["codEstable", "codEstableMH", "codPuntoVenta", "codPuntoVentaMH"]:
        dte["emisor"].pop(key, None)
    dte["identificacion"]["numeroControl"] = "BAD"
    validate_dte_json(dte, db=db_fixture)
    assert dte["identificacion"]["numeroControl"] == "DTE-01-S001P001-000000000000001"


def test_numero_control_secuencial_por_combinacion(
    dte_metadata_factory, tmp_path, monkeypatch, db_fixture
):
    _patch_datos_negocio(tmp_path, monkeypatch)
    monkeypatch.setenv("HOME", str(tmp_path))

    dte1 = dte_metadata_factory()
    dte1["identificacion"]["numeroControl"] = "BAD"
    validate_dte_json(dte1, db=db_fixture)
    n1 = dte1["identificacion"]["numeroControl"]

    dte2 = dte_metadata_factory()
    dte2["identificacion"]["numeroControl"] = "BAD"
    validate_dte_json(dte2, db=db_fixture)
    n2 = dte2["identificacion"]["numeroControl"]

    dte3 = dte_metadata_factory()
    dte3["identificacion"]["numeroControl"] = "BAD"
    dte3["emisor"]["codPuntoVentaMH"] = "0002"
    dte3["emisor"]["codPuntoVenta"] = "0002"
    validate_dte_json(dte3, db=db_fixture)
    n3 = dte3["identificacion"]["numeroControl"]

    assert n1.endswith("000000000000001")
    assert n2.endswith("000000000000002")
    assert n3.startswith("DTE-01-S001P002-")
    assert n3.endswith("000000000000001")


def test_numero_control_idempotencia(dte_metadata_factory, tmp_path, monkeypatch, db_fixture):
    _patch_datos_negocio(tmp_path, monkeypatch)
    monkeypatch.setenv("HOME", str(tmp_path))
    numero = "DTE-01-S123P456-000000000000123"
    dte = dte_metadata_factory()
    dte["identificacion"]["numeroControl"] = numero
    validate_dte_json(dte, db=db_fixture)
    assert dte["identificacion"]["numeroControl"] == numero


def test_numero_control_idempotencia_dura(db_fixture, dte_metadata_factory):
    """
    Si numeroControl YA es válido (regex), debe preservarse aunque
    los códigos de emisor (sucursal/punto) difieran. No se regenera.
    """
    dte = dte_metadata_factory()
    ident = dte["identificacion"]
    ident["tipoDte"] = "01"
    ident["numeroControl"] = "DTE-01-S999P888-000000000000777"
    dte["emisor"]["codEstableMH"] = "001"
    dte["emisor"]["codPuntoVentaMH"] = "001"

    original_nc = ident["numeroControl"]
    validate_dte_json(dte, db=db_fixture)
    assert dte["identificacion"]["numeroControl"] == original_nc


def test_numero_control_no_crea_db_extra(tmp_path, monkeypatch, dte_metadata_factory):
    _patch_datos_negocio(tmp_path, monkeypatch)
    monkeypatch.setenv("HOME", str(tmp_path))
    calls = 0
    orig_init = DB.__init__

    def counting_init(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        orig_init(self, *args, **kwargs)

    monkeypatch.setattr(DB, "__init__", counting_init)
    db = DB()
    dte = dte_metadata_factory()
    validate_dte_json(dte, db=db)
    assert calls == 1


def test_tipo_dte_int_normalizado(dte_metadata_factory, db_fixture):
    dte = dte_metadata_factory()
    dte["identificacion"]["tipoDte"] = 1
    validate_dte_json(dte, db=db_fixture)
    assert dte["identificacion"]["tipoDte"] == "01"


def test_tipo_dte_invalido(dte_metadata_factory, db_fixture):
    dte = dte_metadata_factory()
    dte["identificacion"]["tipoDte"] = "99"
    with pytest.raises(ValueError):
        validate_dte_json(dte, db=db_fixture)


def test_codigo_generacion_generado(dte_metadata_factory, db_fixture):
    dte = dte_metadata_factory()
    dte["identificacion"].pop("codigoGeneracion")
    validate_dte_json(dte, db=db_fixture)
    assert re.fullmatch(UUID4_RE, dte["identificacion"]["codigoGeneracion"])


def test_ident_contingencia_modelo(dte_metadata_factory, db_fixture):
    dte = dte_metadata_factory()
    dte["identificacion"]["tipoModelo"] = 2
    dte["identificacion"]["tipoContingencia"] = 1
    dte["identificacion"]["motivoContin"] = "  EXTRA  "
    validate_dte_json(dte, db=db_fixture)
    ident = dte["identificacion"]
    assert ident["tipoModelo"] == 1
    assert ident["tipoContingencia"] is None
    assert ident["motivoContin"] is None

    dte = dte_metadata_factory()
    dte["identificacion"]["tipoOperacion"] = 2
    dte["identificacion"]["tipoContingencia"] = 1
    validate_dte_json(dte, db=db_fixture)
    ident = dte["identificacion"]
    assert ident["tipoModelo"] == 2
    assert ident["motivoContin"] is None

    dte = dte_metadata_factory()
    dte["identificacion"]["tipoOperacion"] = 2
    dte["identificacion"]["tipoContingencia"] = 5
    dte["identificacion"]["motivoContin"] = " FALLA PROVEEDOR "
    validate_dte_json(dte, db=db_fixture)
    ident = dte["identificacion"]
    assert ident["tipoModelo"] == 2
    assert ident["motivoContin"] == "FALLA PROVEEDOR"


def test_ident_contingencia_rechazos(dte_metadata_factory, db_fixture):
    dte = dte_metadata_factory()
    dte["identificacion"]["tipoOperacion"] = 2
    dte["identificacion"]["tipoContingencia"] = 9
    with pytest.raises(ValueError):
        validate_dte_json(dte, db=db_fixture)

    dte = dte_metadata_factory()
    dte["identificacion"]["tipoOperacion"] = 2
    dte["identificacion"]["tipoContingencia"] = 5
    dte["identificacion"]["motivoContin"] = ""
    with pytest.raises(ValueError):
        validate_dte_json(dte, db=db_fixture)

    dte = dte_metadata_factory()
    dte["identificacion"]["tipoOperacion"] = 2
    dte["identificacion"]["tipoContingencia"] = 5
    dte["identificacion"]["motivoContin"] = "bad"
    with pytest.raises(ValueError):
        validate_dte_json(dte, db=db_fixture)


def test_fecha_hora_format(dte_metadata_factory, db_fixture):
    dte = dte_metadata_factory()
    dte["identificacion"]["fecEmi"] = "01-01-2024"
    with pytest.raises(ValueError):
        validate_dte_json(dte, db=db_fixture)

    dte = dte_metadata_factory()
    dte["identificacion"]["horEmi"] = "25:00:00"
    with pytest.raises(ValueError):
        validate_dte_json(dte, db=db_fixture)


def test_validate_allows_envelope(db_fixture):
    """Un sobre de recepción sin estructura completa de DTE es válido."""
    sobre = {
        "ambiente": "00",
        "idEnvio": 1,
        "version": 1,
        "tipoDte": "01",
        "codigoGeneracion": str(uuid.uuid4()).upper(),
        "documento": "header.payload.signature",
    }

    # No debe lanzar ``ValueError`` aunque falten campos de un DTE tradicional
    validate_dte_json(sobre, db=db_fixture)


def test_totales_rechazan_mas_de_dos_decimales(dte_metadata_factory, db_fixture):
    dte = dte_metadata_factory()
    item = dte["cuerpoDocumento"][0]
    item["precioUni"] = D("1.2345")
    item["ventaGravada"] = D("1.2345")
    item["ivaItem"] = D("0.14")
    dte.setdefault("extra", {})["precios_incluyen_iva"] = True
    with pytest.raises(ValidationError):
        validate_dte_json(dte, db=db_fixture)
