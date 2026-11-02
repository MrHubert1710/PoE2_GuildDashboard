import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { defaults, readQuery, writeQuery } from './browsing'
import type { HistoryQuery, League, TransactionPage } from './browsing'

const errorCodes = new Set(['revision_changed', 'league_not_found', 'invalid_date', 'invalid_date_range', 'database_unavailable', 'invalid_account_regex', 'invalid_item_regex', 'regex_timeout', 'invalid_regex_mode', 'invalid_search_mode'])
class HistoryError extends Error {}

export function useHistory() {
  const leagues = ref<League[]>([])
  const query = ref<HistoryQuery>(readQuery())
  const draft = reactive({ ...query.value })
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
      const params = new URLSearchParams()
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
      if (!query.value.league && leagues.value[0]) query.value.league = leagues.value[0].id
      if (!preserveDraft) Object.assign(draft, query.value)
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

  function change(next: HistoryQuery) {
    query.value = next
    Object.assign(draft, next)
    formError.value = ''
    writeQuery(next)
    void loadRows()
  }

  function selectLeague(id: string) { change({ ...defaults, league: id }) }
  function applyFilters() {
    if (draft.from && draft.to && draft.from > draft.to) {
      formError.value = 'invalid_date_range'
      return
    }
    change({ ...query.value, account: draft.account_regex ? draft.account : draft.account.trim(), stash: [...draft.stash].sort(), item: draft.item_regex ? draft.item : draft.item.trim(),
      account_regex: draft.account_regex, item_regex: draft.item_regex, account_case: draft.account_case, account_word: draft.account_word, item_case: draft.item_case, item_word: draft.item_word,
      from: draft.from, to: draft.to, page: 1 })
  }
  function clearFilters() { change({ ...defaults, league: query.value.league, page_size: query.value.page_size }) }
  function setPage(page: number) { change({ ...query.value, page }) }
  function setPageSize(page_size: number) { change({ ...query.value, page_size, page: 1 }) }
  function sortBy(sort: string) {
    change({ ...query.value, sort, direction: query.value.sort === sort && query.value.direction === 'asc' ? 'desc' : 'asc', page: 1 })
  }
  function popState() {
    const next = readQuery()
    if (JSON.stringify(next) === JSON.stringify(query.value)) return
    query.value = next
    Object.assign(draft, query.value)
    formError.value = ''
    void loadRows()
  }
  onMounted(() => { window.addEventListener('popstate', popState); void loadLeagues() })
  onUnmounted(() => {
    window.removeEventListener('popstate', popState)
    ++rowSequence; ++leagueSequence
    rowController?.abort(); leagueController?.abort()
  })

  return { leagues, query, draft, result, loadingLeagues, loadingRows, leagueError, rowError, formError,
    selected, loadLeagues, refreshRevision: () => loadLeagues(true), selectLeague, applyFilters, clearFilters, setPage, setPageSize, sortBy }
}
