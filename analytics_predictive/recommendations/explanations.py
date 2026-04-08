from __future__ import annotations


def build_explanation(
    *,
    suggested_qty: float,
    demand_daily_avg: float,
    coverage_days: float,
    lead_time_days: int,
    method: str,
    alert_type: str,
    abc_class: str,
    days_since_last_sale: int | None,
    can_recommend: bool,
) -> str:
    if not can_recommend:
        return (
            "No se emite recomendacion automatica por datos criticos incompletos "
            "(lead time o datos base insuficientes)."
        )

    suffix = ""
    if days_since_last_sale is not None:
        suffix = f" Producto lento: {days_since_last_sale} dias sin venta."

    return (
        f"Sugerido {suggested_qty:.2f} unidades. "
        f"Demanda diaria {demand_daily_avg:.2f}, cobertura {coverage_days:.1f} dias, "
        f"lead time {lead_time_days} dias, metodo {method}, alerta {alert_type}, clase ABC {abc_class}."
        f"{suffix}"
    )
