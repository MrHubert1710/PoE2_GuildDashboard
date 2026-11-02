<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import HistoryBrowser from './components/HistoryBrowser.vue'
import Diagnostics from './components/Diagnostics.vue'

const readView = () => new URLSearchParams(location.search).get('view') === 'diagnostics' ? 'diagnostics' : 'history'
const view = ref(readView())
const base = import.meta.env.BASE_URL
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
      <a class="brand" :href="base"><span class="brand-mark" aria-hidden="true">P2</span> poe2guild</a>
      <nav class="app-nav" aria-label="Widoki aplikacji">
        <a href="?" :aria-current="view === 'history' ? 'page' : undefined" @click.prevent="navigate('history')">Historia</a>
        <a href="?view=diagnostics" :aria-current="view === 'diagnostics' ? 'page' : undefined" @click.prevent="navigate('diagnostics')">Diagnostyka</a>
      </nav>
      <span class="phase-tag">Faza 2</span>
    </header>
    <HistoryBrowser v-if="view === 'history'" />
    <Diagnostics v-else />
    <footer v-if="view === 'history'"><span>Historia gildii · lokalne dane · daty UTC</span><span>Faza 2 · do weryfikacji</span></footer>
  </main>
</template>
