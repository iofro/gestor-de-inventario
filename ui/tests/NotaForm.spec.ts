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
          tipo: '01',
          numero: '1',
          fecha: '2024-01-01',
          uuid: '1234567890abcdef',
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

  it('muestra datos de factura en encabezado', () => {
    const wrapper = mount(NotaForm, {
      props: {
        factura: {
          tipo: '01',
          numero: 'A-1',
          fecha: '2024-01-01',
          uuid: 'abcdef1234567890',
          cliente: 'Cliente'
        },
        tipo: 'credito'
      }
    });
    const inputs = wrapper.findAll('.factura-data input[readonly]');
    expect(inputs[0].element.value).toBe('01');
    expect(inputs[1].element.value).toBe('A-1');
    expect(inputs[2].element.value).toBe('2024-01-01');
    expect(inputs[3].element.value).toBe('abcdef12');
  });

  it('separa base e IVA cuando ivaIncluido está activo', async () => {
    const wrapper = mount(NotaForm, {
      props: {
        factura: { numero: '1', cliente: 'A', tipo: '01', fecha: '2024-01-01', uuid: 'abc', total: 0 },
        tipo: 'credito'
      }
    });
    const radioMonto = wrapper.find('input[value="monto"]');
    await radioMonto.setValue();
    const input = wrapper.find('input[type="number"]');
    await input.setValue('11.3');
    await wrapper.vm.$nextTick();
    const cells = wrapper.findAll('tbody td');
    expect(cells[1].text()).toBe('10.00');
    expect(cells[4].text()).toBe('1.30');
    expect(cells[5].text()).toBe('11.30');
  });

  it('interpreta monto como base cuando ivaIncluido está inactivo', async () => {
    const wrapper = mount(NotaForm, {
      props: {
        factura: { numero: '1', cliente: 'A', tipo: '01', fecha: '2024-01-01', uuid: 'abc', total: 0 },
        tipo: 'credito'
      }
    });
    const radioMonto = wrapper.find('input[value="monto"]');
    await radioMonto.setValue();
    const chk = wrapper.find('.nota-controls input[type="checkbox"]');
    await chk.setValue(false);
    const input = wrapper.find('input[type="number"]');
    await input.setValue('10');
    await wrapper.vm.$nextTick();
    const cells = wrapper.findAll('tbody td');
    expect(cells[1].text()).toBe('10.00');
    expect(cells[4].text()).toBe('1.30');
    expect(cells[5].text()).toBe('11.30');
  });

  it('muestra bloques de factura y nota y solo nota cambia', async () => {
    const wrapper = mount(NotaForm, {
      props: {
        factura: {
          tipo: '01',
          numero: '1',
          fecha: '2024-01-01',
          uuid: 'abc',
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
    const facturaTexto = wrapper.find('.factura-resumen').text();
    expect(facturaTexto).toContain('Base gravada: 1000.00');
    const radioMonto = wrapper.find('input[value="monto"]');
    await radioMonto.setValue();
    const chk = wrapper.find('.nota-controls input[type="checkbox"]');
    await chk.setValue(false);
    const input = wrapper.find('input[type="number"]');
    await input.setValue('10');
    await wrapper.vm.$nextTick();
    const notaTexto = wrapper.find('.nota-resumen').text();
    expect(notaTexto).toContain('Base gravada: 10.00');
    expect(wrapper.find('.factura-resumen').text()).toBe(facturaTexto);
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

  it('muestra badge si créditos por producto exceden saldo', async () => {
    const wrapper = mount(NotaForm, {
      props: {
        factura: {
          numero: '1',
          cliente: 'A',
          total: 50,
          ventas_gravadas: 50,
          ventas_exentas: 0,
          ventas_no_sujetas: 0,
          iva: 0
        },
        tipo: 'debito'
      }
    });
    const btnProducto = wrapper.findAll('.tabs button')[1];
    await btnProducto.trigger('click');
    wrapper.vm.items.push({
      id: 1,
      selected: false,
      codigo: 'A1',
      descripcion: 'Test',
      cantidadFacturada: 1,
      cantidadAjustar: 0,
      tipo: 'credito',
      modo: 'monto',
      valor: 0,
      ivaInc: false,
      afectacion: 'gravada',
      previas: 0,
      ajuste: 60,
      concepto: ''
    });
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
    const btn = wrapper.find('.nota-resumen .acciones button');
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
    await wrapper.find('.nota-resumen .acciones button').trigger('click');
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
    const resumen = wrapper.find('.nota-resumen').text();
    expect(resumen).toContain('Base gravada: 100.00');
    expect(resumen).toContain('IVA: 13.00');
    expect(resumen).toContain('Total: 113.00');
  });
});
