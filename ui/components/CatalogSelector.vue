<template>
  <div class="catalog-selector">
    <label :for="catalogId">{{ catalogId }}</label>
    <select v-if="!allowManual" v-model="selected" :id="catalogId">
      <option v-for="(label, code) in options" :key="code" :value="code">
        {{ code }} - {{ label }}
      </option>
    </select>
    <input
      v-else
      :id="catalogId"
      v-model="selected"
      :maxlength="maxLength"
      @blur="onValidate"
    />
    <span v-if="error" class="error">{{ error }}</span>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import { getCatalog, validateCode, manualCatalogs, maxLengthFor } from '../services/catalogs';

defineOptions({ name: 'CatalogSelector' });

const props = defineProps<{ catalogId: string }>();
const selected = ref('');
const options = getCatalog(props.catalogId);
const allowManual = manualCatalogs.includes(props.catalogId);
const maxLength = maxLengthFor(props.catalogId);
const error = ref('');

function onValidate() {
  if (!validateCode(props.catalogId, selected.value)) {
    error.value = 'Código inválido';
  } else {
    error.value = '';
  }
}
</script>
