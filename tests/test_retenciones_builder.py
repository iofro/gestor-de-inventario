from __future__ import annotations

from decimal import Decimal

import pytest

from retenciones.builder import build_cr_payload
from retenciones.catalogos_retencion import CatalogosRetencion
from retenciones.validators import validate_cr

from tests.helpers.retenciones import load_ccf_sample

def _sample_factura() -> dict:
    factura = load_ccf_sample()
    factura["identificacion"]["codigoGeneracion"] = "11111111-2222-3333-4444-555555555555"
    factura["identificacion"]["numeroControl"] = "DTE-03-ABCD1234-000000000000001"
    return factura


def _fixed_ident() -> dict:
    return {
        "numeroControl": "DTE-07-TEST2024-000000000000001",
        "codigoGeneracion": "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE",
    }


def test_documento_relacionado_copies_ident_fields() -> None:
    factura = _sample_factura()
    catalogos = CatalogosRetencion()
    payload = build_cr_payload(
        factura,
        catalogos=catalogos,
        identificacion_override=_fixed_ident(),
    )
    rel = payload["cuerpoDocumento"][0]
    assert rel["numDocumento"] == factura["identificacion"]["numeroControl"]
    assert rel["tipoDoc"] == 2
    assert rel["tipoDte"] == factura["identificacion"]["tipoDte"]
    assert "codGeneracion" not in rel


def test_base_and_retencion_uses_sum_of_items() -> None:
    factura = _sample_factura()
    factura["cuerpoDocumento"] = [
        {"ventaGravada": "10.333"},
        {"ventaGravada": "5.333"},
    ]
    payload = build_cr_payload(
        factura,
        catalogos=CatalogosRetencion(),
        identificacion_override=_fixed_ident(),
    )
    rel = payload["cuerpoDocumento"][0]
    assert rel["montoSujetoGrav"] == Decimal("15.67")
    assert rel["ivaRetenido"] == Decimal("0.16")
    resumen = payload["resumen"]
    assert resumen["totalSujetoRetencion"] == Decimal("15.67")
    assert resumen["totalIVAretenido"] == Decimal("0.16")


def test_payload_validates_against_schema_and_catalogs() -> None:
    factura = _sample_factura()
    payload = build_cr_payload(
        factura,
        catalogos=CatalogosRetencion(),
        identificacion_override=_fixed_ident(),
    )
    # No excepción significa que el CR es válido frente al schema y catálogos.
    validate_cr(payload, catalogos=CatalogosRetencion())


def test_builder_rejects_factura_no_credito_fiscal() -> None:
    factura = _sample_factura()
    factura["identificacion"]["tipoDte"] = "01"
    catalogos = CatalogosRetencion()
    with pytest.raises(ValueError, match="CR-07 solo para DTE 03"):
        build_cr_payload(
            factura,
            catalogos=catalogos,
            identificacion_override=_fixed_ident(),
        )

def test_builder_rejects_non_credito_fiscal() -> None:
    factura = _sample_factura()
    factura["identificacion"]["tipoDte"] = "05"
    catalogos = CatalogosRetencion()
    with pytest.raises(ValueError, match="CR-07 solo para DTE 03"):
        build_cr_payload(factura, catalogos=catalogos, identificacion_override=_fixed_ident())


@pytest.mark.parametrize(
    "items,expected_base,expected_ret",
    [
        (["100.00"], Decimal("100.00"), Decimal("1.00")),
        (["88.57"], Decimal("88.57"), Decimal("0.89")),
        (["1.00"], Decimal("1.00"), Decimal("0.01")),
    ],
)
def test_rounding_cases(items, expected_base, expected_ret) -> None:
    factura = _sample_factura()
    factura["cuerpoDocumento"] = [{"ventaGravada": value} for value in items]
    payload = build_cr_payload(
        factura,
        catalogos=CatalogosRetencion(),
        identificacion_override=_fixed_ident(),
    )
    rel = payload["cuerpoDocumento"][0]
    resumen = payload["resumen"]
    assert rel["montoSujetoGrav"] == expected_base
    assert rel["ivaRetenido"] == expected_ret
    assert resumen["totalSujetoRetencion"] == expected_base
    assert resumen["totalIVAretenido"] == expected_ret


def test_receptor_tipo_documento_inferred_from_nit() -> None:
    factura = _sample_factura()
    factura["receptor"].pop("tipoDocumento", None)
    payload = build_cr_payload(
        factura,
        catalogos=CatalogosRetencion(),
        identificacion_override=_fixed_ident(),
    )
    receptor = payload["receptor"]
    assert receptor["tipoDocumento"] == "36"
    assert receptor["numDocumento"] == factura["receptor"]["nit"]


def test_base_minimum_not_forced() -> None:
    factura = _sample_factura()
    factura["cuerpoDocumento"] = [{"ventaGravada": "0.50"}]
    payload = build_cr_payload(
        factura,
        catalogos=CatalogosRetencion(),
        identificacion_override=_fixed_ident(),
    )
    rel = payload["cuerpoDocumento"][0]
    resumen = payload["resumen"]
    assert rel["montoSujetoGrav"] == Decimal("0.50")
    assert rel["ivaRetenido"] == Decimal("0.01")
    assert resumen["totalSujetoRetencion"] == Decimal("0.50")
    assert resumen["totalIVAretenido"] == Decimal("0.01")


def test_builder_accepts_base_override_and_custom_rate() -> None:
    factura = _sample_factura()
    payload = build_cr_payload(
        factura,
        catalogos=CatalogosRetencion(),
        identificacion_override=_fixed_ident(),
        base_sujeta_override="50.00",
        tasa=Decimal("0.02"),
    )
    rel = payload["cuerpoDocumento"][0]
    resumen = payload["resumen"]
    assert rel["montoSujetoGrav"] == Decimal("50.00")
    assert rel["ivaRetenido"] == Decimal("1.00")
    assert resumen["totalSujetoRetencion"] == Decimal("50.00")
    assert resumen["totalIVAretenido"] == Decimal("1.00")


def test_builder_rejects_invalid_control_number() -> None:
    factura = _sample_factura()
    factura["identificacion"]["numeroControl"] = "DTE-03-INVALID-000000000000001"
    catalogos = CatalogosRetencion()
    with pytest.raises(ValueError, match="formato DTE-03"):
        build_cr_payload(
            factura,
            catalogos=catalogos,
            identificacion_override=_fixed_ident(),
        )
