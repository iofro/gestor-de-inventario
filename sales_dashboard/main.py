"""Entry point for the standalone sales dashboard."""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from PyQt5.QtWidgets import QApplication

from .core.controller import DashboardController
from .core.data_loader import DataValidationError, load_sales_data
from .ui import SalesDashboardWindow


def _infer_timezone(tz_name: str | None) -> str:
    if tz_name:
        return tz_name
    try:
        local_zone = datetime.now().astimezone().tzinfo
        if isinstance(local_zone, ZoneInfo):
            return local_zone.key
        return str(local_zone)
    except Exception:  # pragma: no cover - fallback for unusual environments
        return "UTC"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Panel de estadísticas de venta")
    parser.add_argument(
        "dataset",
        nargs="?",
        default="sample_data.csv",
        help="Ruta al CSV con los datos de ventas.",
    )
    parser.add_argument(
        "--timezone",
        dest="timezone",
        default=None,
        help="Nombre de zona horaria para mostrar en la interfaz.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        dataset = load_sales_data(args.dataset)
    except DataValidationError as exc:
        sys.stderr.write(f"Error al cargar datos: {exc}\n")
        return 1
    tz_label = _infer_timezone(args.timezone)
    controller = DashboardController(dataset, tz_name=tz_label)

    app = QApplication(sys.argv)
    window = SalesDashboardWindow(controller)
    window.show()
    return app.exec_()


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
