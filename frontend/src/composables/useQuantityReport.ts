import { displayTimezone } from '../i18n'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import type { HistoryQuery } from '../browsing'
import { currentUrl, updateUrl } from '../navigation'
import { useApiRequest } from './useApiRequest'
interface Settings { target_stashes: string[] | null; stash_aliases: Record<string, string>; timezone: string }
interface Row { item_name: string; account?: string; stash?: string; source_id?: number; x?: number; y?: number; quantity?: number | null; occurred_at?: string; added?: number; removed?: number; net?: number; inferred_quantity?: number; movements?: number }
interface Report { league_id: string; projection: { state: string; id: string | null; input_revision: string; algorithm_version: string; generated_at: string | null }; settings: Settings; rows: Row[]; page: number; pages: number; total: number; stats: {events: number; unknown: number; inferred: number; excluded: number; warnings: number} | null }
export function useQuantityReport(props: { leagueId: string; revision: string; settingsHash?: string; query: HistoryQuery; view: string; refreshToken: number }, onGenerated: () => void) {
  const view = computed(() => props.view)
  const readPage = () => { const value = Number(new URL(currentUrl.value).searchParams.get('analysis_page')); return Number.isSafeInteger(value) && value >= 1 && value <= 1000000 ? value : 1 }
  const page = ref(readPage())
  const report = ref<Report | null>(null)
  const error = ref(''), jobState = ref(''), busy = ref(false)
  const { request, stopped } = useApiRequest(`${import.meta.env.BASE_URL}api/leagues/${encodeURIComponent(props.leagueId)}`)
  let sequence = 0, wasPending = false
  let timer: ReturnType<typeof setTimeout> | undefined
  function writePage(replace = false) {
    const url = new URL(location.href)
    if (page.value === 1) url.searchParams.delete('analysis_page'); else url.searchParams.set('analysis_page', String(page.value))
    updateUrl(url, replace)
  }
  async function load() {
    const current = ++sequence
    clearTimeout(timer)
    try {
      const params = new URLSearchParams({ timezone:displayTimezone.value, view: view.value, page: String(page.value), page_size: '25', revision: props.revision })
      for (const key of (view.value === 'state' ? ['stash', 'item', 'item_regex', 'item_case', 'item_word'] : ['account', 'account_regex', 'account_case', 'account_word', 'stash', 'item', 'item_regex', 'item_case', 'item_word', 'from', 'to']) as Array<keyof HistoryQuery>) {
        if (key === 'stash') {
          for (const stash of props.query.stash) params.append('stash', stash)
        } else if (typeof props.query[key] === 'boolean') {
          if (props.query[key]) params.set(key, '1')
        } else if (props.query[key]) params.set(key, String(props.query[key]))
      }
      const payload: Report = await request('/quantities?' + params)
      if (stopped() || current !== sequence) return
      if (payload.league_id !== props.leagueId) throw new Error('report_unavailable')
      report.value = payload; error.value = ''
      if (payload.page !== page.value) { page.value = payload.page; writePage(true) }
      if (payload.projection.state === 'ready') {
        clearTimeout(timer)
        jobState.value = ''
        if (wasPending) { wasPending = false; onGenerated() }
      } else {
        wasPending = true
        const status = await request('/refresh')
        if (stopped() || current !== sequence) return
        jobState.value = status.quantities?.job?.state ?? ''
        if (!['queued', 'running', 'failed'].includes(jobState.value)) await enqueue('automatic')
        if (jobState.value !== 'failed') timer = setTimeout(load, 1200)
      }
    } catch (cause) {
      if (!stopped() && current === sequence) error.value = cause instanceof Error ? cause.message : 'report_unavailable'
    }
  }
  async function enqueue(trigger: 'manual' | 'automatic' = 'manual') {
    busy.value = true
    try {
      await request('/refresh', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ kind: 'quantities', trigger }) })
      if (trigger === 'manual' && !stopped()) { jobState.value = 'queued'; clearTimeout(timer); timer = setTimeout(load, 1000) }
    } catch { if (!stopped()) error.value = 'report_unavailable' }
    finally { if (!stopped()) busy.value = false }
  }
  function move(value: number) { page.value = value; writePage(); void load() }
  watch(() => props.view, () => { report.value = null; page.value = readPage(); void load() })
  watch(() => JSON.stringify([props.query.account, props.query.account_regex, props.query.account_case, props.query.account_word, props.query.stash, props.query.item, props.query.item_regex, props.query.item_case, props.query.item_word, props.query.from, props.query.to]), () => { page.value = 1; writePage(true); void load() })
  watch(() => [props.revision, props.settingsHash, props.refreshToken, displayTimezone.value], () => { void load() })
  // Only actual page changes trigger a fetch; language-only navigation does not.
  watch(() => new URL(currentUrl.value).searchParams.get('analysis_page'), () => { const value = readPage(); if (value !== page.value) { page.value = value; void load() } })
  onMounted(() => { void load() })
  onUnmounted(() => { ++sequence; clearTimeout(timer) })
  return { report, error, jobState, busy, move, enqueue, reload: load }
}
