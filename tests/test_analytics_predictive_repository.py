from datetime import date

from analytics_predictive.data.read_only_repository import ReadOnlyRepository


class _FakeDB:
    def get_productos(self):
        return [
            {
                "id": 1,
                "nombre": "Con historial",
                "stock": 10,
                "precio_compra": 2,
                "precio_venta_minorista": 5,
                "lead_time_days": 5,
            },
            {
                "id": 2,
                "nombre": "Sin historial",
                "stock": 3,
                "precio_compra": 1,
                "precio_venta_minorista": 2,
                "lead_time_days": 7,
            },
            {"id": "x", "nombre": "Invalido"},
        ]

    def get_ventas(self, sincronizada=1):
        assert sincronizada == 1
        return [
            {"id": 10, "fecha": "2026-01-01"},
            {"id": 11, "fecha": "bad-date"},
        ]

    def get_detalles_venta(self, sale_id):
        if sale_id == 10:
            return [
                {"producto_id": 1, "cantidad": 4},
                {"producto_id": 0, "cantidad": 2},
            ]
        return []

    def get_compras(self):
        return [
            {"id": 20, "fecha": "2026-01-02"},
            {"id": 21, "fecha": "2026-01-10"},
            {"id": 22, "fecha": "bad-date"},
        ]

    def get_detalles_compra(self, purchase_id):
        if purchase_id in (20, 21):
            return [{"producto_id": 1, "cantidad": 10}]
        if purchase_id == 22:
            return [{"producto_id": 1, "cantidad": 5}]
        return []


def test_extract_historical_data_integration_quality_counters() -> None:
    repo = ReadOnlyRepository(_FakeDB())
    out = repo.extract_historical_data(start=date(2026, 1, 1), end=date(2026, 1, 31))

    assert 1 in out.stock_by_product
    assert 2 in out.stock_by_product
    assert 2 not in out.sales_daily_by_product

    # Invalid date rows are excluded by date-range filtering before normalization.
    assert out.quality["invalid_sales_dates"] == 0
    assert out.quality["invalid_purchases_dates"] == 0
    assert out.quality["missing_product_rows"] == 1
    assert out.quality["skipped_sales_items"] == 1

    assert 1 in out.lead_time_hints
    assert out.lead_time_hints[1].estimated_days is not None
