<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { t, number, date } from '../i18n'
import { section, currentUrl, navigateDiagnostics, navigateSection } from '../navigation'
import { useHistory } from '../useHistory'
import LeaguePicker from './LeaguePicker.vue'
import RefreshPanel from './RefreshPanel.vue'
import QuantityPanel from './QuantityPanel.vue'
import QuantitySettings from './QuantitySettings.vue'
import HistoryTable from './HistoryTable.vue'
import HistoryFilters from './HistoryFilters.vue'
import ArchiveReports from './ArchiveReports.vue'
import WorkspaceNavigation from './WorkspaceNavigation.vue'
defineProps<{ diagnostics: boolean }>()
const { leagues, query, draft, result, loadingLeagues, loadingRows, leagueError, rowError, formError,
  selected, loadLeagues, refreshRevision, selectLeague, applyFilters, clearFilters, setPage, setPageSize, sortBy } = useHistory()
const analysisView = computed(() => {
  const value = ['summary', 'players', 'stashes', 'state'].includes(section.value) ? section.value : new URL(currentUrl.value).searchParams.get('analysis')
  return ['summary', 'players', 'stashes', 'state'].includes(value ?? '') ? value! : 'summary'
})
const refreshToken = ref(0)
const updateState = ref('')
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
const dataSection = computed(() => !['settings', 'archives'].includes(section.value))
</script>

<template>
  <section class="history-browser" aria-labelledby="workspace-title">
    <Teleport v-if="leagues.length && !leagueError" to="#header-league-picker">
      <LeaguePicker :leagues="leagues" :selected-id="query.league" :disabled="loadingLeagues" @select="selectLeague" />
    </Teleport>
    <div class="workspace-heading">
      <div><p class="eyebrow">{{ selected?.name ?? 'POE2 GUILD' }}</p><h1 id="workspace-title">{{ section === 'history' ? t('historyTitle') : t(`workspace.section.${section}`) }}<span>.</span></h1>
        <p v-if="selected" class="workspace-caption">{{ t('historyCount', { count: selected.transactions }) }}</p></div>
      <button type="button" :disabled="loadingLeagues" @click="refreshView">{{ t('refreshHistory') }} <span aria-hidden="true">↗</span></button>
    </div>
    <p v-if="leagueError" role="alert" class="alert">{{ t(leagueError) }}</p>
    <p v-if="loadingLeagues" role="status">{{ t('loadingLeagues') }}</p>
    <p v-if="!loadingLeagues && !leagueError && !leagues.length" class="empty-state">{{ t('noLeagues') }}</p>
    <div v-if="leagues.length && !leagueError && !selected && !loadingLeagues" class="empty-state" role="alert">
      <p>{{ t('unknownLeague') }}</p><button type="button" @click="selectLeague(leagues[0]!.id)">{{ t('firstLeague') }}</button>
    </div>
    <template v-if="selected && !leagueError">
      <Teleport to="#league-sync-diagnostics"><section v-show="diagnostics" class="league-context">
        <h2>{{ selected.name }}</h2><p>{{ t('historyCount', { count: selected.transactions }) }}</p>
        <p>{{ t('range') }} {{ date(selected.oldest_at, selected.timezone ?? 'UTC') }} — {{ date(selected.newest_at, selected.timezone ?? 'UTC') }} {{ selected.timezone ?? 'UTC' }}</p>
        <p>{{ t('historyCompleteness', { status: selected.history_complete === null ? t('unconfirmed') : selected.history_complete ? t('confirmed') : t('incomplete') }) }}</p>
      </section></Teleport>
      <RefreshPanel :key="selected.id" :league-id="selected.id" :revision="selected.revision" :diagnostics="diagnostics" @revision-changed="refreshRevision" @inspect="navigateDiagnostics(true)" />
      <div class="workspace-layout">
        <WorkspaceNavigation />
        <div class="workspace-content">
          <p v-if="updateState" class="projection-status" :role="updateState === 'failed' ? 'alert' : 'status'" aria-live="polite" data-testid="projection-status">{{ t(`quantity.update.${updateState}`) }} <button v-if="updateState === 'failed'" type="button" @click="navigateSection('summary')">{{ t('workspace.section.summary') }}</button></p>
          <HistoryFilters v-show="dataSection" :draft="draft" :stashes="selected.stashes" :form-error="formError" @apply="applyFilters" @clear="clearFilters" />
          <QuantityPanel v-show="['summary', 'players', 'stashes', 'state'].includes(section)" :key="'report-' + selected.id" :league-id="selected.id" :revision="selected.revision" :settings-hash="selected.quantity_settings_hash" :query="query" :view="analysisView" :refresh-token="refreshToken" @generated="refreshRevision" @progress="updateProgress" @problem="updateState === 'pending' && (updateState = 'failed')" />
          <HistoryTable v-show="section === 'history'" :query="query" :result="result" :loading-rows="loadingRows" :row-error="rowError" :timezone="selected.timezone ?? 'UTC'" @set-page="setPage" @set-page-size="setPageSize" @sort-by="sortBy" />
          <QuantitySettings v-show="section === 'settings'" :key="'settings-' + selected.id" :league-id="selected.id" :settings-hash="selected.quantity_settings_hash" :refresh-token="refreshToken" @saved="settingsSaved" />
          <ArchiveReports v-show="section === 'archives'" :selected="selected" />
        </div>
      </div>
    </template>
  </section>
</template>
