<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import type { HistoryQuery } from '../browsing'
import { t, number, date } from '../i18n'
interface Settings { target_stashes: string[] | null; stash_aliases: Record<string, string>; timezone: string }
interface Row { item_name: string; account?: string; stash?: string; source_id?: number; x?: number; y?: number; quantity?: number | null; occurred_at?: string; added?: number; removed?: number; net?: number; inferred_quantity?: number; movements?: number }
interface Report { league_id: string; projection: { state: string; id: string | null; input_revision: string; algorithm_version: string; generated_at: string | null }; settings: Settings; rows: Row[]; page: number; pages: number; total: number; stats: {events: number; unknown: number; inferred: number; excluded: number; warnings: number} | null }
const props = defineProps<{ leagueId: string; revision: string; settingsHash?: string; query: HistoryQuery }>()
const emit = defineEmits<{ generated: []; settingsChanged: [] }>()
const views = ['summary', 'players', 'stashes', 'state']
const readView = () => { const value = new URLSearchParams(location.search).get('analysis') ?? 'summary'; return views.includes(value) ? value : 'summary' }
const readPage = () => Math.max(1, Math.min(1000000, Number(new URLSearchParams(location.search).get('analysis_page')) || 1))
const view = ref(readView()), page = ref(readPage())
const report = ref<Report | null>(null)
const error = ref(''), jobState = ref(''), busy = ref(false), saving = ref(false)
const settingsError = ref('')
const scope = ref('league'), guildAvailable = ref(false), guildHash = ref(''), inherited = ref(false)
const settingsHash = ref(''), rawStashes = ref<string[]>([])
const allStashes = ref(true), targets = ref<string[]>([]), timezone = ref('UTC')
const aliases = reactive<Record<string, string>>({})
const canonicalStashes = computed(() => [...new Set(rawStashes.value.map(name => aliases[name]?.trim() || name))].sort())
const timezones = ['UTC', ...Intl.supportedValuesOf('timeZone')]
const base = `${import.meta.env.BASE_URL}api/leagues/${encodeURIComponent(props.leagueId)}`
let stopped = false, sequence = 0, wasPending = false
let timer: ReturnType<typeof setTimeout> | undefined
const controllers = new Set<AbortController>()
const signed = (value: number) => (value > 0 ? '+' : '') + number(value)
function writeUrl(replace = false) {
  const url = new URL(location.href)
  if (view.value === 'summary') url.searchParams.delete('analysis'); else url.searchParams.set('analysis', view.value)
  if (page.value === 1) url.searchParams.delete('analysis_page'); else url.searchParams.set('analysis_page', String(page.value))
  if (url.href !== location.href) history[replace ? 'replaceState' : 'pushState'](null, '', url)
}
async function request(path: string, options?: RequestInit) {
  const controller = new AbortController(); controllers.add(controller)
  const timeout = setTimeout(() => controller.abort(), 15000)
  try {
    const response = await fetch(base + path, { ...options, cache: 'no-store', signal: controller.signal })
    const payload = await response.json()
    if (!response.ok) throw new Error(payload.error ?? 'report_unavailable')
    return payload
  } finally { clearTimeout(timeout); controllers.delete(controller) }
}
async function loadSettings() {
  const result = await request('/quantity-settings')
  if (stopped) return
  guildAvailable.value = result.guild_available
  guildHash.value = result.guild_hash
  inherited.value = result.provenance === 'guild_defaults'
  settingsHash.value = result.settings_hash
  rawStashes.value = result.stashes
  allStashes.value = result.settings.target_stashes === null
  targets.value = result.settings.target_stashes ?? []
  timezone.value = result.settings.timezone
  for (const key of Object.keys(aliases)) delete aliases[key]
  Object.assign(aliases, result.settings.stash_aliases)
}
async function load() {
  const current = ++sequence
  clearTimeout(timer)
  try {
    const params = new URLSearchParams({ view: view.value, page: String(page.value), page_size: '25', revision: props.revision })
    for (const key of (view.value === 'state' ? ['stash', 'item'] : ['account', 'stash', 'item', 'from', 'to']) as Array<keyof HistoryQuery>) {
      if (key === 'stash') {
        for (const stash of props.query.stash) params.append('stash', stash)
      } else if (props.query[key]) params.set(key, String(props.query[key]))
    }
    const payload: Report = await request('/quantities?' + params)
    if (stopped || current !== sequence) return
    if (payload.league_id !== props.leagueId) throw new Error('report_unavailable')
    report.value = payload; error.value = ''
    if (payload.page !== page.value) { page.value = payload.page; writeUrl(true) }
    if (payload.projection.state === 'ready') {
      clearTimeout(timer)
      jobState.value = ''
      if (wasPending) { wasPending = false; emit('generated') }
    } else {
      wasPending = true
      const status = await request('/refresh')
      if (stopped || current !== sequence) return
      jobState.value = status.quantities?.job?.state ?? ''
      if (!['queued', 'running', 'failed'].includes(jobState.value)) await enqueue('automatic')
      if (jobState.value !== 'failed') timer = setTimeout(load, 1200)
    }
  } catch (cause) {
    if (!stopped && current === sequence) error.value = cause instanceof Error ? cause.message : 'report_unavailable'
  }
}
async function enqueue(trigger: 'manual' | 'automatic' = 'manual') {
  busy.value = true
  try {
    await request('/refresh', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ kind: 'quantities', trigger }) })
    if (trigger === 'manual' && !stopped) { jobState.value = 'queued'; clearTimeout(timer); timer = setTimeout(load, 1000) }
  } catch { if (!stopped) error.value = 'report_unavailable' }
  finally { if (!stopped) busy.value = false }
}
async function save(selectedScope = scope.value) {
  saving.value = true; settingsError.value = ''
  try {
    const stash_aliases = Object.fromEntries(rawStashes.value.map(name => [name, aliases[name]?.trim() ?? '']).filter(([raw, alias]) => alias && alias !== raw))
    const result = await request('/quantity-settings', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ expected_hash: settingsHash.value, scope: selectedScope, expected_guild_hash: guildHash.value,
      settings: { target_stashes: allStashes.value ? null : targets.value, stash_aliases, timezone: timezone.value.trim() } }) })
    if (stopped) return
    settingsHash.value = result.settings_hash
    await loadSettings()
    wasPending = true; report.value = null
    emit('settingsChanged')
    await enqueue('manual'); await load()
  } catch (cause) { if (!stopped) settingsError.value = cause instanceof Error ? cause.message : 'invalid_settings' }
  finally { if (!stopped) saving.value = false }
}
function choose(value: string) { report.value = null; view.value = value; page.value = 1; writeUrl(); void load() }
function move(value: number) { page.value = value; writeUrl(); void load() }
function pop() {
  const nextView = readView(), nextPage = readPage()
  if (nextView !== view.value || nextPage !== page.value) { view.value = nextView; page.value = nextPage; void load() }
}
watch(() => JSON.stringify([props.query.account, props.query.stash, props.query.item, props.query.from, props.query.to]), () => { page.value = 1; writeUrl(true); void load() })
watch(() => [props.revision, props.settingsHash], () => { void load() })
onMounted(() => { window.addEventListener('popstate', pop); void loadSettings().catch(() => { settingsError.value = 'report_unavailable' }); void load() })
onUnmounted(() => { stopped = true; ++sequence; clearTimeout(timer); controllers.forEach(c => c.abort()); window.removeEventListener('popstate', pop) })
</script>

