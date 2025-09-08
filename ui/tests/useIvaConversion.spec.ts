import { describe, it, expect } from 'vitest';
import { toBaseIva, fromBaseIva } from '../services/useIvaConversion';

describe('useIvaConversion', () => {
  it('convierte total a base e iva', () => {
    const { base, iva } = toBaseIva(113);
    expect(base).toBe(100);
    expect(iva).toBe(13);
  });

  it('convierte base a total e iva', () => {
    const { total, iva } = fromBaseIva(100);
    expect(total).toBe(113);
    expect(iva).toBe(13);
  });
});
