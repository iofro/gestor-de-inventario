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
        <tr v-for="(item, index) in filteredItems" :key="item.id">
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
              step="0.0001"
              :disabled="isCantidadLocked(item)"
              :data-testid="getCantidadTestId(item, index)"
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
              step="0.0001"
              :min="item.tipo === 'debito' ? 0 : undefined"
              :disabled="isPrecioLocked(item)"
              :data-testid="getPrecioTestId(item, index)"
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
import { ref, computed, watch } from 'vue';
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

let nextId = 1;
const items = ref<NotaItem[]>([]);

syncFromProps(props.modelValue ?? []);

watch(
  () => props.modelValue,
  (val) => {
    syncFromProps(val ?? []);
  }
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
  emitItems();
}

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
    cantidadAjustar: 0,
    tipo: 'debito',
    modo: 'monto',
    valor: p.precio,
    ivaInc: false,
    afectacion: 'gravada',
    previas: 0,
    ajuste: 0,
    concepto: '',
    unidad: p.unidad,
    isProduct: true
  });
  showProductDialog.value = false;
  emitItems();
}

const cache = new Map<string, any>();
function onFocus(item: NotaItem, field: keyof NotaItem) {
  cache.set(item.id + field, (item as any)[field]);
}
function onEsc(item: NotaItem, field: keyof NotaItem) {
  const key = item.id + field;
  (item as any)[field] = cache.get(key);
  emitItems();
}

function update(item: NotaItem, field: keyof NotaItem, input: any) {
  const targets = applyToSelected.value ? items.value.filter((i) => i.selected) : [item];

  targets.forEach((target) => {
    const isNumericField = field === 'ajuste' || field === 'cantidadAjustar';
    const rawNum = isNumericField ? Number(input) : NaN;
    const raw = isNumericField && Number.isFinite(rawNum) ? rawNum : isNumericField ? 0 : input;

    const isDebitRow = (target.tipo ?? notaTipo.value) === 'debito';
    const effective = field === 'ajuste' && isDebitRow && raw < 0 ? 0 : raw;

    if (field === 'ajuste') {
      handlePrecioChange(target, raw);
    } else if (field === 'cantidadAjustar') {
      handleCantidadChange(target, raw);
    }

    (target as any)[field] = effective;

    if (target.isProduct && (field === 'cantidadAjustar' || field === 'valor')) {
      target.ajuste = target.cantidadAjustar * target.valor;
    }
  });
  emitItems();
}

function handlePrecioChange(target: NotaItem, value: any) {
  const numericValue = Number(value);
  if (isNonZero(numericValue)) {
    target.ajusteCantidad = false;
  } else if (target.ajusteCantidad === false && !isNonZero(numericValue)) {
    target.ajusteCantidad = undefined;
  }
}

function handleCantidadChange(target: NotaItem, value: any) {
  const numericValue = Number(value);
  if (isNonZero(numericValue)) {
    target.ajusteCantidad = true;
  } else if (target.ajusteCantidad === true && !isNonZero(numericValue)) {
    target.ajusteCantidad = undefined;
  }
}

function getCantidadTestId(item: NotaItem, index: number) {
  return `cantidad-input-${getRowIdentifier(item, index)}`;
}

function getPrecioTestId(item: NotaItem, index: number) {
  return `precio-input-${getRowIdentifier(item, index)}`;
}

function getRowIdentifier(item: NotaItem, index: number) {
  const maybeId = Number((item as any).id);
  return Number.isFinite(maybeId) && maybeId > 0 ? maybeId : index;
}

function isCantidadLocked(item: NotaItem) {
  if (item.ajusteCantidad === true) {
    return false;
  }
  if (item.ajusteCantidad === false) {
    return true;
  }
  return isNonZero(Number(item.ajuste)) && !isNonZero(Number(item.cantidadAjustar));
}

function isPrecioLocked(item: NotaItem) {
  if (item.ajusteCantidad === false) {
    return false;
  }
  if (item.ajusteCantidad === true) {
    return true;
  }
  return isNonZero(Number(item.cantidadAjustar));
}

function isNonZero(value: any) {
  const numeric = Number(value);
  return Number.isFinite(numeric) && Math.abs(numeric) > 0;
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

function syncFromProps(source: NotaItem[]) {
  items.value = normalizeItems(source);
}

function emitItems() {
  emit('update:modelValue', items.value);
}

function normalizeItems(source: NotaItem[]) {
  return source.map((original) => {
    const clone = { ...original };
    const maybeId = Number((original as any).id);
    if (Number.isFinite(maybeId) && maybeId > 0) {
      clone.id = maybeId;
      nextId = Math.max(nextId, maybeId + 1);
    } else {
      clone.id = nextId++;
    }
    if (!Number.isFinite(Number(clone.cantidadAjustar))) {
      clone.cantidadAjustar = 0;
    }
    if (clone.ajuste !== undefined && !Number.isFinite(Number(clone.ajuste))) {
      clone.ajuste = 0;
    }
    normalizeAjusteState(clone);
    return clone;
  });
}

function normalizeAjusteState(item: NotaItem) {
  if (isNonZero(item.cantidadAjustar)) {
    item.ajusteCantidad = true;
    return;
  }
  if (item.ajuste !== undefined && isNonZero(item.ajuste)) {
    item.ajusteCantidad = false;
    return;
  }
  item.ajusteCantidad = undefined;
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

