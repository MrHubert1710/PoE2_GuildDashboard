import { normalizeFilterTimestamp } from './timezones'
import { updateUrl } from './navigation'
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
  quantity_settings_hash?: string
  hour_format?: 'auto' | '12' | '24'
  display_settings_hash?: string
  timezone?: string
  stashes: string[]
}

export interface HistoryQuery {
  league: string
  account: string
  account_regex: boolean
  item_regex: boolean
  account_case: boolean
  account_word: boolean
  item_case: boolean
  item_word: boolean
  stash: string[]
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
    quantity?: {
      item_name: string; before_item: string | null; quantity_before: number | null; quantity_after: number | null
      quantity_delta: number | null; effective_action: string; confidence: string; resolution_reason: string
      movements: Array<{ item_name: string; quantity_delta: number; confidence: string; entry_kind?: 'operation' | 'reconstruction' }>
    } | null
  }>
}

export const defaults: HistoryQuery = {
  league: '', account: '', account_regex: false, item_regex: false, account_case: false, account_word: false, item_case: false, item_word: false, stash: [], item: '', from: '', to: '',
  page: 1, page_size: 50, sort: 'date', direction: 'desc',
}

export function readQuery(params = new URLSearchParams(location.search)): HistoryQuery {
  const value = (name: string) => (params.get(name) ?? '').slice(0, 200)
  const page = Number(value('page'))
  const size = Number(value('page_size'))
  return {
    league: value('league'), account: value('account'), stash: [...new Set(params.getAll('stash').filter(Boolean).map(value => value.slice(0, 200)))].slice(0, 100).sort(), item: value('item'),
    account_case: value('account_case') === '1', account_word: value('account_word') === '1', item_case: value('item_case') === '1', item_word: value('item_word') === '1',
    account_regex: value('account_regex') === '1', item_regex: value('item_regex') === '1',
    from: normalizeFilterTimestamp(value('from')), to: normalizeFilterTimestamp(value('to'),true),
    page: Number.isSafeInteger(page) && page >= 1 && page <= 1_000_000 ? page : 1,
    page_size: [25, 50, 100].includes(size) ? size : 50,
    sort: ['date', 'account', 'stash', 'item', 'action'].includes(value('sort')) ? value('sort') : 'date',
    direction: value('direction') === 'asc' ? 'asc' : 'desc',
  }
}

export function writeQuery(query: HistoryQuery, replace = false, resetRange = false) {
  const params = new URLSearchParams()
  const language = new URLSearchParams(location.search).get('lang')
  if (language) params.set('lang', language)
  const previousLeague = new URLSearchParams(location.search).get('league')
  for (const key of ['analysis', 'analysis_page', 'valuation_page', 'unpriced_page', 'section', 'view', 'chart_item', 'chart_from', 'chart_to', 'chart_series', 'chart_base_from', 'chart_base_to', 'chart_ymin', 'chart_ymax', 'chart_mode', 'chart_quantity_item']) {
    if (resetRange && ['valuation_page','unpriced_page','chart_from','chart_to','chart_base_from','chart_base_to'].includes(key)) continue
    if (key.startsWith('chart_') && key !== 'chart_mode' && previousLeague && previousLeague !== query.league) continue
    const value = new URLSearchParams(location.search).get(key)
    if (value !== null) params.set(key, value)
  }
  for (const [key, value] of Object.entries(query)) {
    if (key === 'stash') {
      for (const stash of [...new Set(query.stash)].sort()) params.append('stash', stash)
      continue
    }
    if (typeof value === 'boolean') { if (value) params.set(key, '1'); continue }
    if (String(value) && String(value) !== String(defaults[key as keyof HistoryQuery])) params.set(key, String(value))
  }
  const url = new URL(location.href)
  url.search = params.toString()
  updateUrl(url, replace)
}
