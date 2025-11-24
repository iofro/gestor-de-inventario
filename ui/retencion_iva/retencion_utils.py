"""Utilidades UI-only para Comprobante de Retención."""

from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Iterable
from uuid import UUID

from .retencion_models import CRDetalle, CRDraft, CRResumen


def _decimal(value: float | str | int | None) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def quantize_money(value: float | str | int | Decimal) -> float:
    """Normaliza montos a dos decimales para evitar ruido en la UI."""

    dec = _decimal(value)
    return float(dec.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def is_valid_uuid(value: str | None) -> bool:
    if not value:
        return False
    try:
        UUID(str(value))
    except (ValueError, TypeError):
        return False
    return True


def number_to_words(amount: float) -> str:
    """Stub: convierte importe a texto simple (sin reglas complejas)."""

    dec = _decimal(amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    parte_entera = int(dec)
    centavos = int((dec - Decimal(parte_entera)) * 100)
    return f"{parte_entera} dólares con {centavos:02d} centavos"


def build_resumen(detalles: Iterable[CRDetalle]) -> CRResumen:
    total_sujeto = Decimal("0")
    total_iva = Decimal("0")
    for detalle in detalles:
        total_sujeto += _decimal(detalle.montoSujetoGrav)
        total_iva += _decimal(detalle.ivaRetenido)
    sujeto = total_sujeto.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    iva = total_iva.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return CRResumen(
        totalSujetoRetencion=float(sujeto),
        totalIVAretenido=float(iva),
        totalIVAretenidoLetras=number_to_words(float(iva)),
    )


def draft_to_dict(draft: CRDraft) -> dict:
    """Convierte el borrador a un dict plano apto para serializar."""

    payload = asdict(draft)
    # Ajustar llaves al formato esperado por futuros backends.
    payload["detalles"] = [asdict(detalle) for detalle in draft.detalles]
    payload["resumen"] = asdict(draft.resumen)
    return payload


def ensure_detalle_defaults(detalle: CRDetalle) -> CRDetalle:
    """Devuelve una copia del detalle con campos coherentes para la UI."""

    if detalle.tipoDoc == "2":
        if not is_valid_uuid(detalle.codGeneracion):
            detalle.codGeneracion = ""
    else:
        if not detalle.numDocumento:
            detalle.numDocumento = ""
    detalle.montoSujetoGrav = quantize_money(detalle.montoSujetoGrav)
    detalle.ivaRetenido = quantize_money(detalle.ivaRetenido)
    return detalle

