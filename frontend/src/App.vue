<script setup lang="ts">
import { t, languages, locale, setLanguage } from './i18n'
import { onMounted, onUnmounted, ref } from 'vue'
import HistoryBrowser from './components/HistoryBrowser.vue'
import Diagnostics from './components/Diagnostics.vue'

const readView = () => new URLSearchParams(location.search).get('view') === 'diagnostics' ? 'diagnostics' : 'history'
const view = ref(readView())
function viewUrl(target: 'history' | 'diagnostics') {
  const url = new URL(location.href)
  if (target === 'diagnostics') url.searchParams.set('view', 'diagnostics')
  else url.searchParams.delete('view')
  url.searchParams.set('lang', locale.value)
  return url.pathname + url.search
}
function navigate(target: 'history' | 'diagnostics') {
  const url = new URL(location.href)
  if (target === 'diagnostics') url.searchParams.set('view', 'diagnostics')
  else url.searchParams.delete('view')
  if (url.href !== location.href) history.pushState(null, '', url)
  view.value = target
}
function popState() { view.value = readView() }
onMounted(() => window.addEventListener('popstate', popState))
onUnmounted(() => window.removeEventListener('popstate', popState))
</script>

<template>
  <main class="shell app-shell">
    <header>
      <a class="brand" :href="viewUrl('history')" @click.prevent="navigate('history')"><span class="brand-mark" aria-hidden="true">P2</span> poe2guild</a>
      <nav class="app-nav" :aria-label="t('navigation')">
        <a :href="viewUrl('history')" :aria-current="view === 'history' ? 'page' : undefined" @click.prevent="navigate('history')">{{ t('history') }}</a>
        <a :href="viewUrl('diagnostics')" :aria-current="view === 'diagnostics' ? 'page' : undefined" @click.prevent="navigate('diagnostics')">{{ t('diagnostics') }}</a>
      </nav>
      <div v-show="view === 'history'" id="header-league-picker" class="header-league-picker"></div>
      <label class="language-picker">{{ t('language') }}
        <select :aria-label="t('language')" :value="locale" @change="setLanguage(($event.target as HTMLSelectElement).value)">
          <option v-for="language in languages" :key="language.code" :value="language.code">{{ language.nativeName }}</option>
        </select>
      </label>
      <span class="phase-tag">{{ t('phase') }}</span>
    </header>
    <HistoryBrowser v-if="view === 'history'" />
    <Diagnostics v-else />
    <footer v-if="view === 'history'"><span>{{ t('footer') }}</span><span>{{ t('review') }}</span></footer>
  </main>
</template>
