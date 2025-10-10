<template>
  <div class="nota-form">
    <section class="factura-resumen">
      <div class="factura-data">
        <input readonly :value="factura.tipo" title="Tipo de documento (01/03)" />
        <input readonly :value="factura.numero" title="Serie-correlativo" />
        <input readonly :value="factura.fecha" title="Fecha" />
        <input
          readonly
          :value="factura.uuid ? factura.uuid.slice(0, 8) : ''"
          title="UUID de la factura origen"
        />
        <div>{{ factura.cliente }}</div>
      </div>
      <div class="factura-totales">
        <div>Base gravada: {{ format(facturaResumen.base) }}</div>
        <div>Exenta: {{ format(facturaResumen.exenta) }}</div>
        <div>No sujeta: {{ format(facturaResumen.noSujeta) }}</div>
        <div>IVA: {{ format(facturaResumen.iva) }}</div>
        <div>Total: {{ format(facturaResumen.total) }}</div>
      </div>
    </section>

    <section class="detalle">
      <div class="nota-controls">
        <span class="badge">{{ tipo === 'credito' ? 'Crédito' : 'Débito' }}</span>
        <input v-model="motivo" placeholder="Motivo" maxlength="50" />
        <label>
          IVA Incluido
          <input type="checkbox" v-model="ivaIncluido" />
        </label>
      </div>
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
            step="0.0001"
            title="Porcentaje del total (0-100)"
          />
          <input
            v-else
            type="number"
            v-model.number="monto"
            min="0"
            step="0.0001"
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
              <th title="Suma de base, exenta, no sujeta e IVA">Total</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Global</td>
              <td>{{ format(preview.base) }}</td>
              <td>{{ format(preview.exenta) }}</td>
              <td>{{ format(preview.noSujeta) }}</td>
              <td>{{ format(preview.iva) }}</td>
              <td>{{ format(preview.base + preview.exenta + preview.noSujeta + preview.iva) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-else>
        <EditableNotaTable
          v-model="items"
          :topeCredito="saldoDisponible"
          :ivaIncluido="ivaIncluido"
          :notaTipo="tipo"
        />
      </div>
    </section>

    <section class="nota-resumen">
      <h3>Nota</h3>
      <div>Base gravada: {{ format(preview.base) }}</div>
      <div>Exenta: {{ format(preview.exenta) }}</div>
      <div>No sujeta: {{ format(preview.noSujeta) }}</div>
      <div>IVA: {{ format(preview.iva) }}</div>
      <div>Total: {{ format(total) }}</div>
      <div>Documento relacionado: {{ factura.numero }}</div>
      <span v-if="excedeSaldo" class="badge rojo">Crédito excede saldo</span>
      <div class="acciones">
        <button @click="onPreviewPdf">Previsualizar PDF</button>
        <button @click="onPreviewJson">Previsualizar JSON</button>
        <button @click="onGuardarBorrador">Guardar borrador</button>
        <button @click="onFirmarTransmitir">Firmar &amp; Transmitir</button>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue';
import { previsualizarPdf, previsualizarJson, guardarBorrador, firmarTransmitir } from '../services/notasApi';
import { toBaseIva, fromBaseIva } from '../services/useIvaConversion';
import EditableNotaTable from '../components/EditableNotaTable.vue';
import { prorratearGlobal } from '../services/prorrateo';

const props = defineProps<{
  factura: {
    tipo?: string;
    numero: string;
    fecha?: string;
    uuid?: string;
    cliente: string;
    total?: number;
    ventas_gravadas?: number;
    ventas_exentas?: number;
    ventas_no_sujetas?: number;
    iva?: number;
  };
  tipo: 'credito' | 'debito';
}>();

const motivo = ref('');
const ivaIncluido = ref(true);
const activeTab = ref<'global' | 'producto'>('global');

const modoGlobal = ref<'porcentaje' | 'monto'>('porcentaje');
const porcentaje = ref(0);
const monto = ref(0);

interface NotaItem {
  id: number;
  selected: boolean;
  codigo: string;
  descripcion: string;
  cantidadFacturada: number;
  cantidadAjustar: number;
  tipo: 'debito' | 'credito';
  modo: 'monto' | 'porcentaje';
  valor: number;
  ivaInc: boolean;
  afectacion: 'gravada' | 'exenta' | 'no_sujeta';
  previas?: number;
}

const items = ref<NotaItem[]>([]);

const saldoDisponible = computed(() => props.factura.total ?? 0);

const facturaResumen = computed(() => ({
  base: props.factura.ventas_gravadas ?? 0,
  exenta: props.factura.ventas_exentas ?? 0,
  noSujeta: props.factura.ventas_no_sujetas ?? 0,
  iva: props.factura.iva ?? 0,
  total: props.factura.total ?? 0,
}));

function resolveValor(item: NotaItem) {
  if (item.modo === 'porcentaje') {
    return (item.cantidadFacturada * item.valor) / 100;
  }
  return item.valor;
}

const itemsPreview = computed(() => {
  return items.value.reduce(
    (acc, item) => {
      const valor = item.ajuste !== undefined ? item.ajuste : resolveValor(item);
      if (item.afectacion === 'gravada') {
        if (item.ajuste !== undefined) {
          if (ivaIncluido.value) {
            const { base, iva } = toBaseIva(valor);
            acc.base += base;
            acc.iva += iva;
            acc.total += valor;
          } else {
            const { total, iva } = fromBaseIva(valor);
            acc.base += valor;
            acc.iva += iva;
            acc.total += total;
          }
        } else if (item.ivaInc) {
          const { base, iva } = toBaseIva(valor);
          acc.base += base;
          acc.iva += iva;
          acc.total += valor;
        } else {
          const { total, iva } = fromBaseIva(valor);
          acc.base += valor;
          acc.iva += iva;
          acc.total += total;
        }
      } else if (item.afectacion === 'exenta') {
        acc.exenta += valor;
        acc.total += valor;
      } else {
        acc.noSujeta += valor;
        acc.total += valor;
      }
      return acc;
    },
    { base: 0, exenta: 0, noSujeta: 0, iva: 0, total: 0 }
  );
});

const preview = computed(() => {
  if (activeTab.value === 'global') {
    if (modoGlobal.value === 'porcentaje') {
      const res = prorratearGlobal(props.factura, { porcentaje: porcentaje.value || 0 });
      return {
        base: res.ventas_gravadas,
        exenta: res.ventas_exentas,
        noSujeta: res.ventas_no_sujetas,
        iva: res.iva,
      };
    } else {
      const valor = monto.value || 0;
      if (ivaIncluido.value) {
        const { base, iva } = toBaseIva(valor);
        return { base, exenta: 0, noSujeta: 0, iva };
      } else {
        const { iva } = fromBaseIva(valor);
        return { base: valor, exenta: 0, noSujeta: 0, iva };
      }
    }
  }
  return itemsPreview.value;
});

const total = computed(
  () =>
    preview.value.base +
    preview.value.exenta +
    preview.value.noSujeta +
    preview.value.iva
);

const totalCredito = computed(() => {
  if (activeTab.value === 'producto') {
    return items.value
      .filter((i) => i.tipo === 'credito')
      .reduce((acc, i) => {
        const val = i.ajuste !== undefined ? i.ajuste : resolveValor(i);
        return acc + val;
      }, 0);
  }
  return tipo === 'credito' ? total.value : 0;
});

const excedeSaldo = computed(
  () => totalCredito.value > (saldoDisponible.value)
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

function format(n: number) {
  return n.toFixed(4);
}

const { factura, tipo } = props;
</script>

<style scoped>
.nota-form {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}
.factura-data {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
  align-items: center;
}
.factura-totales {
  display: flex;
  gap: 1rem;
  flex-wrap: wrap;
}
.nota-controls {
  display: flex;
  gap: 1rem;
  align-items: center;
  margin-bottom: 1rem;
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
.nota-resumen {
  margin-top: 1rem;
}
.nota-resumen h3 {
  margin: 0 0 0.5rem 0;
}
</style>

