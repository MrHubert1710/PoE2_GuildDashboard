import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { defaults, readQuery, writeQuery } from './browsing'
import type { HistoryQuery, League, TransactionPage } from './browsing'

const messages: Record<string, string> = {
  revision_changed: 'Dane ligi zmieniły się. Odśwież widok, aby odczytać ich aktualną wersję.',
  league_not_found: 'Wybrana liga nie jest dostępna.',
  invalid_date: 'Sprawdź daty w filtrach. Użyj poprawnej daty dziennej.',
  invalid_date_range: 'Początek zakresu nie może być późniejszy niż koniec.',
  database_unavailable: 'Baza danych jest chwilowo niedostępna.',
}

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
        if (key !== 'league' && String(value)) params.set(key, String(value))
      }
      params.set('revision', league.revision)
      const response = await fetch(`${api}leagues/${encodeURIComponent(league.id)}/transactions?${params}`, {
        signal: controller.signal, cache: 'no-store',
      })
      const payload = await response.json()
      if (sequence !== rowSequence) return
      if (!response.ok) throw new Error(messages[payload.error] ?? 'Nie udało się odczytać transakcji. Spróbuj ponownie.')
      const page: TransactionPage = payload
      if (page.league_id !== league.id || page.revision !== league.revision || !Array.isArray(page.rows)) {
        throw new Error('Otrzymano niezgodną wersję danych. Odśwież widok.')
      }
      result.value = page
      if (page.page !== query.value.page) {
        query.value = { ...query.value, page: page.page }
        writeQuery(query.value, true)
      }
    } catch (error) {
      if (sequence === rowSequence) {
        rowError.value = error instanceof Error && error.name !== 'AbortError'
          ? error.message : 'Odczyt trwał zbyt długo. Spróbuj ponownie.'
      }
    } finally {
      clearTimeout(timer)
      if (sequence === rowSequence) loadingRows.value = false
    }
  }

  async function loadLeagues() {
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
      if (!response.ok) throw new Error('Nie udało się odczytać listy lig. Spróbuj ponownie.')
      const payload = await response.json()
      if (sequence !== leagueSequence) return
      if (!Array.isArray(payload.leagues)) throw new Error('Otrzymano nieprawidłową listę lig.')
      leagues.value = payload.leagues
      if (!query.value.league && leagues.value[0]) query.value.league = leagues.value[0].id
      Object.assign(draft, query.value)
      writeQuery(query.value, true)
      loadingLeagues.value = false
      await loadRows()
    } catch (error) {
      if (sequence === leagueSequence) leagueError.value = error instanceof Error && error.name !== 'AbortError'
        ? error.message : 'Odczyt listy lig trwał zbyt długo. Spróbuj ponownie.'
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
      formError.value = messages.invalid_date_range!
      return
    }
    change({ ...query.value, account: draft.account.trim(), stash: draft.stash, item: draft.item.trim(),
      from: draft.from, to: draft.to, page: 1 })
  }
  function clearFilters() { change({ ...defaults, league: query.value.league, page_size: query.value.page_size }) }
  function setPage(page: number) { change({ ...query.value, page }) }
  function setPageSize(page_size: number) { change({ ...query.value, page_size, page: 1 }) }
  function sortBy(sort: string) {
    change({ ...query.value, sort, direction: query.value.sort === sort && query.value.direction === 'asc' ? 'desc' : 'asc', page: 1 })
  }
  function popState() {
    query.value = readQuery()
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
    selected, loadLeagues, selectLeague, applyFilters, clearFilters, setPage, setPageSize, sortBy }
}
