"""Metrics and aggregations used by the dashboard."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Dict, List

import pandas as pd

from .calculations import calcContribucion, calcMargenBruto, calcTicketPromedio, sortTopProducts


@dataclass
class KPIData:
    ventas: float
    transacciones: int
    ticket_promedio: float
    margen_bruto: float
    cmv: float


@dataclass
class DashboardData:
    df: pd.DataFrame
    kpis: KPIData
    daily: pd.DataFrame
    top_products: List[Dict[str, float]]
    channel_summary: pd.DataFrame
    stock_alerts: pd.DataFrame
    financial_report: pd.DataFrame


MARGIN_KEY = "margen"
CONTRIBUTION_KEY = "contribucion"


def compute_kpis(df: pd.DataFrame) -> KPIData:
    ventas = float(df["total"].sum()) if not df.empty else 0.0
    transacciones = int(len(df))
    cmv = float((df["unidades"] * df["costo_unit"]).sum()) if not df.empty else 0.0
    margen = calcMargenBruto(ventas, cmv)
    ticket = calcTicketPromedio(ventas, transacciones)
    return KPIData(ventas=ventas, transacciones=transacciones, ticket_promedio=ticket, margen_bruto=margen, cmv=cmv)


def _aggregate_product_metrics(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        columns = ["producto", "unidades", "ventas", MARGIN_KEY, CONTRIBUTION_KEY]
        return pd.DataFrame(columns=columns)
    grouped = (
        df.assign(margen=df["total"] - df["unidades"] * df["costo_unit"])
        .groupby("producto", as_index=False)
        .agg({"unidades": "sum", "total": "sum", "margen": "sum"})
    )
    grouped.rename(columns={"total": "ventas"}, inplace=True)
    grouped[CONTRIBUTION_KEY] = grouped.apply(
        lambda row: calcContribucion(row["margen"], row["ventas"]), axis=1
    )
    return grouped


def compute_top_products(df: pd.DataFrame, order_by: str) -> List[Dict[str, float]]:
    grouped = _aggregate_product_metrics(df)
    records = grouped.to_dict(orient="records")
    ordered = sortTopProducts(records, order_by)
    return ordered


def compute_daily_trend(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["fecha", "ventas", "transacciones", "ticket_promedio"])
    daily = (
        df.assign(fecha=df["fecha"].dt.date)
        .groupby("fecha", as_index=False)
        .agg({"total": "sum", "producto": "count", "unidades": "sum"})
    )
    daily.rename(columns={"total": "ventas", "producto": "transacciones"}, inplace=True)
    daily["ticket_promedio"] = daily.apply(
        lambda row: calcTicketPromedio(row["ventas"], int(row["transacciones"])), axis=1
    )
    return daily


def _prepare_channel_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(
            columns=["canal", "ventas", "transacciones", "ticket_promedio", MARGIN_KEY, CONTRIBUTION_KEY]
        )
    grouped = (
        df.assign(margen=df["total"] - df["unidades"] * df["costo_unit"])
        .groupby("canal", as_index=False)
        .agg({"total": "sum", "producto": "count", "unidades": "sum", "margen": "sum"})
    )
    grouped.rename(columns={"total": "ventas", "producto": "transacciones"}, inplace=True)
    grouped["ticket_promedio"] = grouped.apply(
        lambda row: calcTicketPromedio(row["ventas"], int(row["transacciones"])), axis=1
    )
    grouped[CONTRIBUTION_KEY] = grouped.apply(
        lambda row: calcContribucion(row["margen"], row["ventas"]), axis=1
    )
    return grouped


def compute_channel_summary(df: pd.DataFrame) -> pd.DataFrame:
    grouped = _prepare_channel_df(df)
    if grouped.empty:
        return grouped
    total_ventas = grouped["ventas"].sum()
    threshold = total_ventas * 0.03
    major = grouped[grouped["ventas"] >= threshold]
    minor = grouped[grouped["ventas"] < threshold]
    if not minor.empty:
        aggregated = {
            "canal": "Otros",
            "ventas": minor["ventas"].sum(),
            "transacciones": int(minor["transacciones"].sum()),
            "ticket_promedio": calcTicketPromedio(minor["ventas"].sum(), int(minor["transacciones"].sum())),
            MARGIN_KEY: minor[MARGIN_KEY].sum(),
        }
        aggregated[CONTRIBUTION_KEY] = calcContribucion(aggregated[MARGIN_KEY], aggregated["ventas"])
        major = pd.concat([major, pd.DataFrame([aggregated])], ignore_index=True)
    return major.sort_values(by="ventas", ascending=False).reset_index(drop=True)


def compute_stock_alerts(df: pd.DataFrame, max_stock: float = 5) -> pd.DataFrame:
    if df.empty or "stock" not in df.columns:
        return pd.DataFrame(columns=["producto", "stock", "rotacion_30d"])
    latest = (
        df.sort_values("fecha")
        .groupby("producto")
        .agg({"stock": "last"})
        .reset_index()
    )
    last_date = df["fecha"].max()
    start_30d = last_date - timedelta(days=30)
    last_month = df[df["fecha"] >= start_30d]
    rotation = (
        last_month.groupby("producto")["unidades"].sum().reset_index().rename(columns={"unidades": "rotacion_30d"})
    )
    merged = latest.merge(rotation, on="producto", how="left")
    merged["rotacion_30d"].fillna(0.0, inplace=True)
    alerts = merged[merged["stock"] <= max_stock]
    return alerts.sort_values(by=["stock", "producto"], ascending=[True, True]).reset_index(drop=True)


def compute_financial_report(df: pd.DataFrame) -> pd.DataFrame:
    columns = ["periodo", "ingresos", "gastos", "resultado"]
    if df.empty:
        return pd.DataFrame(columns=columns)
    report = (
        df.assign(
            periodo=df["fecha"].dt.normalize(),
            ingresos=df["total"],
            gastos=df["unidades"] * df["costo_unit"],
        )
        .groupby("periodo", as_index=False)
        .agg({"ingresos": "sum", "gastos": "sum"})
    )
    report["resultado"] = report["ingresos"] - report["gastos"]
    report["periodo"] = report["periodo"].dt.date
    totals = pd.DataFrame(
        {
            "periodo": ["Total"],
            "ingresos": [report["ingresos"].sum()],
            "gastos": [report["gastos"].sum()],
            "resultado": [report["resultado"].sum()],
        }
    )
    return pd.concat([report, totals], ignore_index=True)


def build_dashboard_data(df: pd.DataFrame, order_by: str) -> DashboardData:
    kpis = compute_kpis(df)
    daily = compute_daily_trend(df)
    top_products = compute_top_products(df, order_by)
    channel_summary = compute_channel_summary(df)
    stock_alerts = compute_stock_alerts(df)
    financial_report = compute_financial_report(df)
    return DashboardData(
        df=df,
        kpis=kpis,
        daily=daily,
        top_products=top_products,
        channel_summary=channel_summary,
        stock_alerts=stock_alerts,
        financial_report=financial_report,
    )
