import { mount } from '@vue/test-utils';
import { describe, it, expect, vi } from 'vitest';
import NotaForm from '../ventas/NotaForm.vue';

vi.mock('../services/notasApi', () => ({
  previsualizarPdf: vi.fn().mockResolvedValue({}),
  previsualizarJson: vi.fn().mockResolvedValue({}),
  guardarBorrador: vi.fn().mockResolvedValue({}),
  firmarTransmitir: vi.fn().mockResolvedValue({}),
}));

const api = await import('../services/notasApi');

describe('NotaForm', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('cambia input según modo', async () => {
    const wrapper = mount(NotaForm, {
      props: { factura: { numero: '1', cliente: 'A', total: 1000 }, tipo: 'credito' }
    });
    const radioMonto = wrapper.find('input[value="monto"]');
    await radioMonto.setValue();
    const input = wrapper.find('input[type="number"]');
    expect(input.attributes('title')).toContain('Monto');
  });

  it('descompone IVA incluido con toBaseIva', async () => {
    const wrapper = mount(NotaForm, {
      props: { factura: { numero: '1', cliente: 'A', total: 0 }, tipo: 'credito' }
    });
    const radioMonto = wrapper.find('input[value="monto"]');
    await radioMonto.setValue();
    const input = wrapper.find('input[type="number"]');
    await input.setValue('120');
    await wrapper.vm.$nextTick();
    const cells = wrapper.findAll('tbody td');
    expect(cells[1].text()).toBe('106.19');
    expect(cells[4].text()).toBe('13.81');
    expect(cells[5].text()).toBe('120.00');
  });

  it('muestra badge rojo si excede saldo', async () => {
    const wrapper = mount(NotaForm, {
      props: { factura: { numero: '1', cliente: 'A', total: 100 }, tipo: 'credito' }
    });
    const radioMonto = wrapper.find('input[value="monto"]');
    await radioMonto.setValue();
    const input = wrapper.find('input[type="number"]');
    await input.setValue('200');
    await wrapper.vm.$nextTick();
    expect(wrapper.find('.badge.rojo').exists()).toBe(true);
  });

  it('llama API tras validación', async () => {
    const wrapper = mount(NotaForm, {
      props: { factura: { numero: '1', cliente: 'A', total: 1000 }, tipo: 'debito' }
    });
    const radioMonto = wrapper.find('input[value="monto"]');
    await radioMonto.setValue();
    const input = wrapper.find('input[type="number"]');
    await input.setValue('10');
    const motivo = wrapper.find('input[placeholder="Motivo"]');
    await motivo.setValue('ajuste');
    await wrapper.vm.$nextTick();
    const btn = wrapper.find('.resumen .acciones button');
    await btn.trigger('click');
    expect(api.previsualizarPdf).toHaveBeenCalled();
  });

  it('no llama API si validación falla', async () => {
    const wrapper = mount(NotaForm, {
      props: { factura: { numero: '1', cliente: 'A', total: 1000 }, tipo: 'debito' }
    });
    const radioMonto = wrapper.find('input[value="monto"]');
    await radioMonto.setValue();
    const input = wrapper.find('input[type="number"]');
    await input.setValue('10');
    await wrapper.find('.resumen .acciones button').trigger('click');
    expect(api.previsualizarPdf).not.toHaveBeenCalled();
  });
});
