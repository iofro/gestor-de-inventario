"""Helpers to adapt DTE payloads into legacy ticket structures."""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping

from utils.catalogos import FORMA_PAGO

# Replicate the mapping used by ``ticket_pdf`` to keep labels identical.
_PAGO_LABELS = {code.zfill(2): value.upper() for code, value in FORMA_PAGO.items()}
_PAGO_LABELS["01"] = "EFECTIVO"


def _to_decimal(value: Any) -> Decimal | None:
    """Safely convert *value* to :class:`Decimal`.

    ``None`` and empty strings return ``None`` so callers can decide on
    appropriate fallbacks without forcing a numeric zero.
    """

    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        text = str(value).strip()
        if not text:
            return None
        return Decimal(text)
    except (InvalidOperation, ValueError, TypeError):
        return None


def _line_total(entry: Mapping[str, Any]) -> Any:
    """Return the best-effort line total for a DTE item entry."""

    for key in (
        "ventaGravada",
        "ventaExenta",
        "ventaNoSuj",
        "montoTotalOperacion",
        "montoTotal",
        "subTotal",
    ):
        value = entry.get(key)
        if value not in (None, "", 0):
            return value
    return None


def _item_quantity(entry: Mapping[str, Any]) -> Any:
    for key in ("cantidad", "cantidadUniMedida", "uniCantidad"):
        value = entry.get(key)
        if value not in (None, ""):
            return value
    return None


def _item_unit_price(entry: Mapping[str, Any]) -> Any:
    for key in ("precio_unitario", "precioUnitario", "precioUnit", "precioUni", "precio"):
        value = entry.get(key)
        if value not in (None, ""):
            return value
    return None


def _item_description(entry: Mapping[str, Any]) -> str:
    for key in ("descripcion", "descripcionProducto", "producto", "nombre"):
        value = entry.get(key)
        if value:
            return str(value)
    return ""


def _map_items(entries: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    mapped: list[dict[str, Any]] = []
    for entry in entries:
        item: dict[str, Any] = {
            "descripcion": _item_description(entry),
        }
        quantity = _item_quantity(entry)
        if quantity is not None:
            item["cantidad"] = quantity
        unit_price = _item_unit_price(entry)
        if unit_price is not None:
            item["precio_unitario"] = unit_price
        total = _line_total(entry)
        if total is not None:
            item["montoTotal"] = total
        mapped.append(item)
    return mapped


def _map_forma_pago(resumen: Mapping[str, Any], venta: Mapping[str, Any]) -> tuple[str | None, Any | None]:
    pagos = resumen.get("pagos") or []
    if pagos:
        pago = pagos[0]
        codigo = str(pago.get("codigo") or "").zfill(2)
        label = _PAGO_LABELS.get(codigo)
        monto = pago.get("montoPago")
        if label:
            return label, monto
    forma = venta.get("forma_pago")
    if forma:
        return str(forma), venta.get("monto_pago")
    return None, None


def dte_to_legacy_ticket_payload(
    dte_json: Mapping[str, Any] | None,
    venta: Mapping[str, Any] | None,
    detalles: Iterable[Mapping[str, Any]] | None,
    datos_negocio: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Build a payload compatible with the legacy ticket generator.

    The result mirrors the structure used when producing tickets for ventas:

    ``{"venta": {...}, "detalles": [...], "datos_negocio": {...}, "dte_data": {...}}``
    """

    dte_json = deepcopy(dte_json or {})
    venta_data: dict[str, Any] = dict(venta or {})
    datos_negocio = dict(datos_negocio or {})

    identificacion = dte_json.get("identificacion", {}) or {}
    receptor = dte_json.get("receptor", {}) or {}
    resumen = dte_json.get("resumen", {}) or {}

    tipo_dte = str(identificacion.get("tipoDte") or "").zfill(2)
    if tipo_dte == "01":
        venta_data["tipo"] = "CF"
    elif tipo_dte == "03":
        venta_data["tipo"] = "CCF"

    fecha = identificacion.get("fecEmi")
    if fecha:
        venta_data["fecha"] = fecha

    numero_control = identificacion.get("numeroControl")
    if numero_control:
        venta_data["numero_control"] = numero_control

    codigo_generacion = identificacion.get("codigoGeneracion")
    if codigo_generacion:
        venta_data["codigo_generacion"] = codigo_generacion

    cliente_nombre = (
        receptor.get("nombre")
        or receptor.get("razonSocial")
        or receptor.get("denominacionSocial")
    )
    if cliente_nombre and not venta_data.get("cliente"):
        venta_data["cliente"] = cliente_nombre

    documento = (
        receptor.get("nit")
        or receptor.get("dui")
        or receptor.get("numDocumento")
        or receptor.get("numeroDocumento")
    )
    if documento and not venta_data.get("documento"):
        venta_data["documento"] = documento

    subtotal = (
        _to_decimal(resumen.get("sumas"))
        or _to_decimal(resumen.get("subTotal"))
        or _to_decimal(resumen.get("subTotalVentas"))
        or _to_decimal(resumen.get("totalGravada"))
    )

    total = _to_decimal(resumen.get("totalPagar")) or _to_decimal(venta_data.get("total"))
    if total is not None:
        venta_data["total"] = total

    iva = (
        _to_decimal(resumen.get("iva"))
        or _to_decimal(resumen.get("totalIva"))
        or _to_decimal(resumen.get("ivaRete"))
    )
    if iva is None and subtotal is not None and total is not None:
        iva_candidate = total - subtotal
        if iva_candidate > Decimal("0"):
            iva = iva_candidate
    if iva is not None:
        venta_data["iva"] = iva

    if subtotal is not None:
        venta_data.setdefault("sumas", subtotal)

    forma_pago, monto_pago = _map_forma_pago(resumen, venta_data)
    if forma_pago and not venta_data.get("forma_pago"):
        venta_data["forma_pago"] = forma_pago
    if monto_pago is not None and not venta_data.get("monto_pago"):
        venta_data["monto_pago"] = monto_pago
    elif not venta_data.get("forma_pago"):
        venta_data["forma_pago"] = "Contado"

    cuerpo = dte_json.get("cuerpoDocumento")
    if cuerpo and isinstance(cuerpo, Iterable):
        detalles_mapeados = _map_items(cuerpo)
    else:
        detalles_mapeados = _map_items(detalles or [])

    dte_data = {
        "dteJson": dte_json,
    }

    return {
        "venta": venta_data,
        "detalles": detalles_mapeados,
        "datos_negocio": datos_negocio,
        "dte_data": dte_data,
    }
