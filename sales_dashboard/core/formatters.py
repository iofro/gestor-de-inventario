"""Formatting helpers for monetary, percentage and date values."""
from __future__ import annotations

from datetime import date, datetime
from typing import Union

DateLike = Union[date, datetime]


def format_currency(value: float) -> str:
    """Return a currency string using ``$`` with thousands separators."""
    return f"$ {value:,.2f}"


def format_percentage(value: float) -> str:
    """Format the value as percentage with one decimal place."""
    return f"{value * 100:.1f}%"


def format_date(value: DateLike) -> str:
    """Format a ``datetime`` or ``date`` using ``DD/MM/YYYY``."""
    if isinstance(value, datetime):
        value = value.date()
    return value.strftime("%d/%m/%Y")
