import pytest
from utils.monto import D
from dte import calcular_resumen, normalizar_pagos, armar_tributos


def test_monto_total_operacion_uses_quantized_values():
    """montoTotalOperacion debe usar bases e IVA redondeados a 2 dec."""
    base = D("0.555")
    iva = D("0.555")
    resumen = calcular_resumen(base, {}, fiscal={"iva": iva})
    assert resumen["totalGravada"] == pytest.approx(0.56)
    assert resumen["totalIva"] == pytest.approx(0.56)
    assert resumen["montoTotalOperacion"] == pytest.approx(1.12)
    assert resumen["totalPagar"] == pytest.approx(1.12)


def test_resumen_sin_gravadas_omite_iva_y_tributos():
    """Sin ventas gravadas no debe haber IVA ni tributos."""
    resumen = calcular_resumen(0, {"total": 0}, fiscal={"iva": D("5.00")})
    assert resumen["totalGravada"] == 0
    assert resumen["totalIva"] == 0
    assert resumen["tributos"] is None


def test_calcular_resumen_quadra_pagos():
    """La suma de pagos debe cuadrar exactamente con totalPagar."""
    base = D("10")
    iva = D("0.01")
    pagos = [
        {"codigo": "01", "montoPago": 5.005},
        {"codigo": "02", "montoPago": 5.005},
    ]
    resumen = calcular_resumen(
        base, {"total": base + iva}, fiscal={"iva": iva}, extra={"pagos": pagos}
    )
    suma = sum(D(str(p["montoPago"])) for p in resumen["pagos"])
    assert suma == D(str(resumen["totalPagar"]))
    assert resumen["pagos"][-1]["montoPago"] == 5.0


def test_resumen_suma_por_item_sin_redondeo():
    base1 = D("0.555")
    base2 = D("0.555")
    iva1 = base1 * D("0.13")
    iva2 = base2 * D("0.13")
    items_total = base1 + base2
    iva_total = iva1 + iva2
    resumen = calcular_resumen(
        items_total,
        {"total": items_total + iva_total},
        fiscal={"iva": iva_total},
    )
    assert resumen["totalGravada"] == pytest.approx(1.11)
    assert resumen["totalIva"] == pytest.approx(0.14)
    assert resumen["totalPagar"] == pytest.approx(1.25)


def test_normalizar_pagos_normaliza_codigo():
    pagos = [{"codigo": 1, "montoPago": 1}, {"codigo": "02", "montoPago": 1}]
    norm = normalizar_pagos(pagos, 2)
    assert all(isinstance(p["codigo"], str) for p in norm)
    assert norm[0]["codigo"] == "01"


def test_armar_tributos_normaliza_codigo():
    trib = armar_tributos([{"codigo": 19, "valor": 0.1}], "01")
    assert trib[0]["codigo"] == "19"
    assert isinstance(trib[0]["codigo"], str)


def test_campos_requeridos_inicializados_en_cero():
    resumen = calcular_resumen(D("0"), {"total": D("0")})
    assert resumen["ivaRete1"] == 0
    assert resumen["reteRenta"] == 0
    assert resumen["totalNoGravado"] == 0

