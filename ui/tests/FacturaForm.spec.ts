import { mount } from '@vue/test-utils';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import FacturaForm from '../ventas/FacturaForm.vue';

vi.mock('../services/facturasApi', () => ({
  guardarEnContingencia: vi.fn().mockResolvedValue({})
}));

const api = await import('../services/facturasApi');

describe('FacturaForm', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  function mountForm(configOverrides: Record<string, unknown> = {}, facturaId = '1') {
    return mount(FacturaForm, {
      props: {
        facturaId,
        config: {
          modoTransmision: 1,
          pendientesContingencia: [],
          ...configOverrides
        }
      }
    });
  }

  it('oculta controles de contingencia cuando el modo es normal', () => {
    const wrapper = mountForm();
    expect(wrapper.find('#tipo').exists()).toBe(false);
    expect(wrapper.find('.guardar').attributes('disabled')).toBeUndefined();
  });

  it('requiere tipo de contingencia al guardar en modo contingencia', async () => {
    const wrapper = mountForm({ modoTransmision: 2 });
    const saveButton = wrapper.find('.guardar');
    expect(saveButton.attributes('disabled')).toBeUndefined();
    await saveButton.trigger('click');
    await wrapper.vm.$nextTick();
    const tipoError = wrapper
      .findAll('.error-message')
      .map(node => node.text())
      .find(text => text.includes('Selecciona un tipo de contingencia'));
    expect(tipoError).toBeTruthy();
    expect(api.guardarEnContingencia).not.toHaveBeenCalled();
  });

  it('muestra motivo obligatorio cuando el tipo es “Otro” y limita a 500 caracteres', async () => {
    const wrapper = mountForm({ modoTransmision: 2 });
    const select = wrapper.find('#tipo');
    await select.setValue('5');
    const textarea = wrapper.find('#motivo');
    expect(textarea.exists()).toBe(true);
    const longText = 'x'.repeat(600);
    await textarea.setValue(longText);
    expect((textarea.element as HTMLTextAreaElement).value.length).toBe(500);
    expect(wrapper.find('.counter').text()).toBe('500/500');

    await textarea.setValue('   ');
    await wrapper.find('.guardar').trigger('click');
    await wrapper.vm.$nextTick();
    const motivoError = wrapper
      .findAll('.error-message')
      .map(node => node.text())
      .find(text => text.includes('Motivo es obligatorio cuando el tipo es ‘Otro’'));
    expect(motivoError).toBeTruthy();
  });

  it('limpia el motivo cuando se cambia el tipo a un valor diferente de “Otro”', async () => {
    const wrapper = mountForm({ modoTransmision: 2 });
    const select = wrapper.find('#tipo');
    await select.setValue('5');
    const textarea = wrapper.find('#motivo');
    await textarea.setValue('corte eléctrico');
    await select.setValue('4');
    expect(wrapper.find('#motivo').exists()).toBe(false);
  });

  it('envía los indicadores de contingencia al confirmar el guardado', async () => {
    const wrapper = mountForm({ modoTransmision: 2 }, '42');
    await wrapper.find('#tipo').setValue('3');
    await wrapper.find('.guardar').trigger('click');
    await wrapper.vm.$nextTick();
    const confirmDialog = wrapper
      .findAllComponents({ name: 'ConfirmDialog' })
      .find(dialog => dialog.props('title') === 'Modo contingencia activado');
    expect(confirmDialog).toBeTruthy();
    await confirmDialog!.vm.$emit('confirm');
    expect(api.guardarEnContingencia).toHaveBeenCalledWith('42', {
      modeloFacturacion: 2,
      tipoTransmision: 2,
      tipoContingencia: 3
    });
  });

  it('muestra advertencia antes de descartar datos de contingencia', async () => {
    const wrapper = mountForm({
      modoTransmision: 2,
      tipoContingencia: 5,
      motivoContingencia: 'Otro motivo'
    });
    const modoSelect = wrapper.find('#modo');
    await modoSelect.setValue('1');
    await wrapper.vm.$nextTick();
    const warningDialog = wrapper
      .findAllComponents({ name: 'ConfirmDialog' })
      .find(dialog => dialog.props('title') === 'Cambiar a modo normal');
    expect(warningDialog).toBeTruthy();
    await warningDialog!.vm.$emit('confirm');
    await wrapper.vm.$nextTick();
    expect(wrapper.find('#tipo').exists()).toBe(false);
  });

  it('gestiona el flujo de evento de contingencia y valida los campos requeridos', async () => {
    const wrapper = mountForm({
      modoTransmision: 2,
      pendientesContingencia: [
        { codigoGeneracion: 'A', tipoDocumento: '01' },
        { codigoGeneracion: 'B', tipoDocumento: '03' }
      ]
    });
    const eventoButton = wrapper.find('button.evento');
    expect(eventoButton.exists()).toBe(true);
    await eventoButton.trigger('click');
    await wrapper.vm.$nextTick();

    const continuar = wrapper.find('.evento-content .primary');
    await continuar.trigger('click');
    await wrapper.vm.$nextTick();
    expect(wrapper.text()).toContain('Completa la fecha y hora de inicio.');

    const [inicioFecha, finFecha] = wrapper.findAll('input[type="date"]');
    const [inicioHora, finHora] = wrapper.findAll('input[type="time"]');
    await inicioFecha.setValue('2024-01-01');
    await inicioHora.setValue('08:00');
    await finFecha.setValue('2024-01-01');
    await finHora.setValue('09:00');
    await wrapper.find('#evento-tipo').setValue('5');
    await wrapper.find('#evento-motivo').setValue('Fallo prolongado');
    await continuar.trigger('click');
    await wrapper.vm.$nextTick();

    expect(wrapper.text()).toContain('Paso 2: DTE pendientes');
    expect(wrapper.find('.json-preview').text()).toContain('"codigoGeneracion": "A"');
  });

  it('advierte cuando hay más de 1000 DTE y limita la previsualización', async () => {
    const pendientes = Array.from({ length: 1002 }, (_, index) => ({
      codigoGeneracion: `DTE-${index}`,
      tipoDocumento: '01'
    }));
    const wrapper = mountForm({ modoTransmision: 2, pendientesContingencia: pendientes });
    await wrapper.find('button.evento').trigger('click');
    await wrapper.vm.$nextTick();

    const [inicioFecha, finFecha] = wrapper.findAll('input[type="date"]');
    const [inicioHora, finHora] = wrapper.findAll('input[type="time"]');
    await inicioFecha.setValue('2024-01-01');
    await inicioHora.setValue('08:00');
    await finFecha.setValue('2024-01-02');
    await finHora.setValue('09:00');
    await wrapper.find('#evento-tipo').setValue('1');
    await wrapper.find('.evento-content .primary').trigger('click');
    await wrapper.vm.$nextTick();

    const json = wrapper.find('.json-preview').text();
    expect(wrapper.text()).toContain('Divide el envío en varios eventos');
    expect(json).toContain('"codigoGeneracion": "DTE-0"');
    expect(json).not.toContain('"codigoGeneracion": "DTE-1001"');
  });
});
