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
                <th title="Impuesto calculado al 13%">IVA(13)</th>
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
        <div>Base gravada: {{ format(preview.base) }}</div>
        <div>Exenta: {{ format(0) }}</div>
        <div>No sujeta: {{ format(0) }}</div>
        <div>IVA: {{ format(preview.iva) }}</div>
        <div>Total: {{ format(total) }}</div>
        <div>Total en letras: {{ totalLetras }}</div>
        <div>Documento relacionado: {{ factura.numero }}</div>
        <span v-if="excedeSaldo" class="badge rojo">Crédito excede saldo</span>
        <div class="acciones">
          <button @click="onPreviewPdf">Previsualizar PDF</button>
          <button @click="onPreviewJson">Previsualizar JSON</button>
          <button @click="onGuardarBorrador">Guardar borrador</button>
          <button @click="onFirmarTransmitir">Firmar &amp; Transmitir</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue';
import { previsualizarPdf, previsualizarJson, guardarBorrador, firmarTransmitir } from '../services/notasApi';
import { toBaseIva } from '../services/useIvaConversion';

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
  return { base: total, iva: total * 0.13 };
});

const total = computed(() => preview.value.base + preview.value.iva);

const totalLetras = computed(() => numeroALetras(total.value));

const excedeSaldo = computed(
  () => tipo === 'credito' && total.value > (props.factura.total ?? 0)
);

function validar() {
  return total.value > 0 && !excedeSaldo.value;
}

async function onPreviewPdf() {
  if (!validar()) return;
  await previsualizarPdf(getPayload());
}

async function onPreviewJson() {
  if (!validar()) return;
  await previsualizarJson(getPayload());
}

async function onGuardarBorrador() {
  if (!validar()) return;
  await guardarBorrador(getPayload());
}

async function onFirmarTransmitir() {
  if (!validar()) return;
  await firmarTransmitir(getPayload());
}

function getPayload() {
  return {
    factura: factura.numero,
    tipo,
    motivo: motivo.value,
    monto: total.value,
    ivaIncluido: ivaIncluido.value,
  };
}

function numeroALetras(n: number) {
  return n.toFixed(2) + ' USD';
}

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
.badge.rojo {
  background-color: #c00;
  color: #fff;
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

