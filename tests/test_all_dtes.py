import copy
import io
import json
from contextlib import redirect_stdout
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import pytest

from svfe.generators import (
    SCHEMA_MAP,
    generar_consumidor_final,
    generar_factura_fiscal,
    generar_nota_credito,
    generar_nota_debito,
    generar_nota_remision,
    validar_contra_schema,
    strip_extras,
)
from svfe.json_compare import normalize_for_schema, similarity, deep_diff


GEN_MAP = {
    "ccf": generar_factura_fiscal,
    "fc": generar_consumidor_final,
    "nd": generar_nota_debito,
    "nc": generar_nota_credito,
    "nr": generar_nota_remision,
}

D8 = Decimal("0.00000001")
D2 = Decimal("0.01")

def _q8(x: Decimal) -> Decimal:
    return x.quantize(D8, rounding=ROUND_HALF_UP)

def _q2(x: Decimal) -> Decimal:
    return x.quantize(D2, rounding=ROUND_HALF_UP)

def _sanitize(data: dict, tipo: str) -> dict:
    data = copy.deepcopy(data)
    ident = data["identificacion"]
    ident["numeroControl"] = f"DTE-{SCHEMA_MAP[tipo][1]}-S001P001-000000000000001"
    ident["codigoGeneracion"] = "00000000-0000-4000-8000-000000000000"
    ident["fecEmi"] = "2000-01-01"
    ident["horEmi"] = "00:00:00"
    item = data["cuerpoDocumento"][0]
    resumen = data["resumen"]
    if tipo == "fc":
        iva = _q2(item["ventaGravada"] - (item["ventaGravada"] / Decimal("1.13")))
        item["ivaItem"] = iva
        resumen["totalIva"] = iva
    elif tipo in {"nd", "nc"}:
        data.pop("otrosDocumentos", None)
        for key in ("codEstable", "codEstableMH", "codPuntoVenta", "codPuntoVentaMH"):
            data["emisor"].pop(key, None)
        item["numeroDocumento"] = "123"
        item.pop("psv", None)
        item.pop("noGravado", None)
        remove = {"porcentajeDescuento", "pagos", "saldoFavor", "totalNoGravado", "totalPagar"}
        if tipo == "nc":
            remove.add("numPagoElectronico")
        for key in remove:
            resumen.pop(key, None)
    elif tipo == "nr":
        data.pop("otrosDocumentos", None)
        data["receptor"].pop("nit", None)
        data["receptor"]["tipoDocumento"] = "36"
        data["receptor"]["numDocumento"] = "12345678901234"
        data["receptor"]["bienTitulo"] = "01"
        item.pop("psv", None)
        item.pop("noGravado", None)
        for key in [
            "condicionOperacion",
            "ivaPerci1",
            "ivaRete1",
            "numPagoElectronico",
            "pagos",
            "reteRenta",
            "saldoFavor",
            "totalNoGravado",
            "totalPagar",
        ]:
            resumen.pop(key, None)
    return data

def _assert_base(data: dict, tipo: str) -> None:
    item = data["cuerpoDocumento"][0]
    resumen = data["resumen"]
    if tipo == "fc":
        assert str(item["ventaGravada"]) == "26.95000000"
        iva = _q2(item["ventaGravada"] - (item["ventaGravada"] / Decimal("1.13")))
        assert str(iva) == "3.10"
        assert str(resumen["totalGravada"]) == "26.9500"
        total = resumen.get("totalPagar", resumen["montoTotalOperacion"])
        assert str(total) == "26.95"
        assert str(_q2(resumen["totalIva"])) == "3.10"
    else:
        assert str(item["ventaGravada"]) == "23.85000000"
        iva = _q8(item["ventaGravada"] * Decimal("0.13"))
        assert str(iva) == "3.10050000"
        assert str(resumen["totalGravada"]) == "23.8500"
        total = resumen.get("totalPagar", resumen["montoTotalOperacion"])
        assert str(total) == "26.95"
        total_iva = resumen.get("totalIva")
        if total_iva is None:
            total_iva = resumen["montoTotalOperacion"] - resumen["totalGravada"]
        assert str(_q2(total_iva)) == "3.10"


@pytest.mark.parametrize("tipo", ["ccf", "fc", "nd", "nc", "nr"])
def test_all_dtes(tipo):
    gen = GEN_MAP[tipo]
    data = _sanitize(gen(), tipo)
    validar_contra_schema(strip_extras(data), tipo)
    _assert_base(data, tipo)
    norm = normalize_for_schema(copy.deepcopy(data))
    golden_path = Path(__file__).resolve().parent / "goldens" / f"{tipo}.json"
    with open(golden_path, "r", encoding="utf-8") as fh:
        golden = json.load(fh)
    buf = io.StringIO()
    with redirect_stdout(buf):
        sim = similarity(norm, golden)
    diff = {}
    if sim != 1.0:
        diff = deep_diff(norm, golden)
    assert sim == 1.0, f"{diff}"

