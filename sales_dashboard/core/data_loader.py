"""Utilities for loading and preparing sales data."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd

REQUIRED_COLUMNS = {"fecha", "producto", "canal", "unidades", "precio_unit", "costo_unit"}


@dataclass
class SalesDataset:
    """Container for the loaded sales DataFrame and metadata."""

    raw: pd.DataFrame

    @property
    def is_empty(self) -> bool:
        return self.raw.empty


class DataValidationError(Exception):
    """Raised when the dataset is missing required fields."""


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    normalized = df.copy()
    normalized.columns = [c.strip().lower() for c in normalized.columns]
    if "canal" not in normalized.columns and "vendedor" in normalized.columns:
        normalized.rename(columns={"vendedor": "canal"}, inplace=True)
    if "total" not in normalized.columns:
        normalized["total"] = normalized["unidades"].astype(float) * normalized["precio_unit"].astype(float)
    normalized["fecha"] = pd.to_datetime(normalized["fecha"], errors="coerce")
    normalized["unidades"] = normalized["unidades"].astype(float)
    normalized["precio_unit"] = normalized["precio_unit"].astype(float)
    normalized["costo_unit"] = normalized["costo_unit"].astype(float)
    normalized["total"] = normalized["total"].astype(float)
    return normalized


def load_sales_data(path: Path | str | pd.DataFrame) -> SalesDataset:
    """Load sales information from a CSV file or DataFrame."""
    if isinstance(path, pd.DataFrame):
        df = path.copy()
    else:
        df = pd.read_csv(path)
    normalized = _normalize_columns(df)
    missing = REQUIRED_COLUMNS - set(normalized.columns)
    if missing:
        raise DataValidationError(f"Faltan columnas requeridas: {', '.join(sorted(missing))}")
    normalized = normalized.dropna(subset=["fecha", "producto"])
    normalized["fecha"] = normalized["fecha"].dt.tz_localize(None)
    return SalesDataset(raw=normalized)


def filter_by_period(dataset: SalesDataset, start: Optional[datetime], end: Optional[datetime]) -> pd.DataFrame:
    """Filter the dataset by a period inclusive of start and end dates."""
    df = dataset.raw
    if start is not None:
        df = df[df["fecha"] >= start]
    if end is not None:
        df = df[df["fecha"] <= end]
    return df.copy()
