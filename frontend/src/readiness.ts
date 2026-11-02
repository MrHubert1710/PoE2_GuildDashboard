export interface ArchiveReport {
  name: string
  sha256: string
  bytes: number
}

export interface ArchivePrice {
  category_file: string
  sha256: string
  lines: number
  timestamp_provenance: string
  league_provenance: string
}

export interface Readiness {
  schema_version: number
  phase: number
  generated_at: string
  leagues: Array<{
    name: string
    transactions: number
    oldest_at: string | null
    newest_at: string | null
    history_sha256: string
    source_matches: boolean
    issues: Record<string, number>
    reports: ArchiveReport[]
    prices: ArchivePrice[]
  }>
  providers: {
    checked_at: string
    items: Array<{
      id: string
      name: string
      status: 'documented' | 'conditional' | 'not_documented'
      detail: string
      source: string
    }>
  }
}
