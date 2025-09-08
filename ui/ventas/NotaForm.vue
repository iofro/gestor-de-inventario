<template>
  <div class="nota-form">
    <header class="nota-header">
      <div class="factura-data">
        <div>Factura: {{ factura.numero }}</div>
        <div>Cliente: {{ factura.cliente }}</div>
      </div>
      <span class="badge">{{ tipo === 'credito' ? 'Crédito' : 'Débito' }}</span>
      <input v-model="motivo" placeholder="Motivo" />
      <label>
        IVA Incluido
        <input type="checkbox" v-model="ivaIncluido" />
      </label>
    </header>
    <div class="contenido">
      <div class="detalle">
        <div class="tabs">
          <button @click="activeTab = 'global'" :class="{ active: activeTab === 'global' }">Global</button>
          <button @click="activeTab = 'producto'" :class="{ active: activeTab === 'producto' }">Por producto</button>
        </div>
        <div v-if="activeTab === 'global'">
          <!-- Detalle global -->
        </div>
        <div v-else>
          <!-- Detalle por producto -->
        </div>
      </div>
      <div class="resumen">
        <!-- Resumen y acciones -->
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue';

const props = defineProps<{
  factura: { numero: string; cliente: string };
  tipo: 'credito' | 'debito';
}>();

const motivo = ref('');
const ivaIncluido = ref(true);
const activeTab = ref<'global' | 'producto'>('global');

const { factura, tipo } = props;
</script>

<style scoped>
.contenido {
  display: flex;
}
.detalle {
  width: 70%;
}
.resumen {
  width: 30%;
}
.nota-header {
  display: flex;
  gap: 1rem;
  align-items: center;
}
.badge {
  background-color: #eee;
  padding: 0.25rem 0.5rem;
  border-radius: 4px;
}
.tabs {
  margin-bottom: 1rem;
}
.tabs button {
  margin-right: 0.5rem;
}
.tabs button.active {
  font-weight: bold;
}
</style>

