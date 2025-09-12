import copy
from decimal import Decimal

import copy
from decimal import Decimal

import pytest

from utils.catalogos import TRIBUTO_IVA

from svfe.generators import (
    generar_factura_fiscal,
    generar_consumidor_final,
    generar_nota_debito,
    generar_nota_credito,
    generar_nota_remision,
)
from svfe.json_compare import normalize_for_schema, similarity

import svfe.config as svfe_config
import dte as dte_module


@pytest.fixture(autouse=True)
def _stub_datos_negocio(monkeypatch):
    fake = {
        "nit": "06142512891020",
        "nrc": "1234567",
        "nombre": "Demo",
        "nombreComercial": "Demo",
        "codActividad": "46484",
        "descActividad": "Venta",
        "tipoContribuyente": "PN",
        "telefono": "22223333",
        "correo": "demo@example.com",
        "direccion": {"departamento": "06", "municipio": "23", "complemento": ""},
    }
    monkeypatch.setattr(svfe_config, "load_datos_negocio", lambda: fake)
    monkeypatch.setattr(dte_module, "_load_datos_negocio", lambda: fake)


def _assert_base(data):
    item = data["cuerpoDocumento"][0]
    resumen = data["resumen"]
    tipo = data["identificacion"]["tipoDte"]
    trib = next(
        (t.get("valor") for t in resumen.get("tributos") or [] if t.get("codigo") == TRIBUTO_IVA),
        Decimal("0"),
    )
    total = resumen.get("totalPagar", resumen.get("montoTotalOperacion"))
    assert "ivaItem" not in item
    assert "totalIva" not in resumen
    assert str(item["ventaGravada"]) == "23.8500"
    assert str(resumen["totalGravada"]) == "23.85"
    assert str(total) == "26.95"
    assert trib.quantize(Decimal("0.01")) == Decimal("3.10")


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


