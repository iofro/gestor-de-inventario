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
      <div class="contingencia-actions">
        <button
          type="button"
          class="configurar-contingencia"
          ref="contingenciaButton"
          @click="openContingenciaDialog"
        >
          Configurar contingencia…
        </button>
        <button
          type="button"
          class="evento-trigger"
          :disabled="!hasPendingContingencia"
          :title="eventoTriggerTooltip"
          @click="openEventoPanel"
        >
          Evento de contingencia
        </button>
      </div>
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

    <section
      v-if="eventoPanelVisible"
      class="evento-panel"
      aria-label="Borrador de evento de contingencia"
    >
      <header class="evento-header">
        <h2>Evento de contingencia</h2>
        <p class="helper">Zona horaria: America/El_Salvador (UTC-6)</p>
      </header>

      <div class="panel-section">
        <h3>Datos del evento</h3>
        <div :class="['field-group', { error: eventoErrors.tipo }]">
          <label for="evento-tipo">Tipo (CAT-005)</label>
          <select
            id="evento-tipo"
            ref="eventoTipo"
            v-model.number="eventoForm.tipo"
            :aria-invalid="eventoErrors.tipo ? 'true' : 'false'"
            :aria-describedby="eventoErrors.tipo ? 'evento-tipo-error' : undefined"
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
          <p v-if="eventoErrors.tipo" id="evento-tipo-error" class="error-message">
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
            :maxlength="500"
            :aria-invalid="eventoErrors.motivo ? 'true' : 'false'"
            :aria-describedby="eventoErrors.motivo ? 'evento-motivo-error' : undefined"
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

        <div :class="['field-group', { error: eventoErrors.inicio }]">
          <label for="evento-inicio-fecha">Fecha y hora de inicio</label>
          <div class="inputs">
            <input
              id="evento-inicio-fecha"
              ref="eventoInicioFecha"
              v-model="eventoForm.inicioFecha"
              type="date"
              :aria-invalid="eventoErrors.inicio ? 'true' : 'false'"
              :aria-describedby="eventoErrors.inicio ? 'evento-inicio-error' : undefined"
            />
            <input
              id="evento-inicio-hora"
              ref="eventoInicioHora"
              v-model="eventoForm.inicioHora"
              type="time"
              :aria-invalid="eventoErrors.inicio ? 'true' : 'false'"
              :aria-describedby="eventoErrors.inicio ? 'evento-inicio-error' : undefined"
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
          <label for="evento-fin-fecha">Fecha y hora de fin</label>
          <div class="inputs">
            <input
              id="evento-fin-fecha"
              ref="eventoFinFecha"
              v-model="eventoForm.finFecha"
              type="date"
              :aria-invalid="eventoErrors.fin ? 'true' : 'false'"
              :aria-describedby="eventoErrors.fin ? 'evento-fin-error' : undefined"
            />
            <input
              id="evento-fin-hora"
              ref="eventoFinHora"
              v-model="eventoForm.finHora"
              type="time"
              :aria-invalid="eventoErrors.fin ? 'true' : 'false'"
              :aria-describedby="eventoErrors.fin ? 'evento-fin-error' : undefined"
            />
          </div>
          <p v-if="eventoErrors.fin" id="evento-fin-error" class="error-message">
            {{ eventoErrors.fin }}
          </p>
        </div>
      </div>

      <div class="panel-section revision">
        <h3>Revisión</h3>
        <p class="counter">{{ pendingDtes.length }} DTE pendientes</p>
        <p v-if="pendingDtes.length > 1000" class="info warning">
          Máximo 1000 por evento. Se deberá dividir en varios eventos.
        </p>
        <p v-if="eventoErrors.dtes" class="error-message">
          {{ eventoErrors.dtes }}
        </p>
        <ul
          ref="eventoDteList"
          class="dte-list"
          tabindex="-1"
          aria-label="Listado de DTE pendientes"
        >
          <li v-for="dte in eventoDetalleLimit" :key="dte.codigoGeneracion">
            {{ formatCodigoGeneracion(dte.codigoGeneracion) }} —
            {{ formatTipoDocumento(dte.tipoDocumento) }}
          </li>
        </ul>
        <p class="counter">
          Mostrando {{ eventoDetalleLimit.length }} de {{ pendingDtes.length }} (máx. 1000)
        </p>
        <h4>Previsualización (JSON)</h4>
        <pre class="json-preview">{{ eventoPreview }}</pre>
      </div>

      <section
        v-if="eventoDraftMessage"
        class="status success"
        role="status"
        aria-live="polite"
      >
        {{ eventoDraftMessage }}
      </section>

      <footer class="panel-actions">
        <button
          type="button"
          class="primary"
          :disabled="!eventoIsValid"
          @click="generarEventoBorrador"
        >
          Generar borrador
        </button>
        <button type="button" @click="closeEventoPanel">Cerrar</button>
      </footer>
    </section>

    <div class="actions">
      <button
        class="guardar"
        :disabled="isSaveDisabled"
        @click="onSave"
      >
        Guardar y Enviar
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
  ambiente?: string | null;
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
const eventoPanelVisible = ref(false);
const eventoDraftMessage = ref('');

