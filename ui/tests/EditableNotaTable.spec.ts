import { mount } from '@vue/test-utils';
import EditableNotaTable from '../components/EditableNotaTable.vue';

describe('EditableNotaTable', () => {
  it('agrega item cuando se hace click', async () => {
    const wrapper = mount(EditableNotaTable, {
      props: { modelValue: [], topeCredito: 10 }
    });
    await wrapper.find('button.add-item').trigger('click');
    const emitted = wrapper.emitted('update:modelValue');
    expect(emitted).toBeTruthy();
    expect(emitted![0][0]).toHaveLength(1);
  });

  it('filtra por código o descripción', async () => {
    const wrapper = mount(EditableNotaTable, {
      props: {
        modelValue: [
          { id: 1, selected: false, codigo: 'A1', descripcion: 'Test', cantidadFacturada: 1, cantidadAjustar: 0, tipo: 'debito', modo: 'monto', valor: 0, ivaInc: false }
        ]
      }
    });
    expect(wrapper.findAll('tbody tr')).toHaveLength(1);
    await wrapper.find('input[placeholder="Buscar"]').setValue('no existe');
    expect(wrapper.findAll('tbody tr')).toHaveLength(0);
  });
});
