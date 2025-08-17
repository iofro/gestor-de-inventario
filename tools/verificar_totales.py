"""Utilities to verify DTE totals and environment codes."""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dte import calcular_resumen

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config_negocio.json"


def _load_expected_ambiente() -> str:
    """Return "01" for production or "00" for tests based on config."""
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return "01" if data.get("ambiente") == "produccion" else "00"
    except Exception:
        return "00"


def check_document(data: dict, expected_ambiente: str | None = None) -> List[str]:
    """Return a list of inconsistencies found in ``data``.

    The function verifies monetary totals using :func:`dte.calcular_resumen` and
    ensures that ``identificacion.ambiente`` matches ``expected_ambiente``.
    """

    errors: List[str] = []
    ident = data.get("identificacion", {})
    if expected_ambiente is None:
        expected_ambiente = _load_expected_ambiente()
    if ident.get("ambiente") != expected_ambiente:
        errors.append(
            f"identificacion.ambiente {ident.get('ambiente')} != {expected_ambiente}"
        )

    cuerpo = data.get("cuerpoDocumento", [])
    items_total = Decimal("0")
    iva_total = Decimal("0")
    for item in cuerpo:
        cant = Decimal(str(item.get("cantidad") or 0))
        precio = Decimal(
            str(item.get("precioUnitario") or item.get("precioUni") or 0)
        )
        items_total += cant * precio
        iva_item = Decimal(str(item.get("montoIva") or item.get("iva") or 0))
        iva_total += iva_item

    resumen = data.get("resumen", {})
    venta = {"total": resumen.get("totalPagar"), "total_letras": resumen.get("totalLetras", "")}
    fiscal = {
        "descuentos": resumen.get("totalDescu", 0),
        "iva": iva_total,
        "ventas_no_sujetas": resumen.get("totalNoSuj", 0),
        "ventas_exentas": resumen.get("totalExenta", 0),
    }
    extra = {
        "pagos": resumen.get("pagos"),
        "tributos": resumen.get("tributos"),
        "numPagoElectronico": resumen.get("numPagoElectronico"),
    }
    expected = calcular_resumen(
        items_total,
        venta,
        fiscal=fiscal,
        extra=extra,
        tipo_dte=ident.get("tipoDte", "01"),
    )

    compare_keys = [
        "totalGravada",
        "subTotalVentas",
        "totalDescu",
        "subTotal",
        "montoTotalOperacion",
        "totalPagar",
    ]
    for key in compare_keys:
        val = Decimal(str(resumen.get(key, 0)))
        exp = Decimal(str(expected.get(key, 0)))
        if abs(val - exp) > Decimal("0.01"):
            errors.append(f"{key} {val} != {exp}")

    return errors


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Verifica totales y ambiente de documentos DTE"
    )
    parser.add_argument("paths", nargs="+", help="Rutas a archivos JSON a validar")
    args = parser.parse_args()
    ambiente = _load_expected_ambiente()
    any_errors = False
    for path_str in args.paths:
        path = Path(path_str)
        data = json.loads(path.read_text(encoding="utf-8"))
        errors = check_document(data, ambiente)
        if errors:
            any_errors = True
            print(f"{path}:")
            for err in errors:
                print(f" - {err}")
    if not any_errors:
        print("Todos los documentos son consistentes")


if __name__ == "__main__":
    main()
