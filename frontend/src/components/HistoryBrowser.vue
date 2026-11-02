<script setup lang="ts">
import { useHistory } from '../useHistory'
import LeaguePicker from './LeaguePicker.vue'

const { leagues, query, draft, result, loadingLeagues, loadingRows, leagueError, rowError, formError,
  selected, loadLeagues, selectLeague, applyFilters, clearFilters, setPage, setPageSize, sortBy } = useHistory()
const number = (value: number) => value.toLocaleString('pl-PL')
const date = (value: string | null) => value ? new Intl.DateTimeFormat('pl-PL', {
  dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC',
}).format(new Date(value)) : 'Brak danych'
const actionNames: Record<string, string> = { added: 'Dodano', removed: 'Usunięto', modified: 'Zmieniono' }
const columns = [
  { key: 'date', label: 'Data (UTC)' }, { key: 'account', label: 'Gracz' },
  { key: 'action', label: 'Akcja' }, { key: 'stash', label: 'Skrytka' }, { key: 'item', label: 'Przedmiot' },
]
const archiveUrl = (id: number) => `${import.meta.env.BASE_URL}archives/${id}`
</script>

<template>
  <section class="history-browser" aria-labelledby="history-title">
    <div v-if="leagues.length && !leagueError" class="history-options">
      <LeaguePicker :leagues="leagues" :selected-id="query.league" :disabled="loadingLeagues" @select="selectLeague" />
    </div>
    <div class="history-heading">
      <div><p class="eyebrow">POE2 GUILD</p><h1 id="history-title">Historia skrytki<span>.</span></h1><p class="intro">Przeglądaj transakcje gildii z zachowanych danych.</p></div>
      <button type="button" :disabled="loadingLeagues" @click="loadLeagues">Odśwież widok <span aria-hidden="true">↗</span></button>
    </div>

    <p v-if="leagueError" role="alert" class="alert">{{ leagueError }}</p>
    <p v-if="loadingLeagues" role="status">Odczytywanie listy lig…</p>
    <p v-if="!loadingLeagues && !leagueError && !leagues.length" class="empty-state">Brak lig w bazie. Po imporcie historii pojawią się tutaj dane.</p>

    <template v-if="leagues.length && !leagueError">
      <div v-if="!selected && !loadingLeagues" class="empty-state" role="alert">
        <p>Liga wskazana w adresie nie jest dostępna.</p><button type="button" @click="selectLeague(leagues[0]!.id)">Wybierz pierwszą ligę</button>
      </div>

      <template v-if="selected">
        <div class="league-summary">
          <p>{{ number(selected.transactions) }} transakcji w lokalnej historii</p>
          <p>Zakres zachowanych danych: <strong>{{ date(selected.oldest_at) }}</strong> — <strong>{{ date(selected.newest_at) }}</strong> UTC</p>
          <p>Kompletność historii {{ selected.history_complete === null ? 'niepotwierdzona' : selected.history_complete ? 'potwierdzona' : 'niepełna' }}. Widok korzysta z lokalnej bazy.</p>
        </div>

        <form class="filters" @submit.prevent="applyFilters">
          <label>Gracz<input v-model="draft.account" name="account" type="search" maxlength="200" placeholder="Fragment nazwy konta" /></label>
          <label>Skrytka<select v-model="draft.stash" name="stash" aria-label="Skrytka"><option value="">Wszystkie skrytki</option><option v-for="stash in selected.stashes" :key="stash" :value="stash">{{ stash }}</option></select></label>
          <label>Przedmiot<input v-model="draft.item" name="item" type="search" maxlength="200" placeholder="Fragment nazwy przedmiotu" /></label>
          <label>Od dnia (UTC)<input v-model="draft.from" name="from" type="date" /></label>
          <label>Do dnia (UTC)<input v-model="draft.to" name="to" type="date" /></label>
          <div class="filter-actions"><button class="primary" type="submit">Zastosuj filtry</button><button type="button" @click="clearFilters">Wyczyść filtry</button></div>
        </form>
        <p v-if="formError" role="alert" class="alert">{{ formError }}</p>

        <div class="results-heading">
          <h2>Transakcje</h2>
          <label>Na stronie<select aria-label="Na stronie" :value="query.page_size" @change="setPageSize(Number(($event.target as HTMLSelectElement).value))"><option :value="25">25</option><option :value="50">50</option><option :value="100">100</option></select></label>
        </div>
        <p v-if="loadingRows" role="status" class="loading-state">Odczytywanie transakcji…</p>
        <p v-if="rowError" role="alert" class="alert">{{ rowError }}</p>
        <div v-if="result" data-testid="transaction-results">
          <p class="result-count" role="status">Wyniki: {{ number(result.total) }} · strona {{ result.page }} z {{ number(result.pages) }}</p>
          <p v-if="!result.rows.length" class="empty-state">Brak transakcji dla wybranych filtrów.</p>
          <div v-else class="transactions-scroll" tabindex="0" role="region" aria-label="Tabela transakcji — przewijanie poziome">
            <table class="transactions">
              <thead><tr>
                <th v-for="column in columns" :key="column.key" scope="col" :aria-sort="query.sort === column.key ? (query.direction === 'asc' ? 'ascending' : 'descending') : 'none'">
                  <button type="button" @click="sortBy(column.key)">{{ column.label }} <span v-if="query.sort === column.key" aria-hidden="true">{{ query.direction === 'asc' ? '↑' : '↓' }}</span></button>
                </th>
                <th scope="col">Pozycja</th>
              </tr></thead>
              <tbody><tr v-for="row in result.rows" :key="row.id" :data-event-id="row.external_id">
                <td class="date-cell">{{ date(row.occurred_at) }}</td><td>{{ row.account }}</td>
                <td><span class="action" :class="row.action">{{ actionNames[row.action] ?? row.action }}</span></td>
                <td>{{ row.stash }}</td><td class="item-cell">{{ row.item }}</td><td>{{ row.x }}, {{ row.y }}</td>
              </tr></tbody>
            </table>
          </div>
          <nav class="pagination" aria-label="Strony transakcji">
            <button type="button" :disabled="loadingRows || result.page <= 1" @click="setPage(result.page - 1)">← Poprzednia</button>
            <span>{{ result.page }} / {{ number(result.pages) }}</span>
            <button type="button" :disabled="loadingRows || result.page >= result.pages" @click="setPage(result.page + 1)">Następna →</button>
          </nav>
        </div>

        <section class="historical-reports" aria-labelledby="reports-title">
          <div class="section-heading"><h2 id="reports-title">Zachowane raporty</h2><span>{{ selected.name }}</span></div>
          <p v-if="!selected.reports.length" class="footnote">Brak zapisanego raportu HTML dla tej ligi.</p>
          <div v-else class="report-links"><a v-for="report in selected.reports" :key="report.id" :href="archiveUrl(report.id)" target="_blank" rel="noopener noreferrer">{{ report.name.split('/').at(-1) }} <span>{{ report.sha256.slice(0, 8) }} · ↗</span></a></div>
          <p class="footnote">Otwierają się w osobnej karcie i zachowują historyczną wycenę. Nie pobierają nowych danych.</p>
        </section>
      </template>
    </template>
  </section>
</template>
