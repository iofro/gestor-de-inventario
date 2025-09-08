import { describe, it, expect } from 'vitest';
import { sanitizeDocs } from '../services/sanitize';

describe('sanitizeDocs', () => {
  it('limpia NIT y numDocumento', () => {
    const data = { nit: '0614-123456-001-1', receptor: { numDocumento: '0123 45678-9' } };
    const clean = sanitizeDocs(data);
    expect(clean.nit).toBe('06141234560011');
    expect(clean.receptor.numDocumento).toBe('0123456789');
  });
});
