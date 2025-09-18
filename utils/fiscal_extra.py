"""Utilities for fiscal totals stored alongside sales."""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping, Sequence

from utils.monto import d8

D = Decimal

_ALLOWED_FISCAL_KEYS = {
    "sumas",
    "descuentos",
    "iva",
    "subtotal",
    "ventas_exentas",
    "ventas_no_sujetas",
    "no_gravado",
    "precios_incluyen_iva",
    "descu_no_suj",
    "descu_exenta",
    "descu_gravada",
    "sub_total_ventas",
}


def normalize_tipo_fiscal(value: Any) -> str:
    """Normalize ``tipo_fiscal`` values to the canonical set."""

    if value is None:
        return "gravada"
    text = str(value).strip().lower().replace("_", " ")
    if not text:
        return "gravada"
    replacements = {
        "venta gravada": "gravada",
        "gravado": "gravada",
        "gravada": "gravada",
        "venta exenta": "exenta",
        "exenta": "exenta",
        "exento": "exenta",
        "venta no sujeta": "no_sujeta",
        "no sujeta": "no_sujeta",
        "no suj": "no_sujeta",
        "no sujeta a iva": "no_sujeta",
        "venta no gravada": "no_gravada",
        "no gravada": "no_gravada",
        "no gravado": "no_gravada",
        "no afecto": "no_gravada",
    }
    if text in replacements:
        return replacements[text]
    text = text.replace("venta", "").strip()
    if text in replacements:
        return replacements[text]
    if "grav" in text:
        return "gravada"
    if "exen" in text:
        return "exenta"
    if "no su" in text:
        return "no_sujeta"
    if "no gr" in text or "no af" in text:
        return "no_gravada"
    return "gravada"


def _to_decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return D(int(value))
    if value in (None, ""):
        return D("0")
    return D(str(value))


def _lookup_numeric(sources: Sequence[Mapping[str, Any]], key: str) -> Decimal | None:
    for src in sources:
        if key in src and src[key] is not None:
            return _to_decimal(src[key])
    return None


def _item_decimal(item: Mapping[str, Any], *keys: str) -> Decimal:
    for key in keys:
        if key in item and item[key] not in (None, ""):
            return _to_decimal(item[key])
    return D("0")


def build_fiscal_extra(data: Mapping[str, Any]) -> dict[str, Any]:
    """Return a fiscal summary dict ready to persist as JSON.

    The function merges any pre-computed values in ``data`` or ``data['extra']``
    with metrics calculated from ``data['items']``. Values provided explicitly
    take precedence over computed ones.
    """

    extra_src = data.get("extra")
    sources: list[Mapping[str, Any]] = []
    if isinstance(data, Mapping):
        sources.append(data)
    if isinstance(extra_src, Mapping):
        sources.append(extra_src)

    items: Sequence[Mapping[str, Any]] = data.get("items") or ()

    sumas_calc = D("0")
    descuentos_calc = D("0")
    iva_calc = D("0")
    exenta_calc = D("0")
    no_suj_calc = D("0")
    no_gravado_calc = D("0")

    for item in items:
        tipo_norm = normalize_tipo_fiscal(item.get("tipo_fiscal"))
        base = _item_decimal(
            item,
            "subtotal_con_descuento",
            "base",
            "subtotal_sin_descuento",
            "subtotal",
        )
        descuento = _item_decimal(item, "descuento_monto", "desc_con_iva", "descuento")
        if base == 0 and descuento == 0:
            cantidad = _item_decimal(item, "cantidad")
            if cantidad != 0:
                unitario = _item_decimal(item, "precio_unitario", "precio", "precio_con_iva")
                base = cantidad * unitario
        bruto = base + descuento
        iva_item = _item_decimal(item, "iva")
        total_linea = _item_decimal(item, "total", "total_con_iva")
        if total_linea == 0:
            total_linea = base + iva_item
        extra_linea = total_linea - base - iva_item
        if extra_linea > 0:
            no_gravado_calc += extra_linea

        if tipo_norm == "gravada":
            sumas_calc += bruto
            descuentos_calc += descuento
            iva_calc += iva_item
        elif tipo_norm == "exenta":
            exenta_calc += base
        elif tipo_norm == "no_sujeta":
            no_suj_calc += base
        else:  # no_gravada
            no_gravado_calc += base

    subtotal_calc = (sumas_calc - descuentos_calc) + iva_calc

    result: dict[str, Any] = {}
    for key in _ALLOWED_FISCAL_KEYS:
        value = _lookup_numeric(sources, key)
        if value is None:
            if key == "sumas":
                value = sumas_calc
            elif key == "descuentos":
                value = descuentos_calc
            elif key == "iva":
                value = iva_calc
            elif key == "subtotal":
                value = subtotal_calc
            elif key == "ventas_exentas":
                value = exenta_calc
            elif key == "ventas_no_sujetas":
                value = no_suj_calc
            elif key == "no_gravado":
                value = no_gravado_calc
            elif key == "sub_total_ventas":
                value = sumas_calc
            elif key in {"descu_no_suj", "descu_exenta", "descu_gravada"}:
                value = D("0")
            elif key == "precios_incluyen_iva":
                # handled separately below
                continue
            else:
                value = D("0")
        if key == "precios_incluyen_iva":
            continue
        result[key] = float(d8(value))

    precios_flag = None
    if isinstance(data, Mapping) and "precios_incluyen_iva" in data:
        precios_flag = bool(data["precios_incluyen_iva"])
    elif isinstance(extra_src, Mapping) and "precios_incluyen_iva" in extra_src:
        precios_flag = bool(extra_src["precios_incluyen_iva"])
    if precios_flag is None:
        precios_flag = True
        if data.get("iva_agregado"):
            precios_flag = False
        else:
            for item in items:
                iva_tipo = str(item.get("iva_tipo") or "").lower()
                if iva_tipo in {"desglosado", "agregado"}:
                    precios_flag = False
                    break
    result["precios_incluyen_iva"] = precios_flag

    return result
