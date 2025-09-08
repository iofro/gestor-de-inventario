import { mount } from '@vue/test-utils';
import { vi } from 'vitest';
import EditableNotaTable from '../components/EditableNotaTable.vue';

describe('EditableNotaTable', () => {
  it('agrega item cuando se hace click', async () => {
    const originalPrompt = global.prompt;
    global.prompt = vi
      .fn()
      .mockReturnValueOnce('A1')
      .mockReturnValueOnce('Desc')
      .mockReturnValueOnce('1')
      .mockReturnValueOnce('10')
      .mockReturnValueOnce('UND')
      .mockReturnValueOnce('Concepto');
    const wrapper = mount(EditableNotaTable, {
      props: { modelValue: [], topeCredito: 10, ivaIncluido: true, notaTipo: 'debito' }
    });
    await wrapper.find('button.add-item').trigger('click');
    global.prompt = originalPrompt;
    const emitted = wrapper.emitted('update:modelValue');
    expect(emitted).toBeTruthy();
    expect(emitted![0][0]).toHaveLength(1);
  });

  it('filtra por código o descripción', async () => {
    const wrapper = mount(EditableNotaTable, {
      props: {
        modelValue: [
          { id: 1, selected: false, codigo: 'A1', descripcion: 'Test', cantidadFacturada: 1, cantidadAjustar: 0, tipo: 'debito', modo: 'monto', valor: 0, ivaInc: false, afectacion: 'gravada', previas: 0, ajuste: 0, concepto: '' }
        ],
        ivaIncluido: true,
        notaTipo: 'debito'
      }
    });
    expect(wrapper.findAll('tbody tr')).toHaveLength(1);
    await wrapper.find('input[placeholder="Buscar"]').setValue('no existe');
    expect(wrapper.findAll('tbody tr')).toHaveLength(0);
  });

  it('marca error si crédito excede saldo por línea', async () => {
    const wrapper = mount(EditableNotaTable, {
      props: {
        modelValue: [
          { id: 1, selected: false, codigo: 'A1', descripcion: 'Test', cantidadFacturada: 5, cantidadAjustar: 0, tipo: 'credito', modo: 'monto', valor: 0, ivaInc: false, afectacion: 'gravada', previas: 3, ajuste: 0, concepto: '' }
        ],
        topeCredito: 10,
        ivaIncluido: true,
        notaTipo: 'debito'
      }
    });
    const input = wrapper.find('tbody tr input[type="number"]');
    await input.setValue('3');
    await wrapper.vm.$nextTick();
    expect(wrapper.find('span.error').text()).toBe('Excede');
  });

  it('marca error si monto de crédito excede disponible', async () => {
    const wrapper = mount(EditableNotaTable, {
      props: {
        modelValue: [
          {
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
            ajuste: 0,
            concepto: '',
            maxMonto: 5
          }
        ],
        topeCredito: 10,
        ivaIncluido: true,
        notaTipo: 'debito'
      }
    });
    const ajuste = wrapper.find('input.ajuste');
    await ajuste.setValue('6');
    await wrapper.vm.$nextTick();
    expect(wrapper.find('span.error').text()).toBe('Excede');
  });

  it('rechaza ajuste negativo en notas de débito', async () => {
    const wrapper = mount(EditableNotaTable, {
      props: {
        modelValue: [
          {
            id: 1,
            selected: false,
            codigo: 'A1',
            descripcion: 'Test',
            cantidadFacturada: 1,
            cantidadAjustar: 0,
            tipo: 'debito',
            modo: 'monto',
            valor: 0,
            ivaInc: false,
            afectacion: 'gravada',
            previas: 0,
            ajuste: 0,
            concepto: ''
          }
        ],
        ivaIncluido: true,
        notaTipo: 'debito'
      }
    });
    const ajuste = wrapper.find('input.ajuste');
    await ajuste.setValue('-5');
    await wrapper.vm.$nextTick();
    // @ts-expect-error accessing internal state for test
    expect(wrapper.vm.items[0].ajuste).toBe(0);
  });

  it('actualiza base, IVA y total según ivaIncluido', async () => {
    const wrapper = mount(EditableNotaTable, {
      props: {
        modelValue: [
          { id: 1, selected: false, codigo: 'A1', descripcion: 'Test', cantidadFacturada: 1, cantidadAjustar: 0, tipo: 'debito', modo: 'monto', valor: 0, ivaInc: false, afectacion: 'gravada', previas: 0, ajuste: 0, concepto: '' }
        ],
        ivaIncluido: true,
        notaTipo: 'debito'
      }
    });
    const ajusteInput = wrapper.find('input.ajuste');
    await ajusteInput.setValue('120');
    await wrapper.vm.$nextTick();
    let cells = wrapper.findAll('tbody td');
    expect(cells[11].text()).toBe('100.00');
    expect(cells[12].text()).toBe('20.00');
    expect(cells[13].text()).toBe('120.00');
    await wrapper.setProps({ ivaIncluido: false });
    await ajusteInput.setValue('100');
    await wrapper.vm.$nextTick();
    cells = wrapper.findAll('tbody td');
    expect(cells[11].text()).toBe('100.00');
    expect(cells[12].text()).toBe('20.00');
    expect(cells[13].text()).toBe('120.00');
  });
});
