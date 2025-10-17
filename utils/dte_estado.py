"""Utilidades para normalizar y evaluar estados de DTE."""

from __future__ import annotations

from functools import lru_cache
import re
import unicodedata
from typing import Iterable

__all__ = ["estado_apto_para_anexo", "normalizar_estado", "evaluar_estado"]


_ESTADOS_VALIDOS = (
    "aceptado",
    "aceptacion",
    "aceptadodgii",
    "aceptadosat",
    "aceptadohacienda",
    "aprobado",
    "aprobacion",
    "autorizado",
    "autorizacion",
    "enviado",
    "procesado",
    "procesand",
    "enproceso",
    "recibido",
    "recibidodgii",
    "recibidosat",
    "validado",
    "validacion",
)
_ESTADOS_INVALIDOS = (
    "pendiente",
    "pendientedeenvio",
    "pendientedeprocesar",
    "rechazado",
    "rechazo",
    "rechazadodgii",
    "anulado",
    "anulacion",
    "invalidado",
    "cancelado",
)


@lru_cache(maxsize=256)
def _strip_accents(texto: str) -> str:
    """Remueve tildes/acentos manteniendo únicamente caracteres básicos."""

    normalized = unicodedata.normalize("NFKD", texto)
    return "".join(char for char in normalized if not unicodedata.combining(char))


def normalizar_estado(valor: str | None) -> str | None:
    """Normaliza un estado a minúsculas sin espacios ni signos.

    Parameters
    ----------
    valor:
        Cadena original proveniente del payload, metadata o base de datos.

    Returns
    -------
    str | None
        El estado en minúsculas sin espacios ni guiones. Si el valor es vacío o
        `None`, se retorna ``None``.
    """

    if valor is None:
        return None

    texto = str(valor).strip().lower()
    if not texto:
        return None

    texto = _strip_accents(texto)
    texto = re.sub(r"[^a-z0-9]", "", texto)
    return texto or None


def evaluar_estado(valor: str | None) -> bool | None:
    """Evalúa si el estado es válido (True), inválido (False) o desconocido (None)."""

    texto = normalizar_estado(valor)
    if not texto:
        return None

    for candidato in _ESTADOS_VALIDOS:
        if texto.startswith(candidato):
            return True

    for candidato in _ESTADOS_INVALIDOS:
        if texto.startswith(candidato):
            return False

    return None


def _first_truthy(values: Iterable[str | None]) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return str(value).strip()
    return None


def estado_apto_para_anexo(
    estado_automatico: str | None, estado_manual: str | None
) -> bool:
    """Determina si un DTE puede incluirse en un anexo a partir de sus estados.

    La evaluación prioriza el estado manual cuando está disponible. Si el estado
    manual no es concluyente, se evalúa el automático. Ambos estados se
    normalizan eliminando espacios, guiones y tildes antes de realizar la
    comparación.
    """

    manual_texto = _first_truthy((estado_manual,))
    if manual_texto is not None:
        evaluacion_manual = evaluar_estado(manual_texto)
        if evaluacion_manual is not None:
            return bool(evaluacion_manual)

    automatico_texto = _first_truthy((estado_automatico,))
    if automatico_texto is not None:
        evaluacion_auto = evaluar_estado(automatico_texto)
        if evaluacion_auto is not None:
            return bool(evaluacion_auto)

    return False
