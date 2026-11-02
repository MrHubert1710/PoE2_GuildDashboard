<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { t } from '../i18n'
import { useApiRequest } from '../composables/useApiRequest'
const props = defineProps<{ leagueId: string; settingsHash?: string; refreshToken: number }>()
const emit = defineEmits<{ saved: [] }>()
const { request, stopped } = useApiRequest(`${import.meta.env.BASE_URL}api/leagues/${encodeURIComponent(props.leagueId)}`)
const settingsError = ref(''), saving = ref(false), dirty = ref(false), ready = ref(false)
const scope = ref('league'), guildAvailable = ref(false), guildHash = ref(''), inherited = ref(false)
const settingsHash = ref(''), rawStashes = ref<string[]>([])
const allStashes = ref(true), targets = ref<string[]>([]), timezone = ref('UTC')
const aliases = reactive<Record<string, string>>({})
const stashNames = computed(() => {
  const names = new Set([...rawStashes.value, ...Object.keys(aliases)])
  const known = new Set([...names].map(canonicalName))
  for (const name of targets.value) if (!known.has(name)) names.add(name)
  return [...names].sort()
})
const canonicalName = (name: string) => aliases[name]?.trim() || name
const included = (name: string) => allStashes.value || targets.value.includes(canonicalName(name))
function toggleStash(name: string, enabled: boolean) {
  const selected = new Set(allStashes.value ? stashNames.value.map(canonicalName) : targets.value)
  if (enabled) selected.add(canonicalName(name)); else selected.delete(canonicalName(name))
  targets.value = [...selected]
  allStashes.value = false
  dirty.value = true
}
function renameStash(name: string, value: string) {
  const previous = canonicalName(name), enabled = included(name)
  const sharedPrevious = stashNames.value.some(other => other !== name && canonicalName(other) === previous)
  aliases[name] = value
  if (!allStashes.value) {
    const selected = new Set(targets.value)
    if (!sharedPrevious) selected.delete(previous)
    if (enabled) selected.add(canonicalName(name))
    targets.value = [...selected]
  }
  dirty.value = true
}
const timezones = ['UTC', ...Intl.supportedValuesOf('timeZone')]
async function loadSettings() {
  const result = await request('/quantity-settings')
  if (stopped()) return
  guildAvailable.value = result.guild_available
  guildHash.value = result.guild_hash
  inherited.value = result.provenance === 'guild_defaults'
  settingsHash.value = result.settings_hash
  rawStashes.value = result.stashes
  allStashes.value = result.settings.target_stashes === null
  targets.value = result.settings.target_stashes ?? []
  timezone.value = result.settings.timezone
  for (const key of Object.keys(aliases)) delete aliases[key]
  Object.assign(aliases, result.settings.stash_aliases)
  ready.value = true
}
async function save(selectedScope = scope.value) {
  saving.value = true; settingsError.value = ''
  try {
    const stash_aliases = Object.fromEntries(Object.entries(aliases).map(([name, alias]) => [name, alias.trim()]).filter(([raw, alias]) => alias && alias !== raw))
    const result = await request('/quantity-settings', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ expected_hash: settingsHash.value, scope: selectedScope, expected_guild_hash: guildHash.value,
      settings: { target_stashes: allStashes.value ? null : targets.value, stash_aliases, timezone: timezone.value.trim() } }) })
    if (stopped()) return
    settingsHash.value = result.settings_hash
    await loadSettings()
    dirty.value = false
    await request('/refresh', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ kind: 'quantities', trigger: 'manual' }) })
    emit('saved')
  } catch (cause) { if (!stopped()) settingsError.value = cause instanceof Error ? cause.message : 'invalid_settings' }
  finally { if (!stopped()) saving.value = false }
}
watch(() => [props.settingsHash, props.refreshToken], () => { if (!dirty.value) void loadSettings().catch(() => { settingsError.value = 'report_unavailable' }) })
onMounted(() => { void loadSettings().catch(() => { settingsError.value = 'report_unavailable' }) })
</script>
<template><section class="quantity-settings settings-view" data-testid="quantity-settings">
  <h2>{{ t('quantity.settings') }}</h2>
  <p v-if="!ready && !settingsError" role="status">{{ t('workspace.settingsLoading') }}</p>
  <p v-if="!ready && settingsError" role="alert">{{ t(`quantity.error.${settingsError}`) }}</p>
      <form v-if="ready" @input="dirty = true" @submit.prevent="save()">
        <p class="footnote">{{ t('quantity.settingsNote') }}</p>
        <p>{{ t(inherited ? 'quantity.inheriting' : 'quantity.overridden') }}</p>
        <label>{{ t('quantity.saveScope') }}<select v-model="scope" :aria-label="t('quantity.saveScope')"><option value="league">{{ t('quantity.scopeLeague') }}</option><option v-if="guildAvailable" value="guild">{{ t('quantity.scopeGuild') }}</option></select></label>
        <label class="check-label"><input v-model="allStashes" type="checkbox" />{{ t('quantity.allStashes') }}</label>

        <label>{{ t('quantity.timezone') }}<input v-model="timezone" list="quantity-timezones" required maxlength="100" /><datalist id="quantity-timezones"><option v-for="zone in timezones" :key="zone" :value="zone" /></datalist></label>
        <p class="footnote">{{ t('quantity.aliasNote') }}</p>
        <p class="footnote">{{ t('quantity.stashSelectionNote') }}</p>
        <div class="stash-settings-list">
          <div v-for="name in stashNames" :key="name" class="stash-settings-row" :class="{ excluded: !included(name) }">
            <label class="check-label"><input type="checkbox" :checked="included(name)" :aria-label="t('quantity.includeStash', { name })" @change="toggleStash(name, ($event.target as HTMLInputElement).checked)" /><span>{{ name }}</span></label>
            <span class="stash-setting-status">{{ t(included(name) ? 'quantity.stashEnabled' : 'quantity.stashDisabled') }}</span>
            <label>{{ t('quantity.displayName') }}<input :value="aliases[name] ?? ''" :aria-label="t('quantity.aliasFor', { name })" :placeholder="name" maxlength="200" @input="renameStash(name, ($event.target as HTMLInputElement).value)" /></label>
          </div>
        </div>
        <p v-if="settingsError" role="alert">{{ t(`quantity.error.${settingsError}`) }}</p>
        <div class="filter-actions"><button type="submit" :disabled="saving">{{ t('quantity.save') }}</button><button v-if="!inherited" type="button" :disabled="saving" @click="save('inherit')">{{ t('quantity.restoreInheritance') }}</button></div>
      </form>
</section></template>
