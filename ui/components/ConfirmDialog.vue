<template>
  <div v-if="modelValue" class="confirm-dialog">
    <h3>{{ title }}</h3>
    <p v-if="message" class="message">{{ message }}</p>
    <div v-if="hasDetails" class="details-section">
      <button
        type="button"
        class="details-toggle"
        @click="toggleDetails"
        :aria-expanded="detailsVisible ? 'true' : 'false'"
      >
        {{ detailsVisible ? hideDetailsLabel : detailsLabel }}
      </button>
      <pre v-if="detailsVisible" class="details-panel">{{ formattedDetails }}</pre>
    </div>
    <button type="button" @click="onCancel">{{ cancelText }}</button>
    <button type="button" @click="onConfirm">{{ confirmText }}</button>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';

defineOptions({ name: 'ConfirmDialog' });

const props = defineProps({
  modelValue: Boolean,
  title: String,
  message: String,
  confirmText: { type: String, default: 'Confirmar' },
  cancelText: { type: String, default: 'Cancelar' },
  details: { type: [String, Object], default: null },
  detailsLabel: { type: String, default: 'Ver detalles' },
  hideDetailsLabel: { type: String, default: 'Ocultar detalles' }
});

const emit = defineEmits(['update:modelValue', 'confirm', 'cancel']);

const detailsVisible = ref(false);

const formattedDetails = computed(() => normalizeDetails(props.details));
const hasDetails = computed(() => formattedDetails.value.trim().length > 0);

watch(
  () => props.modelValue,
  value => {
    if (!value) {
      detailsVisible.value = false;
    }
  }
);

watch(
  () => props.details,
  () => {
    detailsVisible.value = false;
  }
);

function toggleDetails() {
  detailsVisible.value = !detailsVisible.value;
}

function onConfirm() {
  emit('confirm');
  emit('update:modelValue', false);
}
function onCancel() {
  emit('cancel');
  emit('update:modelValue', false);
}

function normalizeDetails(details: unknown): string {
  if (details == null) {
    return '';
  }
  if (typeof details === 'string') {
    return details;
  }
  if (details instanceof Error) {
    const plain: Record<string, unknown> = {};
    for (const key of Object.getOwnPropertyNames(details)) {
      if (['name', 'message', 'stack'].includes(key)) {
        continue;
      }
      plain[key] = (details as Record<string, unknown>)[key];
    }
    if (!plain.message) {
      plain.message = details.message;
    }
    return normalizeDetails(plain);
  }
  try {
    return JSON.stringify(details, null, 2);
  } catch (error) {
    return String(details);
  }
}
</script>

<style scoped>
.details-section {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.details-toggle {
  align-self: flex-start;
  border: 1px solid currentColor;
  background: transparent;
  color: inherit;
  border-radius: 4px;
  padding: 0.25rem 0.75rem;
  font-size: 0.875rem;
  cursor: pointer;
}

.details-toggle:focus {
  outline: 2px solid currentColor;
  outline-offset: 2px;
}

.details-panel {
  background: #0f172a;
  color: #f8fafc;
  padding: 0.75rem;
  border-radius: 4px;
  max-height: 16rem;
  overflow: auto;
  font-family: ui-monospace, SFMono-Regular, SFMono, Menlo, Monaco, Consolas,
    'Liberation Mono', 'Courier New', monospace;
  white-space: pre-wrap;
  word-break: break-word;
  border: 1px solid rgba(15, 23, 42, 0.4);
}
</style>
