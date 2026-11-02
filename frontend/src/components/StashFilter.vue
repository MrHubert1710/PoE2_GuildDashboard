<script setup lang="ts">
import { t } from '../i18n'
const props = defineProps<{ options: string[]; modelValue: string[] }>()
const emit = defineEmits<{ 'update:modelValue': [value: string[]] }>()
function toggle(stash: string) {
  emit('update:modelValue', props.modelValue.includes(stash)
    ? props.modelValue.filter(value => value !== stash)
    : [...props.modelValue, stash])
}
</script>

<template>
  <fieldset class="stash-filter">
    <legend>{{ t('stashFilterTitle') }}</legend>
    <div class="stash-filter-heading">
      <span role="status">{{ modelValue.length ? t('stashFilterCount', { count: modelValue.length }) : t('allStashes') }}</span>
      <button v-if="modelValue.length" type="button" @click="emit('update:modelValue', [])">{{ t('allStashes') }}</button>
    </div>
    <div class="stash-filter-options">
      <label v-for="stash in [...new Set([...options, ...modelValue])]" :key="stash" :class="{ selected: modelValue.includes(stash) }">
        <input type="checkbox" name="stash" :value="stash" :checked="modelValue.includes(stash)" @change="toggle(stash)" />
        <span>{{ stash }}</span>
      </label>
    </div>
  </fieldset>
</template>
