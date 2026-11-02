<script setup lang="ts">
import { t } from '../i18n'
import { onMounted, onUnmounted, ref, useId } from 'vue'
const props = defineProps<{ options: string[]; modelValue: string[] }>()
const emit = defineEmits<{ 'update:modelValue': [value: string[]] }>()
const root = ref<HTMLElement | null>(null)
const trigger = ref<HTMLButtonElement | null>(null)
const open = ref(false)
const panelId = useId()
function close(focus = false) { open.value = false; if (focus) trigger.value?.focus() }
function outside(event: PointerEvent) { if (!root.value?.contains(event.target as Node)) close() }
onMounted(() => document.addEventListener('pointerdown', outside))
onUnmounted(() => document.removeEventListener('pointerdown', outside))
function selectAll() { emit('update:modelValue', []); trigger.value?.focus() }
function toggle(stash: string) {
  emit('update:modelValue', props.modelValue.includes(stash)
    ? props.modelValue.filter(value => value !== stash)
    : [...props.modelValue, stash])
}
</script>

<template>
  <fieldset ref="root" class="stash-filter" @keydown.esc.stop.prevent="close(true)"
    @focusout="event => { if (!root?.contains(event.relatedTarget as Node)) close() }">
    <legend>{{ t('stashFilterTitle') }}</legend>
    <button ref="trigger" class="stash-filter-trigger" type="button" :aria-label="t('stashFilterTitle')"
      :aria-expanded="open" :aria-controls="panelId" @click="open = !open">
      <span>{{ modelValue.length ? t('stashFilterCount', { count: modelValue.length }) : t('allStashes') }}</span>
      <span aria-hidden="true">⌄</span>
    </button>
    <div v-if="open" :id="panelId" class="stash-filter-panel">
      <div v-if="modelValue.length" class="stash-filter-heading">
        <button type="button" @click="selectAll">{{ t('allStashes') }}</button>
      </div>
      <div class="stash-filter-options">
        <label v-for="stash in [...new Set(options)]" :key="stash" :class="{ selected: modelValue.includes(stash) }">
          <input type="checkbox" name="stash" :value="stash" :checked="modelValue.includes(stash)" @change="toggle(stash)" />
          <span>{{ stash }}</span>
        </label>
      </div>
    </div>
  </fieldset>
</template>
