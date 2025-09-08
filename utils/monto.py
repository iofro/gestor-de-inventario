
"""Utilities for monetary calculations and text conversions."""

from decimal import Decimal, ROUND_HALF_UP, getcontext

getcontext().prec = 28

D = Decimal
Q8 = D("0.00000001")
Q2 = D("0.01")
IVA_TASA = D("0.13")


def d8(value):
    """Return value quantized to 8 decimal places."""
    return D(value).quantize(Q8, rounding=ROUND_HALF_UP)


def d2(value):
    """Return value quantized to 2 decimal places."""
    return D(value).quantize(Q2, rounding=ROUND_HALF_UP)


def iva_item(base_gravada):
    """Return IVA amount for an item based on taxable base."""
    return d8(D(base_gravada) * IVA_TASA)


try:
    from num2words import num2words
except ImportError:  # pragma: no cover - fallback for environments without num2words
    def num2words(n, lang="es"):
        raise ImportError("num2words is required")


def monto_a_texto_sv(monto):
    """Convierte un monto a texto en formato fiscal salvadoreño."""
    entero = int(monto)
    centavos = int(round((monto - entero) * 100))
    palabras = num2words(entero, lang="es").upper()
    return f"{palabras} {centavos:02d}/100 DÓLARES"

