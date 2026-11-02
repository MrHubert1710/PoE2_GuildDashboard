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
const canonicalStashes = computed(() => [...new Set(rawStashes.value.map(name => aliases[name]?.trim() || name))].sort())
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
    const stash_aliases = Object.fromEntries(rawStashes.value.map(name => [name, aliases[name]?.trim() ?? '']).filter(([raw, alias]) => alias && alias !== raw))
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
        <div v-if="!allStashes" class="target-stashes"><label v-for="name in canonicalStashes" :key="name" class="check-label"><input v-model="targets" type="checkbox" :value="name" />{{ name }}</label></div>
        <label>{{ t('quantity.timezone') }}<input v-model="timezone" list="quantity-timezones" required maxlength="100" /><datalist id="quantity-timezones"><option v-for="zone in timezones" :key="zone" :value="zone" /></datalist></label>
        <p class="footnote">{{ t('quantity.aliasNote') }}</p>
        <div class="alias-grid"><label v-for="name in rawStashes" :key="name">{{ name }}<input v-model="aliases[name]" :aria-label="t('quantity.aliasFor', { name })" :placeholder="name" maxlength="200" /></label></div>
        <p v-if="settingsError" role="alert">{{ t(`quantity.error.${settingsError}`) }}</p>
        <div class="filter-actions"><button type="submit" :disabled="saving">{{ t('quantity.save') }}</button><button v-if="!inherited" type="button" :disabled="saving" @click="save('inherit')">{{ t('quantity.restoreInheritance') }}</button></div>
      </form>
</section></template>
