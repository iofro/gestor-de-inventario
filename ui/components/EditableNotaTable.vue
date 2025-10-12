<template>
  <div class="editable-nota-table">
    <div class="controls">
      <input v-model="search" placeholder="Buscar" />
      <label>
        <input type="checkbox" v-model="applyToSelected" /> Aplicar a todas las líneas seleccionadas
      </label>
    </div>
    <table>
      <thead>
        <tr>
          <th><input type="checkbox" :checked="allSelected" @change="toggleAll($event.target.checked)" /></th>
          <th>Código</th>
          <th>Descripción</th>
          <th>Unidad</th>
          <th>Cant. facturada</th>
          <th>Ajuste cantidad</th>
          <th>Tipo</th>
          <th>Modo</th>
          <th>Valor</th>
          <th>Afectación</th>
          <th>IVA inc.</th>
          <th>Ajuste precio (USD)</th>
          <th>Base</th>
          <th>IVA</th>
          <th>Total</th>
          <th>Concepto</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="item in filteredItems" :key="item.id">
          <td><input type="checkbox" v-model="item.selected" /></td>
          <td>{{ item.codigo }}</td>
          <td>{{ item.descripcion }}</td>
          <td>{{ item.unidad }}</td>
          <td>{{ item.cantidadFacturada }}</td>
          <td>
            <input
              class="cantidad-ajuste"
              type="number"
              :value="item.cantidadAjustar"
              :disabled="isCantidadLocked(item)"
              step="0.0001"
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
              step="0.0001"
              @focus="onFocus(item, 'valor')"
              @input="update(item, 'valor', parseFloat($event.target.value))"
              @keydown.enter.prevent="$event.target.blur()"
              @keydown.esc.prevent="onEsc(item, 'valor'); $event.target.blur()"
            />
          </td>
          <td>
            <!-- Cuando está activo, el valor ingresado se considera total con IVA -->
            <input
              type="checkbox"
              :checked="item.ivaInc"
              @change="update(item, 'ivaInc', $event.target.checked)"
              title="Si está activo, el valor ingresado se considera total con IVA"
            />
          </td>
          <td>
            <input
              class="ajuste"
              type="number"
              :value="item.ajuste"
              :disabled="isPrecioLocked(item)"
              step="0.0001"
              @focus="onFocus(item, 'ajuste')"
              @input="update(item, 'ajuste', parseFloat($event.target.value))"
              @keydown.enter.prevent="$event.target.blur()"
              @keydown.esc.prevent="onEsc(item, 'ajuste'); $event.target.blur()"
            />
            <span
              v-if="item.tipo === 'credito' && calcTotal(item) > (item.maxMonto ?? (props.topeCredito ?? 0))"
              class="error"
              >Excede</span
            >
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
          <td>
            <input
              type="text"
              :value="item.concepto"
              placeholder="Concepto opcional"
              @focus="onFocus(item, 'concepto')"
              @input="update(item, 'concepto', $event.target.value)"
              @keydown.enter.prevent="$event.target.blur()"
              @keydown.esc.prevent="onEsc(item, 'concepto'); $event.target.blur()"
            />
          </td>
        </tr>
      </tbody>
    </table>
    <button
      v-if="notaTipo === 'debito'"
      class="add-item"
      @click="addItem"
    >
      + Agregar ítem
    </button>
    <div v-if="showProductDialog" class="product-dialog">
      <div class="dialog-content">
        <input v-model="productSearch" placeholder="Buscar producto" />
        <ul>
          <li
            v-for="p in filteredProducts"
            :key="p.codigo"
            class="product-option"
            @click="selectProduct(p)"
          >
            {{ p.codigo }} - {{ p.descripcion }}
          </li>
        </ul>
        <button @click="showProductDialog = false">Cerrar</button>
      </div>
    </div>
    <p v-if="creditoExcede" class="error">Tope global de crédito excedido</p>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, defineProps, defineEmits, defineOptions, reactive } from 'vue';
import { toBaseIva, fromBaseIva } from '../services/useIvaConversion';

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
  ajuste?: number;
  concepto?: string;
  unidad?: string;
  maxMonto?: number;
  isProduct?: boolean;
  ajusteCantidad?: boolean;
}

interface Producto {
  codigo: string;
  descripcion: string;
  unidad: string;
  precio: number;
}

defineOptions({ name: 'EditableNotaTable' });

const props = defineProps<{
  modelValue: NotaItem[];
  topeCredito?: number;
  ivaIncluido: boolean;
  notaTipo?: 'debito' | 'credito';
  tipoNota?: 'debito' | 'credito';
}>();
const emit = defineEmits(['update:modelValue']);

const notaTipo = computed(() => props.notaTipo ?? props.tipoNota ?? 'debito');

const items = ref<NotaItem[]>(props.modelValue ? [...props.modelValue] : []);
const lockedFields = reactive<Record<number, 'precio' | 'cantidad' | undefined>>({});
watch(
  () => props.modelValue,
  (val) => {
    items.value = val ? [...val] : [];
    resetLocks();
  }
);
watch(
  items,
  (val) => emit('update:modelValue', val),
  { deep: true }
);

const search = ref('');
const applyToSelected = ref(false);

