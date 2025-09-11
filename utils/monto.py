
"""Utilities for monetary calculations and text conversions."""

from decimal import Decimal, ROUND_HALF_UP, getcontext

getcontext().prec = 28

# Helper aliases and quantization constants
D = Decimal
Q8 = D("0.00000001")
Q4 = D("0.0001")
Q2 = D("0.01")
IVA_TASA = D("0.13")


def d8(value):
    """Return ``value`` quantized to 8 decimal places."""
    return D(str(value)).quantize(Q8, rounding=ROUND_HALF_UP)


def d2(value):
    """Return ``value`` quantized to 2 decimal places."""
    return D(str(value)).quantize(Q2, rounding=ROUND_HALF_UP)


def d4(value):
    """Return ``value`` quantized to 4 decimal places."""
    return D(str(value)).quantize(Q4, rounding=ROUND_HALF_UP)


def iva_item(base_gravada):
    """Return IVA amount for an item based on taxable base."""
    return d8(D(str(base_gravada)) * IVA_TASA)


def to_base_iva(total):
    """Return base and IVA portions for ``total`` with IVA included.

    The calculation mirrors the frontend ``toBaseIva`` helper and ensures
    consistency when separating a total that already contains IVA.  Results
    are quantized to 8 decimal places to avoid floating point artifacts.
    """

    total = D(str(total))
    base = d8(total / (D("1") + IVA_TASA))
    iva = d8(total - base)
    return base, iva


try:
    from num2words import num2words
except ImportError:  # pragma: no cover - fallback for environments without num2words
    def num2words(n, lang="es"):
        raise ImportError("num2words is required")


def monto_a_texto_sv(monto):
    """Convierte un monto a texto en formato fiscal salvadoreño.

    Acepta :class:`Decimal` o cualquier valor numérico convertible a
    ``Decimal``. El valor se redondea a 2 decimales utilizando ``ROUND_HALF_UP``
    para que montos con más de dos decimales se conviertan correctamente sin
    pérdidas de precisión.
    """

    monto = D(monto).quantize(Q2, rounding=ROUND_HALF_UP)
    entero = int(monto)
    centavos = int((monto - D(entero)) * 100)
    palabras = num2words(entero, lang="es").upper()
    return f"{palabras} {centavos:02d}/100 DÓLARES"

