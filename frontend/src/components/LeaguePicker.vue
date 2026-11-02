<script setup lang="ts">
import { t, compactNumber, number } from '../i18n'
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import type { League } from '../browsing'

const props = defineProps<{ leagues: League[]; selectedId: string; disabled: boolean }>()
const emit = defineEmits<{ select: [id: string] }>()
const root = ref<HTMLElement | null>(null)
const open = ref(false)
const active = ref(0)
const selected = computed(() => props.leagues.find(league => league.id === props.selectedId))

function status(league: League) {
  if (league.lifecycle === 'active') return { label: 'active', kind: 'active', title: 'activeTitle' }
  if (league.archived) return { label: 'archived', kind: 'archived', title: 'archivedTitle' }
  if (league.lifecycle === 'ended') return { label: 'ended', kind: 'ended', title: 'endedTitle' }
  return { label: 'unknown', kind: 'unknown', title: 'unknownTitle' }
}
function show() {
  if (props.disabled) return
  active.value = Math.max(0, props.leagues.findIndex(league => league.id === props.selectedId))
  open.value = true
}
function choose(index: number) {
  const league = props.leagues[index]
  if (league) emit('select', league.id)
  open.value = false
}
function keydown(event: KeyboardEvent) {
  if (event.key === 'Tab') { open.value = false; return }
  if (event.key === 'Escape') { open.value = false; event.preventDefault(); return }
  if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
    event.preventDefault()
    if (!open.value) show()
    else if (event.key === 'ArrowDown') active.value = Math.min(props.leagues.length - 1, active.value + 1)
    else if (event.key === 'ArrowUp') active.value = Math.max(0, active.value - 1)
    if (event.key === 'Home') active.value = 0
    if (event.key === 'End') active.value = props.leagues.length - 1
    void nextTick(() => root.value?.querySelector('[data-active="true"]')?.scrollIntoView({ block: 'nearest' }))
  }
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    if (open.value) choose(active.value)
    else show()
  }
}
function outside(event: PointerEvent) {
  if (!root.value?.contains(event.target as Node)) open.value = false
}
onMounted(() => document.addEventListener('pointerdown', outside))
onUnmounted(() => document.removeEventListener('pointerdown', outside))
</script>

<template>
  <div ref="root" class="league-picker" @focusout="event => { if (!root?.contains(event.relatedTarget as Node)) open = false }">
    <button type="button" role="combobox" :aria-label="t('league')" aria-haspopup="listbox" aria-controls="league-options"
      :aria-expanded="open" :aria-activedescendant="open ? `league-option-${active}` : undefined" :disabled="disabled"
      @click="open ? open = false : show()" @keydown="keydown">
      <span class="picker-caption">{{ t('league') }}</span><span class="picker-name">{{ selected?.name ?? t('chooseLeague') }}</span>
      <span v-if="selected" class="league-status" :class="status(selected).kind" :title="t(status(selected).title)">{{ t(status(selected).label) }}</span>
      <span v-if="selected" class="league-count" :title="t('historyCount',{count:number(selected.transactions)})">{{ compactNumber(selected.transactions) }}</span>
      <span aria-hidden="true" class="picker-arrow">⌄</span>
    </button>
    <ul v-if="open" id="league-options" role="listbox" :aria-label="t('availableLeagues')" class="league-options">
      <li v-for="(league, index) in leagues" :id="`league-option-${index}`" :key="league.id" role="option"
        :aria-selected="league.id === selectedId" :data-active="index === active" @pointermove="active = index"
        @mousedown.prevent @click="choose(index)">
        <span>{{ league.name }}</span><span class="league-status" :class="status(league).kind" :title="t(status(league).title)">{{ t(status(league).label) }}</span><span class="league-count" :title="t('historyCount',{count:number(league.transactions)})">{{ compactNumber(league.transactions) }}</span>
      </li>
    </ul>
  </div>
</template>
