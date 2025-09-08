import { mount } from '@vue/test-utils';
import { describe, it, expect } from 'vitest';
import NotaForm from '../ventas/NotaForm.vue';

describe('NotaForm', () => {
  it('muestra input según el modo seleccionado', async () => {
    const wrapper = mount(NotaForm);
    expect(wrapper.find('input[placeholder="%"]').exists()).toBe(true);
    await wrapper.find('input[value="amount"]').setChecked();
    expect(wrapper.find('input[placeholder="Monto"]').exists()).toBe(true);
  });
});