type EventoTipo = ContingenciaOptionValue | null;
interface EventoFormState {
  tipo: EventoTipo;
  motivo: string;
  inicioFecha: string;
  inicioHora: string;
  finFecha: string;
  finHora: string;
}

type EventoErrorField = 'tipo' | 'motivo' | 'inicio' | 'fin' | 'dtes';

const eventoForm = reactive<EventoFormState>({
  tipo: contingenciaConfig.tipo ?? null,
  motivo:
    contingenciaConfig.tipo === 5
      ? contingenciaConfig.motivo.trim()
      : '',
  inicioFecha: '',
  inicioHora: '',
  finFecha: '',
  finHora: ''
});

const eventoErrors = reactive<Record<EventoErrorField, string>>({
  tipo: '',
  motivo: '',
  inicio: '',
  fin: '',
  dtes: ''
});

const eventoValidationActive = ref(false);

const eventoTipo = ref<HTMLSelectElement>();
const eventoMotivo = ref<HTMLTextAreaElement>();
const eventoInicioFecha = ref<HTMLInputElement>();
const eventoInicioHora = ref<HTMLInputElement>();
const eventoFinFecha = ref<HTMLInputElement>();
const eventoFinHora = ref<HTMLInputElement>();
const eventoDteList = ref<HTMLUListElement>();

const eventoRequiresMotivo = computed(() => eventoForm.tipo === 5);
const eventoMotivoLength = computed(() => eventoForm.motivo.length);
const eventoTriggerTooltip = computed(() => {
  if (!hasPendingContingencia.value) {
    return 'No hay DTE pendientes en contingencia.';
  }
  return undefined;
});

const eventoDetalleLimit = computed(() => pendingDtes.value.slice(0, 1000));

const ambienteTexto = computed(
  () => props.config?.ambiente?.trim() || 'DESCONOCIDO'
);

const eventoIsValid = computed(() => collectEventoErrors().firstInvalid === null);

const eventoPreview = computed(() => {
  if (!eventoPanelVisible.value) {
    return '';
  }
  const detalle = eventoDetalleLimit.value.map((dte, index) => ({
    noItem: index + 1,
    codigoGeneracion: formatCodigoGeneracion(dte.codigoGeneracion),
    tipoDoc: sanitizeTipoDoc(dte.tipoDocumento)
  }));
  const motivoDescripcion = eventoRequiresMotivo.value
    ? eventoForm.motivo.trim()
    : CONTINGENCIA_OPTIONS.find((o) => o.value === eventoForm.tipo)?.label ?? '';
  const { date: fechaTransmision, time: horaTransmision } =
    getNowInElSalvador();
  const payload = {
    identificacion: {
      version: 3,
      ambiente: ambienteTexto.value,
      codigoGeneracion: 'xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx',
      fTransmision: fechaTransmision,
      hTransmision: horaTransmision
    },
    motivo: {
      tipo: eventoForm.tipo ?? null,
      motivo: motivoDescripcion,
      fInicio: eventoForm.inicioFecha || '----',
      hInicio: eventoForm.inicioHora || '--:--',
      fFin: eventoForm.finFecha || '----',
      hFin: eventoForm.finHora || '--:--'
    },
    detalleDTE: detalle
  };
  return JSON.stringify(payload, null, 2);
});

