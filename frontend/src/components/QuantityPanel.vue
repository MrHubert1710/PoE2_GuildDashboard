<script setup lang="ts">
import CollapsiblePanel from './CollapsiblePanel.vue'
import { watch } from 'vue'
import type { HistoryQuery } from '../browsing'
import { t, number, date } from '../i18n'
import { useQuantityReport } from '../composables/useQuantityReport'
const props = defineProps<{ leagueId: string; revision: string; settingsHash?: string; query: HistoryQuery; view: string; refreshToken: number }>()
const emit = defineEmits<{ generated: []; progress: [state: 'pending' | 'failed' | 'ready']; problem: []; projection: [id: string | null] }>()
const { report, error, jobState, busy, move, enqueue } = useQuantityReport(props, () => emit('generated'))
watch(report, value => emit('projection', value?.projection.id ?? null))
watch(error, value => { if (value) emit('problem') })
watch([report, jobState], () => {
  if (jobState.value === 'failed') emit('progress', 'failed')
  else if (report.value) emit('progress', report.value.projection.state === 'ready' ? 'ready' : 'pending')
})
const signed = (value: number) => (value > 0 ? '+' : '') + number(value)
</script>
<template>
  <section class="quantity-panel" :aria-label="t('quantity.title')" data-testid="quantity-panel">
    <p v-if="error" role="alert">{{ t(`quantity.error.${error}`) }}</p>
    <p v-if="report && report.projection.state !== 'ready'" role="status">{{ t(`quantity.${jobState === 'failed' ? 'failed' : 'pending'}`) }}</p>
    <p v-if="!report && !error" role="status">{{ t('quantity.loading') }}</p>
    <button v-if="error || jobState === 'failed'" type="button" :disabled="busy" @click="enqueue('manual')">{{ t('quantity.rebuild') }}</button>
    <template v-if="report?.projection.state === 'ready'">
      <slot v-if="!error" />
      <CollapsiblePanel :title="t('layout.table')" :storage-key="'table:'+leagueId+':'+view" data-testid="quantity-table-container">
      <p v-if="!report.rows.length" class="empty-state">{{ t('quantity.empty') }}</p>
      <div v-else class="transactions-scroll" tabindex="0" role="region" :aria-label="t('quantity.table')">
        <table class="transactions quantity-table"><thead><tr>
          <th v-if="view === 'players'">{{ t('player') }}</th><th v-if="view === 'stashes' || view === 'state'">{{ t('stash') }}</th><th v-if="view === 'state'">{{ t('position') }}</th>
          <th>{{ t('item') }}</th>
          <template v-if="view === 'state'"><th>{{ t('quantity.observedQuantity') }}</th><th>{{ t('quantity.lastEvent') }}</th></template>
          <template v-else><th>{{ t('added') }}</th><th>{{ t('removed') }}</th><th>{{ t('quantity.balance') }}</th><th>{{ t('quantity.inferredUnits') }}</th></template>
        </tr></thead><tbody><tr v-for="(row, index) in report.rows" :key="index">
          <td v-if="view === 'players'">{{ row.reconstruction ? t('quantity.reconstruction') : row.account }}</td><td v-if="view === 'stashes' || view === 'state'">{{ row.stash }}</td><td v-if="view === 'state'">{{ row.x }}, {{ row.y }}</td><td>{{ row.item_name }}</td>
          <template v-if="view === 'state'"><td>{{ row.quantity === null ? t('quantity.unknown') : number(row.quantity!) }}</td><td>{{ date(row.occurred_at!, report.settings.timezone) }}</td></template>
          <template v-else><td>+{{ number(row.added!) }}</td><td>−{{ number(row.removed!) }}</td><td>{{ signed(row.net!) }}</td><td>{{ number(row.inferred_quantity!) }}</td></template>
        </tr></tbody></table>
      </div>
      <nav v-if="report.pages > 1" class="pagination" :aria-label="t('quantity.pages')"><button :disabled="report.page <= 1" @click="move(report.page - 1)">{{ t('previous') }}</button><span>{{ number(report.page) }} / {{ number(report.pages) }}</span><button :disabled="report.page >= report.pages" @click="move(report.page + 1)">{{ t('next') }}</button></nav>
      </CollapsiblePanel>
      <CollapsiblePanel :title="t('layout.info')" :storage-key="'info:'+leagueId+':'+view" :initial-open="false" data-testid="report-info">
      <div v-if="view === 'summary' && report.stats" class="overview-cards">
        <article><span>{{ t('workspace.events') }}</span><strong>{{ number(report.stats.events) }}</strong></article>
        <article><span>{{ t('workspace.unresolved') }}</span><strong>{{ number(report.stats.unknown) }}</strong></article>
        <article><span>{{ t('workspace.inferred') }}</span><strong>{{ number(report.stats.inferred) }}</strong></article>
      </div>

      <p class="footnote">{{ t('quantity.generated', { date: date(report.projection.generated_at, report.settings.timezone), zone: report.settings.timezone, version: report.projection.algorithm_version }) }}</p>
      <p v-if="report.stats && view !== 'state'" class="footnote" data-testid="quantity-stats">{{ t('quantity.stats', { events: report.stats.events, unknown: report.stats.unknown, inferred: report.stats.inferred, excluded: report.stats.excluded, warnings: report.stats.warnings }) }}</p>
      <p v-if="view === 'state'" class="footnote">{{ t('quantity.stateNote') }}</p>
      <p v-if="view !== 'state'" class="footnote">{{ t('quantity.reconstructionNote') }}</p>
      <p v-if="view !== 'state'" class="footnote">{{ t('quantity.filtersNote',{zone:report.settings.timezone}) }}</p>
        <button type="button" :disabled="busy || jobState === 'running' || jobState === 'queued'" @click="enqueue('manual')">{{ t('quantity.rebuild') }}</button>
      </CollapsiblePanel>
    </template>

  </section>
</template>
