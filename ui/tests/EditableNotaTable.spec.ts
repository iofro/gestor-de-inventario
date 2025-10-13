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
    expect(cells[13].text()).toBe('100.0000');
    expect(cells[14].text()).toBe('13.0000');
    expect(cells[15].text()).toBe('113.0000');
    await wrapper.setProps({ ivaIncluido: false });
    await ajusteInput.setValue('100');
    await wrapper.vm.$nextTick();
    cells = wrapper.findAll('tbody td');
    expect(cells[13].text()).toBe('100.0000');
    expect(cells[14].text()).toBe('13.0000');
    expect(cells[15].text()).toBe('113.0000');
  });

  it('muestra la columna Ajuste precio (USD)', async () => {
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

    const headers = wrapper.findAll('thead th').map((th) => th.text());
    expect(headers).toContain('Ajuste precio (USD)');
  });

  it('bloquea precio al activar Modificar cantidad', async () => {
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

    const cantidadRadio = wrapper.get('[data-testid="modo-selector-1"] input[value="cantidad"]');
    const precioInput = wrapper.get('[data-testid="precio-input-1"]');

    await cantidadRadio.setChecked();
    await wrapper.vm.$nextTick();

    expect((precioInput.element as HTMLInputElement).disabled).toBe(true);
    expect((precioInput.element as HTMLInputElement).value).toBe('0');
  });

  it('bloquea cantidad al activar Modificar precio', async () => {
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

    const precioRadio = wrapper.get('[data-testid="modo-selector-1"] input[value="precio"]');
    const cantidadInput = wrapper.get('[data-testid="cantidad-input-1"]');

    await precioRadio.setChecked();
    await wrapper.vm.$nextTick();

    expect((cantidadInput.element as HTMLInputElement).disabled).toBe(true);
    expect((cantidadInput.element as HTMLInputElement).value).toBe('0');
  });

  it('auto selecciona el modo al ingresar un valor cuando no hay selección', async () => {
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

    const cantidadInput = wrapper.get('[data-testid="cantidad-input-1"]');
    const precioInput = wrapper.get('[data-testid="precio-input-1"]');

    await cantidadInput.setValue('2');
    await wrapper.vm.$nextTick();

    const cantidadRadio = wrapper.get('[data-testid="modo-selector-1"] input[value="cantidad"]');
    expect((cantidadRadio.element as HTMLInputElement).checked).toBe(true);
    expect((precioInput.element as HTMLInputElement).disabled).toBe(true);

    await cantidadInput.setValue('0');
    await wrapper.vm.$nextTick();
    expect((cantidadRadio.element as HTMLInputElement).checked).toBe(true);

    await cantidadRadio.trigger('click');
    await wrapper.vm.$nextTick();
    expect((cantidadRadio.element as HTMLInputElement).checked).toBe(false);
    expect((precioInput.element as HTMLInputElement).disabled).toBe(false);

    await precioInput.setValue('3');
    await wrapper.vm.$nextTick();

    const precioRadio = wrapper.get('[data-testid="modo-selector-1"] input[value="precio"]');
    expect((precioRadio.element as HTMLInputElement).checked).toBe(true);
    expect((cantidadInput.element as HTMLInputElement).disabled).toBe(true);
  });

  it('no emite propiedades adicionales para el modo de edición', async () => {
    const initialItem = {
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
    };
    const wrapper = mount(EditableNotaTable, {
      props: {
        modelValue: [initialItem],
        ivaIncluido: true,
        notaTipo: 'credito'
      }
    });

    const precioRadio = wrapper.get('[data-testid="modo-selector-1"] input[value="precio"]');
    await precioRadio.setChecked();
    await wrapper.vm.$nextTick();

    const emitted = wrapper.emitted('update:modelValue');
    expect(emitted).toBeTruthy();
    const payload = emitted!.at(-1)![0] as Array<Record<string, unknown>>;
    const keys = Object.keys(payload[0]).sort();
    const expectedKeys = Object.keys({ ...initialItem, ajusteCantidad: false }).sort();
    expect(keys).toEqual(expectedKeys);
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
