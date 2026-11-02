import type { Catalog } from '../scripts/locale-catalog.mjs'
export function formatMessage(catalogs: Record<string, Catalog>, locale: string, key: string, parameters?: Record<string, string | number>): string
