import { mount } from '@vue/test-utils';
import { describe, it, expect, vi } from 'vitest';
import FacturaForm from '../ventas/FacturaForm.vue';

vi.mock('../services/facturasApi', () => ({
  guardarEnContingencia: vi.fn().mockResolvedValue({})
}));

const api = await import('../services/facturasApi');

describe('FacturaForm', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });
  it('confirma contingencia cuando está activa', async () => {
    const wrapper = mount(FacturaForm, {
      props: { facturaId: '1', config: { modoContingencia: true } }
    });
    await wrapper.find('button').trigger('click');
    const dialog = wrapper.findComponent({ name: 'ConfirmDialog' });
    expect(dialog.exists()).toBe(true);
    await dialog.vm.$emit('confirm');
    expect(api.guardarEnContingencia).toHaveBeenCalledWith('1');
  });

  it('muestra diálogo de error y guarda en contingencia tras fallo', async () => {
    const wrapper = mount(FacturaForm, {
      props: { facturaId: '2', config: { modoContingencia: false } }
    });
    await wrapper.find('button').trigger('click');
    const dialogs = wrapper.findAllComponents({ name: 'ConfirmDialog' });
    const errorDialog = dialogs.find(d => d.props('title') === 'Error al enviar a Hacienda');
    expect(errorDialog).toBeTruthy();
    await errorDialog!.vm.$emit('confirm');
    expect(api.guardarEnContingencia).toHaveBeenCalledWith('2');
  });

  it('no llama API al cancelar', async () => {
    const wrapper = mount(FacturaForm, {
      props: { facturaId: '3', config: { modoContingencia: true } }
    });
    await wrapper.find('button').trigger('click');
    const dialog = wrapper.findComponent({ name: 'ConfirmDialog' });
    await dialog.vm.$emit('cancel');
    expect(api.guardarEnContingencia).not.toHaveBeenCalled();
  });
});
