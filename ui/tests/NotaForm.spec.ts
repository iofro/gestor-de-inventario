import { mount } from '@vue/test-utils';
import { describe, it, expect } from 'vitest';
import NotaForm from '../ventas/NotaForm.vue';

describe('NotaForm', () => {
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
    expect(cells[1].text()).toBe('100.00');
    expect(cells[4].text()).toBe('20.00');
    expect(cells[5].text()).toBe('120.00');
  });
});
