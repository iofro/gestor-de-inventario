from __future__ import annotations

import logging
from collections import defaultdict
from contextlib import nullcontext
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional

from .models import (
    DailyDemandPoint,
    DailyPurchasePoint,
    HistoricalDataBundle,
    LeadTimeHint,
    ProductSnapshot,
)


logger = logging.getLogger(__name__)


class ReadOnlyRepository:
    """Repositorio de solo lectura para extraer datos sin afectar transacciones."""

    def __init__(self, db: Any) -> None:
        self.db = db

    def extract_historical_data(
        self,
        start: Optional[date] = None,
        end: Optional[date] = None,
    ) -> HistoricalDataBundle:
        """Extrae y normaliza series historicas de solo lectura para analitica.

        Incluye ventas diarias, compras diarias, stock actual y pistas de lead time.
        """

        quality = {
            "invalid_sales_dates": 0,
            "invalid_purchases_dates": 0,
            "missing_product_rows": 0,
            "skipped_sales_items": 0,
            "skipped_purchase_items": 0,
        }

        products = self.get_products()
        stock_by_product = self._normalize_product_snapshots(products, quality)

        sales = self.get_sales(start=start, end=end)
        sales_daily = self._build_sales_daily_by_product(sales, quality)

        purchases = self.get_purchases(start=start, end=end)
        purchases_daily, purchase_days = self._build_purchases_daily_by_product(purchases, quality)

        lead_time_hints = self._estimate_lead_time_hints(purchase_days)

        logger.info(
            "Predictive read-only extraction done: products=%s sales=%s purchases=%s",
            len(stock_by_product),
            len(sales_daily),
            len(purchases_daily),
        )

        return HistoricalDataBundle(
            sales_daily_by_product=sales_daily,
            purchases_daily_by_product=purchases_daily,
            stock_by_product=stock_by_product,
            lead_time_hints=lead_time_hints,
            quality=quality,
        )

    def get_products(self) -> List[Dict[str, Any]]:
        rows = list(self.db.get_productos())
        return [dict(r) for r in rows if isinstance(r, dict)]

    def get_sales(self, start: Optional[date] = None, end: Optional[date] = None) -> List[Dict[str, Any]]:
        rows = list(self.db.get_ventas(sincronizada=1))
        return [r for r in rows if self._in_date_range(r.get("fecha"), start, end)]

    def get_sale_details(self, sale_id: int) -> List[Dict[str, Any]]:
        rows = list(self.db.get_detalles_venta(sale_id))
        return [dict(r) for r in rows if isinstance(r, dict)]

    def get_purchases(self, start: Optional[date] = None, end: Optional[date] = None) -> List[Dict[str, Any]]:
        rows = list(self.db.get_compras())
        return [r for r in rows if self._in_date_range(r.get("fecha"), start, end)]

    def get_purchase_details(self, purchase_id: int) -> List[Dict[str, Any]]:
        rows = list(self.db.get_detalles_compra(purchase_id))
        return [dict(r) for r in rows if isinstance(r, dict)]

    def _normalize_product_snapshots(
        self,
        products: Iterable[Dict[str, Any]],
        quality: Dict[str, int],
    ) -> Dict[int, ProductSnapshot]:
        snapshots: Dict[int, ProductSnapshot] = {}
        for p in products:
            product_id = self._to_int(p.get("id"))
            if product_id <= 0:
                quality["missing_product_rows"] += 1
                continue
            name = str(p.get("nombre") or f"Producto {product_id}").strip()
            stock = self._to_float(p.get("stock"))
            cost = self._to_float(p.get("precio_compra"))
            sale_price = self._to_float(
                p.get("precio_venta_minorista")
                or p.get("precio_venta_mayorista")
                or p.get("precio")
            )
            lead_time = self._to_optional_int(p.get("lead_time_days"))
            in_transit = self._to_float(p.get("stock_in_transit"))

            snapshots[product_id] = ProductSnapshot(
                product_id=product_id,
                name=name,
                stock_current=max(stock, 0.0),
                cost_unit=max(cost, 0.0),
                sale_price=max(sale_price, 0.0),
                lead_time_days=lead_time,
                stock_in_transit=max(in_transit, 0.0),
            )
        return snapshots

    def _build_sales_daily_by_product(
        self,
        sales: Iterable[Dict[str, Any]],
        quality: Dict[str, int],
    ) -> Dict[int, List[DailyDemandPoint]]:
        grouped: Dict[int, Dict[date, float]] = defaultdict(lambda: defaultdict(float))

        for sale in sales:
            sale_id = self._to_int(sale.get("id"))
            if sale_id <= 0:
                continue
            day = self._parse_date(sale.get("fecha"))
            if day is None:
                quality["invalid_sales_dates"] += 1
                continue
            for item in self.get_sale_details(sale_id):
                product_id = self._to_int(item.get("producto_id"))
                if product_id <= 0:
                    quality["skipped_sales_items"] += 1
                    continue
                units = self._to_float(item.get("cantidad"))
                if units < 0:
                    quality["skipped_sales_items"] += 1
                    continue
                grouped[product_id][day] += units

        out: Dict[int, List[DailyDemandPoint]] = {}
        for product_id, day_map in grouped.items():
            points = [
                DailyDemandPoint(product_id=product_id, day=day, units=qty)
                for day, qty in sorted(day_map.items(), key=lambda x: x[0])
            ]
            out[product_id] = points
        return out

    def _build_purchases_daily_by_product(
        self,
        purchases: Iterable[Dict[str, Any]],
        quality: Dict[str, int],
    ) -> tuple[Dict[int, List[DailyPurchasePoint]], Dict[int, List[date]]]:
        grouped: Dict[int, Dict[date, float]] = defaultdict(lambda: defaultdict(float))
        purchase_days: Dict[int, List[date]] = defaultdict(list)

        for purchase in purchases:
            purchase_id = self._to_int(purchase.get("id"))
            if purchase_id <= 0:
                continue
            day = self._parse_date(purchase.get("fecha"))
            if day is None:
                quality["invalid_purchases_dates"] += 1
                continue
            for item in self.get_purchase_details(purchase_id):
                product_id = self._to_int(item.get("producto_id"))
                if product_id <= 0:
                    quality["skipped_purchase_items"] += 1
                    continue
                units = self._to_float(item.get("cantidad"))
                if units < 0:
                    quality["skipped_purchase_items"] += 1
                    continue
                grouped[product_id][day] += units
                purchase_days[product_id].append(day)

        out: Dict[int, List[DailyPurchasePoint]] = {}
        for product_id, day_map in grouped.items():
            points = [
                DailyPurchasePoint(product_id=product_id, day=day, units=qty)
                for day, qty in sorted(day_map.items(), key=lambda x: x[0])
            ]
            out[product_id] = points

        for product_id, days in purchase_days.items():
            purchase_days[product_id] = sorted(set(days))

        return out, dict(purchase_days)

    def _estimate_lead_time_hints(
        self,
        purchase_days: Dict[int, List[date]],
    ) -> Dict[int, LeadTimeHint]:
        """Estimacion auxiliar de lead time basada en intervalos de compra."""

        hints: Dict[int, LeadTimeHint] = {}
        for product_id, days in purchase_days.items():
            if len(days) < 2:
                hints[product_id] = LeadTimeHint(
                    product_id=product_id,
                    estimated_days=None,
                    sample_size=len(days),
                )
                continue

            intervals = [
                max((days[i] - days[i - 1]).days, 0)
                for i in range(1, len(days))
            ]
            if not intervals:
                hints[product_id] = LeadTimeHint(
                    product_id=product_id,
                    estimated_days=None,
                    sample_size=len(days),
                )
                continue

            estimated = int(round(sum(intervals) / len(intervals)))
            hints[product_id] = LeadTimeHint(
                product_id=product_id,
                estimated_days=max(estimated, 1),
                sample_size=len(intervals),
            )
        return hints

    @staticmethod
    def _in_date_range(raw_date: Any, start: Optional[date], end: Optional[date]) -> bool:
        if start is None and end is None:
            return True
        parsed = ReadOnlyRepository._parse_date(raw_date)
        if parsed is None:
            return False
        if start is not None and parsed < start:
            return False
        if end is not None and parsed > end:
            return False
        return True

    @staticmethod
    def _parse_date(raw_date: Any) -> Optional[date]:
        if isinstance(raw_date, date):
            return raw_date
        if not isinstance(raw_date, str) or not raw_date.strip():
            return None
        text = raw_date.strip()
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
        return None

    @staticmethod
    def _to_int(value: Any) -> int:
        try:
            return int(str(value).strip())
        except Exception:
            return 0

    @staticmethod
    def _to_optional_int(value: Any) -> Optional[int]:
        try:
            text = str(value).strip()
            if not text:
                return None
            parsed = int(text)
            return parsed if parsed > 0 else None
        except Exception:
            return None

    @staticmethod
    def _to_float(value: Any) -> float:
        try:
            if value is None:
                return 0.0
            return float(value)
        except Exception:
            return 0.0
