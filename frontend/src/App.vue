<script setup lang="ts">
import { isAdmin } from './auth'
import AdminAccess from './components/AdminAccess.vue'
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { appName, appMotto } from './branding'
import scalesIcon from './assets/scales.svg'
import { t, languages, locale, setLanguage, displayTimezone } from './i18n'
import { section, sectionUrl, diagnosticsUrl, diagnosticsVisible, navigateSection, navigateDiagnostics } from './navigation'
import HistoryBrowser from './components/HistoryBrowser.vue'
import Diagnostics from './components/Diagnostics.vue'
const header=ref<HTMLElement|null>(null)
let headerObserver:ResizeObserver|undefined
onMounted(()=>{headerObserver=new ResizeObserver(()=>{if(header.value)document.documentElement.style.setProperty('--app-header-height',Math.ceil(header.value.getBoundingClientRect().height)+'px')});if(header.value)headerObserver.observe(header.value)})
onUnmounted(()=>headerObserver?.disconnect())
const visitedDiagnostics = ref(false)
watch([diagnosticsVisible, isAdmin], ([visible, admin]) => {
  if (visible && admin) visitedDiagnostics.value = true
  if (!admin) { visitedDiagnostics.value = false; if (visible) navigateDiagnostics(false) }
})
</script>

<template>
  <main class="shell app-shell">
    <header ref="header" class="app-header">
      <a class="brand" :href="sectionUrl('summary').toString()" @click.prevent="navigateSection('summary')"><img class="brand-mark" :src="scalesIcon" alt="" width="36" height="36" /><span class="brand-copy"><span class="brand-title">{{ appName }}</span><span class="brand-motto" lang="en">{{ appMotto }}</span></span></a>
      <nav v-if="isAdmin" class="app-nav" :aria-label="t('navigation')">
        <a :href="sectionUrl(section).toString()" :aria-current="!diagnosticsVisible ? 'page' : undefined" @click.prevent="navigateDiagnostics(false)">{{ t('workspace.home') }}</a>
        <a :href="diagnosticsUrl().toString()" :aria-current="diagnosticsVisible ? 'page' : undefined" @click.prevent="navigateDiagnostics(true)">{{ t('diagnostics') }}</a>
      </nav>
      <div id="header-league-picker" class="header-league-picker"></div>
      <div id="header-actions" class="header-actions"></div>
      <label class="language-picker">{{ t('language') }}
        <select :aria-label="t('language')" :value="locale" @change="setLanguage(($event.target as HTMLSelectElement).value)">
          <option v-for="language in languages" :key="language.code" :value="language.code">{{ language.nativeName }}</option>
        </select>
      </label>
      <AdminAccess />
    </header>
    <div v-show="isAdmin && diagnosticsVisible" class="diagnostics-page">
      <div id="league-sync-diagnostics"></div>
      <Diagnostics v-if="isAdmin && visitedDiagnostics" />
    </div>
    <HistoryBrowser v-show="!isAdmin || !diagnosticsVisible" :diagnostics="isAdmin && diagnosticsVisible" />
    <footer><span>{{ appName }} · {{ t('workspace.footer') }}</span><span>{{ displayTimezone }}</span></footer>
  </main>
</template>
