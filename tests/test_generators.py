import copy
from decimal import Decimal

import pytest
from jsonschema.exceptions import ValidationError

from svfe.generators import (
    generar_factura_fiscal,
    generar_consumidor_final,
    generar_nota_debito,
    generar_nota_credito,
    generar_nota_remision,
    validar_contra_schema,
)
from svfe.json_compare import normalize_for_schema, similarity


def _assert_base(data):
    item = data["cuerpoDocumento"][0]
    assert str(item["ventaGravada"]) == "23.85000000"
    venta = item["ventaGravada"]
    iva = (venta * Decimal("0.13")).quantize(Decimal("0.00000001"))
    assert str(iva) == "3.10050000"

    resumen = data["resumen"]
    assert str(resumen["totalGravada"]) == "23.85"
    total = resumen.get("totalPagar", resumen["montoTotalOperacion"])
    assert str(total) == "26.95"
    total_iva = resumen.get("totalIva")
    if total_iva is None:
        total_iva = resumen["montoTotalOperacion"] - resumen["totalGravada"]
    total_iva = total_iva.quantize(Decimal("0.01"))
    assert str(total_iva) == "3.10"


def _run_generator(gen):
    data = gen()
    _assert_base(data)
    golden = normalize_for_schema(copy.deepcopy(data))
    assert similarity(normalize_for_schema(data), golden) == 1.0


def test_generar_factura_fiscal():
    _run_generator(generar_factura_fiscal)


def test_generar_consumidor_final():
    _run_generator(generar_consumidor_final)


def test_generar_nota_debito():
    _run_generator(generar_nota_debito)


def test_generar_nota_credito():
    _run_generator(generar_nota_credito)


def test_generar_nota_remision():
    _run_generator(generar_nota_remision)


def test_validar_contra_schema_missing_required_field():
    data = generar_factura_fiscal()
    data.pop("resumen")
    with pytest.raises(ValidationError):
        validar_contra_schema(data, "ccf")
