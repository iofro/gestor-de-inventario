import { describe, it, expect } from 'vitest';
import { toBaseIva, fromBaseIva } from '../services/useIvaConversion';

describe('useIvaConversion', () => {
  it('convierte total a base e iva', () => {
    const { base, iva } = toBaseIva(120);
    expect(base).toBe(100);
    expect(iva).toBe(20);
  });

  it('convierte base a total e iva', () => {
    const { total, iva } = fromBaseIva(100);
    expect(total).toBe(120);
    expect(iva).toBe(20);
  });
});
