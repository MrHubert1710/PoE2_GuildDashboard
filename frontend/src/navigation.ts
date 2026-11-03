import { computed, ref } from 'vue'
import { isAdmin } from './auth'

export const workspaceSections = ['summary', 'players', 'stashes', 'state', 'history', 'settings', 'configuration'] as const
export type WorkspaceSection = typeof workspaceSections[number]
function normalizeUrl(url:URL){url.searchParams.delete('chart_pricing');return url}
const initialUrl=normalizeUrl(new URL(location.href))
if(initialUrl.href!==location.href)history.replaceState(null,'',initialUrl)
export const currentUrl = ref(location.href)
export function updateUrl(url: URL, replace = false) {
  normalizeUrl(url)
  if (url.href !== location.href) history[replace ? 'replaceState' : 'pushState'](null, '', url)
  currentUrl.value = location.href
}
window.addEventListener('popstate', () => { updateUrl(new URL(location.href),true) })
export const diagnosticsVisible = computed(() => new URL(currentUrl.value).searchParams.get('view') === 'diagnostics')
export const section = computed<WorkspaceSection>(() => {
  const params = new URL(currentUrl.value).searchParams
  const requested = params.get('section')
  if (requested === 'configuration' && !isAdmin.value) return 'settings'
  if (workspaceSections.includes(requested as WorkspaceSection)) return requested as WorkspaceSection
  const legacy = params.get('analysis')
  return ['players', 'stashes', 'state'].includes(legacy ?? '') ? legacy as WorkspaceSection : 'summary'
})
export function sectionUrl(target: WorkspaceSection) {
  const url = new URL(currentUrl.value)
  url.searchParams.delete('view')
  url.searchParams.set('section', target)
  if (['summary', 'players', 'stashes', 'state'].includes(target)) {
    if (target === 'summary') url.searchParams.delete('analysis'); else url.searchParams.set('analysis', target)
    if (section.value !== target) url.searchParams.delete('analysis_page')
  }
  return url
}
export function navigateSection(target: WorkspaceSection) { updateUrl(sectionUrl(target)) }
export function navigateDiagnostics(show: boolean) {
  const url = new URL(currentUrl.value)
  if (show) url.searchParams.set('view', 'diagnostics'); else url.searchParams.delete('view')
  updateUrl(url)
}
export function diagnosticsUrl() { const url = new URL(currentUrl.value); url.searchParams.set('view', 'diagnostics'); return url }
