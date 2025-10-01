<template>
  <div class="factura-form">
    <section class="modo-transmision">
      <label for="modo">Modo de transmisión</label>
      <select
        id="modo"
        ref="modoSelect"
        v-model.number="modoTransmision"
        aria-label="Selecciona el modo de transmisión"
      >
        <option :value="1">1 — Normal</option>
        <option :value="2">2 — Contingencia</option>
      </select>
    </section>

    <section v-if="isContingencia" class="contingencia-panel">
      <button
        type="button"
        class="configurar-contingencia"
        ref="contingenciaButton"
        @click="openContingenciaDialog"
      >
        Configurar contingencia…
      </button>
      <div class="contingencia-resumen" aria-live="polite">
        <span v-if="contingenciaSummary" class="chip">
          {{ contingenciaSummary }}
        </span>
      </div>
    </section>

    <section
      v-if="statusMessage"
      class="status success"
      role="status"
      aria-live="polite"
    >
      {{ statusMessage }}
    </section>
    <section
      v-if="saveErrorMessage"
      class="status error"
      role="alert"
      aria-live="assertive"
    >
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
      message="Perderás la configuración de contingencia. ¿Continuar?"
      confirm-text="Continuar"
      cancel-text="Cancelar"
      @confirm="confirmClearContingencia"
      @cancel="cancelClearContingencia"
    />

    <ContingenciaConfigDialog
      v-model:visible="contingenciaDialogVisible"
      :initial-config="contingenciaDialogInitial"
      @confirm="handleContingenciaConfirm"
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
                :aria-invalid="eventoErrors.inicio ? 'true' : 'false'"
                :aria-describedby="
                  eventoErrors.inicio ? 'evento-inicio-error' : undefined
                "
              />
              <input
                type="time"
                ref="eventoInicioHora"
                v-model="eventoForm.inicioHora"
                :aria-invalid="eventoErrors.inicio ? 'true' : 'false'"
                :aria-describedby="
                  eventoErrors.inicio ? 'evento-inicio-error' : undefined
                "
              />
            </div>
            <p
              v-if="eventoErrors.inicio"
              id="evento-inicio-error"
              class="error-message"
            >
              {{ eventoErrors.inicio }}
            </p>
          </div>
          <div :class="['field-group', { error: eventoErrors.fin }]">
            <label>Fecha y hora de fin</label>
            <div class="inputs">
              <input
                type="date"
                ref="eventoFinFecha"
                v-model="eventoForm.finFecha"
                :aria-invalid="eventoErrors.fin ? 'true' : 'false'"
                :aria-describedby="
                  eventoErrors.fin ? 'evento-fin-error' : undefined
                "
              />
              <input
                type="time"
                ref="eventoFinHora"
                v-model="eventoForm.finHora"
                :aria-invalid="eventoErrors.fin ? 'true' : 'false'"
                :aria-describedby="
                  eventoErrors.fin ? 'evento-fin-error' : undefined
                "
              />
            </div>
            <p
              v-if="eventoErrors.fin"
              id="evento-fin-error"
              class="error-message"
            >
              {{ eventoErrors.fin }}
            </p>
          </div>
          <div :class="['field-group', { error: eventoErrors.tipo }]">
            <label for="evento-tipo">Tipo (CAT-005)</label>
            <select
              id="evento-tipo"
              ref="eventoTipo"
              v-model.number="eventoForm.tipo"
              :aria-invalid="eventoErrors.tipo ? 'true' : 'false'"
              :aria-describedby="
                eventoErrors.tipo ? 'evento-tipo-error' : undefined
              "
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
            <p
              v-if="eventoErrors.tipo"
              id="evento-tipo-error"
              class="error-message"
            >
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
              :aria-invalid="eventoErrors.motivo ? 'true' : 'false'"
              :aria-describedby="
                eventoErrors.motivo ? 'evento-motivo-error' : undefined
              "
            ></textarea>
            <div class="field-footer">
              <span class="counter">{{ eventoMotivoLength }}/500</span>
            </div>
            <p
              v-if="eventoErrors.motivo"
              id="evento-motivo-error"
              class="error-message"
            >
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
          <p class="counter">Mostrando {{ eventoDetalleLimit.length }} de {{ pendingDtes.length }} (máx. 1000)</p>
          <button
            type="button"
            class="copy-codes"
            @click="copyEventoCodigos"
          >
            Copiar códigos
          </button>
          <p
            v-if="eventoCopyMessage"
            class="copy-status"
            role="status"
            aria-live="polite"
          >
            {{ eventoCopyMessage }}
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
import ContingenciaConfigDialog from '../components/ContingenciaConfigDialog.vue';
import { guardarEnContingencia } from '../services/facturasApi';

