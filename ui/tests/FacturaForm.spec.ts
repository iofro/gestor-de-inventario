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
    expect(wrapper.find('.actions .evento-trigger').exists()).toBe(false);
    expect(wrapper.find('.guardar').attributes('disabled')).toBeUndefined();
  });

  it('muestra el botón de contingencia al activar el modo', async () => {
    const wrapper = mountForm();
    const modoSelect = wrapper.find('#modo');
    await modoSelect.setValue('2');
    await wrapper.vm.$nextTick();
    expect(wrapper.find('.configurar-contingencia').exists()).toBe(true);
    expect(wrapper.find('.actions .evento-trigger').exists()).toBe(true);
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
    expect(wrapper.find('.actions .evento-trigger').exists()).toBe(false);

    await wrapper.setProps({
      config: {
        ...wrapper.props().config,
        modoTransmision: 2
      }
    });
    await wrapper.vm.$nextTick();
    expect(wrapper.find('.configurar-contingencia').exists()).toBe(true);
    expect(wrapper.find('.actions .evento-trigger').exists()).toBe(true);
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

  it('deshabilita el botón de evento cuando no hay pendientes', () => {
    const wrapper = mountForm({ modoTransmision: 2 });
    const eventoButton = wrapper.find('.actions .evento-trigger');
    expect(eventoButton.exists()).toBe(true);
    expect(eventoButton.attributes('disabled')).toBeDefined();
    expect(eventoButton.attributes('title')).toContain(
      'No hay DTE pendientes en contingencia'
    );
  });

  it('abre el panel del evento con validaciones iniciales', async () => {
    const wrapper = mountForm({
      modoTransmision: 2,
      pendientesContingencia: [{ codigoGeneracion: 'abc', tipoDocumento: '01' }],
      tipoContingencia: 5,
      motivoContingencia: 'Interrupción previa'
    });
    const trigger = wrapper.find('.actions .evento-trigger');
    await trigger.trigger('click');
    await wrapper.vm.$nextTick();
    await wrapper.vm.$nextTick();

    const panel = wrapper.find('.evento-panel');
    expect(panel.exists()).toBe(true);
    expect(panel.text()).toContain('Zona horaria: America/El_Salvador (UTC-6)');
    const tipoSelect = panel.find('#evento-tipo');
    expect((tipoSelect.element as HTMLSelectElement).value).toBe('5');
    const motivo = panel.find('#evento-motivo');
    expect(motivo.exists()).toBe(true);
    expect((motivo.element as HTMLTextAreaElement).value).toBe(
      'Interrupción previa'
    );
    const inicioError = panel.find('#evento-inicio-error');
    expect(inicioError.exists()).toBe(true);
    expect(inicioError.text()).toContain('Completa la fecha y hora de inicio.');
    const generar = panel.find('.panel-actions .primary');
    expect(generar.attributes('disabled')).toBeDefined();
  });

  it('habilita la generación del borrador con datos válidos', async () => {
    const wrapper = mountForm({
      modoTransmision: 2,
      tipoContingencia: 3,
      pendientesContingencia: [
        { codigoGeneracion: 'abc123', tipoDocumento: '3' },
        { codigoGeneracion: 'def456', tipoDocumento: '99' }
      ],
      ambiente: 'PRUEBAS'
    });
    await wrapper.find('.actions .evento-trigger').trigger('click');
    await wrapper.vm.$nextTick();

    await wrapper.find('#evento-tipo').setValue('3');
    await wrapper.find('#evento-inicio-fecha').setValue('2024-05-01');
    await wrapper.find('#evento-inicio-hora').setValue('08:00');
    await wrapper.find('#evento-fin-fecha').setValue('2024-05-01');
    await wrapper.find('#evento-fin-hora').setValue('09:00');
    await wrapper.vm.$nextTick();

    const generar = wrapper.find('.panel-actions .primary');
    expect(generar.attributes('disabled')).toBeUndefined();
    await generar.trigger('click');
    await wrapper.vm.$nextTick();
    expect(wrapper.text()).toContain('Borrador generado (solo UI).');

    const preview = wrapper.find('.json-preview').text();
    expect(preview).toContain('"version": 3');
    expect(preview).toContain('"ambiente": "PRUEBAS"');
    expect(preview).toContain('"codigoGeneracion": "ABC123"');
    expect(preview).toContain('"tipoDoc": "03"');
    expect(preview).toContain('"tipoDoc": "15"');
  });

  it('muestra advertencia cuando hay más de 1000 DTE', async () => {
    const pendientes = Array.from({ length: 1002 }, (_, index) => ({
      codigoGeneracion: `dte-${index}`,
      tipoDocumento: '01'
    }));
    const wrapper = mountForm({
      modoTransmision: 2,
      pendientesContingencia: pendientes
    });
    await wrapper.find('.actions .evento-trigger').trigger('click');
    await wrapper.vm.$nextTick();

    await wrapper.find('#evento-tipo').setValue('1');
    await wrapper.find('#evento-inicio-fecha').setValue('2024-05-01');
    await wrapper.find('#evento-inicio-hora').setValue('08:00');
    await wrapper.find('#evento-fin-fecha').setValue('2024-05-02');
    await wrapper.find('#evento-fin-hora').setValue('09:00');
    await wrapper.vm.$nextTick();

    const panel = wrapper.find('.evento-panel');
    expect(panel.text()).toContain('Máximo 1000 por evento. Se deberá dividir en varios eventos.');
    expect(panel.text()).toContain('Máximo 1000 DTE por evento.');
    expect(panel.text()).toContain('Mostrando 1000 de 1002 (máx. 1000)');
    expect(wrapper.find('.panel-actions .primary').attributes('disabled')).toBeDefined();
  });

  it('colapsa el panel al presionar cerrar', async () => {
    const wrapper = mountForm({
      modoTransmision: 2,
      pendientesContingencia: [{ codigoGeneracion: 'xyz', tipoDocumento: '01' }]
    });
    await wrapper.find('.actions .evento-trigger').trigger('click');
    await wrapper.vm.$nextTick();
    expect(wrapper.find('.evento-panel').exists()).toBe(true);

    const buttons = wrapper.findAll('.panel-actions button');
    await buttons[1].trigger('click');
    await wrapper.vm.$nextTick();
    expect(wrapper.find('.evento-panel').exists()).toBe(false);
  });

  it('permite ver los detalles devueltos por Hacienda cuando falla el envío', async () => {
    const wrapper = mountForm();
    await wrapper.find('.guardar').trigger('click');
    await wrapper.vm.$nextTick();
    await wrapper.vm.$nextTick();

    expect(wrapper.text()).toContain(
      'No fue posible enviar la factura a Hacienda. Revisa los detalles o guárdala en contingencia.'
    );

    const inlineToggle = wrapper.find('.status.error .details-toggle');
    expect(inlineToggle.exists()).toBe(true);
    expect(inlineToggle.text()).toBe('Ver detalles');
    await inlineToggle.trigger('click');
    await wrapper.vm.$nextTick();
    const inlineDetails = wrapper.find('.status.error .error-details');
    expect(inlineDetails.exists()).toBe(true);
    expect(inlineDetails.text()).toContain('fallo');

    const errorDialog = wrapper
      .findAllComponents({ name: 'ConfirmDialog' })
      .find(dialog => dialog.props('title') === 'Error al enviar a Hacienda');
    expect(errorDialog).toBeTruthy();

    const dialogToggle = errorDialog!.find('.details-toggle');
    expect(dialogToggle.exists()).toBe(true);
    expect(dialogToggle.text()).toBe('Ver detalles');
    await dialogToggle.trigger('click');
    await wrapper.vm.$nextTick();
    const dialogDetails = errorDialog!.find('.details-panel');
    expect(dialogDetails.exists()).toBe(true);
    expect(dialogDetails.text()).toContain('fallo');
  });

  it('normaliza valores inválidos del modo de transmisión a normal', () => {
    const wrapper = mountForm({ modoTransmision: 5 as unknown as number });
    const modo = wrapper.find('#modo');
    expect((modo.element as HTMLSelectElement).value).toBe('1');
  });
});
