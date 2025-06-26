try:
    from num2words import num2words
except Exception:  # pragma: no cover - fallback for environments without num2words
    def num2words(n, lang='es'):
        raise ImportError("num2words is required")


def monto_a_texto_sv(monto):
    """Convierte un monto a texto en formato fiscal salvadoreño."""
    entero = int(monto)
    centavos = int(round((monto - entero) * 100))
    palabras = num2words(entero, lang='es').upper()
    return f"{palabras} {centavos:02d}/100 DÓLARES"
