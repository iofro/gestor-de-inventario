from decimal import Decimal, ROUND_HALF_UP

try:
    from num2words import num2words
except ImportError:  # pragma: no cover - fallback for environments without num2words
    def num2words(n, lang='es'):
        raise ImportError("num2words is required")


def monto_a_texto_sv(monto):
    """Convierte un monto a texto en formato fiscal salvadoreño."""
    entero = int(monto)
    centavos = int(round((monto - entero) * 100))
    palabras = num2words(entero, lang='es').upper()
    return f"{palabras} {centavos:02d}/100 DÓLARES"


def d2(value):
    """Redondea ``value`` a 2 decimales usando ``ROUND_HALF_UP``."""
    if value is None:
        value = 0
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
