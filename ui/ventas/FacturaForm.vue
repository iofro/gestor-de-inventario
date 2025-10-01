<template>
  <div class="factura-form">
    <section class="modo-transmision">
      <label for="modo">Modo de transmisión</label>
      <select id="modo" v-model.number="modoTransmision">
        <option :value="1">1 — Normal</option>
        <option :value="2">2 — Contingencia</option>
      </select>
    </section>

    <section v-if="isContingencia" class="contingencia-panel">
      <p class="helper">Si eliges “Otro”, el motivo es obligatorio.</p>
      <div :class="['field', { error: showTipoError }]">
        <label for="tipo">Tipo de Contingencia (CAT-005)</label>
        <select
          id="tipo"
          ref="tipoSelect"
          v-model.number="tipoContingencia"
        >
          <option disabled value="">Selecciona una opción</option>
          <option
            v-for="option in CONTINGENCIA_OPTIONS"
            :key="option.value"
            :value="option.value"
          >
            {{ option.label }}
          </option>
        </select>
        <p v-if="showTipoError" class="error-message">
          {{ tipoErrorMessage }}
        </p>
      </div>

      <div
        v-if="requiresMotivo"
        :class="['field', { error: showMotivoError }]"
      >
        <label for="motivo">Motivo</label>
        <textarea
          id="motivo"
          ref="motivoInput"
          v-model="motivoContingencia"
          @input="enforceMotivoLimit"
          rows="3"
        ></textarea>
        <div class="field-footer">
          <span class="counter">{{ motivoLength }}/500</span>
        </div>
        <p v-if="showMotivoError" class="error-message">
          {{ motivoErrorMessage }}
        </p>
      </div>
    </section>

    <section v-if="statusMessage" class="status success">
      {{ statusMessage }}
    </section>
    <section v-if="saveErrorMessage" class="status error">
      {{ saveErrorMessage }}
    </section>

    <div class="actions">
      <button
        class="guardar"
        :disabled="isSaveDisabled"
        @click="onSave"
      >
        Guardar y Enviar
      </button>
      <button
        v-if="hasPendingContingencia"
        class="evento"
        @click="openEventoDialog"
      >
        Crear Evento de Contingencia
      </button>
    </div>

    <ConfirmDialog
      v-model="confirmVisible"
      title="Modo contingencia activado"
      message="El modo contingencia está activado. ¿Desea continuar y guardar esta factura en modo contingencia?"
      confirm-text="Guardar en contingencia"
      cancel-text="Cancelar"
      @confirm="saveContingencia"
    />
    <ConfirmDialog
      v-model="errorVisible"
      title="Error al enviar a Hacienda"
      message="¿Desea guardar esta factura en modo contingencia para enviarla más tarde?"
      confirm-text="Guardar en contingencia"
      cancel-text="No"
      @confirm="saveContingencia"
    />
    <ConfirmDialog
      v-model="lossConfirmVisible"
      title="Cambiar a modo normal"
      message="Perderás los datos de contingencia de esta factura. ¿Continuar?"
      confirm-text="Continuar"
      cancel-text="Cancelar"
      @confirm="confirmClearContingencia"
      @cancel="cancelClearContingencia"
    />

    <div v-if="eventoVisible" class="evento-dialog">
      <div class="evento-content">
        <header>
          <h2>Evento de Contingencia</h2>
          <button class="cerrar" type="button" @click="closeEventoDialog">×</button>
        </header>
        <section v-if="eventoStep === 1" class="evento-step">
          <h3>Paso 1: Datos del evento</h3>
          <p class="helper">Zona horaria: America/El_Salvador (UTC-6)</p>
          <div :class="['field-group', { error: eventoErrors.inicio }]">
            <label>Fecha y hora de inicio</label>
            <div class="inputs">
              <input
                type="date"
                ref="eventoInicioFecha"
                v-model="eventoForm.inicioFecha"
              />
              <input
                type="time"
                ref="eventoInicioHora"
                v-model="eventoForm.inicioHora"
              />
            </div>
            <p v-if="eventoErrors.inicio" class="error-message">
              {{ eventoErrors.inicio }}
            </p>
          </div>
          <div :class="['field-group', { error: eventoErrors.fin }]">
            <label>Fecha y hora de fin</label>
            <div class="inputs">
              <input type="date" ref="eventoFinFecha" v-model="eventoForm.finFecha" />
              <input type="time" ref="eventoFinHora" v-model="eventoForm.finHora" />
            </div>
            <p v-if="eventoErrors.fin" class="error-message">
              {{ eventoErrors.fin }}
            </p>
          </div>
          <div :class="['field-group', { error: eventoErrors.tipo }]">
            <label for="evento-tipo">Tipo (CAT-005)</label>
            <select
              id="evento-tipo"
              ref="eventoTipo"
              v-model.number="eventoForm.tipo"
            >
              <option disabled value="">Selecciona una opción</option>
              <option
                v-for="option in CONTINGENCIA_OPTIONS"
                :key="`evento-${option.value}`"
                :value="option.value"
              >
                {{ option.label }}
              </option>
            </select>
            <p v-if="eventoErrors.tipo" class="error-message">
              {{ eventoErrors.tipo }}
            </p>
          </div>
          <div
            v-if="eventoRequiresMotivo"
            :class="['field-group', { error: eventoErrors.motivo }]"
          >
            <label for="evento-motivo">Motivo</label>
            <textarea
              id="evento-motivo"
              ref="eventoMotivo"
              v-model="eventoForm.motivo"
              @input="enforceEventoMotivoLimit"
              rows="3"
            ></textarea>
            <div class="field-footer">
              <span class="counter">{{ eventoMotivoLength }}/500</span>
            </div>
            <p v-if="eventoErrors.motivo" class="error-message">
              {{ eventoErrors.motivo }}
            </p>
          </div>
          <footer class="dialog-actions">
            <button type="button" @click="closeEventoDialog">Cancelar</button>
            <button type="button" class="primary" @click="continuarEvento">
              Continuar
            </button>
          </footer>
        </section>
        <section v-else class="evento-step">
          <h3>Paso 2: DTE pendientes</h3>
          <p>Total de DTE: {{ pendingDtes.length }}</p>
          <p v-if="pendingDtes.length > 1000" class="info">
            Se generarán hasta 1000 DTE por evento. Divide el envío en varios eventos si es necesario.
          </p>
          <ul class="dte-list">
            <li v-for="dte in eventoDetalleLimit" :key="dte.codigoGeneracion">
              {{ dte.codigoGeneracion }} — {{ dte.tipoDocumento }}
            </li>
          </ul>
          <h4>Previsualización del evento (JSON)</h4>
          <pre class="json-preview">{{ eventoPreview }}</pre>
          <footer class="dialog-actions">
            <button type="button" @click="volverEvento">Volver</button>
            <button type="button" class="primary" @click="closeEventoDialog">
              Cerrar
            </button>
          </footer>
        </section>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, reactive, ref, watch } from 'vue';
