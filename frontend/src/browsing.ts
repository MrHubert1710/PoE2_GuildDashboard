export interface HistoricalReport {
  id: number
  name: string
  sha256: string
  bytes: number
}

export interface League {
  id: string
  name: string
  game: string
  realm: string
  lifecycle: 'unknown' | 'active' | 'ended'
  archived: boolean
  history_complete: boolean | null
  transactions: number
  oldest_at: string | null
  newest_at: string | null
  revision: string
  stashes: string[]
  reports: HistoricalReport[]
}

export interface HistoryQuery {
  league: string
  account: string
  stash: string
  item: string
  from: string
  to: string
  page: number
  page_size: number
  sort: string
  direction: string
}

export interface TransactionPage {
  league_id: string
  revision: string
  page: number
  page_size: number
  total: number
  pages: number
  sort: string
  direction: string
  rows: Array<{
    id: number
    external_id: string
    occurred_at: string
    account: string
    action: string
    stash: string
    item: string
    x: number
    y: number
  }>
}

export const defaults: HistoryQuery = {
  league: '', account: '', stash: '', item: '', from: '', to: '',
  page: 1, page_size: 50, sort: 'date', direction: 'desc',
}

export function readQuery(): HistoryQuery {
  const params = new URLSearchParams(location.search)
  const value = (name: string) => (params.get(name) ?? '').slice(0, 200)
  const page = Number(value('page'))
  const size = Number(value('page_size'))
  return {
    league: value('league'), account: value('account'), stash: value('stash'), item: value('item'),
    from: value('from'), to: value('to'),
    page: Number.isSafeInteger(page) && page >= 1 && page <= 1_000_000 ? page : 1,
    page_size: [25, 50, 100].includes(size) ? size : 50,
    sort: ['date', 'account', 'stash', 'item', 'action'].includes(value('sort')) ? value('sort') : 'date',
    direction: value('direction') === 'asc' ? 'asc' : 'desc',
  }
}

export function writeQuery(query: HistoryQuery, replace = false) {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (String(value) && String(value) !== String(defaults[key as keyof HistoryQuery])) params.set(key, String(value))
  }
  const url = new URL(location.href)
  url.search = params.toString()
  if (url.href !== location.href) {
    history[replace ? 'replaceState' : 'pushState'](null, '', url)
  }
}
