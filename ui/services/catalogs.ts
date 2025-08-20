export const manualCatalogs = ['CAT-012','CAT-013','CAT-014','CAT-015','CAT-016','CAT-017'];

export const catalogs: Record<string, Record<string,string>> = {
  'CAT-001': { '00': 'Modo prueba', '01': 'Modo producción' },
  'CAT-002': {
    '01': 'Factura',
    '03': 'Comprobante de crédito fiscal',
    '04': 'Nota de remisión',
    '05': 'Nota de crédito',
    '06': 'Nota de débito',
    '07': 'Comprobante de retención',
    '08': 'Comprobante de liquidación',
    '09': 'Documento contable de liquidación',
    '11': 'Facturas de exportación',
    '14': 'Factura de sujeto excluido',
    '15': 'Comprobante de donación',
  },
  'CAT-003': { '1': 'Previo', '2': 'Diferido' },
  'CAT-004': { '1': 'Normal', '2': 'Contingencia' },
  'CAT-005': {
    '1': 'No disponibilidad de sistema del MH',
    '2': 'No disponibilidad de sistema del emisor',
    '3': 'Falla en servicio de Internet del emisor',
    '4': 'Falla en energía eléctrica del emisor',
    '5': 'Otro',
  },
  'CAT-006': {
    '19': 'IVA 13%',
    'A8': 'IVA 13%',
    '57': 'Renta',
    '90': 'IVA retenido',
    'D4': 'IEPES',
    'D5': 'IVA',
    '25': 'Fovial',
    'A6': 'CESC',
  },
  'CAT-007': {
    '01': 'Sucursal',
    '02': 'Casa Matriz',
    '04': 'Bodega',
    '07': 'Patio',
  },
  'CAT-008': {
    '1': 'Bienes',
    '2': 'Servicios',
    '3': 'Ambos',
    '4': 'Otros tributos por ítem',
  },
  'CAT-009': { '01': 'Días', '02': 'Meses', '03': 'Años' },
  'CAT-010': {
    '36': 'NIT',
    '13': 'DUI',
    '37': 'Otro',
    '03': 'Pasaporte',
    '02': 'Carnet de Residente',
    '00': 'Sin documento',
  },
  'CAT-016': { '1': 'contado', '2': 'crédito', '3': 'otras' },
  'CAT-017': {
    '01': 'Efectivo',
    '02': 'Cheque',
    '03': 'Transferencia',
    '04': 'Tarjeta',
  },
};

// Inicializa catálogos vacíos restantes hasta CAT-032
for (let i = 1; i <= 32; i++) {
  const key = `CAT-${String(i).padStart(3,'0')}`;
  catalogs[key] = catalogs[key] || {};
}

export const catalogPatterns: Record<string, RegExp> = {
  'CAT-012': /^\d{2}$/,
  'CAT-013': /^\d{3}$/,
  'CAT-014': /^[A-Z0-9]{1,5}$/,
  'CAT-015': /^\d{2}$/,
  'CAT-016': /^[1-3]$/,
  'CAT-017': /^\d{2}$/,
};

const maxLengths: Record<string, number> = {
  'CAT-012': 2,
  'CAT-013': 3,
  'CAT-014': 5,
  'CAT-015': 2,
  'CAT-016': 1,
  'CAT-017': 2,
};

export function getCatalog(id: string): Record<string,string> {
  return catalogs[id] || {};
}

export function validateCode(id: string, code: string): boolean {
  const cat = getCatalog(id);
  if (cat && Object.keys(cat).length && !manualCatalogs.includes(id)) {
    return Object.prototype.hasOwnProperty.call(cat, code);
  }
  const pattern = catalogPatterns[id];
  return pattern ? pattern.test(code) : true;
}

export function maxLengthFor(id: string): number {
  return maxLengths[id] || 10;
}
