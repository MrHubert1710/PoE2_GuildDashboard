<script setup lang="ts">
import { authFetch } from '../auth'
import { displayTimezone, t, number, date } from '../i18n'
import { computed, onMounted, ref } from 'vue'
import type { Readiness } from '../readiness'
import type { DatabaseStatus } from '../database-status'

const state = ref<'loading' | 'ready' | 'error'>('loading')
const snapshot = ref<Readiness | null>(null)
const database = ref<DatabaseStatus | null>(null)
const databaseState = ref<'loading' | 'ready' | 'error'>('loading')
const total = computed(() => snapshot.value?.leagues.reduce((sum, league) => sum + league.transactions, 0) ?? 0)
const labels = { documented: 'documented', conditional: 'conditional', not_documented: 'notDocumented' }

async function loadReference() {
  if (state.value === 'loading' && snapshot.value) return
  state.value = 'loading'
  try {
    const response = await authFetch(`${import.meta.env.BASE_URL}api/rework-readiness`, {
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
    const response = await authFetch(`${import.meta.env.BASE_URL}api/database-status`, {
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
      <p class="eyebrow">{{ t('diagEyebrow') }}</p>
      <h1 id="page-title">{{ t('dataDiagnostics') }}<span>.</span></h1>
      <p class="intro">{{ t('diagIntro') }}</p>
      <div class="toolbar">
        <p role="status" aria-live="polite">
          <template v-if="state === 'loading'">{{ t('loadingReference') }}</template>
          <template v-else-if="state === 'ready'">{{ t('referenceCount', { count: total, leagues: snapshot?.leagues.length ?? 0 }) }}</template>
          <template v-else>{{ t('referenceFailed') }}</template>
        </p>
        <button type="button" :disabled="state === 'loading' || databaseState === 'loading'" @click="refreshView">{{ t('refreshDiagnostics') }} <span aria-hidden="true">↗</span></button>
      </div>
      <p v-if="state === 'error'" role="alert" class="alert">
        {{ snapshot ? t('lastSnapshot') : t('retry') }}
      </p>
    </section>

    <section aria-labelledby="database-title" class="database-section">
      <div class="section-heading"><h2 id="database-title">{{ t('database') }}</h2><span>{{ t('databasePhase') }}</span></div>
      <p v-if="databaseState === 'loading'" role="status">{{ t('loadingDatabase') }}</p>
      <p v-if="databaseState === 'error'" role="alert" class="alert" data-testid="database-error">
        {{ database ? t('databaseRefreshFailed') : t('databaseUnavailable') }}
      </p>
      <div v-if="database" data-testid="database-summary">
        <div class="card database-overview">
          <div class="card-heading"><h3>{{ t('sqliteCount', { count: database.transactions }) }}</h3><span class="badge" :class="database.integrity?.current ? 'good' : 'warning'">{{ database.integrity?.current ? t('integrityOK') : t('needsVerification') }}</span></div>
          <p class="small">{{ t('schemaMode', { schema: database.schema_version, mode: database.journal_mode.toUpperCase(), count: database.leagues.length }) }}</p>
          <p v-if="database.integrity" class="small">{{ t('lastVerification', { date: date(database.integrity.checked_at), zone: displayTimezone }) }}</p>
          <details v-if="database.last_import">
            <summary>{{ t('lastImport') }} · {{ database.last_import.status === 'completed' ? t('completed') : t('failed') }}</summary>
            <dl class="facts">
              <div><dt>{{ t('inserted') }}</dt><dd>{{ number(database.last_import.inserted_count) }}</dd></div>
              <div><dt>{{ t('duplicates') }}</dt><dd>{{ number(database.last_import.duplicate_count) }}</dd></div>
              <div><dt>{{ t('conflicts') }}</dt><dd>{{ number(database.last_import.invalid_count) }} / {{ number(database.last_import.conflict_count) }}</dd></div>
            </dl>
          </details>
        </div>
        <div class="league-grid database-leagues">
          <article v-for="league in database.leagues" :key="league.id" class="card" :data-database-league="league.name">
            <div class="card-heading"><h3>{{ league.name }}</h3><span class="badge" :class="league.baseline_match ? 'good' : 'warning'">{{ league.baseline_match === true ? t('baselineMatch') : league.baseline_match === false ? t('baselineMismatch') : t('noComparison') }}</span></div>
            <p class="count">{{ t('recordCount', { count: league.transactions }) }}</p>
            <dl class="facts">
              <div><dt>{{ t('firstTransaction') }}</dt><dd>{{ date(league.oldest_at) }}</dd></div>
              <div><dt>{{ t('lastTransaction') }}</dt><dd>{{ date(league.newest_at) }}</dd></div>
              <div><dt>{{ t('registeredFiles') }}</dt><dd>{{ number(Object.values(league.files).reduce((sum, count) => sum + count, 0)) }}</dd></div>
              <div><dt>{{ t('leagueCompleteness') }}</dt><dd>{{ t('unknownCompleteness', { status: league.history_complete === null ? t('unconfirmed') : league.history_complete ? t('full') : t('incomplete') }) }}</dd></div>
              <div><dt>{{ t('policy') }}</dt><dd>{{ t(league.monitored ? 'catalog.monitored' : 'catalog.notMonitored') }}</dd></div>
            </dl>
          </article>
        </div>
        <p class="footnote">{{ t('importNote') }}</p>
      </div>
    </section>

    <template v-if="snapshot">
      <section aria-labelledby="archives-title">
        <div class="section-heading"><h2 id="archives-title">{{ t('archives') }}</h2><span>{{ t('rangeZone',{zone:displayTimezone}) }}</span></div>
        <div class="league-grid">
          <article v-for="league in snapshot.leagues" :key="league.name" class="card" :data-league="league.name">
            <div class="card-heading"><h3>{{ league.name }}</h3><span class="badge" :class="league.source_matches ? 'good' : 'warning'">{{ league.source_matches ? t('copyMatch') : t('needsChecking') }}</span></div>
            <p class="count">{{ t('transactionCount', { count: league.transactions }) }}</p>
            <dl class="facts">
              <div><dt>{{ t('firstTransaction') }}</dt><dd>{{ date(league.oldest_at) }}</dd></div>
              <div><dt>{{ t('lastTransaction') }}</dt><dd>{{ date(league.newest_at) }}</dd></div>
              <div><dt>{{ t('priceFiles') }}</dt><dd>{{ number(league.prices.length) }} · {{ t('priceTimeUnknown') }}</dd></div>
            </dl>
            <p class="audit" :class="Object.keys(league.issues).length ? 'warning' : 'good'">
              {{ Object.keys(league.issues).length ? t('issuesDetected') : t('noIssues') }}
            </p>
            <ul v-if="Object.keys(league.issues).length"><li v-for="(count, issue) in league.issues" :key="issue">{{ t(`issue.${issue}`) }}: {{ number(count) }}</li></ul>
            <details>
              <summary>{{ t('evidence') }}</summary>
              <p class="small">{{ t('historyChecksum') }}</p><code>{{ league.history_sha256 }}</code>
              <p class="small">{{ t('cachedCategories') }}</p>
              <ul class="file-list"><li v-for="price in league.prices" :key="price.category_file">{{ price.category_file }} · {{ t('entries', { count: price.lines }) }}</li></ul>
            </details>
          </article>
        </div>
        <p class="footnote">{{ t('archiveNote') }}</p>
      </section>

      <section aria-labelledby="integrations-title" class="integrations">
        <div class="section-heading"><h2 id="integrations-title">{{ t('integrations') }}</h2><span>{{ t('docsChecked', { date: snapshot.providers.checked_at }) }}</span></div>
        <article v-for="provider in snapshot.providers.items" :key="provider.id" class="provider-row">
          <div><h3>{{ t(`provider.${provider.id}.name`) }}</h3><p>{{ t(`provider.${provider.id}.detail`) }}</p><a :href="provider.source" target="_blank" rel="noopener noreferrer">{{ t('sourceDocs') }}</a></div>
          <span class="badge" :class="provider.status === 'documented' ? 'good' : 'warning'">{{ t(labels[provider.status]) }}</span>
        </article>
      </section>
      <footer><span>{{ t('referenceAudit', { date: date(snapshot.generated_at), zone: displayTimezone }) }}</span><span>{{ t('dataDiagnostics') }}</span></footer>
    </template>
  </div>
</template>
