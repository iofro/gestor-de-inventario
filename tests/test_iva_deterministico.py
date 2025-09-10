from utils.monto import D
from utils.iva import calcular_detalle_iva, cerrar_totales, d4


def test_caso_a_precio_final():
    res = calcular_detalle_iva([
        {"qty": D("1"), "pf_unit": D("1.00")}
    ])
    linea = res["lineas"][0]
    assert linea["base"] == D("0.8850")
    assert linea["iva"] == D("0.1150")
    assert linea["pf"] == D("1.0000")
    tot = res["totales"]
    assert tot["base"] == D("0.89")
    assert tot["iva"] == D("0.12")
    assert tot["pf"] == D("1.00")
    assert "ajuste_redondeo_iva" not in res


def test_caso_b_multiples():
    res = calcular_detalle_iva([
        {"qty": D("3"), "pf_unit": D("1.00")}
    ])
    linea = res["lineas"][0]
    assert linea["base"] == D("2.6550")
    assert linea["iva"] == D("0.3450")
    assert linea["pf"] == D("3.0000")
    tot = res["totales"]
    assert tot["base"] == D("2.66")
    assert tot["iva"] == D("0.35")
    assert tot["pf"] == D("3.00")
    assert "ajuste_redondeo_iva" not in res


def test_caso_c_descuento_linea():
    res = calcular_detalle_iva([
        {"qty": D("1"), "pf_unit": D("18.01"), "desc": D("1.01")}
    ])
    linea = res["lineas"][0]
    assert linea["pf"] == D("17.0000")
    assert linea["base"] == D("15.0442")
    assert linea["iva"] == D("1.9558")
    tot = res["totales"]
    assert tot["base"] == D("15.04")
    assert tot["iva"] == D("1.96")
    assert tot["pf"] == D("17.00")


def test_caso_d_ajuste_centavo():
    bases = [D("0.8850"), D("0.8850"), D("7.0796")]
    ivas = [D("0.1150"), D("0.1150"), D("0.9096")]
    pfs = [D("1.0000"), D("1.0000"), D("8.0000")]
    base_total, iva_total, pf_total, delta = cerrar_totales(bases, ivas, pfs)
    assert base_total == D("8.85")
    assert iva_total == D("1.15")
    assert pf_total == D("10.00")
    assert delta == D("0.01")
    assert ivas[-1] == d4(D("0.9096") + D("0.01"))
