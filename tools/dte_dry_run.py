"""Quick development script to verify DTE rounding logic.

This script builds a minimal DTE in-memory with one item
(cantidad=2.5, precio=9.54) and prints the intermediate
calculations using utilities from :mod:`utils.monto` and
:func:`dte.calcular_resumen`.

It is intended for local dry runs only.  No signing or API calls
are performed.  Run with::

    python tools/dte_dry_run.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure parent directory is on ``sys.path`` for local execution
sys.path.append(str(Path(__file__).resolve().parents[1]))

from utils.monto import D, d8, d2, iva_item
from dte import calcular_resumen


def main() -> None:
    # Build item values
    cantidad = D("2.5")
    precio = D("9.54")

    venta = d8(cantidad * precio)
    monto_iva = iva_item(venta)

    # Build summary using existing helper
    resumen_calc = calcular_resumen(
        venta, {"total": venta + monto_iva}, fiscal={"iva": monto_iva}
    )

    resumen = {
        "totalGravada": f"{d2(resumen_calc['totalGravada']):.2f}",
        "montoIva": f"{d2(resumen_calc.get('totalIva', resumen_calc.get('ivaPerci1', 0))):.2f}",
        "totalPagar": f"{d2(resumen_calc['totalPagar']):.2f}",
    }

    print("Ítem: venta=", venta)
    print("Ítem: montoIva=", monto_iva)
    print("Resumen:", resumen)

    # Local asserts
    assert str(venta) == "23.85000000"
    assert str(monto_iva) == "3.10050000"
    assert resumen["totalGravada"] == "23.85"
    assert resumen["montoIva"] == "3.10"
    assert resumen["totalPagar"] == "26.95"


if __name__ == "__main__":
    main()
