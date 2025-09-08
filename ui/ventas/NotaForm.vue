<template>
  <div class="nota-form">
    <div class="right-column">
      <div>Base gravada: {{ nota.baseGravada }}</div>
      <div>Base exenta: {{ nota.exenta }}</div>
      <div>No sujeta: {{ nota.noSujeta }}</div>
      <div>IVA: {{ nota.iva }}</div>
      <div>Total: {{ nota.total }}</div>
      <div>Total en letras: {{ nota.totalLetras }}</div>
      <div>Documento relacionado: {{ nota.documentoRelacionado }}</div>
      <div>
        Crédito: <span class="badge" :class="{ red: excedeSaldo }">{{ nota.credito }}</span>
      </div>
    </div>
    <div class="actions">
      <button @click="onPreviewPdf">Previsualizar PDF</button>
      <button @click="onPreviewJson">Previsualizar JSON</button>
      <button @click="onGuardarBorrador">Guardar borrador</button>
      <button @click="onFirmarTransmitir">Firmar &amp; Transmitir</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { previsualizarPdf, previsualizarJson, guardarBorrador, firmarTransmitir } from '../services/notasApi';

const props = defineProps<{
  nota: {
    id: string;
    baseGravada: number;
    exenta: number;
    noSujeta: number;
    iva: number;
    total: number;
    totalLetras: string;
    documentoRelacionado: string;
    credito: number;
  };
  saldoDisponible: number;
}>();

const excedeSaldo = computed(() => props.nota.credito > props.saldoDisponible);

function validar() {
  return !excedeSaldo.value;
}

async function onPreviewPdf() {
  if (validar()) {
    await previsualizarPdf(props.nota.id);
  }
}

async function onPreviewJson() {
  if (validar()) {
    await previsualizarJson(props.nota.id);
  }
}

async function onGuardarBorrador() {
  if (validar()) {
    await guardarBorrador(props.nota);
  }
}

async function onFirmarTransmitir() {
  if (validar()) {
    await firmarTransmitir(props.nota);
  }
}
</script>

<style scoped>
.badge {
  padding: 2px 4px;
  border-radius: 4px;
  background-color: #ddd;
}
.badge.red {
  background-color: red;
  color: white;
}
</style>