import ConfirmDialog from '../components/ConfirmDialog.vue';
import { guardarEnContingencia } from '../services/facturasApi';

const CONTINGENCIA_OPTIONS = [
  { value: 1, label: '1 — No disponibilidad del sistema del MH' },
  { value: 2, label: '2 — No disponibilidad del sistema del emisor' },
  { value: 3, label: '3 — Falla en servicio de Internet del emisor' },
  { value: 4, label: '4 — Falla en energía eléctrica del emisor' },
  { value: 5, label: '5 — Otro' }
] as const;

type ContingenciaOptionValue = (typeof CONTINGENCIA_OPTIONS)[number]['value'];

type PendingDte = {
  codigoGeneracion: string;
  tipoDocumento: string;
};

interface FacturaConfig {
  modoTransmision: ContingenciaOptionValue | 1 | 2;
  tipoContingencia?: ContingenciaOptionValue | null;
  motivoContingencia?: string | null;
  pendientesContingencia?: PendingDte[];
}

const props = defineProps<{ facturaId: string; config: FacturaConfig }>();

const confirmVisible = ref(false);
const errorVisible = ref(false);
const lossConfirmVisible = ref(false);
const statusMessage = ref('');
const saveErrorMessage = ref('');
const hasAttemptedSubmit = ref(false);

