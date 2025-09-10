from __future__ import annotations

"""Deterministic IVA calculations with cent-closing adjustments."""

from decimal import Decimal, ROUND_HALF_UP
from dataclasses import dataclass
from typing import Iterable, List

D = Decimal
IVA_TASA = D("0.13")
Q4 = D("0.0001")
Q2 = D("0.01")


def d4(value: "object") -> D:
    """Return ``value`` rounded to 4 decimal places (ROUND_HALF_UP)."""
    return D(str(value)).quantize(Q4, rounding=ROUND_HALF_UP)


def d2(value: "object") -> D:
    """Return ``value`` rounded to 2 decimal places (ROUND_HALF_UP)."""
    return D(str(value)).quantize(Q2, rounding=ROUND_HALF_UP)


@dataclass
class LineaResultado:
    base: D
    iva: D
    pf: D


def _calcular_linea_pf(qty: D, pf_unit: D) -> LineaResultado:
    base_unit = d4(pf_unit / (D("1") + IVA_TASA))
    iva_unit = d4(pf_unit - base_unit)
    pf_line = d4(pf_unit * qty)
    base_line = d4(base_unit * qty)
    iva_line = d4(pf_line - base_line)
    return LineaResultado(base_line, iva_line, pf_line)


def _calcular_linea_base(qty: D, base_unit: D) -> LineaResultado:
    iva_unit = d4(base_unit * IVA_TASA)
    pf_unit = d4(base_unit + iva_unit)
    base_line = d4(base_unit * qty)
    iva_line = d4(iva_unit * qty)
    pf_line = d4(base_line + iva_line)
    return LineaResultado(base_line, iva_line, pf_line)


def cerrar_totales(bases: List[D], ivas: List[D], pfs: List[D]):
    """Apply cent-closing rule to totals and last line IVA."""
    sum_base = sum(bases)
    sum_iva = sum(ivas)
    sum_pf = sum(pfs)

    base_total = d2(sum_base)
    iva_total = d2(sum_iva)
    pf_total = d2(sum_pf)
    delta = pf_total - (base_total + iva_total)
    if delta == D("0.01") and ivas:
        iva_total += delta
        ivas[-1] = d4(ivas[-1] + delta)
    return base_total, iva_total, pf_total, delta


def calcular_detalle_iva(lineas: Iterable[dict], descuento_global: D | int | float | str | None = None):
    """Compute base and IVA for each line and totals.

    ``lineas`` is an iterable of dictionaries with ``qty`` and either
    ``pf_unit`` (price with IVA) or ``base_unit`` (price without IVA).  Each
    line may include ``desc`` (absolute discount over final price) or
    ``desc_pct`` (percentage).  Discounts are applied over the final price and
    then base/IVA are recalculated from the net price.

    ``descuento_global`` is an absolute discount applied to the sum of final
    prices and distributed proportionally among the lines before recalculating
    base and IVA.
    """

    resultados: List[LineaResultado] = []
    pf_totales: List[D] = []

    for data in lineas:
        qty = D(str(data.get("qty", 0)))
        if "pf_unit" in data:
            pf_unit = D(str(data["pf_unit"]))
            res = _calcular_linea_pf(qty, pf_unit)
        else:
            base_unit = D(str(data.get("base_unit", 0)))
            res = _calcular_linea_base(qty, base_unit)
        descuento = D(str(data.get("desc", 0)))
        desc_pct = D(str(data.get("desc_pct", 0)))
        if desc_pct:
            descuento += d4(res.pf * desc_pct / D("100"))
        if descuento:
            pf_neto = d4(res.pf - descuento)
            res = _calcular_linea_pf(D("1"), pf_neto)
        resultados.append(res)
        pf_totales.append(res.pf)

    if descuento_global:
        desc_glob = D(str(descuento_global))
        total_pf = sum(pf_totales)
        nuevos: List[LineaResultado] = []
        for res in resultados:
            propor = res.pf / total_pf if total_pf else D("0")
            pf_neto = d4(res.pf - d4(desc_glob * propor))
            nuevos.append(_calcular_linea_pf(D("1"), pf_neto))
        resultados = nuevos

    bases = [res.base for res in resultados]
    ivas = [res.iva for res in resultados]
    pfs = [res.pf for res in resultados]

    base_total, iva_total, pf_total, delta = cerrar_totales(bases, ivas, pfs)

    line_dicts = [
        {"base": res.base, "iva": res.iva, "pf": res.pf}
        for res in resultados
    ]
    result = {
        "lineas": line_dicts,
        "totales": {"base": base_total, "iva": iva_total, "pf": pf_total},
    }
    if delta == D("0.01"):
        result["ajuste_redondeo_iva"] = delta
    return result
