<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import type { Readiness } from '../readiness'
import type { DatabaseStatus } from '../database-status'

const state = ref<'loading' | 'ready' | 'error'>('loading')
const snapshot = ref<Readiness | null>(null)
const database = ref<DatabaseStatus | null>(null)
const databaseState = ref<'loading' | 'ready' | 'error'>('loading')
const total = computed(() => snapshot.value?.leagues.reduce((sum, league) => sum + league.transactions, 0) ?? 0)
const number = (value: number) => value.toLocaleString('pl-PL')
const date = (value: string | null) => value
  ? new Intl.DateTimeFormat('pl-PL', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC' }).format(new Date(value))
  : 'Brak poprawnej daty'
const labels = { documented: 'Udokumentowane', conditional: 'Warunkowe', not_documented: 'Brak publicznego kontraktu' }

async function loadReference() {
  if (state.value === 'loading' && snapshot.value) return
  state.value = 'loading'
  try {
    const response = await fetch(`${import.meta.env.BASE_URL}api/rework-readiness`, {
      cache: 'no-store', signal: AbortSignal.timeout(8000),
    })
    if (!response.ok) throw new Error('Reference unavailable')
    const result: Readiness = await response.json()
    if (result.schema_version !== 1 || result.phase !== 0 || !Array.isArray(result.leagues) || !result.providers?.items) {
      throw new Error('Unexpected reference')
    }
    snapshot.value = result
    state.value = 'ready'
  } catch {
    state.value = 'error'
  }
}

async function loadDatabase() {
  databaseState.value = 'loading'
  try {
    const response = await fetch(`${import.meta.env.BASE_URL}api/database-status`, {
      cache: 'no-store', signal: AbortSignal.timeout(8000),
    })
    if (!response.ok) throw new Error('Database unavailable')
    const result: DatabaseStatus = await response.json()
    if (result.state !== 'ready' || !Array.isArray(result.leagues)) throw new Error('Unexpected database status')
    database.value = result
    databaseState.value = 'ready'
  } catch {
    databaseState.value = 'error'
  }
}

async function refreshView() {
  await Promise.all([loadReference(), loadDatabase()])
}

onMounted(refreshView)
</script>

<template>
  <div class="diagnostics">
    <section class="page-intro" aria-labelledby="page-title">
      <p class="eyebrow">BAZA DANYCH I IMPORT</p>
      <h1 id="page-title">Diagnostyka<br>danych<span>.</span></h1>
      <p class="intro">Dane obu lig w niezależnej bazie SQLite. Poniżej wynik importu i porównanie z zachowanymi archiwami.</p>
      <div class="toolbar">
        <p role="status" aria-live="polite">
          <template v-if="state === 'loading'">Odczytywanie wyniku weryfikacji…</template>
          <template v-else-if="state === 'ready'">Liczba transakcji: {{ number(total) }} · Ligi: {{ snapshot?.leagues.length }}</template>
          <template v-else>Nie udało się odczytać wyniku weryfikacji.</template>
        </p>
        <button type="button" :disabled="state === 'loading' || databaseState === 'loading'" @click="refreshView">Odśwież podgląd <span aria-hidden="true">↗</span></button>
      </div>
      <p v-if="state === 'error'" role="alert" class="alert">
        {{ snapshot ? 'Pokazuję ostatni odczytany wynik.' : 'Sprawdź połączenie i spróbuj ponownie.' }}
      </p>
    </section>

    <section aria-labelledby="database-title" class="database-section">
      <div class="section-heading"><h2 id="database-title">Baza danych</h2><span>Faza 1 · tylko odczyt podglądu</span></div>
      <p v-if="databaseState === 'loading'" role="status">Odczytywanie stanu bazy…</p>
      <p v-if="databaseState === 'error'" role="alert" class="alert" data-testid="database-error">
        {{ database ? 'Nie udało się odświeżyć stanu bazy. Pokazuję ostatni odczytany wynik.' : 'Baza jest niedostępna lub wymaga przygotowania. Podgląd archiwów pozostaje niezależny.' }}
      </p>
      <div v-if="database" data-testid="database-summary">
        <div class="card database-overview">
          <div class="card-heading"><h3>{{ number(database.transactions) }} transakcji w SQLite</h3><span class="badge" :class="database.integrity?.current ? 'good' : 'warning'">{{ database.integrity?.current ? 'Integralność OK' : 'Wymaga weryfikacji' }}</span></div>
          <p class="small">Schemat {{ database.schema_version }} · tryb {{ database.journal_mode.toUpperCase() }} · {{ database.leagues.length }} ligi</p>
          <p v-if="database.integrity" class="small">Ostatnia weryfikacja bazy: {{ date(database.integrity.checked_at) }} UTC</p>
          <details v-if="database.last_import">
            <summary>Ostatni import · {{ database.last_import.status === 'completed' ? 'zakończony' : 'nieudany lub przerwany' }}</summary>
            <dl class="facts">
              <div><dt>Dodane rekordy</dt><dd>{{ number(database.last_import.inserted_count) }}</dd></div>
              <div><dt>Pominięte duplikaty</dt><dd>{{ number(database.last_import.duplicate_count) }}</dd></div>
              <div><dt>Błędne rekordy / konflikty ID</dt><dd>{{ database.last_import.invalid_count }} / {{ database.last_import.conflict_count }}</dd></div>
            </dl>
          </details>
        </div>
        <div class="league-grid database-leagues">
          <article v-for="league in database.leagues" :key="league.id" class="card" :data-database-league="league.name">
            <div class="card-heading"><h3>{{ league.name }}</h3><span class="badge" :class="league.baseline_match ? 'good' : 'warning'">{{ league.baseline_match === true ? 'Zgodna z audytem' : league.baseline_match === false ? 'Różni się od audytu' : 'Brak porównania' }}</span></div>
            <p class="count">{{ number(league.transactions) }} <span>rekordów w bazie</span></p>
            <dl class="facts">
              <div><dt>Pierwsza transakcja</dt><dd>{{ date(league.oldest_at) }}</dd></div>
              <div><dt>Ostatnia transakcja</dt><dd>{{ date(league.newest_at) }}</dd></div>
              <div><dt>Zarejestrowane pliki</dt><dd>{{ Object.values(league.files).reduce((sum, count) => sum + count, 0) }}</dd></div>
              <div><dt>Status ligi / kompletność historii</dt><dd>Nieustalony / {{ league.history_complete === null ? 'niepotwierdzona' : league.history_complete ? 'pełna' : 'niepełna' }}</dd></div>
              <div><dt>Lokalna polityka</dt><dd>{{ league.archived ? 'Archiwum · bez fetchowania' : 'Monitorowanie' }}</dd></div>
            </dl>
          </article>
        </div>
        <p class="footnote">Import zachowuje surowe rekordy, oddziela ligi i źródła. Zgodność dotyczy liczby rekordów, zakresu dat i SHA-256 źródłowego CSV. Nie potwierdza kompletności historii ligi.</p>
      </div>
    </section>

    <template v-if="snapshot">
      <section aria-labelledby="archives-title">
        <div class="section-heading"><h2 id="archives-title">Archiwa lig</h2><span>Zakres dat w UTC</span></div>
        <div class="league-grid">
          <article v-for="league in snapshot.leagues" :key="league.name" class="card" :data-league="league.name">
            <div class="card-heading"><h3>{{ league.name }}</h3><span class="badge" :class="league.source_matches ? 'good' : 'warning'">{{ league.source_matches ? 'Kopia zgodna' : 'Wymaga sprawdzenia' }}</span></div>
            <p class="count">{{ number(league.transactions) }} <span>transakcji</span></p>
            <dl class="facts">
              <div><dt>Pierwsza transakcja</dt><dd>{{ date(league.oldest_at) }}</dd></div>
              <div><dt>Ostatnia transakcja</dt><dd>{{ date(league.newest_at) }}</dd></div>
              <div><dt>Raporty HTML</dt><dd>{{ league.reports.length }}</dd></div>
              <div><dt>Pliki cen</dt><dd>{{ league.prices.length }} · czas cen niepotwierdzony</dd></div>
            </dl>
            <p class="audit" :class="Object.keys(league.issues).length ? 'warning' : 'good'">
              {{ Object.keys(league.issues).length ? 'Wykryto problemy w historii' : 'Brak błędów wykrytych w audycie historii' }}
            </p>
            <ul v-if="Object.keys(league.issues).length"><li v-for="(count, issue) in league.issues" :key="issue">{{ issue }}: {{ count }}</li></ul>
            <details>
              <summary>Sumy kontrolne i zachowane pliki</summary>
              <p class="small">SHA-256 historii</p><code>{{ league.history_sha256 }}</code>
              <p class="small">Raporty</p>
              <ul class="file-list"><li v-for="report in league.reports" :key="report.name">{{ report.name }}<code>{{ report.sha256 }}</code></li></ul>
              <p class="small">Kategorie w zachowanym cache</p>
              <ul class="file-list"><li v-for="price in league.prices" :key="price.category_file">{{ price.category_file }} · {{ price.lines }} pozycji</li></ul>
            </details>
          </article>
        </div>
        <p class="footnote">Zgodność oznacza identyczne pliki w kopii i starym projekcie w chwili audytu. Nie potwierdza kompletności historii ligi ani dokładności wyceny.</p>
      </section>

      <section aria-labelledby="integrations-title" class="integrations">
        <div class="section-heading"><h2 id="integrations-title">Możliwości integracji</h2><span>Dokumentacja sprawdzona: {{ snapshot.providers.checked_at }}</span></div>
        <article v-for="provider in snapshot.providers.items" :key="provider.id" class="provider-row">
          <div><h3>{{ provider.name }}</h3><p>{{ provider.detail }}</p><a :href="provider.source" target="_blank" rel="noopener noreferrer">Dokumentacja źródła ↗</a></div>
          <span class="badge" :class="provider.status === 'documented' ? 'good' : 'warning'">{{ labels[provider.status] }}</span>
        </article>
      </section>
      <footer><span>Audyt referencyjny: {{ date(snapshot.generated_at) }} UTC</span><span>Diagnostyka danych</span></footer>
    </template>
  </div>
</template>
