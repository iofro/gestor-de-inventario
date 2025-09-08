import { mount } from '@vue/test-utils';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import NotaForm from '../ventas/NotaForm.vue';

vi.mock('../services/notasApi', () => ({
  previsualizarPdf: vi.fn().mockResolvedValue({}),
  previsualizarJson: vi.fn().mockResolvedValue({}),
  guardarBorrador: vi.fn().mockResolvedValue({}),
  firmarTransmitir: vi.fn().mockResolvedValue({}),
}));

const api = await import('../services/notasApi');

const baseNota = {
  id: '1',
  baseGravada: 10,
  exenta: 0,
  noSujeta: 0,
  iva: 1.3,
  total: 11.3,
  totalLetras: 'once',
  documentoRelacionado: 'F001',
  credito: 50,
};

describe('NotaForm', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('muestra badge rojo si el crédito excede el saldo', () => {
    const wrapper = mount(NotaForm, {
      props: { nota: { ...baseNota, credito: 150 }, saldoDisponible: 100 },
    });
    const badge = wrapper.find('.badge');
    expect(badge.classes()).toContain('red');
  });

  it('no llama API si la validación falla', async () => {
    const wrapper = mount(NotaForm, {
      props: { nota: { ...baseNota, credito: 150 }, saldoDisponible: 100 },
    });
    await wrapper.find('button').trigger('click');
    expect(api.previsualizarPdf).not.toHaveBeenCalled();
  });

  it('llama previsualizarJson cuando es válido', async () => {
    const wrapper = mount(NotaForm, {
      props: { nota: baseNota, saldoDisponible: 100 },
    });
    await wrapper.findAll('button')[1].trigger('click');
    expect(api.previsualizarJson).toHaveBeenCalledWith('1');
  });
});
