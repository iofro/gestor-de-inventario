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
          <div class="global-options">
            <label title="Aplica un porcentaje del total">
              <input type="radio" value="porcentaje" v-model="modoGlobal" />
              Por porcentaje
            </label>
            <label title="Aplica un monto fijo">
              <input type="radio" value="monto" v-model="modoGlobal" />
              Por monto
            </label>
          </div>
          <div>
            <input
              v-if="modoGlobal === 'porcentaje'"
              type="number"
              v-model.number="porcentaje"
              min="0"
              max="100"
              title="Porcentaje del total (0-100)"
            />
            <input
              v-else
              type="number"
              v-model.number="monto"
              min="0"
              title="Monto total de la nota. Se descompone si IVA incluido"
            />
          </div>
          <table class="preview">
            <thead>
              <tr>
                <th title="Descripción del ajuste">Concepto</th>
                <th title="Monto sujeto a IVA">Base gravada</th>
                <th title="Ventas exentas del impuesto">Exenta</th>
                <th title="Operaciones no sujetas al impuesto">No sujeta</th>
                <th title="Impuesto calculado al 20%">IVA(20)</th>
                <th title="Suma de base e IVA">Total</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Global</td>
                <td>{{ format(preview.base) }}</td>
                <td>{{ format(0) }}</td>
                <td>{{ format(0) }}</td>
                <td>{{ format(preview.iva) }}</td>
                <td>{{ format(preview.base + preview.iva) }}</td>
              </tr>
            </tbody>
          </table>
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
import { ref, computed } from 'vue';

const props = defineProps<{
  factura: { numero: string; cliente: string; total?: number };
  tipo: 'credito' | 'debito';
}>();

const motivo = ref('');
const ivaIncluido = ref(true);
const activeTab = ref<'global' | 'producto'>('global');

const modoGlobal = ref<'porcentaje' | 'monto'>('porcentaje');
const porcentaje = ref(0);
const monto = ref(0);

function toBaseIva(total: number, tasa = 0.2) {
  const base = total / (1 + tasa);
  return { base, iva: total - base };
}

const globalMonto = computed(() => {
  return modoGlobal.value === 'porcentaje'
    ? (props.factura.total ?? 0) * (porcentaje.value || 0) / 100
    : monto.value || 0;
});

const preview = computed(() => {
  const total = globalMonto.value;
  if (ivaIncluido.value) {
    return toBaseIva(total);
  }
  return { base: total, iva: total * 0.2 };
});

function format(n: number) {
  return n.toFixed(2);
}

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