const CONTINGENCIA_OPTIONS = [
  { value: 1, label: '1 — No disponibilidad del sistema del MH' },
  { value: 2, label: '2 — No disponibilidad del sistema del emisor' },
  { value: 3, label: '3 — Falla en servicio de Internet del emisor' },
  { value: 4, label: '4 — Falla en energía eléctrica del emisor' },
  { value: 5, label: '5 — Otro' }
] as const;

type ContingenciaOptionValue = (typeof CONTINGENCIA_OPTIONS)[number]['value'];
type ModoTransmision = 1 | 2;
type ModoTransmisionInput =
  | ModoTransmision
  | `${ModoTransmision}`
  | number
  | string
  | null
  | undefined;

type PendingDte = {
  codigoGeneracion: string;
  tipoDocumento: string;
};

interface FacturaConfig {
  modoTransmision: ModoTransmisionInput;
  tipoContingencia?: ContingenciaOptionValue | null;
  motivoContingencia?: string | null;
  pendientesContingencia?: PendingDte[];
}

interface ContingenciaConfigState {
  tipo: ContingenciaOptionValue | null;
  motivo: string;
}

const props = defineProps<{ facturaId: string; config: FacturaConfig }>();

const confirmVisible = ref(false);
const errorVisible = ref(false);
const lossConfirmVisible = ref(false);
const statusMessage = ref('');
const saveErrorMessage = ref('');

const modoSelect = ref<HTMLSelectElement>();
const contingenciaButton = ref<HTMLButtonElement>();

function sanitizeModo(value: ModoTransmisionInput): ModoTransmision {
  if (value === 2 || value === '2') {
    return 2;
  }
  if (value === 1 || value === '1') {
    return 1;
  }
  if (typeof value === 'string') {
    const parsed = Number.parseInt(value, 10);
    if (parsed === 2) {
      return 2;
    }
    if (parsed === 1) {
      return 1;
    }
  }
  if (typeof value === 'number' && !Number.isNaN(value)) {
    return value === 2 ? 2 : 1;
  }
  return 1;
}

const modoTransmision = ref<ModoTransmision>(
  sanitizeModo(props.config?.modoTransmision)
);
const isProgrammaticModoChange = ref(false);
const initialIsContingencia = modoTransmision.value === 2;
const contingenciaConfig = reactive<ContingenciaConfigState>({
  tipo: initialIsContingencia ? props.config?.tipoContingencia ?? null : null,
  motivo: initialIsContingencia
    ? props.config?.motivoContingencia?.trim() ?? ''
    : ''
});
const contingenciaConfigured = ref(
  initialIsContingencia &&
    contingenciaConfig.tipo !== null &&
    (contingenciaConfig.tipo !== 5 || contingenciaConfig.motivo.trim().length > 0)
);

const contingenciaDialogVisible = ref(false);
const contingenciaDialogInitial = ref<ContingenciaConfigState>({
  tipo: contingenciaConfig.tipo,
  motivo: contingenciaConfig.motivo
});

const pendingDtes = computed(() => props.config?.pendientesContingencia ?? []);
const hasPendingContingencia = computed(() => pendingDtes.value.length > 0);

