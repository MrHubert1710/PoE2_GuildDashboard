<script setup lang="ts">
import { isAdmin } from '../auth'
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { t, date, displayTimezone } from '../i18n'
import { section, currentUrl, navigateSection } from '../navigation'
import { useHistory } from '../useHistory'
import LeaguePicker from './LeaguePicker.vue'
import RefreshPanel from './RefreshPanel.vue'
import QuantityPanel from './QuantityPanel.vue'
import QuantityChart from './QuantityChart.vue'
import ClientSettings from './ClientSettings.vue'
import QuantitySettings from './QuantitySettings.vue'
import HistoryTable from './HistoryTable.vue'
import HistoryFilters from './HistoryFilters.vue'
import ArchiveReports from './ArchiveReports.vue'
import WorkspaceNavigation from './WorkspaceNavigation.vue'
defineProps<{ diagnostics: boolean }>()
const { leagues, query, draft, result, loadingLeagues, loadingRows, leagueError, rowError, formError,
  selected, loadLeagues, refreshRevision, selectLeague, applyFilters, clearFilters, setPage, setPageSize, sortBy, setDateRange } = useHistory()
const analysisView = computed(() => {
  const value = ['summary', 'players', 'stashes', 'state'].includes(section.value) ? section.value : new URL(currentUrl.value).searchParams.get('analysis')
  return ['summary', 'players', 'stashes', 'state'].includes(value ?? '') ? value! : 'summary'
})
const contentScroll=ref<HTMLElement|null>(null)
watch(section,()=>{void nextTick(()=>contentScroll.value?.scrollTo(0,0))})
const mounted = ref(false)
onMounted(() => { mounted.value = true })
const refreshToken = ref(0)
const updateState = ref('')
const projectionId = ref<string | null>(null)
watch([() => selected.value?.id,() => selected.value?.quantity_settings_hash], () => { projectionId.value = null })
watch(() => selected.value?.id, () => { updateState.value = '' })
function updateProgress(state: 'pending' | 'failed' | 'ready') {
  if (state !== 'ready' || updateState.value) updateState.value = state
}
async function settingsSaved() {
  updateState.value = 'pending'
  await refreshRevision()
  refreshToken.value++
}
async function refreshView() { await loadLeagues(true); refreshToken.value++ }
const dataSection = computed(() => !['settings', 'configuration', 'archives'].includes(section.value))
</script>

<template>
  <section class="history-browser" :aria-label="t(`workspace.section.${section}`)">
    <Teleport v-if="leagues.length && !leagueError" to="#header-league-picker">
      <LeaguePicker :leagues="leagues" :selected-id="query.league" :disabled="loadingLeagues" @select="selectLeague" />
    </Teleport>
    <Teleport v-if="mounted" to="#header-actions"><button type="button" :disabled="loadingLeagues" @click="refreshView">{{ t('refreshHistory') }}</button></Teleport>
    <p v-if="leagueError" role="alert" class="alert">{{ t(leagueError) }}</p>
    <p v-if="loadingLeagues" role="status">{{ t('loadingLeagues') }}</p>
    <p v-if="!loadingLeagues && !leagueError && !leagues.length" class="empty-state">{{ t('noLeagues') }}</p>
    <div v-if="leagues.length && !leagueError && !selected && !loadingLeagues" class="empty-state" role="alert">
      <p>{{ t('unknownLeague') }}</p><button type="button" @click="selectLeague(leagues[0]!.id)">{{ t('firstLeague') }}</button>
    </div>
    <template v-if="selected && !leagueError">
      <Teleport to="#league-sync-diagnostics"><section v-if="isAdmin && diagnostics" class="league-context">
        <h2>{{ selected.name }}</h2><p>{{ t('historyCount', { count: selected.transactions }) }}</p>
        <p>{{ t('range') }} {{ date(selected.oldest_at, displayTimezone) }} — {{ date(selected.newest_at, displayTimezone) }} {{ displayTimezone }}</p>
        <p>{{ t('historyCompleteness', { status: selected.history_complete === null ? t('unconfirmed') : selected.history_complete ? t('confirmed') : t('incomplete') }) }}</p>
      </section></Teleport>
      <RefreshPanel :key="selected.id" :league-id="selected.id" :revision="selected.revision" :diagnostics="diagnostics" @revision-changed="refreshRevision" />
      <div class="workspace-layout">
        <WorkspaceNavigation />
        <div class="workspace-content">

          <HistoryFilters v-show="dataSection" :draft="draft" :stashes="selected.stashes" :form-error="formError" :timezone="displayTimezone" @apply="applyFilters" @clear="clearFilters" />
          <div ref="contentScroll" class="workspace-scroll">
          <p v-if="updateState" class="projection-status" :role="updateState === 'failed' ? 'alert' : 'status'" aria-live="polite" data-testid="projection-status">{{ t(`quantity.update.${updateState}`) }} <button v-if="updateState === 'failed'" type="button" @click="navigateSection('summary')">{{ t('workspace.section.summary') }}</button></p>
          <QuantityPanel v-show="['summary', 'players', 'stashes', 'state'].includes(section)" :key="'report-' + selected.id" :league-id="selected.id" :revision="selected.revision" :settings-hash="selected.quantity_settings_hash" :query="query" :view="analysisView" :refresh-token="refreshToken" @projection="projectionId = $event" @generated="refreshRevision" @progress="updateProgress" @problem="updateState === 'pending' && (updateState = 'failed')">
            <QuantityChart v-show="['summary','players','stashes'].includes(section)" :key="'chart-' + selected.id" :league-id="selected.id" :revision="selected.revision" :settings-hash="selected.quantity_settings_hash" :projection-id="projectionId" :view="analysisView" :query="query" :active="!diagnostics && ['summary','players','stashes'].includes(section)" :refresh-token="refreshToken" @range="setDateRange" />
          </QuantityPanel>
          <HistoryTable v-show="section === 'history'" :query="query" :result="result" :loading-rows="loadingRows" :row-error="rowError" :timezone="displayTimezone" @set-page="setPage" @set-page-size="setPageSize" @sort-by="sortBy" />
          <ClientSettings v-show="section === 'settings'" />
          <QuantitySettings v-if="isAdmin" v-show="section === 'configuration'" :key="'settings-' + selected.id" :league-id="selected.id" :settings-hash="selected.quantity_settings_hash" :refresh-token="refreshToken" :display-hash="selected.display_settings_hash" @saved="settingsSaved" />
          <ArchiveReports v-show="section === 'archives'" :selected="selected" />
          </div>
        </div>
      </div>
    </template>
  </section>
</template>
