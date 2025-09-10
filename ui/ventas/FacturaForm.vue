<template>
  <div>
    <div v-if="props.config?.modoContingencia">
      <select v-model.number="tipoContingencia">
        <option v-for="n in 5" :key="n" :value="n">{{ n }}</option>
      </select>
      <input v-if="tipoContingencia === 5" v-model="motivoContin" />
    </div>
    <button @click="onSave">Guardar y Enviar</button>
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
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import ConfirmDialog from '../components/ConfirmDialog.vue';
import { guardarEnContingencia } from '../services/facturasApi';

const props = defineProps<{ facturaId: string; config: { modoContingencia: boolean } }>();

const confirmVisible = ref(false);
const errorVisible = ref(false);
const tipoContingencia = ref(1);
const motivoContin = ref('');

async function onSave() {
  if (props.config?.modoContingencia) {
    confirmVisible.value = true;
  } else {
    try {
      await enviarAHacienda();
    } catch (e) {
      errorVisible.value = true;
    }
  }
}

async function saveContingencia() {
  await guardarEnContingencia(
    props.facturaId,
    tipoContingencia.value,
    motivoContin.value
  );
}

function enviarAHacienda() {
  throw new Error('fallo');
}
</script>
