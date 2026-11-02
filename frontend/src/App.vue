<script setup lang="ts">
import { ref, watch } from 'vue'
import { t, languages, locale, setLanguage } from './i18n'
import { section, sectionUrl, diagnosticsUrl, diagnosticsVisible, navigateSection, navigateDiagnostics } from './navigation'
import HistoryBrowser from './components/HistoryBrowser.vue'
import Diagnostics from './components/Diagnostics.vue'
const visitedDiagnostics = ref(diagnosticsVisible.value)
watch(diagnosticsVisible, value => { if (value) visitedDiagnostics.value = true })
</script>

<template>
  <main class="shell app-shell">
    <header class="app-header">
      <a class="brand" :href="sectionUrl('summary').toString()" @click.prevent="navigateSection('summary')"><span class="brand-mark" aria-hidden="true">P2</span> poe2guild</a>
      <nav class="app-nav" :aria-label="t('navigation')">
        <a :href="sectionUrl(section).toString()" :aria-current="!diagnosticsVisible ? 'page' : undefined" @click.prevent="navigateDiagnostics(false)">{{ t('workspace.home') }}</a>
        <a :href="diagnosticsUrl().toString()" :aria-current="diagnosticsVisible ? 'page' : undefined" @click.prevent="navigateDiagnostics(true)">{{ t('diagnostics') }}</a>
      </nav>
      <div id="header-league-picker" class="header-league-picker"></div>
      <label class="language-picker">{{ t('language') }}
        <select :aria-label="t('language')" :value="locale" @change="setLanguage(($event.target as HTMLSelectElement).value)">
          <option v-for="language in languages" :key="language.code" :value="language.code">{{ language.nativeName }}</option>
        </select>
      </label>
    </header>
    <div v-show="diagnosticsVisible" class="diagnostics-page">
      <div id="league-sync-diagnostics"></div>
      <Diagnostics v-if="visitedDiagnostics" />
    </div>
    <HistoryBrowser v-show="!diagnosticsVisible" :diagnostics="diagnosticsVisible" />
    <footer><span>{{ t('workspace.footer') }}</span><span>poe2guild</span></footer>
  </main>
</template>
