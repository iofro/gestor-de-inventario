from decimal import Decimal

from utils.fiscal_extra import normalize_retencion_payload, parse_retencion_values


def test_parse_retencion_values_normalizes_percent_and_geo() -> None:
    block = {
        "enabled": True,
        "base": "125.50",
        "tasa": 1,  # porcentaje
        "codigoRetencionMH": "22",
        "geoEmisor": "2",
        "geoReceptor": "10",
    }
    enabled, base, reten, codigo, tasa_pct, geo_emisor, geo_receptor = parse_retencion_values(block)
    assert enabled is True
    assert base == Decimal("125.50")
    assert reten == Decimal("1.26")  # 1% de 125.50 redondeado a centavos
    assert codigo == "22"
    assert tasa_pct == Decimal("1")
    assert geo_emisor == "02"
    assert geo_receptor == "10"

    normalized = normalize_retencion_payload(block)
    assert normalized is not None
    assert normalized["tasa"] == 1.0
    assert normalized["geoEmisor"] == "02"
    assert normalized["geoReceptor"] == "10"
    assert normalized["montoRetenido"] == float(reten)
