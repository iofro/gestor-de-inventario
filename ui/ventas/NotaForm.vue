<template>
  <div>
    <h3>Global</h3>
    <div>
      <label title="Aplicar un porcentaje global">
        <input type="radio" value="percentage" v-model="mode" /> Por porcentaje
      </label>
      <label title="Aplicar un monto fijo global">
        <input type="radio" value="amount" v-model="mode" /> Por monto
      </label>
    </div>
    <div>
      <input
        v-if="mode === 'percentage'"
        type="number"
        v-model.number="value"
        placeholder="%"
        title="Límite 100%"
        min="0"
        max="100"
      />
      <input
        v-else
        type="number"
        v-model.number="value"
        placeholder="Monto"
        title="Monto en moneda"
        min="0"
      />
    </div>
    <table>
      <thead>
        <tr>
          <th>Concepto</th>
          <th title="Monto sujeto a IVA">Base gravada</th>
          <th title="Monto exento de IVA">Exenta</th>
          <th title="Monto no sujeto a IVA">No sujeta</th>
          <th title="IVA calculado al 20%">IVA(20)</th>
          <th>Total</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>{{ concepto }}</td>
          <td>{{ format(preview.baseGravada) }}</td>
          <td>{{ format(preview.exenta) }}</td>
          <td>{{ format(preview.noSujeta) }}</td>
          <td>{{ format(preview.iva) }}</td>
          <td>{{ format(preview.total) }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue';

const props = defineProps<{
  ivaIncluido?: boolean;
  baseReferencia?: number;
  concepto?: string;
}>();

const mode = ref<'percentage' | 'amount'>('percentage');
const value = ref(0);
const concepto = computed(() => props.concepto ?? 'Global');

function toBaseIva(total: number) {
  const base = total / 1.2;
  const iva = total - base;
  return { base, iva };
}

function format(n: number) {
  return n.toFixed(2);
}

const preview = computed(() => {
  const baseRef = props.baseReferencia ?? 0;
  const amount =
    mode.value === 'percentage' ? (baseRef * value.value) / 100 : value.value;
  if (props.ivaIncluido) {
    const { base, iva } = toBaseIva(amount);
    return {
      baseGravada: base,
      exenta: 0,
      noSujeta: 0,
      iva,
      total: amount,
    };
  } else {
    const iva = amount * 0.2;
    return {
      baseGravada: amount,
      exenta: 0,
      noSujeta: 0,
      iva,
      total: amount + iva,
    };
  }
});
</script>
