<script setup lang="ts">
import { useId } from 'vue'
import { t } from '../i18n'
defineProps<{ modelValue: string; regex: boolean; matchCase: boolean; wholeWord: boolean; name: string; label: string; placeholder: string }>()
const emit = defineEmits<{ 'update:modelValue': [value: string]; 'update:regex': [value: boolean]; 'update:matchCase': [value: boolean]; 'update:wholeWord': [value: boolean] }>()
const id = useId()
</script>

<template>
  <div class="text-filter">
    <label :for="id">{{ label }}</label>
    <div class="text-filter-control">
      <input :id="id" :value="modelValue" :name="name" type="search" maxlength="200" :placeholder="placeholder"
        @input="emit('update:modelValue', ($event.target as HTMLInputElement).value)" />
      <div class="text-filter-actions">
        <button type="button" class="text-filter-option" :class="{ active: matchCase }" :aria-pressed="matchCase"
          :aria-label="t('caseToggle', { field: label })" :title="t(matchCase ? 'caseEnabled' : 'caseDisabled')"
          @mousedown.prevent @click="emit('update:matchCase', !matchCase)"><span aria-hidden="true">Aa</span></button>
        <button type="button" class="text-filter-option whole-word-toggle" :class="{ active: wholeWord }" :aria-pressed="wholeWord"
          :aria-label="t('wordToggle', { field: label })" :title="t(wholeWord ? 'wordEnabled' : 'wordDisabled')"
          @mousedown.prevent @click="emit('update:wholeWord', !wholeWord)"><span aria-hidden="true">ab</span></button>
        <button type="button" class="text-filter-option regex-toggle" :class="{ active: regex }" :aria-pressed="regex"
          :aria-label="t('regexToggle', { field: label })" :title="t(regex ? 'regexEnabled' : 'regexDisabled')"
          @mousedown.prevent @click="emit('update:regex', !regex)"><span aria-hidden="true">.*</span></button>
      </div>
    </div>
  </div>
</template>
