import { describe, it, expect } from 'vitest';
import { prorratearGlobal } from '../services/prorrateo';

describe('prorratearGlobal', () => {
  const factura = {
    ventas_gravadas: 100,
    ventas_exentas: 50,
    ventas_no_sujetas: 25,
    iva: 20,
  };

  it('prorratea según porcentaje', () => {
    const res = prorratearGlobal(factura, { porcentaje: 10 });
    expect(res.ventas_gravadas).toBeCloseTo(10);
    expect(res.ventas_exentas).toBeCloseTo(5);
    expect(res.ventas_no_sujetas).toBeCloseTo(2.5);
    expect(res.iva).toBeCloseTo(2);
    expect(res.total).toBeCloseTo(19.5);
  });

  it('prorratea según monto', () => {
    const res = prorratearGlobal(factura, { monto: 19.5 });
    expect(res.ventas_gravadas).toBeCloseTo(10);
    expect(res.iva).toBeCloseTo(2);
    expect(res.total).toBeCloseTo(19.5);
  });
});

