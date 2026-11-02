<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import type { Readiness } from './readiness'

const state = ref<'loading' | 'ready' | 'error'>('loading')
const snapshot = ref<Readiness | null>(null)
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

onMounted(loadReference)
</script>

<template>
  <main class="shell">
    <header>
      <a class="brand" :href="'.'"><span class="brand-mark" aria-hidden="true">P2</span> poe2guild</a>
      <span class="phase-tag">Rework · Faza 0</span>
    </header>
    <section class="page-intro" aria-labelledby="page-title">
      <p class="eyebrow">PUNKT ODNIESIENIA</p>
      <h1 id="page-title">Dane gotowe<br>do portowania<span>.</span></h1>
      <p class="intro">Weryfikacja archiwów i możliwości integracji przed budową nowej bazy danych.</p>
      <div class="toolbar">
        <p role="status" aria-live="polite">
          <template v-if="state === 'loading'">Odczytywanie wyniku weryfikacji…</template>
          <template v-else-if="state === 'ready'">Liczba transakcji: {{ number(total) }} · Ligi: {{ snapshot?.leagues.length }}</template>
          <template v-else>Nie udało się odczytać wyniku weryfikacji.</template>
        </p>
        <button type="button" :disabled="state === 'loading'" @click="loadReference">Odśwież podgląd <span aria-hidden="true">↗</span></button>
      </div>
      <p v-if="state === 'error'" role="alert" class="alert">
        {{ snapshot ? 'Pokazuję ostatni odczytany wynik.' : 'Sprawdź połączenie i spróbuj ponownie.' }}
      </p>
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
      <footer><span>Audyt wygenerowany: {{ date(snapshot.generated_at) }} UTC</span><span>Faza 0 · do weryfikacji manualnej</span></footer>
    </template>
  </main>
</template>
