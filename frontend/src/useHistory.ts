import { clientPreferences, initializeDisplayPreferences } from './client-settings'
import { displayTimezone } from './i18n'
import { dayBoundaryUtc, localDay } from './timezones'
import { updateUrl } from './navigation'
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { defaults, readQuery, writeQuery } from './browsing'
import type { HistoryQuery, League, TransactionPage } from './browsing'

const errorCodes = new Set(['revision_changed', 'league_not_found', 'invalid_date', 'invalid_date_range', 'database_unavailable', 'invalid_account_regex', 'invalid_item_regex', 'regex_timeout', 'invalid_regex_mode', 'invalid_search_mode'])
class HistoryError extends Error {}

export function useHistory() {
  const initialParams=new URLSearchParams(location.search)
  const explicitWorkspace=[...initialParams.keys()].some(key=>!['lang','tz','chart_mode','chart_pricing'].includes(key))
  let initialized=false
  const leagues = ref<League[]>([])
  const query = ref<HistoryQuery>(readQuery())
  function draftDates(){
    const day=(value:string,end=false)=>{const stamp=Date.parse(value);return Number.isFinite(stamp)?localDay(stamp-(end?1:0),displayTimezone.value):''}
    return {...query.value,stash:[...query.value.stash],from:day(query.value.from),to:day(query.value.to,true)}
  }
  const draft = reactive(draftDates())
  const result = ref<TransactionPage | null>(null)
  const loadingLeagues = ref(true)
  const loadingRows = ref(false)
  const leagueError = ref('')
  const rowError = ref('')
  const formError = ref('')
  const selected = computed(() => leagues.value.find(league => league.id === query.value.league))
  let rowSequence = 0
  let leagueSequence = 0
  let rowController: AbortController | null = null
  let leagueController: AbortController | null = null
  const api = import.meta.env.BASE_URL + 'api/'

  async function loadRows() {
    const sequence = ++rowSequence
    rowController?.abort()
    result.value = null
    rowError.value = ''
    if (!selected.value) { loadingRows.value = false; return }
    const league = selected.value
    const requested = { ...query.value }
    const controller = new AbortController()
    rowController = controller
    loadingRows.value = true
    const timer = setTimeout(() => controller.abort(), 10_000)
    try {
      const params = new URLSearchParams({timezone:displayTimezone.value})
      for (const [key, value] of Object.entries(requested)) {
        if (key === 'stash') {
          for (const stash of requested.stash) params.append('stash', stash)
          continue
        }
        if (typeof value === 'boolean') { if (value) params.set(key, '1'); continue }
        if (key !== 'league' && String(value)) params.set(key, String(value))
      }
      params.set('revision', league.revision)
      const response = await fetch(`${api}leagues/${encodeURIComponent(league.id)}/transactions?${params}`, {
        signal: controller.signal, cache: 'no-store',
      })
      const payload = await response.json()
      if (sequence !== rowSequence) return
      if (!response.ok) throw new HistoryError(errorCodes.has(payload.error) ? payload.error : 'transactions_failed')
      const page: TransactionPage = payload
      if (page.league_id !== league.id || page.revision !== league.revision || !Array.isArray(page.rows)) {
        throw new HistoryError('incompatible_revision')
      }
      result.value = page
      if (page.page !== query.value.page) {
        query.value = { ...query.value, page: page.page }
        writeQuery(query.value, true)
      }
    } catch (error) {
      if (sequence === rowSequence) {
        rowError.value = error instanceof HistoryError ? error.message : controller.signal.aborted ? 'transactions_timeout' : 'transactions_failed'
      }
    } finally {
      clearTimeout(timer)
      if (sequence === rowSequence) loadingRows.value = false
    }
  }

  async function loadLeagues(preserveDraft = false) {
    const sequence = ++leagueSequence
    leagueController?.abort()
    const controller = new AbortController()
    leagueController = controller
    ++rowSequence
    rowController?.abort()
    result.value = null
    loadingRows.value = false
    loadingLeagues.value = true
    leagueError.value = ''
    const timer = setTimeout(() => controller.abort(), 10_000)
    try {
      const response = await fetch(api + 'leagues', { signal: controller.signal, cache: 'no-store' })
      if (!response.ok) throw new HistoryError('leagues_failed')
      const payload = await response.json()
      if (sequence !== leagueSequence) return
      if (!Array.isArray(payload.leagues)) throw new HistoryError('invalid_leagues')
      leagues.value = payload.leagues
      if (!query.value.league && leagues.value[0]) query.value.league=leagues.value[0].id
      if(!initialized){
        initialized=true
        if(!explicitWorkspace){
          const url=new URL(location.href);url.searchParams.set('section',clientPreferences.value.defaultView);updateUrl(url,true)
        }
      }
      if(selected.value){
        initializeDisplayPreferences(selected.value.timezone??'UTC',selected.value.hour_format??'auto')
      }
      if (!preserveDraft) Object.assign(draft, draftDates())
      // Retire selections hidden by new settings, including saved URLs and unsaved drafts.
      if (selected.value) {
        const visible = new Set(selected.value.stashes)
        const keep = query.value.stash.filter(name => visible.has(name))
        if (keep.length !== query.value.stash.length) query.value = { ...query.value, stash: keep, page: 1 }
        draft.stash = draft.stash.filter(name => visible.has(name))
      }
      writeQuery(query.value, true)
      loadingLeagues.value = false
      await loadRows()
    } catch (error) {
      if (sequence === leagueSequence) leagueError.value = error instanceof HistoryError ? error.message : controller.signal.aborted ? 'leagues_timeout' : 'leagues_failed'
    } finally {
      clearTimeout(timer)
      if (sequence === leagueSequence) loadingLeagues.value = false
    }
  }

  function visibleQuery(next: HistoryQuery) {
    const league = leagues.value.find(value => value.id === next.league)
    if (!league) return next
    return { ...next, stash: next.stash.filter(name => league.stashes.includes(name)) }
  }
  function change(next: HistoryQuery, resetRange = false, replace = false) {
    query.value = visibleQuery(next)
    Object.assign(draft, draftDates())
    formError.value = ''
    writeQuery(query.value, replace, resetRange)
    void loadRows()
  }

  function selectLeague(id: string) {change({...defaults,league:id},true)}
  function applyFilters() {
    if (draft.from && draft.to && draft.from > draft.to) {
      formError.value = 'invalid_date_range'
      return
    }
    const displayed=draftDates(),changedDates=draft.from!==displayed.from||draft.to!==displayed.to
    change({ ...query.value, account: draft.account_regex ? draft.account : draft.account.trim(), stash: [...draft.stash].sort(), item: draft.item_regex ? draft.item : draft.item.trim(),
      account_regex: draft.account_regex, item_regex: draft.item_regex, account_case: draft.account_case, account_word: draft.account_word, item_case: draft.item_case, item_word: draft.item_word,
      from: draft.from===displayed.from?query.value.from:draft.from?dayBoundaryUtc(draft.from,displayTimezone.value):'', to: draft.to===displayed.to?query.value.to:draft.to?dayBoundaryUtc(draft.to,displayTimezone.value,true):'', page: 1 }, changedDates)
  }
  function clearFilters() { change({ ...defaults, league: query.value.league, page_size: query.value.page_size }, true) }
  function setDateRange(from: string, to: string) { if (from === query.value.from && to === query.value.to) return; change({ ...query.value, from, to, page: 1 }, false, true) }
  function setPage(page: number) { change({ ...query.value, page }) }
  function setPageSize(page_size: number) { change({ ...query.value, page_size, page: 1 }) }
  function sortBy(sort: string) {
    change({ ...query.value, sort, direction: query.value.sort === sort && query.value.direction === 'asc' ? 'desc' : 'asc', page: 1 })
  }
  function popState() {
    const next = readQuery()
    if (JSON.stringify(next) === JSON.stringify(query.value)) return
    query.value = visibleQuery(next)
    writeQuery(query.value, true)
    Object.assign(draft, draftDates())
    formError.value = ''
    void loadRows()
  }
  watch(displayTimezone,()=>{const dates=draftDates();draft.from=dates.from;draft.to=dates.to;if(selected.value&&!loadingLeagues.value)void loadRows()})
  onMounted(() => { window.addEventListener('popstate', popState); void loadLeagues() })
  onUnmounted(() => {
    window.removeEventListener('popstate', popState)
    ++rowSequence; ++leagueSequence
    rowController?.abort(); leagueController?.abort()
  })

  return { leagues, query, draft, result, loadingLeagues, loadingRows, leagueError, rowError, formError,
    selected, loadLeagues, refreshRevision: () => loadLeagues(true), selectLeague, applyFilters, clearFilters, setPage, setPageSize, sortBy, setDateRange }
}
