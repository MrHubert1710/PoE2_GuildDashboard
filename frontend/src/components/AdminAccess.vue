<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { t } from '../i18n'
import { role, username, isAdmin, loginAvailable, defaultPassword, loadAuth, login, logout, changePassword } from '../auth'
const dialog = ref<HTMLDialogElement|null>(null)
const name = ref('admin'), password = ref(''), newPassword = ref(''), confirmation = ref('')
const changeMode = ref(false), busy = ref(false), error = ref(''), notice = ref('')
let timer: ReturnType<typeof setInterval>|undefined
let warned = false
onMounted(() => { void loadAuth(); timer = setInterval(loadAuth, 60000) })
onUnmounted(() => clearInterval(timer))
watch(defaultPassword, active => {
  if (active && !warned) { warned = true; changeMode.value = true; name.value = 'admin'; if (!dialog.value?.open) dialog.value?.showModal() }
})
function clearPasswords() { password.value = ''; newPassword.value = ''; confirmation.value = '' }
async function submit() {
  busy.value = true; error.value = ''; notice.value = ''
  try {
    if (changeMode.value) {
      if (newPassword.value !== confirmation.value) throw new Error('password_mismatch')
      if (!isAdmin.value || username.value !== 'admin') await login('admin', password.value)
      await changePassword(password.value, newPassword.value)
      changeMode.value = false; notice.value = 'auth.passwordChanged'
    } else if (isAdmin.value) { await logout(); dialog.value?.close() }
    else {
      await login(name.value, password.value)
      if (defaultPassword.value && username.value === 'admin') changeMode.value = true
      else dialog.value?.close()
    }
  } catch (reason) { error.value = reason instanceof Error ? reason.message : 'auth_unavailable' }
  finally { clearPasswords(); busy.value = false }
}
function open() { error.value = ''; notice.value = ''; changeMode.value = false; clearPasswords(); void loadAuth(); dialog.value?.showModal() }
</script>
<template>
  <button type="button" class="admin-status" data-testid="admin-status" :aria-label="t('auth.access')" @click="open">{{ role }}</button>
  <dialog ref="dialog" class="auth-dialog" @click="event => { if (event.target === dialog) dialog?.close() }" @close="clearPasswords">
    <form @submit.prevent="submit">
      <div class="section-heading"><h2>{{ t(changeMode ? 'auth.setPassword' : isAdmin ? 'auth.administrator' : 'auth.login') }}</h2><button type="button" :aria-label="t('auth.close')" @click="dialog?.close()">×</button></div>
      <p v-if="defaultPassword" class="default-password-notice" role="status">{{ t('auth.defaultPasswordWarning') }}</p>
      <p v-if="notice" role="status">{{ t(notice) }}</p>
      <template v-if="changeMode">
        <p>{{ t('auth.changeAccount') }}</p>
        <p v-if="!loginAvailable" role="status">{{ t('auth.httpsRequired') }}</p>
        <label>{{ t('auth.currentPassword') }}<input v-model="password" type="password" autocomplete="current-password" required maxlength="1024" :disabled="!loginAvailable || busy" /></label>
        <label>{{ t('auth.newPassword') }}<input v-model="newPassword" type="password" autocomplete="new-password" required minlength="12" maxlength="1024" :disabled="!loginAvailable || busy" /></label>
        <label>{{ t('auth.confirmPassword') }}<input v-model="confirmation" type="password" autocomplete="new-password" required minlength="12" maxlength="1024" :disabled="!loginAvailable || busy" /></label>
      </template>
      <p v-else-if="isAdmin">{{ username }}</p>
      <template v-else>
        <p v-if="!loginAvailable" role="status">{{ t('auth.httpsRequired') }}</p>
        <label>{{ t('auth.username') }}<input v-model="name" autocomplete="username" required maxlength="100" :disabled="!loginAvailable || busy" /></label>
        <label>{{ t('auth.password') }}<input v-model="password" type="password" autocomplete="current-password" required maxlength="1024" :disabled="!loginAvailable || busy" /></label>
      </template>
      <p v-if="error" role="alert">{{ t('auth.errors.' + error) }}</p>
      <div class="filter-actions">
        <button type="submit" :disabled="busy || (!isAdmin && !loginAvailable) || (changeMode && !loginAvailable)">{{ t(busy ? 'auth.pending' : changeMode ? 'auth.setPassword' : isAdmin ? 'auth.logout' : 'auth.login') }}</button>
        <button v-if="defaultPassword && !changeMode" type="button" @click="changeMode = true; clearPasswords()">{{ t('auth.setPassword') }}</button>
        <button v-if="changeMode" type="button" :disabled="busy" @click="dialog?.close()">{{ t('auth.skipPassword') }}</button>
      </div>
    </form>
  </dialog>
</template>
<style scoped>
.auth-dialog{box-sizing:border-box;background:var(--panel,#182128);color:inherit;border:1px solid #53616c;border-radius:8px;min-width:min(340px,85vw);max-width:min(460px,90vw);padding:20px}.auth-dialog::backdrop{background:#0009}.auth-dialog label{display:grid;gap:5px;margin:14px 0}.auth-dialog input{width:100%;box-sizing:border-box}.auth-dialog h2{margin:0}.admin-status{border-color:#98bca4;font-weight:600}.default-password-notice{border-left:3px solid #d5b478;padding-left:10px}
</style>
