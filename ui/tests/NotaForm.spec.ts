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
      props: {
        factura: {
          numero: '1',
          cliente: 'A',
          total: 1000,
          ventas_gravadas: 1000,
          ventas_exentas: 0,
          ventas_no_sujetas: 0,
          iva: 0
        },
        tipo: 'credito'
      }
    });
    const radioMonto = wrapper.find('input[value="monto"]');
    await radioMonto.setValue();
    const input = wrapper.find('input[type="number"]');
    expect(input.attributes('title')).toContain('Monto');
  });

  it('prorratea monto global con prorratearGlobal', async () => {
    const wrapper = mount(NotaForm, {
      props: {
        factura: {
          numero: '1',
          cliente: 'A',
          total: 188,
          ventas_gravadas: 100,
          ventas_exentas: 50,
          ventas_no_sujetas: 25,
          iva: 13
        },
        tipo: 'credito'
      }
    });
    const radioMonto = wrapper.find('input[value="monto"]');
    await radioMonto.setValue();
    const input = wrapper.find('input[type="number"]');
    await input.setValue('18.8');
    await wrapper.vm.$nextTick();
    const cells = wrapper.findAll('tbody td');
    expect(cells[1].text()).toBe('10.00');
    expect(cells[2].text()).toBe('5.00');
    expect(cells[3].text()).toBe('2.50');
    expect(cells[4].text()).toBe('1.30');
    expect(cells[5].text()).toBe('18.80');
  });

  it('muestra badge rojo si excede saldo', async () => {
    const wrapper = mount(NotaForm, {
      props: {
        factura: {
          numero: '1',
          cliente: 'A',
          total: 100,
          ventas_gravadas: 100,
          ventas_exentas: 0,
          ventas_no_sujetas: 0,
          iva: 0
        },
        tipo: 'credito'
      }
    });
    const radioMonto = wrapper.find('input[value="monto"]');
    await radioMonto.setValue();
    const input = wrapper.find('input[type="number"]');
    await input.setValue('200');
    await wrapper.vm.$nextTick();
    expect(wrapper.find('.badge.rojo').exists()).toBe(true);
  });

  it('llama API tras validación sin motivo', async () => {
    const wrapper = mount(NotaForm, {
      props: {
        factura: {
          numero: '1',
          cliente: 'A',
          total: 1000,
          ventas_gravadas: 1000,
          ventas_exentas: 0,
          ventas_no_sujetas: 0,
          iva: 0
        },
        tipo: 'debito'
      }
    });
    const radioMonto = wrapper.find('input[value="monto"]');
    await radioMonto.setValue();
    const input = wrapper.find('input[type="number"]');
    await input.setValue('10');
    await wrapper.vm.$nextTick();
    const btn = wrapper.find('.resumen .acciones button');
    await btn.trigger('click');
    expect(api.previsualizarPdf).toHaveBeenCalled();
  });

  it('no llama API si total es cero', async () => {
    const wrapper = mount(NotaForm, {
      props: {
        factura: {
          numero: '1',
          cliente: 'A',
          total: 1000,
          ventas_gravadas: 1000,
          ventas_exentas: 0,
          ventas_no_sujetas: 0,
          iva: 0
        },
        tipo: 'debito'
      }
    });
    const radioMonto = wrapper.find('input[value="monto"]');
    await radioMonto.setValue();
    await wrapper.find('.resumen .acciones button').trigger('click');
    expect(api.previsualizarPdf).not.toHaveBeenCalled();
  });

  it('calcula totales para ítems en pestaña producto', async () => {
    const wrapper = mount(NotaForm, {
      props: {
        factura: {
          numero: '1',
          cliente: 'A',
          total: 1000,
          ventas_gravadas: 1000,
          ventas_exentas: 0,
          ventas_no_sujetas: 0,
          iva: 0
        },
        tipo: 'debito'
      }
    });
    const btnProducto = wrapper.findAll('.tabs button')[1];
    await btnProducto.trigger('click');
    wrapper.vm.ivaIncluido = false;
    wrapper.vm.items.push({
      id: 1,
      selected: false,
      codigo: 'A1',
      descripcion: 'Test',
      cantidadFacturada: 1,
      cantidadAjustar: 0,
      tipo: 'debito',
      modo: 'monto',
      valor: 100,
      ivaInc: false,
      afectacion: 'gravada',
      previas: 0,
      ajuste: 100,
      concepto: ''
    });
    await wrapper.vm.$nextTick();
    const resumen = wrapper.find('.resumen').text();
    expect(resumen).toContain('Base gravada: 100.00');
    expect(resumen).toContain('IVA: 13.00');
    expect(resumen).toContain('Total: 113.00');
  });
});
