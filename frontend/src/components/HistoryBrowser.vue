<script setup lang="ts">
import { t, number, date } from '../i18n'
import { useHistory } from '../useHistory'
import LeaguePicker from './LeaguePicker.vue'
import RefreshPanel from './RefreshPanel.vue'

const { leagues, query, draft, result, loadingLeagues, loadingRows, leagueError, rowError, formError,
  selected, loadLeagues, refreshRevision, selectLeague, applyFilters, clearFilters, setPage, setPageSize, sortBy } = useHistory()
const actionNames: Record<string, string> = { added: 'added', removed: 'removed', modified: 'modified' }
const columns = [
  { key: 'date', label: 'dateColumn' }, { key: 'account', label: 'player' },
  { key: 'action', label: 'action' }, { key: 'stash', label: 'stash' }, { key: 'item', label: 'item' },
]
const archiveUrl = (id: number) => `${import.meta.env.BASE_URL}archives/${id}`
</script>

<template>
  <section class="history-browser" aria-labelledby="history-title">
    <Teleport v-if="leagues.length && !leagueError" to="#header-league-picker">
      <LeaguePicker :leagues="leagues" :selected-id="query.league" :disabled="loadingLeagues" @select="selectLeague" />
    </Teleport>
    <div class="history-heading">
      <div><p class="eyebrow">POE2 GUILD</p><h1 id="history-title">{{ t('historyTitle') }}<span>.</span></h1><p class="intro">{{ t('historyIntro') }}</p></div>
      <button type="button" :disabled="loadingLeagues" @click="loadLeagues()">{{ t('refreshHistory') }} <span aria-hidden="true">↗</span></button>
    </div>

    <p v-if="leagueError" role="alert" class="alert">{{ t(leagueError) }}</p>
    <p v-if="loadingLeagues" role="status">{{ t('loadingLeagues') }}</p>
    <p v-if="!loadingLeagues && !leagueError && !leagues.length" class="empty-state">{{ t('noLeagues') }}</p>

    <template v-if="leagues.length && !leagueError">
      <div v-if="!selected && !loadingLeagues" class="empty-state" role="alert">
        <p>{{ t('unknownLeague') }}</p><button type="button" @click="selectLeague(leagues[0]!.id)">{{ t('firstLeague') }}</button>
      </div>

      <template v-if="selected">
        <RefreshPanel :key="selected.id" :league-id="selected.id" :revision="selected.revision" @revision-changed="refreshRevision" />
        <div class="league-summary">
          <p>{{ t('historyCount', { count: selected.transactions }) }}</p>
          <p>{{ t('range') }} <strong>{{ date(selected.oldest_at) }}</strong> — <strong>{{ date(selected.newest_at) }}</strong> UTC</p>
          <p>{{ t('historyCompleteness', { status: selected.history_complete === null ? t('unconfirmed') : selected.history_complete ? t('confirmed') : t('incomplete') }) }}</p>
        </div>

        <form class="filters" @submit.prevent="applyFilters">
          <label>{{ t('player') }}<input v-model="draft.account" name="account" type="search" maxlength="200" :placeholder="t('accountPlaceholder')" /></label>
          <label>{{ t('stash') }}<select v-model="draft.stash" name="stash" :aria-label="t('stash')"><option value="">{{ t('allStashes') }}</option><option v-for="stash in selected.stashes" :key="stash" :value="stash">{{ stash }}</option></select></label>
          <label>{{ t('item') }}<input v-model="draft.item" name="item" type="search" maxlength="200" :placeholder="t('itemPlaceholder')" /></label>
          <label>{{ t('fromDay') }}<input v-model="draft.from" name="from" type="date" /></label>
          <label>{{ t('toDay') }}<input v-model="draft.to" name="to" type="date" /></label>
          <div class="filter-actions"><button class="primary" type="submit">{{ t('applyFilters') }}</button><button type="button" @click="clearFilters">{{ t('clearFilters') }}</button></div>
        </form>
        <p v-if="formError" role="alert" class="alert">{{ t(formError) }}</p>

        <div class="results-heading">
          <h2>{{ t('transactions') }}</h2>
          <label>{{ t('pageSize') }}<select :aria-label="t('pageSize')" :value="query.page_size" @change="setPageSize(Number(($event.target as HTMLSelectElement).value))"><option :value="25">25</option><option :value="50">50</option><option :value="100">100</option></select></label>
        </div>
        <p v-if="loadingRows" role="status" class="loading-state">{{ t('loadingTransactions') }}</p>
        <p v-if="rowError" role="alert" class="alert">{{ t(rowError) }}</p>
        <div v-if="result" data-testid="transaction-results">
          <p class="result-count" role="status">{{ t('resultCount', { count: result.total, page: result.page, pages: result.pages }) }}</p>
          <p v-if="!result.rows.length" class="empty-state">{{ t('noTransactions') }}</p>
          <div v-else class="transactions-scroll" tabindex="0" role="region" :aria-label="t('tableRegion')">
            <table class="transactions">
              <thead><tr>
                <th v-for="column in columns" :key="column.key" scope="col" :aria-sort="query.sort === column.key ? (query.direction === 'asc' ? 'ascending' : 'descending') : 'none'">
                  <button type="button" @click="sortBy(column.key)">{{ t(column.label) }} <span v-if="query.sort === column.key" aria-hidden="true">{{ query.direction === 'asc' ? '↑' : '↓' }}</span></button>
                </th>
                <th scope="col">{{ t('position') }}</th>
              </tr></thead>
              <tbody><tr v-for="row in result.rows" :key="row.id" :data-event-id="row.external_id">
                <td class="date-cell">{{ date(row.occurred_at) }}</td><td>{{ row.account }}</td>
                <td><span class="action" :class="row.action">{{ actionNames[row.action] ? t(actionNames[row.action]!) : row.action }}</span></td>
                <td>{{ row.stash }}</td><td class="item-cell">{{ row.item }}</td><td>{{ row.x }}, {{ row.y }}</td>
              </tr></tbody>
            </table>
          </div>
          <nav class="pagination" :aria-label="t('pages')">
            <button type="button" :disabled="loadingRows || result.page <= 1" @click="setPage(result.page - 1)">{{ t('previous') }}</button>
            <span>{{ result.page }} / {{ number(result.pages) }}</span>
            <button type="button" :disabled="loadingRows || result.page >= result.pages" @click="setPage(result.page + 1)">{{ t('next') }}</button>
          </nav>
        </div>

        <section class="historical-reports" aria-labelledby="reports-title">
          <div class="section-heading"><h2 id="reports-title">{{ t('reportsTitle') }}</h2><span>{{ selected.name }}</span></div>
          <p v-if="!selected.reports.length" class="footnote">{{ t('noReports') }}</p>
          <div v-else class="report-links"><a v-for="report in selected.reports" :key="report.id" :href="archiveUrl(report.id)" target="_blank" rel="noopener noreferrer">{{ report.name.split('/').at(-1) }} <span>{{ report.sha256.slice(0, 8) }} · ↗</span></a></div>
          <p class="footnote">{{ t('reportsNote') }}</p>
        </section>
      </template>
    </template>
  </section>
</template>