const isContingencia = computed(() => modoTransmision.value === 2);
const contingenciaSummary = computed(() => {
  if (!contingenciaConfigured.value || contingenciaConfig.tipo === null) {
    return '';
  }
  const base = `En contingencia: Tipo ${contingenciaConfig.tipo}`;
  if (contingenciaConfig.tipo === 5 && contingenciaConfig.motivo.trim()) {
    return `${base} — Motivo capturado`;
  }
  return base;
});

function resetContingenciaState() {
  contingenciaConfig.tipo = null;
  contingenciaConfig.motivo = '';
  contingenciaConfigured.value = false;
  statusMessage.value = '';
  saveErrorMessage.value = '';
}

function applyConfigFromProps(config: FacturaConfig) {
  const sanitizedModo = sanitizeModo(config?.modoTransmision);
  if (sanitizedModo !== modoTransmision.value) {
    isProgrammaticModoChange.value = true;
    modoTransmision.value = sanitizedModo;
    nextTick(() => {
      isProgrammaticModoChange.value = false;
    });
  }
  if (sanitizedModo === 2) {
    contingenciaConfig.tipo = config?.tipoContingencia ?? null;
    contingenciaConfig.motivo = config?.motivoContingencia?.trim() ?? '';
    contingenciaConfigured.value =
      contingenciaConfig.tipo !== null &&
      (contingenciaConfig.tipo !== 5 || contingenciaConfig.motivo.trim().length > 0);
  } else {
    resetContingenciaState();
  }
}

const isSaveDisabled = computed(() => false);
const eventoCopyMessage = ref('');

watch(modoTransmision, async (newValue, oldValue) => {
  if (isProgrammaticModoChange.value) {
    if (newValue !== 2) {
      resetContingenciaState();
    }
    return;
  }
  if (oldValue === 2 && newValue === 1 && hasContingenciaData()) {
    lossConfirmVisible.value = true;
    await nextTick();
    modoTransmision.value = 2;
    return;
  }
  if (newValue !== 2) {
    resetContingenciaState();
  }
});

watch(
  () => [
    props.config.modoTransmision,
    props.config.tipoContingencia,
    props.config.motivoContingencia
  ] as const,
  () => {
    applyConfigFromProps(props.config);
  }
);

function hasContingenciaData(): boolean {
  if (contingenciaConfigured.value) {
    return true;
  }
  return (
    contingenciaConfig.tipo !== null || contingenciaConfig.motivo.trim().length > 0
  );
}

