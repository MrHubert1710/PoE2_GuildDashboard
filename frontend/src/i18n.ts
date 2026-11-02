import { ref, watchEffect } from 'vue'
import { updateUrl } from './navigation'
import { formatMessage } from './message-format.mjs'
import type { Catalog } from '../scripts/locale-catalog.mjs'

// Vite discovers the files; its plugin validates the same catalog before serving/building.
const files = import.meta.glob<Catalog>('./locales/*.json', { eager: true, import: 'default' })
const catalogs = Object.fromEntries(Object.entries(files).map(([path, value]) => [path.split('/').at(-1)!.replace('.json', ''), value]))
export const languages = Object.entries(catalogs).map(([code, catalog]) => ({ code, nativeName: catalog.nativeName }))
const storageKey = 'poe2guild.language'
function saved() { try { return localStorage.getItem(storageKey) } catch { return null } }
function supported(code: string | null | undefined) { return code && Object.hasOwn(catalogs, code) ? code : undefined }
function browserLanguage() {
  for (const code of navigator.languages ?? [navigator.language]) {
    const match = supported(code) ?? supported(code.split('-')[0])
    if (match) return match
  }
}
function resolveLanguage() { return supported(new URLSearchParams(location.search).get('lang')) ?? supported(saved()) ?? browserLanguage() ?? 'en' }
export const locale = ref(resolveLanguage())
function synchronize(replace: boolean) {
  const url = new URL(location.href)
  url.searchParams.set('lang', locale.value)
  updateUrl(url, replace)
  try { localStorage.setItem(storageKey, locale.value) } catch { /* Private browsers can deny storage. URL still works. */ }
}
export function setLanguage(code: string) {
  if (!supported(code) || code === locale.value) return
  locale.value = code
  synchronize(false)
}
synchronize(true)
window.addEventListener('popstate', () => { locale.value = resolveLanguage(); synchronize(true) })
export function number(value: number) { return new Intl.NumberFormat(locale.value).format(value) }
export function t(key: string, parameters: Record<string, string | number> = {}) {
  return formatMessage(catalogs, locale.value, key, parameters)
}

export function date(value: string | null, timeZone = 'UTC') {
  return value ? new Intl.DateTimeFormat(locale.value, { dateStyle: 'medium', timeStyle: 'short', timeZone }).format(new Date(value)) : t('noData')
}
watchEffect(() => {
  document.documentElement.lang = locale.value
  document.title = `poe2guild — ${t('documentTitle')}`
})