const modoTransmision = ref<number>(props.config?.modoTransmision ?? 1);
const tipoContingencia = ref<number | ''>(
  props.config?.modoTransmision === 2
    ? props.config?.tipoContingencia ?? ''
    : ''
);
const motivoContingencia = ref(props.config?.motivoContingencia ?? '');

const tipoSelect = ref<HTMLSelectElement>();
const motivoInput = ref<HTMLTextAreaElement>();

const pendingDtes = computed(() => props.config?.pendientesContingencia ?? []);
const hasPendingContingencia = computed(() => pendingDtes.value.length > 0);

const isContingencia = computed(() => modoTransmision.value === 2);
const requiresMotivo = computed(
  () => isContingencia.value && tipoContingencia.value === 5
);

const motivoLength = computed(() => motivoContingencia.value.length);

const tipoErrorMessage = computed(() => {
  if (!isContingencia.value) {
    return '';
  }
  const value = tipoContingencia.value;
  if (value === '' || value === null) {
    return 'Selecciona un tipo de contingencia (CAT-005).';
  }
  if (![1, 2, 3, 4, 5].includes(Number(value))) {
    return 'Selecciona un tipo de contingencia (CAT-005).';
  }
  return '';
});

const showTipoError = computed(
  () => hasAttemptedSubmit.value && tipoErrorMessage.value !== ''
);

const motivoErrorMessage = computed(() => {
  if (!requiresMotivo.value) {
    return '';
  }
  const trimmed = motivoContingencia.value.trim();
  if (!trimmed) {
    return "Motivo es obligatorio cuando el tipo es ‘Otro’ (máx. 500).";
  }
  if (trimmed.length > 500) {
    return 'Motivo no puede exceder 500 caracteres.';
  }
  return '';
});

const showMotivoError = computed(
  () => hasAttemptedSubmit.value && motivoErrorMessage.value !== ''
);

const isFormValid = computed(() => {
  if (!isContingencia.value) {
    return true;
  }
  return tipoErrorMessage.value === '' && motivoErrorMessage.value === '';
});

const isSaveDisabled = computed(
  () => isContingencia.value && hasAttemptedSubmit.value && !isFormValid.value
);

watch(modoTransmision, async (newValue, oldValue) => {
  if (oldValue === 2 && newValue === 1 && hasContingenciaData()) {
    lossConfirmVisible.value = true;
    await nextTick();
    modoTransmision.value = 2;
    return;
  }
  if (newValue !== 2) {
    tipoContingencia.value = '';
    motivoContingencia.value = '';
    hasAttemptedSubmit.value = false;
  }
});

watch(tipoContingencia, (newValue) => {
  if (newValue !== 5) {
    motivoContingencia.value = '';
  }
});

watch(motivoContingencia, (value) => {
  if (value.length > 500) {
    motivoContingencia.value = value.slice(0, 500);
  }
});

function hasContingenciaData(): boolean {
  const tipo = tipoContingencia.value;
  const motivo = motivoContingencia.value.trim();
  return tipo !== '' || motivo.length > 0;
}

function enforceMotivoLimit(): void {
  if (motivoContingencia.value.length > 500) {
    motivoContingencia.value = motivoContingencia.value.slice(0, 500);
  }
}

async function onSave() {
  hasAttemptedSubmit.value = true;
  statusMessage.value = '';
  saveErrorMessage.value = '';
  if (isContingencia.value) {
    if (!isFormValid.value) {
      await nextTick();
      focusFirstInvalid();
      return;
    }
    confirmVisible.value = true;
    return;
  }
  try {
    await enviarAHacienda();
  } catch (e) {
    errorVisible.value = true;
  }
}

async function saveContingencia() {
  try {
    const motivo = requiresMotivo.value
      ? motivoContingencia.value.trim()
      : undefined;
    await guardarEnContingencia(props.facturaId, {
      modeloFacturacion: 2,
      tipoTransmision: 2,
      tipoContingencia: Number(tipoContingencia.value),
      ...(motivo ? { motivoContingencia: motivo } : {})
    });
    statusMessage.value = 'Contingencia guardada en la factura.';
  } catch (error) {
    saveErrorMessage.value =
      error instanceof Error ? error.message : 'Ocurrió un error al guardar.';
  }
}

