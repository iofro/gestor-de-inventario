import pytest
import re
import uuid
import pytest
from dte import sanitize_dte_payload, validate_dte_json, generar_numero_control

UUID4_RE = r"^[0-9A-F]{8}-[0-9A-F]{4}-4[0-9A-F]{3}-[89AB][0-9A-F]{3}-[0-9A-F]{12}$"


def test_dte_valido_pasa(dte_metadata_factory):
    dte = dte_metadata_factory()
    validate_dte_json(dte)


def test_codigo_invalido_rechazado(dte_metadata_factory):
    dte = dte_metadata_factory()
    dte["identificacion"]["tipoDte"] = "99"
    with pytest.raises(ValueError):
        validate_dte_json(dte)


def test_longitud_nit_invalida(dte_metadata_factory):
    dte = dte_metadata_factory()
    dte["emisor"]["nit"] = "123"
    dte["resumen"].pop("pagos", None)
    with pytest.raises(ValueError):
        validate_dte_json(dte)


def test_longitud_num_documento_invalida(dte_metadata_factory):
    dte = dte_metadata_factory()
    dte["receptor"]["numDocumento"] = "123"
    with pytest.raises(ValueError):
        validate_dte_json(dte)


def test_codigo_generacion_debe_ser_uuid_v4(dte_metadata_factory):
    dte = dte_metadata_factory()
    dte["identificacion"]["codigoGeneracion"] = "not-a-uuid"
    with pytest.raises(ValueError):
        validate_dte_json(dte)
    dte["identificacion"]["codigoGeneracion"] = "12345678-1234-1234-1234-1234567890AB"
    with pytest.raises(ValueError):
        validate_dte_json(dte)


def test_codigo_generacion_rechaza_uuids_no_v4(dte_metadata_factory):
    dte = dte_metadata_factory()
    dte["identificacion"]["codigoGeneracion"] = str(uuid.uuid1()).upper()
    with pytest.raises(ValueError):
        validate_dte_json(dte)
    dte["identificacion"]["codigoGeneracion"] = str(uuid.uuid3(uuid.NAMESPACE_DNS, "test")).upper()
    with pytest.raises(ValueError):
        validate_dte_json(dte)


def test_estructura_invalida(dte_metadata_factory, monkeypatch):
    dte = dte_metadata_factory()
    del dte["emisor"]["nit"]
    monkeypatch.setattr("dte._load_datos_negocio", lambda: {})
    with pytest.raises(ValueError) as exc:
        validate_dte_json(dte)
    assert "nit" in str(exc.value)


def test_strips_additional_properties(dte_metadata_factory):
    dte = dte_metadata_factory()
    dte["firmaElectronica"] = "XYZ"
    dte["selloRecibido"] = "ABC"
    dte["identificacion"]["firmaElectronica"] = "XYZ"
    clean = sanitize_dte_payload(dte)
    assert "firmaElectronica" not in clean
    assert "selloRecibido" not in clean
    assert "firmaElectronica" not in clean["identificacion"]
    clean["resumen"].pop("pagos", None)
    validate_dte_json(clean)


def test_missing_top_level_fields_listed():
    with pytest.raises(ValueError) as exc:
        validate_dte_json({})
    msg = str(exc.value)
    for key in [
        "identificacion",
        "emisor",
        "receptor",
        "cuerpoDocumento",
        "resumen",
    ]:
        assert key in msg


def test_missing_emisor_fields_listed(dte_metadata_factory, monkeypatch):
    dte = dte_metadata_factory()
    dte["emisor"] = {}
    monkeypatch.setattr("dte._load_datos_negocio", lambda: {})
    monkeypatch.setattr(
        "svfe.config.get_emisor_direccion", lambda: (_ for _ in ()).throw(ValueError())
    )
    with pytest.raises(ValueError) as exc:
        validate_dte_json(dte)
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



def test_recalcula_totales(dte_metadata_factory):
    dte = dte_metadata_factory()
    # Manipulamos totales para que sean incorrectos
    dte["resumen"]["totalGravada"] = 20.0
    dte["resumen"]["subTotalVentas"] = 20.0
    dte["resumen"]["montoTotalOperacion"] = 20.0
    dte["resumen"]["totalPagar"] = 20.0

    validate_dte_json(dte)

    assert dte["resumen"]["totalGravada"] == pytest.approx(10.0)
    assert dte["resumen"]["subTotalVentas"] == pytest.approx(10.0)
    assert dte["resumen"]["montoTotalOperacion"] == pytest.approx(10.0)
    assert dte["resumen"]["totalPagar"] == pytest.approx(10.0)


def test_autocompleta_tributos(dte_metadata_factory):
    dte = dte_metadata_factory()
    item = dte["cuerpoDocumento"][0]
    # Eliminamos tributos para forzar el valor por defecto
    item.pop("tributos", None)
    item.pop("codTributo", None)
    validate_dte_json(dte)
    item = dte["cuerpoDocumento"][0]
    assert item["tributos"] == ["19"]
    assert item["codTributo"] == "19"


