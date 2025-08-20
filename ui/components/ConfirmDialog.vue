<template>
  <div v-if="modelValue" class="confirm-dialog">
    <h3>{{ title }}</h3>
    <p>{{ message }}</p>
    <button @click="onCancel">{{ cancelText }}</button>
    <button @click="onConfirm">{{ confirmText }}</button>
  </div>
</template>

<script setup lang="ts">
import { defineProps, defineEmits, defineOptions } from 'vue';

defineOptions({ name: 'ConfirmDialog' });

const props = defineProps({
  modelValue: Boolean,
  title: String,
  message: String,
  confirmText: { type: String, default: 'Confirmar' },
  cancelText: { type: String, default: 'Cancelar' }
});

const emit = defineEmits(['update:modelValue', 'confirm', 'cancel']);

function onConfirm() {
  emit('confirm');
  emit('update:modelValue', false);
}
function onCancel() {
  emit('cancel');
  emit('update:modelValue', false);
}
</script>