function focusFirstInvalid() {
  if (tipoErrorMessage.value && tipoSelect.value) {
    tipoSelect.value.focus();
    return;
  }
  if (motivoErrorMessage.value && motivoInput.value) {
    motivoInput.value.focus();
  }
}

function confirmClearContingencia() {
  lossConfirmVisible.value = false;
  modoTransmision.value = 1;
  tipoContingencia.value = '';
  motivoContingencia.value = '';
  hasAttemptedSubmit.value = false;
}

function cancelClearContingencia() {
  lossConfirmVisible.value = false;
}

function openEventoDialog() {
  eventoVisible.value = true;
  eventoStep.value = 1;
  resetEvento();
}

function closeEventoDialog() {
  eventoVisible.value = false;
}

function volverEvento() {
  eventoStep.value = 1;
}

const eventoVisible = ref(false);
const eventoStep = ref<1 | 2>(1);
const eventoForm = reactive({
  inicioFecha: '',
  inicioHora: '',
  finFecha: '',
  finHora: '',
  tipo: '' as number | '',
  motivo: ''
});
const eventoErrors = reactive({
  inicio: '',
  fin: '',
  tipo: '',
  motivo: ''
});

const eventoInicioFecha = ref<HTMLInputElement>();
const eventoInicioHora = ref<HTMLInputElement>();
const eventoFinFecha = ref<HTMLInputElement>();
const eventoFinHora = ref<HTMLInputElement>();
const eventoTipo = ref<HTMLSelectElement>();
const eventoMotivo = ref<HTMLTextAreaElement>();

const eventoRequiresMotivo = computed(() => eventoForm.tipo === 5);
const eventoMotivoLength = computed(() => eventoForm.motivo.length);

watch(
  () => eventoForm.tipo,
  (newValue) => {
    if (newValue !== 5) {
      eventoForm.motivo = '';
    }
  }
);

watch(
  () => eventoForm.motivo,
  (value) => {
    if (value.length > 500) {
      eventoForm.motivo = value.slice(0, 500);
    }
  }
);

function enforceEventoMotivoLimit() {
  if (eventoForm.motivo.length > 500) {
    eventoForm.motivo = eventoForm.motivo.slice(0, 500);
  }
}

function resetEvento() {
  eventoForm.inicioFecha = '';
  eventoForm.inicioHora = '';
  eventoForm.finFecha = '';
  eventoForm.finHora = '';
  eventoForm.tipo = '';
  eventoForm.motivo = '';
  eventoErrors.inicio = '';
  eventoErrors.fin = '';
  eventoErrors.tipo = '';
  eventoErrors.motivo = '';
}

function continuarEvento() {
  eventoErrors.inicio = '';
  eventoErrors.fin = '';
  eventoErrors.tipo = '';
  eventoErrors.motivo = '';

  const inicioCompleto =
    eventoForm.inicioFecha && eventoForm.inicioHora
      ? new Date(`${eventoForm.inicioFecha}T${eventoForm.inicioHora}`)
      : null;
  const finCompleto =
    eventoForm.finFecha && eventoForm.finHora
      ? new Date(`${eventoForm.finFecha}T${eventoForm.finHora}`)
      : null;

  if (!eventoForm.inicioFecha || !eventoForm.inicioHora) {
    eventoErrors.inicio = 'Completa la fecha y hora de inicio.';
  }
  if (!eventoForm.finFecha || !eventoForm.finHora) {
    eventoErrors.fin = 'Completa la fecha y hora de fin.';
  }
  if (inicioCompleto && finCompleto && finCompleto <= inicioCompleto) {
    eventoErrors.fin = 'La fecha/hora final debe ser mayor que la inicial.';
  }
  if (eventoForm.tipo === '' || eventoForm.tipo === null) {
    eventoErrors.tipo = 'Selecciona un tipo de contingencia (CAT-005).';
  }
  if (eventoRequiresMotivo.value) {
    const trimmed = eventoForm.motivo.trim();
    if (!trimmed) {
      eventoErrors.motivo =
        "Motivo es obligatorio cuando el tipo es ‘Otro’ (máx. 500).";
    }
  }

  if (
    eventoErrors.inicio ||
    eventoErrors.fin ||
    eventoErrors.tipo ||
    eventoErrors.motivo
  ) {
    focusEventoFirstInvalid();
    return;
  }

  eventoStep.value = 2;
}

