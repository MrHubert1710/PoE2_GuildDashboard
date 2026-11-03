import { clientPreferences, saveClientPreferences } from './client-settings'
import { appName } from './branding'
import { computed, ref, watchEffect } from 'vue'
import { formatZonedDate } from './timezones'
import { updateUrl } from './navigation'
import { formatMessage, formatNumber } from './message-format.mjs'
import type { Catalog } from '../scripts/locale-catalog.mjs'

// Vite discovers the files; its plugin validates the same catalog before serving/building.
const files = import.meta.glob<Catalog>('./locales/*.json', { eager: true, import: 'default' })
const catalogs = Object.fromEntries(Object.entries(files).map(([path, value]) => [path.split('/').at(-1)!.replace('.json', ''), value]))
export const languages = Object.entries(catalogs).map(([code, catalog]) => ({ code, nativeName: catalog.nativeName }))
function supported(code: string | null | undefined) { return code && Object.hasOwn(catalogs, code) ? code : undefined }
function resolveLanguage() { return supported(new URLSearchParams(location.search).get('lang')) ?? supported(clientPreferences.value.language) ?? 'en' }
export const locale = ref(resolveLanguage())
function synchronize(replace: boolean) {
  const url = new URL(location.href)
  url.searchParams.set('lang', locale.value)
  updateUrl(url, replace)
  saveClientPreferences({language:locale.value})
}
export function setLanguage(code: string) {
  if (!supported(code) || code === locale.value) return
  locale.value = code
  synchronize(false)
}
synchronize(true)
window.addEventListener('popstate', () => { locale.value = resolveLanguage(); synchronize(true) })
// Formatting only: retain the original numeric value for charts and calculations.
export function number(value: number, decimal = false) {
  return formatNumber(value, locale.value, { minimumFractionDigits: decimal || !Number.isInteger(value) ? 2 : 0, maximumFractionDigits: 2 })
}
export function t(key: string, parameters: Record<string, string | number> = {}) {
  return formatMessage(catalogs, locale.value, key, parameters)
}

export const displayTimezone = computed(()=>clientPreferences.value.timezone??'UTC')
export const displayHourFormat = computed(()=>clientPreferences.value.hourFormat??'auto')
export function compactNumber(value: number) {
  if (value < 1000) return number(value)
  const scale = value >= 1e9 ? 1e9 : value >= 1e6 ? 1e6 : 1e3
  return number(value/scale)+(scale===1e9?'B':scale===1e6?'M':'k')
}
export function date(value: string | null, timeZone = displayTimezone.value) {
  return value ? formatZonedDate(value, locale.value, timeZone, undefined, displayHourFormat.value) : t('noData')
}
watchEffect(() => {
  document.documentElement.lang = locale.value
  document.title = `${appName} — ${t('documentTitle')}`
})
