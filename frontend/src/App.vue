<script setup lang="ts">
import { onMounted, ref } from 'vue'

const state = ref<'loading' | 'ready' | 'error'>('loading')

async function checkConnection() {
  state.value = 'loading'
  try {
    const response = await fetch(`${import.meta.env.BASE_URL}api/health`, {
      cache: 'no-store',
      signal: AbortSignal.timeout(8000),
    })
    if (!response.ok) throw new Error('Backend unavailable')
    const result = await response.json()
    if (result.service !== 'poe2guild' || result.status !== 'ok') {
      throw new Error('Unexpected response')
    }
    state.value = 'ready'
  } catch {
    state.value = 'error'
  }
}

onMounted(checkConnection)
</script>

<template>
  <main class="shell">
    <header><span class="brand-mark" aria-hidden="true">P2</span> poe2guild</header>
    <section class="welcome" aria-labelledby="welcome-title">
      <p class="eyebrow">NOWY POCZĄTEK</p>
      <h1 id="welcome-title">Hello World<span>.</span></h1>
      <p class="intro">Nowy szkielet Poe2Loggera jest gotowy do dalszej pracy.</p>
      <div class="connection" role="status" aria-live="polite">
        <span class="dot" :class="state" aria-hidden="true"></span>
        <span v-if="state === 'ready'">Połączenie z backendem działa</span>
        <span v-else-if="state === 'loading'">Sprawdzanie połączenia…</span>
        <span v-else>Nie udało się połączyć z backendem</span>
      </div>
      <button type="button" :disabled="state === 'loading'" @click="checkConnection">
        Sprawdź ponownie <span aria-hidden="true">↗</span>
      </button>
    </section>
    <footer>Vue · TypeScript · Vite <span>Flask API</span></footer>
  </main>
</template>
