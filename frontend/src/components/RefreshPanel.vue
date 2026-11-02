<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { t, date, displayTimezone } from '../i18n'
interface Job { state: string; attempts: number; error_code: string | null; available_at: string }
interface ScopeStatus { available: boolean; reason: string | null; last_success_at: string | null; cooldown_until: string | null; automatic_retry_at: string | null; job: Job | null; last_result: { transactions: number; revision: string } | null }
interface Status { display_settings_hash?: string; quantity_settings_hash?: string; league_id: string; revision: string; worker: string; history: ScopeStatus; local_verify: ScopeStatus; last_generated_at: string | null }
const props = defineProps<{ leagueId: string; revision: string; diagnostics: boolean }>()
const emit = defineEmits<{ revisionChanged: [] }>()
const status = ref<Status | null>(null)
const busy = ref(false)
const error = ref(false)
const requestError = ref(false)
let noticeKind: 'history' | 'local_verify' = 'history'
const notice = ref('')
let timer: ReturnType<typeof setTimeout> | undefined
let stopped = false
let sequence = 0
let previousSettings: string | undefined
const controllers = new Set<AbortController>()
const url = `${import.meta.env.BASE_URL}api/leagues/${encodeURIComponent(props.leagueId)}/refresh`
const active = (scope: ScopeStatus | undefined) => !!scope?.job && ['queued', 'running'].includes(scope.job.state)
const pending = computed(() => active(status.value?.history) || active(status.value?.local_verify))
async function request(options?: RequestInit) {
  const controller = new AbortController()
  controllers.add(controller)
  const timeout = setTimeout(() => controller.abort(), 8000)
  try {
    const response = await fetch(url, { ...options, cache: 'no-store', signal: controller.signal })
    if (!response.ok) throw new Error('Refresh unavailable')
    return await response.json()
  } finally { clearTimeout(timeout); controllers.delete(controller) }
}
async function load() {
  const current = ++sequence
  try {
    const payload: Status = await request()
    if (stopped || current !== sequence) return
    if (payload.league_id !== props.leagueId || !payload.history || !payload.local_verify) throw new Error('Invalid status')
    if (['refresh.queued', 'refresh.coalesced', 'refresh.cooldown'].includes(notice.value) && !active(payload[noticeKind])) notice.value = ''
    status.value = payload
    error.value = false
    if (payload.revision !== props.revision || (previousSettings && previousSettings !== payload.quantity_settings_hash + ':' + (payload.display_settings_hash ?? ''))) emit('revisionChanged')
    previousSettings = payload.quantity_settings_hash + ':' + (payload.display_settings_hash ?? '')
  } catch { if (!stopped && current === sequence) error.value = true }
}
async function submit(kind: 'history' | 'local_verify', trigger: 'manual' | 'automatic' = 'manual') {
  busy.value = true
  requestError.value = false
  noticeKind = kind
  try {
    const result = await request({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ kind, trigger }) })
    if (!stopped && trigger === 'manual') notice.value = `refresh.${result.reason ?? result.outcome}`
  } catch { if (!stopped) requestError.value = true }
  finally {
    if (!stopped) {
      busy.value = false
      await load()
      if (trigger === 'manual' && !stopped) { clearTimeout(timer); timer = setTimeout(poll, pending.value ? 1000 : 5000) }
    }
  }
}
async function poll() {
  await load()
  if (!stopped) timer = setTimeout(poll, pending.value ? 1000 : 5000)
}
function jobText(scope: ScopeStatus) {
  if (!scope.job) return t('refresh.idle')
  return t(`refresh.${scope.job.state}`)
}
onMounted(async () => {
  await submit('history', 'automatic')
  if (!stopped) timer = setTimeout(poll, pending.value ? 1000 : 5000)
})
onUnmounted(() => { stopped = true; clearTimeout(timer); controllers.forEach(controller => controller.abort()) })
</script>

<template>
  <Teleport to="#header-actions"><div class="sync-strip" data-testid="sync-strip">
    <span v-if="pending" role="status">{{ t('workspace.updating') }}</span>
    <button type="button" :disabled="busy || !status?.history.available || active(status?.history)" :title="status?.history.reason ? t(`refresh.${status.history.reason}`) : undefined" @click="submit('history')">{{ t('refresh.fetch') }}</button>
    <span v-if="error" role="alert">{{ t('refresh.statusError') }}</span>
    <span v-if="requestError" role="alert">{{ t('refresh.requestError') }}</span>
  </div></Teleport>
  <Teleport to="#league-sync-diagnostics">

  <section v-show="diagnostics" class="refresh-panel" :aria-label="t('refresh.title')" data-testid="refresh-panel">
    <div class="section-heading"><h2>{{ t('refresh.title') }}</h2><span>{{ t(!status ? 'refresh.loading' : status.worker === 'online' ? 'refresh.workerOnline' : 'refresh.workerOffline') }}</span></div>
    <p v-if="error" role="alert">{{ t('refresh.statusError') }}</p>
    <p v-if="requestError" role="alert">{{ t('refresh.requestError') }}</p>
    <template v-if="status">
      <p class="footnote">{{ t(status.history.reason === 'archived' ? 'refresh.archiveNote' : status.history.reason === 'source_unavailable' ? 'refresh.unavailableNote' : 'refresh.autoNote') }}</p>
      <div class="refresh-facts">
        <p>{{ t('refresh.lastSync', { date: status.history.last_success_at ? date(status.history.last_success_at) + ' ' + displayTimezone : t('refresh.never') }) }}</p>
        <p>{{ t('refresh.lastGenerated', { date: status.last_generated_at ? date(status.last_generated_at) + ' ' + displayTimezone : t('refresh.never') }) }}</p>
        <p>{{ t('refresh.lastVerified', { date: status.local_verify.last_success_at ? date(status.local_verify.last_success_at) + ' ' + displayTimezone : t('refresh.never') }) }}</p>
      </div>
      <div class="filter-actions">
        <button type="button" :disabled="busy || !status.history.available || active(status.history)" @click="submit('history')">{{ t('refresh.fetch') }}</button>
        <button type="button" :disabled="busy || active(status.local_verify)" @click="submit('local_verify')">{{ t('refresh.verify') }}</button>
      </div>
      <p v-if="notice" role="status">{{ t(notice) }}</p>
      <div v-for="kind in (['history', 'local_verify'] as const)" :key="kind" class="refresh-job">
        <p v-if="status[kind].job" role="status">{{ t(kind === 'history' ? 'refresh.historyJob' : 'refresh.localJob', { state: jobText(status[kind]), attempts: status[kind].job!.attempts }) }}</p>
        <p v-if="status[kind].job?.error_code" class="footnote">{{ t(`refresh.error.${status[kind].job!.error_code}`) }}</p>
        <p v-if="status[kind].job?.state === 'queued'" class="footnote">{{ t('refresh.waitUntil', { date: date(status[kind].job!.available_at) + ' ' + displayTimezone }) }}</p>
      </div>
      <p v-if="status.history.automatic_retry_at" class="footnote">{{ t('refresh.limitUntil', { date: date(status.history.automatic_retry_at) + ' ' + displayTimezone }) }}</p>
      <p v-if="status.local_verify.last_result" class="footnote">{{ t('refresh.verifiedCount', { count: status.local_verify.last_result.transactions }) }}</p>
      <p class="footnote">{{ t('refresh.localNote') }}</p>
    </template>
  </section>
  </Teleport>
</template>
