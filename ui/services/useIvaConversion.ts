/**
 * Utilidades para convertir montos con IVA del 13%.
 *
 * - Cuando un precio tiene `ivaIncluido = true`, usa `toBaseIva` para separar
 *   el total en base imponible e impuesto.
 * - Cuando `ivaIncluido = false`, parte de la base con `fromBaseIva` para
 *   obtener el total con IVA.
 */
const IVA_FACTOR = 1.13;
const IVA_RATE = IVA_FACTOR - 1;

function roundHalfUp(value: number, decimals = 2): number {
  const factor = Math.pow(10, decimals);
  return (Math.sign(value) * Math.round(Math.abs(value) * factor + Number.EPSILON)) / factor;
}

/**
 * Convierte un monto con `ivaIncluido = true` en base imponible e IVA.
 */
export function toBaseIva(total: number): { base: number; iva: number } {
  const base = roundHalfUp(total / IVA_FACTOR, 2);
  const iva = roundHalfUp(base * IVA_RATE, 2);
  return { base, iva };
}

/**
 * Convierte una base imponible con `ivaIncluido = false` al total con IVA.
 */
export function fromBaseIva(base: number): { total: number; iva: number } {
  const iva = roundHalfUp(base * IVA_RATE, 2);
  const total = roundHalfUp(base + iva, 2);
  return { total, iva };
}
