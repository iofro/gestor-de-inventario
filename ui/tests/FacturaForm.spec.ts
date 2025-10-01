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
    expect(wrapper.find('.contingencia-panel').exists()).toBe(false);
    expect(wrapper.find('.guardar').attributes('disabled')).toBeUndefined();
  });

  it('muestra el botón de contingencia al activar el modo', async () => {
    const wrapper = mountForm();
    const modoSelect = wrapper.find('#modo');
    await modoSelect.setValue('2');
    await wrapper.vm.$nextTick();
    expect(wrapper.find('.configurar-contingencia').exists()).toBe(true);
  });

  it('resume los datos existentes al iniciar en modo contingencia', () => {
    const wrapper = mountForm({ modoTransmision: 2, tipoContingencia: 3 });
    expect(wrapper.find('.configurar-contingencia').exists()).toBe(true);
    expect(wrapper.find('.chip').text()).toContain('Tipo 3');
  });

  it('interpreta valores de modo provenientes como texto', () => {
    const wrapper = mountForm({ modoTransmision: '2 - Contingencia' });
    expect(wrapper.find('.configurar-contingencia').exists()).toBe(true);
  });

  it('refleja cambios programáticos del modo', async () => {
    const wrapper = mountForm();
    expect(wrapper.find('.configurar-contingencia').exists()).toBe(false);

    await wrapper.setProps({
      config: {
        ...wrapper.props().config,
        modoTransmision: 2
      }
    });
    await wrapper.vm.$nextTick();
    expect(wrapper.find('.configurar-contingencia').exists()).toBe(true);
  });

  it('exige completar la configuración de contingencia antes de guardar', async () => {
    const wrapper = mountForm({ modoTransmision: 2 });
    await wrapper.find('.guardar').trigger('click');
    await wrapper.vm.$nextTick();
    expect(wrapper.text()).toContain(
      'Completa la configuración de contingencia antes de guardar.'
    );
    expect(api.guardarEnContingencia).not.toHaveBeenCalled();
  });

  it('valida tipo y motivo dentro del diálogo de contingencia', async () => {
    const wrapper = mountForm({ modoTransmision: 2 });
    await wrapper.find('.configurar-contingencia').trigger('click');
    await wrapper.vm.$nextTick();

    const modal = wrapper.find('.contingencia-dialog');
    expect(modal.exists()).toBe(true);

    const confirmButton = modal.find('.primary');
    expect(confirmButton.attributes('disabled')).toBeDefined();

    const tipoSelect = modal.find('#contingencia-tipo');
    expect(modal.text()).toContain('Selecciona un tipo de contingencia (CAT-005).');

    await tipoSelect.setValue('5');
    await wrapper.vm.$nextTick();
    const motivo = modal.find('#contingencia-motivo');
    expect(motivo.exists()).toBe(true);

    const longText = 'x'.repeat(600);
    await motivo.setValue(longText);
    expect((motivo.element as HTMLTextAreaElement).value.length).toBe(500);
    expect(modal.find('.counter').text()).toBe('500/500');

    await motivo.setValue('motivo válido');
    await wrapper.vm.$nextTick();
    expect(modal.find('.primary').attributes('disabled')).toBeUndefined();

    await motivo.setValue('   ');
    await wrapper.vm.$nextTick();
    expect(modal.text()).toContain(
      'Motivo es obligatorio cuando el tipo es ‘Otro’ (máx. 500).'
    );
    expect(modal.find('.primary').attributes('disabled')).toBeDefined();
  });

  it('actualiza el resumen al confirmar la configuración', async () => {
    const wrapper = mountForm({ modoTransmision: 2 });
    await wrapper.find('.configurar-contingencia').trigger('click');
    await wrapper.vm.$nextTick();
    const modal = wrapper.find('.contingencia-dialog');
    await modal.find('#contingencia-tipo').setValue('3');
    await wrapper.vm.$nextTick();
    await modal.find('.primary').trigger('click');
    await wrapper.vm.$nextTick();
    expect(wrapper.find('.chip').text()).toContain('Tipo 3');
  });

  it('marca motivo capturado cuando el tipo es “Otro”', async () => {
    const wrapper = mountForm({ modoTransmision: 2 });
    await wrapper.find('.configurar-contingencia').trigger('click');
    await wrapper.vm.$nextTick();
    const modal = wrapper.find('.contingencia-dialog');
    await modal.find('#contingencia-tipo').setValue('5');
    await wrapper.vm.$nextTick();
    const motivo = modal.find('#contingencia-motivo');
    await motivo.setValue('Falla eléctrica prolongada');
    await wrapper.vm.$nextTick();
    await modal.find('.primary').trigger('click');
    await wrapper.vm.$nextTick();
    expect(wrapper.find('.chip').text()).toContain('Motivo capturado');
  });

  it('advierte al cerrar el diálogo con cambios sin confirmar', async () => {
    const wrapper = mountForm({ modoTransmision: 2 });
    await wrapper.find('.configurar-contingencia').trigger('click');
    await wrapper.vm.$nextTick();
    const modal = wrapper.find('.contingencia-dialog');
    await modal.find('#contingencia-tipo').setValue('1');
    await wrapper.vm.$nextTick();
    await modal.find('.close').trigger('click');
    await wrapper.vm.$nextTick();

    const discardDialog = wrapper
      .findAllComponents({ name: 'ConfirmDialog' })
      .find(dialog =>
        dialog.props('message') === 'Tienes cambios sin guardar. ¿Deseas descartarlos?'
      );
    expect(discardDialog).toBeTruthy();
    await discardDialog!.vm.$emit('confirm');
    await wrapper.vm.$nextTick();
    expect(wrapper.find('.contingencia-dialog').exists()).toBe(false);
  });

  it('envía los indicadores de contingencia al confirmar el guardado', async () => {
    const wrapper = mountForm({ modoTransmision: 2 }, '42');
    await wrapper.find('.configurar-contingencia').trigger('click');
    await wrapper.vm.$nextTick();
    const modal = wrapper.find('.contingencia-dialog');
    await modal.find('#contingencia-tipo').setValue('3');
    await wrapper.vm.$nextTick();
    await modal.find('.primary').trigger('click');
    await wrapper.vm.$nextTick();

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
      .find(dialog =>
        dialog.props('message') === 'Perderás la configuración de contingencia. ¿Continuar?'
      );
    expect(warningDialog).toBeTruthy();
    await warningDialog!.vm.$emit('confirm');
    await wrapper.vm.$nextTick();
    expect(wrapper.find('.configurar-contingencia').exists()).toBe(false);
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
    const preview = wrapper.find('.json-preview').text();
    expect(preview).toContain('"version": 3');
    expect(preview).toContain('"noItem": 1');
    expect(preview).toContain('"codigoGeneracion": "A"');
    expect(preview).toContain('"tipoDoc": "01"');
    expect(wrapper.text()).toContain('Mostrando 2 de 2 (máx. 1000)');
    expect(wrapper.find('.copy-codes').exists()).toBe(true);
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
    expect(wrapper.text()).toContain('Mostrando 1000 de 1002 (máx. 1000)');
  });

  it('normaliza valores inválidos del modo de transmisión a normal', () => {
    const wrapper = mountForm({ modoTransmision: 5 as unknown as number });
    const modo = wrapper.find('#modo');
    expect((modo.element as HTMLSelectElement).value).toBe('1');
  });

  it('permite copiar los códigos de los DTE en la previsualización del evento', async () => {
    const pendientes = [
      { codigoGeneracion: 'abc123', tipoDocumento: '01' },
      { codigoGeneracion: 'def456', tipoDocumento: '03' }
    ];
    const wrapper = mountForm({ modoTransmision: 2, pendientesContingencia: pendientes });
    await wrapper.find('button.evento').trigger('click');
    await wrapper.vm.$nextTick();

    const [inicioFecha, finFecha] = wrapper.findAll('input[type="date"]');
    const [inicioHora, finHora] = wrapper.findAll('input[type="time"]');
    await inicioFecha.setValue('2024-01-01');
    await inicioHora.setValue('08:00');
    await finFecha.setValue('2024-01-01');
    await finHora.setValue('09:30');
    await wrapper.find('#evento-tipo').setValue('1');
    await wrapper.find('.evento-content .primary').trigger('click');
    await wrapper.vm.$nextTick();

    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(window.navigator, 'clipboard', {
      value: { writeText },
      configurable: true
    });

    await wrapper.find('.copy-codes').trigger('click');
    await wrapper.vm.$nextTick();

    expect(writeText).toHaveBeenCalledWith('ABC123\nDEF456');
    expect(wrapper.text()).toContain('Códigos copiados al portapapeles.');

    // clean up clipboard mock
    // @ts-expect-error
    delete window.navigator.clipboard;
  });
});
