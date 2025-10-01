<template>
  <div v-if="visible" class="contingencia-dialog-overlay">
    <div class="contingencia-dialog" role="dialog" aria-modal="true">
      <header class="dialog-header">
        <h2>Configurar contingencia</h2>
        <button
          type="button"
          class="close"
          @click="requestClose"
          aria-label="Cerrar"
        >
          ×
        </button>
      </header>
      <section class="dialog-body">
        <p class="helper">
          Tipo de Contingencia (CAT-005) — obligatorio. Si seleccionas “Otro”,
          el motivo es obligatorio.
        </p>
        <div :class="['field', { error: showTipoError }]">
          <label for="contingencia-tipo">Tipo de Contingencia (CAT-005)</label>
          <select
            id="contingencia-tipo"
            ref="tipoSelect"
            v-model.number="form.tipo"
            :aria-invalid="showTipoError ? 'true' : 'false'"
            :aria-describedby="
              showTipoError ? 'contingencia-tipo-error' : undefined
            "
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
          <p
            v-if="showTipoError"
            id="contingencia-tipo-error"
            class="error-message"
          >
            Selecciona un tipo de contingencia (CAT-005).
          </p>
        </div>

        <div v-if="requiresMotivo" :class="['field', { error: showMotivoError }]">
          <label for="contingencia-motivo">Motivo</label>
            <textarea
              id="contingencia-motivo"
              ref="motivoInput"
              v-model="form.motivo"
              rows="3"
              @input="enforceMotivoLimit"
              :aria-invalid="showMotivoError ? 'true' : 'false'"
              :aria-describedby="
                showMotivoError ? 'contingencia-motivo-error' : undefined
              "
            ></textarea>
          <div class="field-footer">
            <span class="counter">{{ motivoLength }}/500</span>
          </div>
          <p
            v-if="showMotivoError"
            id="contingencia-motivo-error"
            class="error-message"
          >
            Motivo es obligatorio cuando el tipo es ‘Otro’ (máx. 500).
          </p>
        </div>

        <section class="evento-informativo">
          <h3>Evento de contingencia (informativo)</h3>
          <p class="helper">Zona horaria: America/El_Salvador (UTC-6)</p>
          <div class="field-group">
            <label>Fecha y hora de inicio</label>
            <input type="datetime-local" disabled />
          </div>
          <div class="field-group">
            <label>Fecha y hora de fin</label>
            <input type="datetime-local" disabled />
          </div>
        </section>
      </section>
      <footer class="dialog-footer">
        <button type="button" @click="requestClose">Cancelar</button>
        <button
          type="button"
          class="primary"
          :disabled="confirmDisabled"
          @click="handleConfirm"
        >
          Confirmar
        </button>
      </footer>
    </div>

    <ConfirmDialog
      v-model="discardDialogVisible"
      title="Descartar cambios"
      message="Tienes cambios sin guardar. ¿Deseas descartarlos?"
      confirm-text="Descartar"
      cancel-text="Seguir editando"
      @confirm="confirmDiscard"
      @cancel="cancelDiscard"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, reactive, ref, watch } from 'vue';
import ConfirmDialog from './ConfirmDialog.vue';

const CONTINGENCIA_OPTIONS = [
  { value: 1, label: '1 — No disponibilidad del sistema del MH' },
  { value: 2, label: '2 — No disponibilidad del sistema del emisor' },
  { value: 3, label: '3 — Falla en servicio de Internet del emisor' },
  { value: 4, label: '4 — Falla en energía eléctrica del emisor' },
  { value: 5, label: '5 — Otro' }
] as const;

type ContingenciaOptionValue = (typeof CONTINGENCIA_OPTIONS)[number]['value'];

type ContingenciaFormState = {
  tipo: ContingenciaOptionValue | null;
  motivo: string;
};

const props = defineProps<{
  visible: boolean;
  initialConfig: ContingenciaFormState;
}>();

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void;
  (e: 'confirm', payload: { tipo: ContingenciaOptionValue; motivo?: string }): void;
  (e: 'cancel'): void;
}>();

const form = reactive<ContingenciaFormState>({ tipo: null, motivo: '' });
const tipoSelect = ref<HTMLSelectElement>();
const motivoInput = ref<HTMLTextAreaElement>();
const discardDialogVisible = ref(false);
const pristineSnapshot = ref<ContingenciaFormState>({ tipo: null, motivo: '' });

