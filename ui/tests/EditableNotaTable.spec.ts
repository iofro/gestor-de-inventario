import { mount } from '@vue/test-utils';
import EditableNotaTable from '../components/EditableNotaTable.vue';

describe('EditableNotaTable', () => {
  it('agrega item cuando se selecciona un producto', async () => {
    const wrapper = mount(EditableNotaTable, {
      props: { modelValue: [], topeCredito: 10, ivaIncluido: true, notaTipo: 'debito' }
    });
    await wrapper.find('button.add-item').trigger('click');
    await wrapper.find('.product-option').trigger('click');
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
    await ajusteInput.setValue('113');
    await wrapper.vm.$nextTick();
    let cells = wrapper.findAll('tbody td');
    expect(cells[12].text()).toBe('100.0000');
    expect(cells[13].text()).toBe('13.0000');
    expect(cells[14].text()).toBe('113.0000');
    await wrapper.setProps({ ivaIncluido: false });
    await ajusteInput.setValue('100');
    await wrapper.vm.$nextTick();
    cells = wrapper.findAll('tbody td');
    expect(cells[12].text()).toBe('100.0000');
    expect(cells[13].text()).toBe('13.0000');
    expect(cells[14].text()).toBe('113.0000');
  });

  it('coloca la cantidad en cero cuando se ingresa un ajuste de precio', async () => {
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

    const ajusteInput = wrapper.find('input.ajuste');
    await ajusteInput.setValue('10');
    await wrapper.vm.$nextTick();

    const cantidadInput = wrapper.find('input.cantidad-ajuste');
    expect((cantidadInput.element as HTMLInputElement).value).toBe('0');
    expect((cantidadInput.element as HTMLInputElement).disabled).toBe(true);
    // @ts-expect-error accessing internal state for test
    expect(wrapper.vm.items[0].ajusteCantidad).toBe(false);
  });

  it('coloca el ajuste de precio en cero cuando se modifica la cantidad', async () => {
    const wrapper = mount(EditableNotaTable, {
      props: {
        modelValue: [
          {
            id: 1,
            selected: false,
            codigo: 'A1',
            descripcion: 'Test',
            cantidadFacturada: 5,
            cantidadAjustar: 0,
            tipo: 'credito',
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
        notaTipo: 'credito'
      }
    });

    const cantidadInput = wrapper.find('input.cantidad-ajuste');
    await cantidadInput.setValue('2');
    await wrapper.vm.$nextTick();

    const ajusteInput = wrapper.find('input.ajuste');
    expect((ajusteInput.element as HTMLInputElement).value).toBe('0');
    expect((ajusteInput.element as HTMLInputElement).disabled).toBe(true);
    // @ts-expect-error accessing internal state for test
    expect(wrapper.vm.items[0].ajusteCantidad).toBe(true);
  });

  it('permite reactivar ambos ajustes cuando regresan a cero', async () => {
    const wrapper = mount(EditableNotaTable, {
      props: {
        modelValue: [
          {
            id: 1,
            selected: false,
            codigo: 'A1',
            descripcion: 'Test',
            cantidadFacturada: 5,
            cantidadAjustar: 0,
            tipo: 'credito',
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
        notaTipo: 'credito'
      }
    });

    const cantidadInput = wrapper.find('input.cantidad-ajuste');
    await cantidadInput.setValue('3');
    await wrapper.vm.$nextTick();
    expect((wrapper.find('input.ajuste').element as HTMLInputElement).value).toBe('0');
    expect((wrapper.find('input.ajuste').element as HTMLInputElement).disabled).toBe(true);

    await cantidadInput.setValue('0');
    await wrapper.vm.$nextTick();
    expect((wrapper.find('input.ajuste').element as HTMLInputElement).disabled).toBe(false);

    await wrapper.find('input.ajuste').setValue('5');
    await wrapper.vm.$nextTick();
    expect((cantidadInput.element as HTMLInputElement).value).toBe('0');
    expect((cantidadInput.element as HTMLInputElement).disabled).toBe(true);
  });

  it('bloquea el campo opuesto cuando el valor es negativo', async () => {
    const wrapper = mount(EditableNotaTable, {
      props: {
        modelValue: [
          {
            id: 1,
            selected: false,
            codigo: 'A1',
            descripcion: 'Test',
            cantidadFacturada: 5,
            cantidadAjustar: 0,
            tipo: 'credito',
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
        notaTipo: 'credito'
      }
    });

    const ajusteInput = wrapper.find('input.ajuste');
    await ajusteInput.setValue('-5');
    await wrapper.vm.$nextTick();

    const cantidadInput = wrapper.find('input.cantidad-ajuste');
    expect((cantidadInput.element as HTMLInputElement).disabled).toBe(true);

    await ajusteInput.setValue('0');
    await wrapper.vm.$nextTick();

    expect((cantidadInput.element as HTMLInputElement).disabled).toBe(false);
  });

  it('asigna un identificador interno cuando el item no lo provee', async () => {
    const wrapper = mount(EditableNotaTable, {
      props: {
        // @ts-expect-error simulando datos sin id
        modelValue: [
          {
            selected: false,
            codigo: 'A1',
            descripcion: 'Test',
            cantidadFacturada: 5,
            cantidadAjustar: 0,
            tipo: 'credito',
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
        notaTipo: 'credito'
      }
    });

    const ajusteInput = wrapper.find('input.ajuste');
    await ajusteInput.setValue('5');
    await wrapper.vm.$nextTick();

    expect((wrapper.find('input.cantidad-ajuste').element as HTMLInputElement).value).toBe('0');
  });
});
