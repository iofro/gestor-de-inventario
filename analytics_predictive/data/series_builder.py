from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from statistics import pstdev
from typing import Dict, Iterable, List

from .models import DailyDemandPoint


def build_daily_series(
    sale_details_by_day: Dict[date, List[dict]],
) -> Dict[int, List[DailyDemandPoint]]:
    """Convierte detalles diarios en series de demanda por producto."""

    grouped: Dict[int, List[DailyDemandPoint]] = defaultdict(list)
    for day, details in sale_details_by_day.items():
        for item in details:
            product_id = int(item.get("producto_id") or 0)
            if product_id <= 0:
                continue
            units = float(item.get("cantidad") or 0)
            grouped[product_id].append(DailyDemandPoint(product_id=product_id, day=day, units=units))

    for product_id, points in grouped.items():
        grouped[product_id] = sorted(points, key=lambda p: p.day)

    return dict(grouped)


def fill_missing_days(points: Iterable[DailyDemandPoint]) -> List[DailyDemandPoint]:
    """Rellena dias faltantes con demanda cero para mantener continuidad."""

    ordered = sorted(points, key=lambda p: p.day)
    if not ordered:
        return []

    product_id = ordered[0].product_id
    start = ordered[0].day
    end = ordered[-1].day
    by_day = {p.day: p.units for p in ordered}

    out: List[DailyDemandPoint] = []
    cursor = start
    while cursor <= end:
        out.append(DailyDemandPoint(product_id=product_id, day=cursor, units=by_day.get(cursor, 0.0)))
        cursor += timedelta(days=1)
    return out


def demand_stats(points: Iterable[DailyDemandPoint]) -> tuple[float, float]:
    values = [float(p.units) for p in points]
    if not values:
        return 0.0, 0.0
    avg = sum(values) / len(values)
    std = pstdev(values) if len(values) > 1 else 0.0
    return avg, std
