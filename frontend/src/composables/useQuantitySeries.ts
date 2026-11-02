import { computed, onUnmounted, ref, watch } from 'vue'
import type { HistoryQuery } from '../browsing'
import { currentUrl, updateUrl } from '../navigation'
import { useApiRequest } from './useApiRequest'
export interface SeriesPoint { timestamp: number; end: number; added: number; removed: number; net: number; inferred: number }
export interface SeriesData {
  league_id: string; projection: { id: string | null; state: string }; timezone: string
  unresolved_events: number; item: string | null; items: string[]; points: SeriesPoint[]; bucket_seconds: number | null
  bounds: { start: number; end: number } | null; totals: { added: number; removed: number; net: number; inferred: number }
}
export function useQuantitySeries(props: { leagueId: string; revision: string; settingsHash?: string; projectionId: string | null; query: HistoryQuery; active: boolean; refreshToken: number }) {
  const data = ref<SeriesData | null>(null), error = ref(''), loading = ref(false)
  const selectedItem = computed(() => new URL(currentUrl.value).searchParams.get('chart_item') ?? '')
  const { request, stopped } = useApiRequest(`${import.meta.env.BASE_URL}api/leagues/${encodeURIComponent(props.leagueId)}`)
  let sequence = 0, controllerTimer: ReturnType<typeof setTimeout> | undefined
  function chooseItem(value: string) {
    const url = new URL(currentUrl.value)
    if (value) url.searchParams.set('chart_item', value); else url.searchParams.delete('chart_item')
    url.searchParams.delete('chart_from'); url.searchParams.delete('chart_to')
    updateUrl(url)
  }
  async function load() {
    const current = ++sequence
    if (!props.active || !props.projectionId) { data.value = null; loading.value = false; return }
    loading.value = true; error.value = ''
    // Never keep a chart from an earlier filter or projection while reading the next one.
    data.value = null
    const params = new URLSearchParams({ revision: props.revision, projection_id: props.projectionId, max_points: '240' })
    for (const key of ['account','account_regex','account_case','account_word','stash','item','item_regex','item_case','item_word','from','to'] as Array<keyof HistoryQuery>) {
      const value = props.query[key]
      if (key === 'stash') { for (const name of props.query.stash) params.append('stash', name) }
      else if (typeof value === 'boolean') { if (value) params.set(key, '1') }
      else if (value) params.set(key, String(value))
    }
    if (selectedItem.value) params.set('series_item', selectedItem.value)
    try {
      const result: SeriesData = await request('/quantity-series?' + params)
      if (stopped() || current !== sequence) return
      if (result.league_id !== props.leagueId || result.projection.id !== props.projectionId) throw Error('projection_changed')
      data.value = result
    } catch (cause) {
      if (!stopped() && current === sequence) error.value = cause instanceof Error ? cause.message : 'report_unavailable'
    } finally { if (!stopped() && current === sequence) loading.value = false }
  }
  watch(() => JSON.stringify([props.active,props.projectionId,props.revision,props.settingsHash,props.refreshToken,selectedItem.value,
    props.query.account,props.query.account_regex,props.query.account_case,props.query.account_word,props.query.stash,
    props.query.item,props.query.item_regex,props.query.item_case,props.query.item_word,props.query.from,props.query.to]), () => {
      clearTimeout(controllerTimer)
      // Collapse the report + filter updates in one browser frame.
      controllerTimer = setTimeout(() => { void load() }, 0)
    }, { immediate: true })
  onUnmounted(() => { ++sequence; clearTimeout(controllerTimer) })
  return { data, error, loading, selectedItem, chooseItem, reload: load }
}