const showProductDialog = ref(false);
const productSearch = ref('');
const productos = ref<Producto[]>([
  { codigo: 'P1', descripcion: 'Producto 1', unidad: 'UND', precio: 1 },
  { codigo: 'P2', descripcion: 'Producto 2', unidad: 'UND', precio: 2 }
]);

const filteredProducts = computed(() => {
  if (!productSearch.value) return productos.value;
  return productos.value.filter(
    (p) =>
      p.codigo.toLowerCase().includes(productSearch.value.toLowerCase()) ||
      p.descripcion.toLowerCase().includes(productSearch.value.toLowerCase())
  );
});

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
  productSearch.value = '';
  showProductDialog.value = true;
}

function selectProduct(p: Producto) {
  items.value.push({
    id: nextId++,
    selected: false,
    codigo: p.codigo,
    descripcion: p.descripcion,
    cantidadFacturada: 0,
    cantidadAjustar: 1,
    tipo: 'debito',
    modo: 'monto',
    valor: p.precio,
    ivaInc: false,
    afectacion: 'gravada',
    previas: 0,
    ajuste: p.precio,
    concepto: '',
    unidad: p.unidad,
    isProduct: true
  });
  showProductDialog.value = false;
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
  if (field === 'ajuste' && notaTipo.value === 'debito' && value < 0) {
    value = 0;
  }
  const targets = applyToSelected.value ? items.value.filter((i) => i.selected) : [item];
  targets.forEach((target) => {
    (target as any)[field] = value;
    if (target.isProduct && (field === 'cantidadAjustar' || field === 'valor')) {
      target.ajuste = target.cantidadAjustar * target.valor;
    }
    if (field === 'ajuste') {
      if (shouldLockByPrecio(value)) {
        target.ajusteCantidad = false;
      } else if (target.ajusteCantidad === false) {
        target.ajusteCantidad = undefined;
      }
      updateLock(target, 'precio', value);
    } else if (field === 'cantidadAjustar') {
      target.ajusteCantidad = true;
      updateLock(target, 'cantidad', value);
      if (!shouldLockByCantidad(value)) {
        target.ajusteCantidad = undefined;
      }
    }
  });
}

function resolveValor(item: NotaItem) {
  if (item.modo === 'porcentaje') {
    return (item.cantidadFacturada * item.valor) / 100;
  }
  return item.valor;
}

function getMonto(item: NotaItem) {
  return item.ajuste !== undefined ? item.ajuste : resolveValor(item);
}
function calcBase(item: NotaItem) {
  const monto = getMonto(item);
  if (item.afectacion !== 'gravada') {
    return monto;
  }
  if (item.ajuste !== undefined) {
    return props.ivaIncluido ? toBaseIva(monto).base : monto;
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
  const monto = getMonto(item);
  if (item.ajuste !== undefined) {
    return props.ivaIncluido ? toBaseIva(monto).iva : fromBaseIva(monto).iva;
  }
  if (item.ivaInc) {
    return toBaseIva(monto).iva;
  }
  return fromBaseIva(monto).iva;
}
function calcTotal(item: NotaItem) {
  const monto = getMonto(item);
  if (item.afectacion !== 'gravada') {
    return monto;
  }
  if (item.ajuste !== undefined) {
    return props.ivaIncluido ? monto : fromBaseIva(monto).total;
  }
  if (item.ivaInc) {
    return monto;
  }
  return calcBase(item) + calcIva(item);
}

function formatNumber(n: number) {
  return isNaN(n) ? '' : n.toFixed(4);
}

const totalCredito = computed(() =>
  items.value
    .filter((i) => i.tipo === 'credito')
    .reduce((acc, i) => acc + calcTotal(i), 0)
);

const creditoExcede = computed(() =>
  props.topeCredito !== undefined && totalCredito.value > props.topeCredito
);

resetLocks();

function updateLock(item: NotaItem, field: 'precio' | 'cantidad', rawValue: any) {
  const key = item.id;
  const shouldLock = field === 'precio' ? shouldLockByPrecio(rawValue) : shouldLockByCantidad(rawValue);
  if (shouldLock) {
    lockedFields[key] = field;
  } else if (lockedFields[key] === field) {
    delete lockedFields[key];
  }
}

function shouldLockByPrecio(value: any) {
  return Number.isFinite(value) && Number(value) !== 0;
}

function shouldLockByCantidad(value: any) {
  return Number.isFinite(value) && Number(value) > 0;
}

function isCantidadLocked(item: NotaItem) {
  return lockedFields[item.id] === 'precio';
}

function isPrecioLocked(item: NotaItem) {
  return lockedFields[item.id] === 'cantidad';
}

function resetLocks() {
  Object.keys(lockedFields).forEach((key) => delete lockedFields[Number(key)]);
  items.value.forEach((item) => {
    if (item.ajusteCantidad) {
      lockedFields[item.id] = 'cantidad';
    } else if (shouldLockByPrecio(item.ajuste)) {
      lockedFields[item.id] = 'precio';
    }
  });
}
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
.product-dialog {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
}
.dialog-content {
  background: #fff;
  padding: 1rem;
  max-height: 80vh;
  overflow-y: auto;
}
.product-option {
  cursor: pointer;
  padding: 0.25rem 0;
}
</style>

