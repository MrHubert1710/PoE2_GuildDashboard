import { computed, ref } from 'vue'
export const role = ref<'Player'|'Admin'>('Player')
export const username = ref('')
export const loginAvailable = ref(false)
export const authReady = ref(false)
export const defaultPassword = ref(false)
export const isAdmin = computed(() => role.value === 'Admin')
let csrf = ''
export async function authFetch(input: RequestInfo | URL, options: RequestInit = {}) {
  const headers = new Headers(options.headers)
  if (options.method && !['GET','HEAD'].includes(options.method.toUpperCase()) && csrf) headers.set('X-CSRF-Token', csrf)
  const response = await fetch(input, { ...options, headers, cache: 'no-store' })
  if (response.status === 401 && !String(input).endsWith('/auth/login')) role.value = 'Player'
  return response
}
async function call(path: string, options?: RequestInit) {
  const response = await authFetch(`${import.meta.env.BASE_URL}api/auth/${path}`, options)
  const data = await response.json()
  if (!response.ok) throw new Error(data.error || 'auth_unavailable')
  role.value = data.role
  username.value = data.username || ''
  if (data.csrf_token) csrf = data.csrf_token
  if ('default_password' in data) defaultPassword.value = data.default_password
  if ('login_available' in data) loginAvailable.value = data.login_available
  return data
}
export async function loadAuth() {
  try { await call('status'); authReady.value = true } catch { role.value = 'Player'; loginAvailable.value = false }
}
export async function login(password: string) {
  await loadAuth()
  await call('login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ password }) })
}
export async function logout() {
  await call('logout', { method: 'POST' })
  await loadAuth()
}

export async function changePassword(currentPassword: string, password: string) {
  await call('password', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ current_password: currentPassword, password }) })
  await loadAuth()
}
