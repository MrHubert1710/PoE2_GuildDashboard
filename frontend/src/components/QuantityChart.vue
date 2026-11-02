<script setup lang="ts">
import { computed, defineAsyncComponent, ref } from 'vue'
import type { HistoryQuery } from '../browsing'
import { currentUrl, updateUrl } from '../navigation'
import { useQuantitySeries } from '../composables/useQuantitySeries'
import { t, date, number } from '../i18n'
const TimeSeriesChart = defineAsyncComponent(() => import('./TimeSeriesChart.vue'))
const props = defineProps<{ leagueId: string; revision: string; settingsHash?: string; projectionId: string | null; query: HistoryQuery; active: boolean; refreshToken: number }>()
const emit = defineEmits<{ range: [from: string, to: string] }>()
const { data, error, loading, selectedItem, chooseItem, reload } = useQuantitySeries(props)
const graph = ref<InstanceType<typeof import('./TimeSeriesChart.vue')['default']>>()
const enabled = computed(() => {
  const value = new URL(currentUrl.value).searchParams.get('chart_series')
  return value === null ? ['added','removed','net'] : value.split(',').filter(key => ['added','removed','net'].includes(key))
})
const window = computed(() => {
  if (!data.value?.bounds) return null
  const params = new URL(currentUrl.value).searchParams
  const from = Number(params.get('chart_from')), to = Number(params.get('chart_to'))
  if (!params.has('chart_from') || !Number.isSafeInteger(from) || !Number.isSafeInteger(to) || from >= to) return null
  const start = Math.max(from, data.value.bounds.start), end = Math.min(to, data.value.bounds.end)
  return start < end ? { start, end } : null
})
const items = computed(() => [...new Set([data.value?.item, selectedItem.value, ...(data.value?.items ?? [])].filter((value): value is string => Boolean(value)))])
function toggle(key: string, checked: boolean) {
  const values = new Set(enabled.value)
  if (checked) values.add(key); else values.delete(key)
  const url = new URL(currentUrl.value); url.searchParams.set('chart_series', [...values].join(',')); updateUrl(url, true)
}
function zoom(value: { start: number; end: number }) {
  const url = new URL(currentUrl.value)
  url.searchParams.set('chart_from', String(value.start)); url.searchParams.set('chart_to', String(value.end)); updateUrl(url, true)
}
function reset() {
  const url = new URL(currentUrl.value); url.searchParams.delete('chart_from'); url.searchParams.delete('chart_to'); updateUrl(url, true)
}
function applyRange() {
  if (!window.value) return
  const from = new Date(window.value.start).toISOString().slice(0,10)
  const to = new Date(Math.max(window.value.start,window.value.end-1)).toISOString().slice(0,10)
  emit('range', from, to)
}
</script>
<template><section class="quantity-chart" :aria-label="t('chart.title')" data-testid="quantity-chart">
  <div class="section-heading"><h2>{{ t('chart.title') }}</h2><button type="button" :disabled="loading || !projectionId" @click="reload">{{ t('chart.refresh') }}</button></div>
  <p class="footnote">{{ t('chart.note') }}</p>
  <label class="chart-item">{{ t('chart.item') }}<select :aria-label="t('chart.item')" :value="data?.item ?? selectedItem" :disabled="loading || !items.length" @change="chooseItem(($event.target as HTMLSelectElement).value)"><option v-for="item in items" :key="item" :value="item">{{ item }}</option></select></label>
  <p v-if="error" role="alert">{{ t(`quantity.error.${error}`) }}</p>
  <p v-else-if="loading" role="status">{{ t('chart.loading') }}</p>
  <p v-else-if="!projectionId" role="status">{{ t('quantity.pending') }}</p>
  <p v-else-if="!data?.points.length" class="empty-state">{{ t('chart.empty') }}</p>
  <p v-if="data?.unresolved_events" class="footnote" data-testid="chart-unresolved">{{ t('chart.unresolved',{count:data.unresolved_events}) }}</p>
  <template v-if="data?.points.length && data.bounds">
    <div class="chart-controls">
      <label v-for="key in ['added','removed','net']" :key="key" class="check-label"><input type="checkbox" :checked="enabled.includes(key)" @change="toggle(key,($event.target as HTMLInputElement).checked)" />{{ t(`chart.series.${key}`) }}</label>
      <button type="button" @click="graph?.zoomIn()">{{ t('chart.zoom') }}</button><button type="button" @click="reset">{{ t('chart.reset') }}</button>
      <button type="button" :disabled="!window" @click="applyRange">{{ t('chart.apply') }}</button>
    </div>
    <p v-if="window" class="footnote" data-testid="chart-window">{{ date(new Date(window.start).toISOString(),data.timezone) }} — {{ date(new Date(window.end).toISOString(),data.timezone) }} {{ data.timezone }}</p>
    <TimeSeriesChart ref="graph" :points="data.points" :bounds="data.bounds" :timezone="data.timezone" :enabled="enabled" :window="window" @zoom="zoom" />
    <p class="footnote">{{ t('chart.bucket',{hours:number((data.bucket_seconds ?? 0)/3600),count:data.points.length}) }} {{ t('chart.interaction') }}</p>
    <p class="footnote" data-testid="chart-totals">{{ t('chart.totals',{added:number(data.totals.added),removed:number(data.totals.removed),net:number(data.totals.net),inferred:number(data.totals.inferred)}) }}</p>
    <details class="chart-data"><summary>{{ t('chart.data') }}</summary><div class="transactions-scroll" tabindex="0"><table class="transactions"><thead><tr><th>{{ t('quantity.dateZone',{zone:data.timezone}) }}</th><th>{{ t('added') }}</th><th>{{ t('removed') }}</th><th>{{ t('quantity.balance') }}</th></tr></thead><tbody><tr v-for="point in data.points" :key="point.timestamp"><td>{{ date(new Date(point.timestamp).toISOString(),data.timezone) }}</td><td>{{ number(point.added) }}</td><td>{{ number(point.removed) }}</td><td>{{ number(point.net) }}</td></tr></tbody></table></div></details>
  </template>
</section></template>