function focusEventoFirstInvalid() {
  if (eventoErrors.inicio) {
    if (!eventoForm.inicioFecha && eventoInicioFecha.value) {
      eventoInicioFecha.value.focus();
      return;
    }
    if (!eventoForm.inicioHora && eventoInicioHora.value) {
      eventoInicioHora.value.focus();
      return;
    }
  }
  if (eventoErrors.fin) {
    if (!eventoForm.finFecha && eventoFinFecha.value) {
      eventoFinFecha.value.focus();
      return;
    }
    if (!eventoForm.finHora && eventoFinHora.value) {
      eventoFinHora.value.focus();
      return;
    }
  }
  if (eventoErrors.tipo && eventoTipo.value) {
    eventoTipo.value.focus();
    return;
  }
  if (eventoErrors.motivo && eventoMotivo.value) {
    eventoMotivo.value.focus();
  }
}

const eventoDetalleLimit = computed(() => pendingDtes.value.slice(0, 1000));

const eventoPreview = computed(() => {
  if (eventoStep.value !== 2) {
    return '';
  }
  const detalle = eventoDetalleLimit.value.map((dte) => ({
    codigoGeneracion: dte.codigoGeneracion,
    tipoDocumento: dte.tipoDocumento
  }));
  const motivo = eventoRequiresMotivo.value
    ? eventoForm.motivo.trim()
    : CONTINGENCIA_OPTIONS.find((o) => o.value === eventoForm.tipo)?.label ?? '';
  const payload = {
    identificacion: {
      tipoEvento: 'CONTINGENCIA',
      tipoContingencia: eventoForm.tipo,
      periodo: {
        inicio: `${eventoForm.inicioFecha}T${eventoForm.inicioHora}`,
        fin: `${eventoForm.finFecha}T${eventoForm.finHora}`
      }
    },
    emisor: {
      nit: '000000-0',
      nombre: 'Ejemplo S.A. de C.V.'
    },
    motivo,
    detalleDTE: detalle
  };
  return JSON.stringify(payload, null, 2);
});

function enviarAHacienda(): Promise<void> {
  return Promise.reject(new Error('fallo'));
}
</script>

<style scoped>
.factura-form {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.field,
.field-group {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.field.error select,
.field.error textarea,
.field-group.error input,
.field-group.error select,
.field-group.error textarea {
  border: 1px solid #c0392b;
}

.error-message {
  color: #c0392b;
  font-size: 0.875rem;
}

.helper {
  font-size: 0.875rem;
  color: #555;
}

.field-footer {
  display: flex;
  justify-content: flex-end;
  font-size: 0.875rem;
  color: #555;
}

.status {
  padding: 0.75rem;
  border-radius: 4px;
}

.status.success {
  background: #e8f5e9;
  color: #2e7d32;
}

.status.error {
  background: #fdecea;
  color: #c62828;
}

.actions {
  display: flex;
  gap: 1rem;
}

button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.evento-dialog {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.evento-content {
  background: #fff;
  padding: 1.5rem;
  border-radius: 8px;
  max-width: 600px;
  width: 100%;
  max-height: 90vh;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.evento-content header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.evento-content .cerrar {
  background: transparent;
  border: none;
  font-size: 1.5rem;
  cursor: pointer;
}

.inputs {
  display: flex;
  gap: 0.5rem;
}

.dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
}

.dialog-actions .primary {
  background: #1976d2;
  color: #fff;
  border: none;
  padding: 0.5rem 1rem;
  cursor: pointer;
}

.dte-list {
  max-height: 200px;
  overflow-y: auto;
  padding-left: 1rem;
}

.dte-list li {
  list-style: disc;
}

.json-preview {
  background: #f5f5f5;
  padding: 1rem;
  border-radius: 4px;
  max-height: 200px;
  overflow: auto;
}

.info {
  background: #fff7e6;
  color: #8c6d1f;
  padding: 0.5rem;
  border-radius: 4px;
}
</style>
