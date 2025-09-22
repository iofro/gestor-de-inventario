"""CLI to compare line calculations between Venta and DTE.

Run with::

    python tools/venta_vs_dte_debug.py <venta_id> --db path/to/db
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Ensure repository root is on sys.path when executed directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db import DB  # type: ignore  # noqa: E402
from inventory_manager import InventoryManager  # type: ignore  # noqa: E402
from utils.doc_generation import log_venta_vs_dte  # type: ignore  # noqa: E402
from paths import DEFAULT_DB_PATH  # type: ignore  # noqa: E402

DEFAULT_DB_HELP = str(DEFAULT_DB_PATH)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Log line-by-line comparison between Venta and DTE calculations"
    )
    parser.add_argument("venta_id", type=int, help="ID de la venta a inspeccionar")
    parser.add_argument(
        "--db",
        dest="db_path",
        default=None,
        help=f"Ruta al archivo de base de datos (por defecto {DEFAULT_DB_HELP})",
    )
    parser.add_argument(
        "--level",
        default="INFO",
        help="Nivel de logging (INFO o DEBUG)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=getattr(logging, args.level.upper(), logging.INFO))
    db = DB(args.db_path)
    manager = InventoryManager(db=db)
    log_venta_vs_dte(manager, args.venta_id)


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    main()