watch(
  () => eventoForm.tipo,
  (value) => {
    if (value !== 5) {
      eventoForm.motivo = '';
    }
    if (eventoValidationActive.value) {
      refreshEventoValidation();
    }
  }
);

watch(
  () => eventoForm.motivo,
  (value) => {
    if (value.length > 500) {
      eventoForm.motivo = value.slice(0, 500);
    }
    if (eventoValidationActive.value) {
      refreshEventoValidation();
    }
  }
);

watch(
  () => [
    eventoForm.inicioFecha,
    eventoForm.inicioHora,
    eventoForm.finFecha,
    eventoForm.finHora
  ],
  () => {
    if (eventoValidationActive.value) {
      refreshEventoValidation();
    }
  }
);

watch(
  () => pendingDtes.value.length,
  () => {
    if (eventoValidationActive.value) {
      refreshEventoValidation();
    }
  }
);

function openEventoPanel() {
  if (!hasPendingContingencia.value) {
    return;
  }
  eventoPanelVisible.value = true;
  eventoDraftMessage.value = '';
  eventoValidationActive.value = true;
  eventoForm.tipo = contingenciaConfig.tipo ?? null;
  eventoForm.motivo =
    eventoForm.tipo === 5 ? contingenciaConfig.motivo.trim() : '';
  eventoForm.inicioFecha = '';
  eventoForm.inicioHora = '';
  eventoForm.finFecha = '';
  eventoForm.finHora = '';
  clearEventoErrors();
  nextTick(() => {
    refreshEventoValidation({ focus: true });
  });
}

function closeEventoPanel() {
  eventoPanelVisible.value = false;
  eventoDraftMessage.value = '';
  eventoValidationActive.value = false;
  clearEventoErrors();
}

function generarEventoBorrador() {
  const { isValid } = refreshEventoValidation({ focus: true });
  if (!isValid) {
    return;
  }
  eventoDraftMessage.value = 'Borrador generado (solo UI).';
}

function enforceEventoMotivoLimit() {
  if (eventoForm.motivo.length > 500) {
    eventoForm.motivo = eventoForm.motivo.slice(0, 500);
  }
}

function clearEventoErrors() {
  (Object.keys(eventoErrors) as EventoErrorField[]).forEach((key) => {
    eventoErrors[key] = '';
  });
}

function refreshEventoValidation({ focus = false } = {}) {
  const { errors, firstInvalid, isValid } = collectEventoErrors();
  (Object.keys(eventoErrors) as EventoErrorField[]).forEach((key) => {
    eventoErrors[key] = errors[key] ?? '';
  });
  if (focus && firstInvalid) {
    focusEventoField(firstInvalid);
  }
  return { isValid };
}

function collectEventoErrors(): {
  errors: Partial<Record<EventoErrorField, string>>;
  firstInvalid: EventoErrorField | null;
  isValid: boolean;
} {
  const errors: Partial<Record<EventoErrorField, string>> = {};
  let firstInvalid: EventoErrorField | null = null;

  const tipoVal = eventoForm.tipo;
  if (tipoVal === null || Number.isNaN(tipoVal) || tipoVal < 1 || tipoVal > 5) {
    errors.tipo = 'Selecciona un tipo de contingencia (CAT-005).';
    firstInvalid = firstInvalid ?? 'tipo';
  }

  if (eventoRequiresMotivo.value) {
    const trimmed = eventoForm.motivo.trim();
    if (!trimmed) {
      errors.motivo =
        'Motivo es obligatorio cuando el tipo es “Otro” (máx. 500).';
      firstInvalid = firstInvalid ?? 'motivo';
    }
  }

  if (!eventoForm.inicioFecha || !eventoForm.inicioHora) {
    errors.inicio = 'Completa la fecha y hora de inicio.';
    firstInvalid = firstInvalid ?? 'inicio';
  }

  if (!eventoForm.finFecha || !eventoForm.finHora) {
    errors.fin = 'Completa la fecha y hora de fin.';
    firstInvalid = firstInvalid ?? 'fin';
  }

  if (
    eventoForm.inicioFecha &&
    eventoForm.inicioHora &&
    eventoForm.finFecha &&
    eventoForm.finHora
  ) {
    const inicio = new Date(`${eventoForm.inicioFecha}T${eventoForm.inicioHora}`);
    const fin = new Date(`${eventoForm.finFecha}T${eventoForm.finHora}`);
    if (!(fin > inicio)) {
      errors.fin = 'La fecha/hora final debe ser mayor que la inicial.';
      firstInvalid = firstInvalid ?? 'fin';
    }
  }

  if (pendingDtes.value.length === 0) {
    errors.dtes = 'Debe existir al menos un DTE pendiente.';
    firstInvalid = firstInvalid ?? 'dtes';
  } else if (pendingDtes.value.length > 1000) {
    errors.dtes = 'Máximo 1000 DTE por evento.';
    firstInvalid = firstInvalid ?? 'dtes';
  }

  return { errors, firstInvalid, isValid: firstInvalid === null };
}

