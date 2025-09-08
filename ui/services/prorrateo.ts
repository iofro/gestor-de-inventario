export interface FacturaResumen {
  ventas_gravadas?: number;
  ventas_exentas?: number;
  ventas_no_sujetas?: number;
  iva?: number;
}

export interface ProrrateoResultado {
  ventas_gravadas: number;
  ventas_exentas: number;
  ventas_no_sujetas: number;
  iva: number;
  total: number;
}

export function prorratearGlobal(
  factura: FacturaResumen,
  ajuste: { monto?: number; porcentaje?: number }
): ProrrateoResultado {
  const gravada = factura.ventas_gravadas ?? 0;
  const exenta = factura.ventas_exentas ?? 0;
  const noSujeta = factura.ventas_no_sujetas ?? 0;
  const iva = factura.iva ?? 0;
  const totalFactura = gravada + exenta + noSujeta + iva;

  let ratio: number | undefined;
  if (ajuste.porcentaje != null) {
    ratio = ajuste.porcentaje / 100;
  } else if (ajuste.monto != null) {
    ratio = totalFactura > 0 ? ajuste.monto / totalFactura : 0;
  }
  if (ratio == null || ratio < 0) {
    throw new Error('Debe especificar un monto o porcentaje válido');
  }

  const gravadaRes = gravada * ratio;
  const exentaRes = exenta * ratio;
  const noSujetaRes = noSujeta * ratio;
  const ivaRes = iva * ratio;
  const totalRes = gravadaRes + exentaRes + noSujetaRes + ivaRes;

  return {
    ventas_gravadas: gravadaRes,
    ventas_exentas: exentaRes,
    ventas_no_sujetas: noSujetaRes,
    iva: ivaRes,
    total: totalRes,
  };
}

