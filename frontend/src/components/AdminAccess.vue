<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { t } from '../i18n'
import { role, username, isAdmin, loginAvailable, loadAuth, login, logout } from '../auth'
const dialog = ref<HTMLDialogElement|null>(null)
const name = ref('admin'), password = ref(''), busy = ref(false), error = ref('')
let timer: ReturnType<typeof setInterval>|undefined
onMounted(() => { void loadAuth(); timer = setInterval(loadAuth, 60000) })
onUnmounted(() => clearInterval(timer))
async function submit() {
  busy.value = true; error.value = ''
  try { if (isAdmin.value) await logout(); else await login(name.value, password.value); password.value = ''; dialog.value?.close() }
  catch (reason) { error.value = reason instanceof Error ? reason.message : 'auth_unavailable' }
  finally { password.value = ''; busy.value = false }
}
function open() { error.value = ''; password.value = ''; void loadAuth(); dialog.value?.showModal() }
</script>
<template>
  <button type="button" class="admin-status" data-testid="admin-status" :aria-label="t('auth.access')" @click="open">{{ role }}</button>
  <dialog ref="dialog" class="auth-dialog" @click="event => { if (event.target === dialog) dialog?.close() }" @close="password = ''">
    <form @submit.prevent="submit">
      <div class="section-heading"><h2>{{ t(isAdmin ? 'auth.administrator' : 'auth.login') }}</h2><button type="button" :aria-label="t('auth.close')" @click="dialog?.close()">×</button></div>
      <p v-if="isAdmin">{{ username }}</p>
      <template v-else>
        <p v-if="!loginAvailable" role="status">{{ t('auth.httpsRequired') }}</p>
        <label>{{ t('auth.username') }}<input v-model="name" autocomplete="username" required maxlength="100" :disabled="!loginAvailable || busy" /></label>
        <label>{{ t('auth.password') }}<input v-model="password" type="password" autocomplete="current-password" required maxlength="1024" :disabled="!loginAvailable || busy" /></label>
      </template>
      <p v-if="error" role="alert">{{ t('auth.errors.' + error) }}</p>
      <button type="submit" :disabled="busy || (!isAdmin && !loginAvailable)">{{ t(busy ? 'auth.pending' : isAdmin ? 'auth.logout' : 'auth.login') }}</button>
    </form>
  </dialog>
</template>
<style scoped>
.auth-dialog{background:var(--panel,#182128);color:inherit;border:1px solid #53616c;border-radius:8px;min-width:min(340px,85vw);max-width:90vw;padding:20px}.auth-dialog::backdrop{background:#0009}.auth-dialog label{display:grid;gap:5px;margin:14px 0}.auth-dialog input{width:100%;box-sizing:border-box}.auth-dialog h2{margin:0}.admin-status{border-color:#98bca4;font-weight:600}
</style>
