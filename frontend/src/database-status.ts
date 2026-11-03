export interface DatabaseStatus {
  state: 'ready'
  schema_version: number
  instance_id: string
  journal_mode: string
  transactions: number
  leagues: Array<{
    id: string
    name: string
    lifecycle: string
    monitored: boolean
    history_complete: boolean | null
    transactions: number
    oldest_at: string | null
    newest_at: string | null
    files: Record<string, number>
    baseline_match: boolean | null
  }>
  integrity: null | { result: string; checked_at: string; current: boolean; transaction_count: number }
  last_import: null | {
    id: string
    status: string
    finished_at: string
    inserted_count: number
    duplicate_count: number
    invalid_count: number
    conflict_count: number
  }
}
