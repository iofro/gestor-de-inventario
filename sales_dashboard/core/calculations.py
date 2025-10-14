"""Utility functions for sales metrics calculations."""
from __future__ import annotations

from typing import Iterable, List, Dict, Any


def calcTicketPromedio(ventas: float, transacciones: int) -> float:
    """Return the average ticket rounded to two decimals.

    When there are no transactions the ticket promedio is 0.0.
    """
    if transacciones <= 0:
        return 0.0
    return round(ventas / transacciones, 2)


def calcMargenBruto(ventas: float, cmv: float) -> float:
    """Compute gross margin as ``ventas - costo de mercancía vendida``."""
    return ventas - cmv


def calcContribucion(margen: float, ventas: float) -> float:
    """Return the contribution percentage as ``margen / ventas``.

    Handles ``ventas`` equal to zero returning ``0.0`` to avoid ``ZeroDivisionError``.
    """
    if ventas == 0:
        return 0.0
    return margen / ventas


def sortTopProducts(datos: Iterable[Dict[str, Any]], por: str) -> List[Dict[str, Any]]:
    """Return the products ordered by the provided metric.

    The ``por`` argument must correspond to a numeric key in each record.  The
    function sorts the data in descending order using the value of ``por`` and
    breaks ties using the ``producto`` field to guarantee deterministic
    ordering.
    """
    key = por
    return sorted(
        datos,
        key=lambda item: (-float(item.get(key, 0.0)), str(item.get("producto", "").lower())),
    )
