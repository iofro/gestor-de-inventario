from decimal import Decimal as D

from .monto import d8, IVA_TASA

def compute_line_totals(quantity, unit_price_iva, discount=D('0'), discount_type='$', iva_rate=IVA_TASA):
    """Compute monetary values for a sale line.

    Parameters
    ----------
    quantity: Decimal or convertible
        Quantity of items.
    unit_price_iva: Decimal or convertible
        Unit price **including** IVA.
    discount: Decimal or convertible
        Discount value. Interpreted as percentage when ``discount_type`` is
        "%". Any negative discount is treated as ``0``.
    discount_type: str
        Either "%" for percentage or "$" for absolute amount.
    iva_rate: Decimal
        IVA rate to apply. Use ``0`` for exenta/no sujeta lines.

    Returns
    -------
    dict
        Dictionary with keys ``bruto``, ``desc_con_iva``, ``total_con_iva``,
        ``base``, ``iva`` and ``unit_con_iva_efectivo``. All values are
        quantized to 8 decimal places using ``ROUND_HALF_UP``.
    """
    q = D(str(quantity))
    p = D(str(unit_price_iva))
    if q <= 0:
        q = D('0')
    bruto = d8(q * p)

    desc = D(str(discount))
    if desc < 0:
        desc = D('0')
    if discount_type == '%':
        desc_val = d8(bruto * desc / D('100'))
    else:
        desc_val = d8(desc)
    if desc_val > bruto:
        desc_val = bruto
    total = d8(bruto - desc_val)
    if iva_rate and iva_rate != 0:
        base = d8(total / (D('1') + D(str(iva_rate))))
    else:
        base = total
    iva = d8(total - base)
    unit_con_iva_efectivo = d8(total / q) if q != 0 else D('0')
    return {
        'bruto': bruto,
        'desc_con_iva': desc_val,
        'total_con_iva': total,
        'base': base,
        'iva': iva,
        'unit_con_iva_efectivo': unit_con_iva_efectivo,
    }