watch(
  () => props.visible,
  async (visible) => {
    if (visible) {
      const rawTipo = props.initialConfig?.tipo ?? null;
      const tipo =
        rawTipo !== null &&
        CONTINGENCIA_OPTIONS.some(option => option.value === rawTipo)
          ? rawTipo
          : null;
      const motivo = props.initialConfig?.motivo?.slice(0, 500) ?? '';
      pristineSnapshot.value = { tipo, motivo };
      form.tipo = tipo;
      form.motivo = motivo;
      await nextTick();
      if (tipoSelect.value) {
        tipoSelect.value.focus();
      }
    } else {
      discardDialogVisible.value = false;
    }
  }
);

const visible = computed({
  get: () => props.visible,
  set: (value: boolean) => emit('update:visible', value)
});

const requiresMotivo = computed(() => form.tipo === 5);
const motivoLength = computed(() => form.motivo.length);

const tipoError = computed(
  () =>
    form.tipo === null ||
    !CONTINGENCIA_OPTIONS.some(option => option.value === form.tipo)
);
const motivoError = computed(() => {
  if (!requiresMotivo.value) {
    return false;
  }
  return form.motivo.trim().length === 0;
});

const showTipoError = computed(() => tipoError.value);
const showMotivoError = computed(() => motivoError.value);

const confirmDisabled = computed(
  () => tipoError.value || (requiresMotivo.value && motivoError.value)
);

const isDirty = computed(() => {
  if (form.tipo !== pristineSnapshot.value.tipo) {
    return true;
  }
  return form.motivo !== pristineSnapshot.value.motivo;
});

watch(
  () => form.tipo,
  (value) => {
    if (
      value !== null &&
      !CONTINGENCIA_OPTIONS.some(option => option.value === value)
    ) {
      form.tipo = null;
    }
  }
);

function enforceMotivoLimit() {
  if (form.motivo.length > 500) {
    form.motivo = form.motivo.slice(0, 500);
  }
}

function handleConfirm() {
  if (tipoError.value) {
    if (tipoSelect.value) {
      tipoSelect.value.focus();
    }
    return;
  }
  if (requiresMotivo.value && motivoError.value) {
    if (motivoInput.value) {
      motivoInput.value.focus();
    }
    return;
  }
  emit('confirm', {
    tipo: form.tipo as ContingenciaOptionValue,
    ...(requiresMotivo.value ? { motivo: form.motivo.trim() } : {})
  });
  emit('update:visible', false);
}

function requestClose() {
  if (isDirty.value) {
    discardDialogVisible.value = true;
    return;
  }
  emit('update:visible', false);
  emit('cancel');
}

function confirmDiscard() {
  discardDialogVisible.value = false;
  emit('update:visible', false);
  emit('cancel');
}

function cancelDiscard() {
  discardDialogVisible.value = false;
}
</script>

<style scoped>
.contingencia-dialog-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.contingencia-dialog {
  background: #fff;
  border-radius: 8px;
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.2);
  max-width: 480px;
  width: 100%;
  display: flex;
  flex-direction: column;
  max-height: 90vh;
}

.dialog-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1rem 1.25rem;
  border-bottom: 1px solid #e0e0e0;
}

.dialog-body {
  padding: 1.25rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 0.75rem;
  padding: 1rem 1.25rem;
  border-top: 1px solid #e0e0e0;
}

.close {
  background: transparent;
  border: none;
  font-size: 1.5rem;
  line-height: 1;
  cursor: pointer;
}

.field,
.field-group {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.field select,
.field textarea,
.field-group input {
  border: 1px solid #ccc;
  border-radius: 4px;
  padding: 0.5rem;
  font-size: 1rem;
}

.field.error select,
.field.error textarea {
  border-color: #c0392b;
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

.counter {
  font-variant-numeric: tabular-nums;
}

.dialog-footer .primary {
  background-color: #2c3e50;
  color: #fff;
  border: none;
  border-radius: 4px;
  padding: 0.5rem 1rem;
  cursor: pointer;
}

.dialog-footer button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.evento-informativo {
  padding: 1rem;
  border: 1px dashed #ccc;
  border-radius: 6px;
  background: #fafafa;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.evento-informativo input {
  background: #f0f0f0;
  color: #666;
}
</style>