<template>
  <section class="quantity-panel" :aria-label="t('quantity.title')" data-testid="quantity-panel">
    <div class="section-heading"><h2>{{ t('quantity.title') }}</h2><button type="button" :disabled="busy || jobState === 'running' || jobState === 'queued'" @click="enqueue('manual')">{{ t('quantity.rebuild') }}</button></div>
    <p class="footnote">{{ t('quantity.observedOnly') }}</p>
    <details class="quantity-settings">
      <summary>{{ t('quantity.settings') }}</summary>
      <form @submit.prevent="save()">
        <p class="footnote">{{ t('quantity.settingsNote') }}</p>
        <p>{{ t(inherited ? 'quantity.inheriting' : 'quantity.overridden') }}</p>
        <label>{{ t('quantity.saveScope') }}<select v-model="scope" :aria-label="t('quantity.saveScope')"><option value="league">{{ t('quantity.scopeLeague') }}</option><option v-if="guildAvailable" value="guild">{{ t('quantity.scopeGuild') }}</option></select></label>
        <label class="check-label"><input v-model="allStashes" type="checkbox" />{{ t('quantity.allStashes') }}</label>
        <div v-if="!allStashes" class="target-stashes"><label v-for="name in canonicalStashes" :key="name" class="check-label"><input v-model="targets" type="checkbox" :value="name" />{{ name }}</label></div>
        <label>{{ t('quantity.timezone') }}<input v-model="timezone" list="quantity-timezones" required maxlength="100" /><datalist id="quantity-timezones"><option v-for="zone in timezones" :key="zone" :value="zone" /></datalist></label>
        <p class="footnote">{{ t('quantity.aliasNote') }}</p>
        <div class="alias-grid"><label v-for="name in rawStashes" :key="name">{{ name }}<input v-model="aliases[name]" :aria-label="t('quantity.aliasFor', { name })" :placeholder="name" maxlength="200" /></label></div>
        <p v-if="settingsError" role="alert">{{ t(`quantity.error.${settingsError}`) }}</p>
        <div class="filter-actions"><button type="submit" :disabled="saving">{{ t('quantity.save') }}</button><button v-if="!inherited" type="button" :disabled="saving" @click="save('inherit')">{{ t('quantity.restoreInheritance') }}</button></div>
      </form>
    </details>
    <nav class="quantity-tabs" :aria-label="t('quantity.views')"><button v-for="value in views" :key="value" type="button" :aria-current="view === value ? 'page' : undefined" @click="choose(value)">{{ t(`quantity.view.${value}`) }}</button></nav>
    <p v-if="error" role="alert">{{ t(`quantity.error.${error}`) }}</p>
    <p v-if="report && report.projection.state !== 'ready'" role="status">{{ t(`quantity.${jobState === 'failed' ? 'failed' : 'pending'}`) }}</p>
    <p v-if="!report && !error" role="status">{{ t('quantity.loading') }}</p>
    <template v-if="report?.projection.state === 'ready'">
      <p class="footnote">{{ t('quantity.generated', { date: date(report.projection.generated_at, report.settings.timezone), zone: report.settings.timezone, version: report.projection.algorithm_version }) }}</p>
      <p v-if="report.stats && view !== 'state'" class="footnote" data-testid="quantity-stats">{{ t('quantity.stats', { events: report.stats.events, unknown: report.stats.unknown, inferred: report.stats.inferred, excluded: report.stats.excluded, warnings: report.stats.warnings }) }}</p>
      <p v-if="view === 'state'" class="footnote">{{ t('quantity.stateNote') }}</p>
      <p v-else class="footnote">{{ t('quantity.filtersNote') }}</p>
      <p v-if="!report.rows.length" class="empty-state">{{ t('quantity.empty') }}</p>
      <div v-else class="transactions-scroll" tabindex="0" role="region" :aria-label="t('quantity.table')">
        <table class="transactions quantity-table"><thead><tr>
          <th v-if="view === 'players'">{{ t('player') }}</th><th v-if="view === 'stashes' || view === 'state'">{{ t('stash') }}</th><th v-if="view === 'state'">{{ t('position') }}</th>
          <th>{{ t('item') }}</th>
          <template v-if="view === 'state'"><th>{{ t('quantity.observedQuantity') }}</th><th>{{ t('quantity.lastEvent') }}</th></template>
          <template v-else><th>{{ t('added') }}</th><th>{{ t('removed') }}</th><th>{{ t('quantity.balance') }}</th><th>{{ t('quantity.inferredUnits') }}</th></template>
        </tr></thead><tbody><tr v-for="(row, index) in report.rows" :key="index">
          <td v-if="view === 'players'">{{ row.account }}</td><td v-if="view === 'stashes' || view === 'state'">{{ row.stash }}</td><td v-if="view === 'state'">{{ row.x }}, {{ row.y }}</td><td>{{ row.item_name }}</td>
          <template v-if="view === 'state'"><td>{{ row.quantity === null ? t('quantity.unknown') : number(row.quantity!) }}</td><td>{{ date(row.occurred_at!, report.settings.timezone) }}</td></template>
          <template v-else><td>+{{ number(row.added!) }}</td><td>−{{ number(row.removed!) }}</td><td>{{ signed(row.net!) }}</td><td>{{ number(row.inferred_quantity!) }}</td></template>
        </tr></tbody></table>
      </div>
      <nav v-if="report.pages > 1" class="pagination" :aria-label="t('quantity.pages')"><button :disabled="report.page <= 1" @click="move(report.page - 1)">{{ t('previous') }}</button><span>{{ number(report.page) }} / {{ number(report.pages) }}</span><button :disabled="report.page >= report.pages" @click="move(report.page + 1)">{{ t('next') }}</button></nav>
    </template>
  </section>
</template>
