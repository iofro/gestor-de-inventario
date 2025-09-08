<template>
  <div class="editable-nota-table">
    <div class="controls">
      <input v-model="search" placeholder="Buscar" />
      <label>
        <input type="checkbox" v-model="applyToSelected" /> Aplicar a todas las líneas seleccionadas
      </label>
      <button class="add-item" @click="addItem">+ Agregar ítem</button>
    </div>
    <table>
      <thead>
        <tr>
          <th><input type="checkbox" :checked="allSelected" @change="toggleAll($event.target.checked)" /></th>
          <th>Código</th>
          <th>Descripción</th>
          <th>Cant. facturada</th>
          <th>Cant. a ajustar</th>
          <th>Tipo</th>
          <th>Modo</th>
          <th>Valor</th>
          <th>Afectación</th>
          <th>IVA inc.</th>
          <th>Base</th>
          <th>IVA</th>
          <th>Total</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="item in filteredItems" :key="item.id">
          <td><input type="checkbox" v-model="item.selected" /></td>
          <td>{{ item.codigo }}</td>
          <td>{{ item.descripcion }}</td>
          <td>{{ item.cantidadFacturada }}</td>
          <td>
            <input
              type="number"
              :value="item.cantidadAjustar"
              @focus="onFocus(item, 'cantidadAjustar')"
              @input="update(item, 'cantidadAjustar', parseFloat($event.target.value))"
              @keydown.enter.prevent="$event.target.blur()"
              @keydown.esc.prevent="onEsc(item, 'cantidadAjustar'); $event.target.blur()"
            />
            <span
              v-if="item.tipo === 'credito' && item.cantidadAjustar > item.cantidadFacturada - (item.previas || 0)"
              class="error"
              >Excede</span
            >
          </td>
          <td>
            <select
              :value="item.tipo"
              @change="update(item, 'tipo', $event.target.value)"
            >
              <option value="debito">Débito</option>
              <option value="credito">Crédito</option>
            </select>
          </td>
          <td>
            <select
              :value="item.modo"
              @change="update(item, 'modo', $event.target.value)"
            >
              <option value="monto">Monto</option>
              <option value="porcentaje">%</option>
            </select>
          </td>
          <td>
            <input
              type="number"
              :value="item.valor"
              @focus="onFocus(item, 'valor')"
              @input="update(item, 'valor', parseFloat($event.target.value))"
              @keydown.enter.prevent="$event.target.blur()"
              @keydown.esc.prevent="onEsc(item, 'valor'); $event.target.blur()"
            />
          </td>
          <td>
            <input
              type="checkbox"
              :checked="item.ivaInc"
              @change="update(item, 'ivaInc', $event.target.checked)"
            />
          </td>
          <td>
            <select :value="item.afectacion" @change="update(item, 'afectacion', $event.target.value)">
              <option value="gravada">Gravada</option>
              <option value="exenta">Exenta</option>
              <option value="no_sujeta">No sujeta</option>
            </select>
          </td>
          <td>{{ formatNumber(calcBase(item)) }}</td>
          <td>{{ formatNumber(calcIva(item)) }}</td>
          <td>{{ formatNumber(calcTotal(item)) }}</td>
        </tr>
      </tbody>
    </table>
    <p v-if="creditoExcede" class="error">Tope global de crédito excedido</p>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, defineProps, defineEmits, defineOptions } from 'vue';
import { toBaseIva } from '../services/useIvaConversion';

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

defineOptions({ name: 'EditableNotaTable' });

const props = defineProps<{ modelValue: NotaItem[]; topeCredito?: number }>();
const emit = defineEmits(['update:modelValue']);

const items = ref<NotaItem[]>(props.modelValue ? [...props.modelValue] : []);
watch(
  () => props.modelValue,
  (val) => {
    items.value = val ? [...val] : [];
  }
);
watch(
  items,
  (val) => emit('update:modelValue', val),
  { deep: true }
);

const search = ref('');
const applyToSelected = ref(false);

const filteredItems = computed(() => {
  if (!search.value) return items.value;
  return items.value.filter(
    (i) =>
      i.codigo.toLowerCase().includes(search.value.toLowerCase()) ||
      i.descripcion.toLowerCase().includes(search.value.toLowerCase())
  );
});

const allSelected = computed(() => filteredItems.value.length > 0 && filteredItems.value.every((i) => i.selected));

function toggleAll(val: boolean) {
  filteredItems.value.forEach((i) => (i.selected = val));
}

let nextId = 1;
function addItem() {
  items.value.push({
    id: nextId++,
    selected: false,
    codigo: '',
    descripcion: '',
    cantidadFacturada: 0,
    cantidadAjustar: 0,
    tipo: 'debito',
    modo: 'monto',
    valor: 0,
    ivaInc: false,
    afectacion: 'gravada',
    previas: 0,
  });
}

const cache = new Map<string, any>();
function onFocus(item: NotaItem, field: keyof NotaItem) {
  cache.set(item.id + field, (item as any)[field]);
}
function onEsc(item: NotaItem, field: keyof NotaItem) {
  const key = item.id + field;
  (item as any)[field] = cache.get(key);
}

function update(item: NotaItem, field: keyof NotaItem, value: any) {
  if (applyToSelected.value) {
    items.value
      .filter((i) => i.selected)
      .forEach((i) => ((i as any)[field] = value));
  } else {
    (item as any)[field] = value;
  }
}

function resolveValor(item: NotaItem) {
  if (item.modo === 'porcentaje') {
    return (item.cantidadFacturada * item.valor) / 100;
  }
  return item.valor;
}

function calcBase(item: NotaItem) {
  const monto = resolveValor(item);
  if (item.afectacion !== 'gravada') {
    return monto;
  }
  if (item.ivaInc) {
    return toBaseIva(monto).base;
  }
  return monto;
}
function calcIva(item: NotaItem) {
  if (item.afectacion !== 'gravada') {
    return 0;
  }
  const monto = resolveValor(item);
  if (item.ivaInc) {
    return toBaseIva(monto).iva;
  }
  return monto * 0.13;
}
function calcTotal(item: NotaItem) {
  if (item.ivaInc) {
    return resolveValor(item);
  }
  return calcBase(item) + calcIva(item);
}

function formatNumber(n: number) {
  return isNaN(n) ? '' : n.toFixed(2);
}

const totalCredito = computed(() =>
  items.value
    .filter((i) => i.tipo === 'credito')
    .reduce((acc, i) => acc + calcTotal(i), 0)
);

const creditoExcede = computed(() =>
  props.topeCredito !== undefined && totalCredito.value > props.topeCredito
);
</script>

<style scoped>
.editable-nota-table {
  overflow-x: auto;
}
.controls {
  display: flex;
  gap: 1rem;
  align-items: center;
  margin-bottom: 0.5rem;
}
table {
  width: 100%;
  border-collapse: collapse;
}
th,
 td {
  border: 1px solid #ccc;
  padding: 4px;
  text-align: left;
}
.error {
  color: red;
  font-size: 0.8rem;
}
</style>