def test_tributos_invalidos_rechazados(dte_metadata_factory):
    dte = dte_metadata_factory()
    dte["identificacion"]["tipoDte"] = "03"
    dte["cuerpoDocumento"][0]["tributos"] = ["ZZ"]
    with pytest.raises(ValueError):
        validate_dte_json(dte)

    dte = dte_metadata_factory()
    dte["identificacion"]["tipoDte"] = "03"
    dte["cuerpoDocumento"][0]["codTributo"] = "ZZ"
    with pytest.raises(ValueError):
        validate_dte_json(dte)


def test_numero_control_generado_si_invalido(dte_metadata_factory):
    dte = dte_metadata_factory()
    dte["identificacion"]["numeroControl"] = "INVALID"
    validate_dte_json(dte)
    assert re.fullmatch(r"^DTE-\d{2}-S\d{3}P\d{3}-\d{15}$", dte["identificacion"]["numeroControl"])


@pytest.mark.parametrize(
    "numero",
    [
        "DTE-01-S001P001-123456789012345",
        "DTE-99-S999P123-000000000000000",
    ],
)
def test_numero_control_validos(dte_metadata_factory, numero):
    dte = dte_metadata_factory()
    dte["identificacion"]["numeroControl"] = numero
    validate_dte_json(dte)
    assert dte["identificacion"]["numeroControl"] == numero


@pytest.mark.parametrize(
    "numero",
    [
        "DTE-1-S001P001-123456789012345",
        "DTE-01-S1P001-123456789012345",
        "DTE-01-S001P001-12345",
        "dte-01-S001P001-123456789012345",
    ],
)
def test_numero_control_invalidos_generan(dte_metadata_factory, numero):
    dte = dte_metadata_factory()
    dte["identificacion"]["numeroControl"] = numero
    validate_dte_json(dte)
    assert re.fullmatch(r"^DTE-\d{2}-S\d{3}P\d{3}-\d{15}$", dte["identificacion"]["numeroControl"])
    assert dte["identificacion"]["numeroControl"] != numero


def test_generar_numero_control_zero_pad():
    numero = generar_numero_control("1", "2", 3)
    assert numero.startswith("DTE-01-S002P003-")


def test_tipo_dte_int_normalizado(dte_metadata_factory):
    dte = dte_metadata_factory()
    dte["identificacion"]["tipoDte"] = 1
    validate_dte_json(dte)
    assert dte["identificacion"]["tipoDte"] == "01"


def test_tipo_dte_invalido(dte_metadata_factory):
    dte = dte_metadata_factory()
    dte["identificacion"]["tipoDte"] = "99"
    with pytest.raises(ValueError):
        validate_dte_json(dte)


def test_codigo_generacion_generado(dte_metadata_factory):
    dte = dte_metadata_factory()
    dte["identificacion"].pop("codigoGeneracion")
    validate_dte_json(dte)
    assert re.fullmatch(UUID4_RE, dte["identificacion"]["codigoGeneracion"])


def test_ident_contingencia_modelo(dte_metadata_factory):
    dte = dte_metadata_factory()
    dte["identificacion"]["tipoModelo"] = 2
    dte["identificacion"]["tipoContingencia"] = 1
    dte["identificacion"]["motivoContin"] = "  EXTRA  "
    validate_dte_json(dte)
    ident = dte["identificacion"]
    assert ident["tipoModelo"] == 1
    assert ident["tipoContingencia"] is None
    assert ident["motivoContin"] is None

    dte = dte_metadata_factory()
    dte["identificacion"]["tipoOperacion"] = 2
    dte["identificacion"]["tipoContingencia"] = 1
    validate_dte_json(dte)
    ident = dte["identificacion"]
    assert ident["tipoModelo"] == 2
    assert ident["motivoContin"] is None

    dte = dte_metadata_factory()
    dte["identificacion"]["tipoOperacion"] = 2
    dte["identificacion"]["tipoContingencia"] = 5
    dte["identificacion"]["motivoContin"] = " FALLA PROVEEDOR "
    validate_dte_json(dte)
    ident = dte["identificacion"]
    assert ident["tipoModelo"] == 2
    assert ident["motivoContin"] == "FALLA PROVEEDOR"


def test_ident_contingencia_rechazos(dte_metadata_factory):
    dte = dte_metadata_factory()
    dte["identificacion"]["tipoOperacion"] = 2
    dte["identificacion"]["tipoContingencia"] = 9
    with pytest.raises(ValueError):
        validate_dte_json(dte)

    dte = dte_metadata_factory()
    dte["identificacion"]["tipoOperacion"] = 2
    dte["identificacion"]["tipoContingencia"] = 5
    dte["identificacion"]["motivoContin"] = ""
    with pytest.raises(ValueError):
        validate_dte_json(dte)

    dte = dte_metadata_factory()
    dte["identificacion"]["tipoOperacion"] = 2
    dte["identificacion"]["tipoContingencia"] = 5
    dte["identificacion"]["motivoContin"] = "bad"
    with pytest.raises(ValueError):
        validate_dte_json(dte)


def test_fecha_hora_format(dte_metadata_factory):
    dte = dte_metadata_factory()
    dte["identificacion"]["fecEmi"] = "01-01-2024"
    with pytest.raises(ValueError):
        validate_dte_json(dte)

    dte = dte_metadata_factory()
    dte["identificacion"]["horEmi"] = "25:00:00"
    with pytest.raises(ValueError):
        validate_dte_json(dte)
