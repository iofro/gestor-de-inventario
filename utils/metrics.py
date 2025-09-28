"""Lightweight helpers for emitting instrumentation metrics.

The project historically didn't collect metrics, however several new
workflows expect an ``inc`` helper to be present.  This module keeps the
interface intentionally small so call sites can record counters without
introducing an external dependency.  The current implementation simply
logs the event at ``DEBUG`` level which is sufficient for unit tests.
"""
from __future__ import annotations

import logging
from typing import Any

__all__ = ["inc"]

_logger = logging.getLogger("metrics")


def inc(name: str, value: int = 1, **labels: Any) -> None:
    """Increment counter ``name``.

    Parameters
    ----------
    name:
        Metric identifier.  Empty names are ignored so callers can pass
        dynamic values without additional guards.
    value:
        Increment amount.  Non-integer values are coerced to ``int`` when
        possible.
    labels:
        Optional keyword labels attached to the event.
    """

    if not name:
        return
    try:
        amount = int(value)
    except (TypeError, ValueError):
        amount = 1
    if labels:
        _logger.debug("metric_inc %s=%s labels=%s", name, amount, labels)
    else:
        _logger.debug("metric_inc %s=%s", name, amount)
