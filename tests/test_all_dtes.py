import copy

import pytest

from svfe.generators import (
    generar_consumidor_final,
    generar_factura_fiscal,
    generar_nota_credito,
    generar_nota_debito,
    generar_nota_remision,
    validar_contra_schema,
)


GEN_MAP = {
    "ccf": generar_factura_fiscal,
    "fc": generar_consumidor_final,
    "nd": generar_nota_debito,
    "nc": generar_nota_credito,
    "nr": generar_nota_remision,
}


def _sanitize(data, tipo):
    if tipo == "fc":
        data["receptor"].pop("nit", None)
        data["receptor"].pop("nombreComercial", None)
        data["receptor"]["tipoDocumento"] = "36"
        data["receptor"]["numDocumento"] = "06141990011019"
    elif tipo in {"nd", "nc"}:
        for key in ("codEstable", "codEstableMH", "codPuntoVenta", "codPuntoVentaMH"):
            data["emisor"].pop(key, None)
        data["cuerpoDocumento"][0]["numeroDocumento"] = "123"
    elif tipo == "nr":
        data["receptor"].pop("nit", None)
        data["receptor"]["tipoDocumento"] = "36"
        data["receptor"]["numDocumento"] = "12345678901234"
        data["receptor"]["bienTitulo"] = "01"
    return data


@pytest.mark.parametrize("tipo", ["ccf", "fc", "nd", "nc", "nr"])
def test_dtes_invalidos(tipo):
    gen = GEN_MAP[tipo]
    data = _sanitize(gen(), tipo)

    missing = copy.deepcopy(data)
    missing["identificacion"].pop("version")
    with pytest.raises(ValueError) as excinfo:
        validar_contra_schema(missing, tipo)
    assert "identificacion.version" in str(excinfo.value)

    wrong = copy.deepcopy(data)
    wrong["cuerpoDocumento"][0]["precioUni"] = "foo"
    with pytest.raises(ValueError) as excinfo:
        validar_contra_schema(wrong, tipo)
    assert "cuerpoDocumento.0.precioUni" in str(excinfo.value)