async function onSave() {
  statusMessage.value = '';
  saveErrorMessage.value = '';
  if (isContingencia.value) {
    if (!contingenciaConfigured.value) {
      saveErrorMessage.value =
        'Completa la configuración de contingencia antes de guardar.';
      await nextTick();
      focusMainContingenciaTrigger();
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
    if (contingenciaConfig.tipo === null) {
      throw new Error('Configuración de contingencia incompleta.');
    }
    const motivo =
      contingenciaConfig.tipo === 5
        ? contingenciaConfig.motivo.trim()
        : undefined;
    await guardarEnContingencia(props.facturaId, {
      modeloFacturacion: 2,
      tipoTransmision: 2,
      tipoContingencia: Number(contingenciaConfig.tipo),
      ...(motivo ? { motivoContingencia: motivo } : {})
    });
    statusMessage.value = 'Contingencia guardada en la factura.';
  } catch (error) {
    saveErrorMessage.value =
      error instanceof Error ? error.message : 'Ocurrió un error al guardar.';
  }
}

function confirmClearContingencia() {
  lossConfirmVisible.value = false;
  isProgrammaticModoChange.value = true;
  modoTransmision.value = 1;
  resetContingenciaState();
  nextTick(() => {
    isProgrammaticModoChange.value = false;
  });
}

function cancelClearContingencia() {
  lossConfirmVisible.value = false;
}

function openContingenciaDialog() {
  contingenciaDialogInitial.value = {
    tipo: contingenciaConfig.tipo,
    motivo: contingenciaConfig.motivo
  };
  contingenciaDialogVisible.value = true;
}

function handleContingenciaConfirm({
  tipo,
  motivo
}: {
  tipo: ContingenciaOptionValue;
  motivo?: string;
}) {
  contingenciaConfig.tipo = tipo;
  contingenciaConfig.motivo = motivo?.trim() ?? '';
  contingenciaConfigured.value = true;
  contingenciaDialogVisible.value = false;
  saveErrorMessage.value = '';
}

function openEventoDialog() {
  eventoVisible.value = true;
  eventoStep.value = 1;
  resetEvento();
}

function closeEventoDialog() {
  eventoVisible.value = false;
  eventoCopyMessage.value = '';
}

function volverEvento() {
  eventoStep.value = 1;
  eventoCopyMessage.value = '';
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
  eventoCopyMessage.value = '';
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
  const detalle = eventoDetalleLimit.value.map((dte, index) => ({
    noItem: index + 1,
    codigoGeneracion: dte.codigoGeneracion.toUpperCase(),
    tipoDoc: dte.tipoDocumento
  }));
  const descripcionMotivo = eventoRequiresMotivo.value
    ? eventoForm.motivo.trim()
    : CONTINGENCIA_OPTIONS.find((o) => o.value === eventoForm.tipo)?.label ?? '';
  const payload = {
    identificacion: {
      version: 3,
      ambiente: '00',
      tipoEvento: 'CONTINGENCIA',
      tipoContingencia: eventoForm.tipo || null,
      codigoGeneracion: '00000000-0000-0000-0000-000000000000',
      fTransmision: eventoForm.inicioFecha || '----',
      hTransmision: eventoForm.inicioHora || '--:--'
    },
    motivo: {
      tipoContingencia: eventoForm.tipo || null,
      descripcion: descripcionMotivo,
      fInicio: eventoForm.inicioFecha || '----',
      hInicio: eventoForm.inicioHora || '--:--',
      fFin: eventoForm.finFecha || '----',
      hFin: eventoForm.finHora || '--:--'
    },
    detalleDTE: detalle
  };
  return JSON.stringify(payload, null, 2);
});

function enviarAHacienda(): Promise<void> {
  return Promise.reject(new Error('fallo'));
}

function focusMainContingenciaTrigger() {
  if (contingenciaButton.value) {
    contingenciaButton.value.focus();
    return;
  }
  if (modoSelect.value) {
    modoSelect.value.focus();
  }
}

async function copyEventoCodigos() {
  const codes = eventoDetalleLimit.value
    .map((dte) => dte.codigoGeneracion.toUpperCase())
    .join('\n');
  if (!codes) {
    eventoCopyMessage.value = 'No hay códigos para copiar.';
    return;
  }
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(codes);
    } else {
      const textarea = document.createElement('textarea');
      textarea.value = codes;
      textarea.setAttribute('readonly', 'true');
      textarea.style.position = 'absolute';
      textarea.style.left = '-9999px';
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand('copy');
      document.body.removeChild(textarea);
    }
    eventoCopyMessage.value = 'Códigos copiados al portapapeles.';
  } catch (error) {
    eventoCopyMessage.value = 'No se pudieron copiar los códigos.';
  }
}
</script>

<style scoped>
.factura-form {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.contingencia-panel {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  align-items: flex-start;
}

.configurar-contingencia {
  background-color: #2c3e50;
  color: #fff;
  border: none;
  border-radius: 4px;
  padding: 0.5rem 1rem;
  cursor: pointer;
}

.configurar-contingencia:hover {
  background-color: #1f2e3a;
}

.contingencia-resumen {
  min-height: 1.5rem;
}

.chip {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  background: #e3f2fd;
  color: #0d47a1;
  padding: 0.25rem 0.75rem;
  border-radius: 9999px;
  font-size: 0.875rem;
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

.copy-codes {
  align-self: flex-start;
  background: #1976d2;
  color: #fff;
  border: none;
  border-radius: 4px;
  padding: 0.4rem 0.75rem;
  cursor: pointer;
}

.copy-codes:hover {
  background: #125a9c;
}

.copy-status {
  font-size: 0.875rem;
  color: #2e7d32;
}
</style>