function focusEventoField(field: EventoErrorField) {
  if (field === 'tipo' && eventoTipo.value) {
    eventoTipo.value.focus();
    return;
  }
  if (field === 'motivo' && eventoMotivo.value) {
    eventoMotivo.value.focus();
    return;
  }
  if (field === 'inicio') {
    if (eventoInicioFecha.value) {
      eventoInicioFecha.value.focus();
      return;
    }
    if (eventoInicioHora.value) {
      eventoInicioHora.value.focus();
      return;
    }
  }
  if (field === 'fin') {
    if (eventoFinFecha.value) {
      eventoFinFecha.value.focus();
      return;
    }
    if (eventoFinHora.value) {
      eventoFinHora.value.focus();
      return;
    }
  }
  if (field === 'dtes' && eventoDteList.value) {
    eventoDteList.value.focus();
  }
}

function getNowInElSalvador() {
  const now = new Date();
  const dateFormatter = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'America/El_Salvador',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit'
  });
  const timeFormatter = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'America/El_Salvador',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false
  });
  return {
    date: dateFormatter.format(now),
    time: timeFormatter.format(now)
  };
}

function sanitizeTipoDoc(tipo: unknown): string {
  const numeric = Number.parseInt(String(tipo ?? '').replace(/[^0-9]/g, ''), 10);
  if (Number.isNaN(numeric)) {
    return '01';
  }
  const bounded = Math.min(15, Math.max(1, numeric));
  return String(bounded).padStart(2, '0');
}

function formatTipoDocumento(tipo: unknown): string {
  return sanitizeTipoDoc(tipo);
}

function formatCodigoGeneracion(codigo: unknown): string {
  return String(codigo ?? '').toUpperCase();
}

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

.contingencia-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
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

.evento-trigger {
  border: 1px solid #3949ab;
  color: #1a237e;
  background: #eef2ff;
  border-radius: 4px;
  padding: 0.5rem 1rem;
  cursor: pointer;
}

.evento-trigger:disabled {
  background: #f3f4f6;
  border-color: #d0d7de;
  color: #7a7a7a;
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

.evento-panel {
  border: 1px solid #d0d7de;
  border-radius: 8px;
  padding: 1rem;
  background: #fff;
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.evento-header {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.evento-panel h2 {
  margin: 0;
}

.panel-section {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.panel-section h3 {
  margin: 0;
}

.panel-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
}

.panel-actions button {
  border: 1px solid #d0d7de;
  background: #fff;
  color: #1f2933;
  padding: 0.5rem 1rem;
  border-radius: 4px;
  cursor: pointer;
}

.panel-actions .primary {
  background: #1976d2;
  color: #fff;
  border: none;
  padding: 0.5rem 1rem;
  cursor: pointer;
  border-radius: 4px;
}

.panel-actions button:disabled {
  cursor: not-allowed;
}

.panel-actions .primary:disabled {
  background: #c9d6ff;
  color: #5f6caf;
}

.actions {
  display: flex;
  gap: 1rem;
}

button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.inputs {
  display: flex;
  gap: 0.5rem;
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

.warning {
  border: 1px solid #f0ad4e;
}
</style>
