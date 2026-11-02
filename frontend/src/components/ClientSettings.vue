<script setup lang="ts">
import { ref, watch } from 'vue'
import { clientPreferences, saveClientPreferences, storageAvailable, defaultViews } from '../client-settings'
import { t, locale, languages, setLanguage, displayTimezone, displayHourFormat } from '../i18n'
import { normalizeDisplayTimezone, timezoneSuggestions } from '../timezones'
const timezone=ref(displayTimezone.value),hourFormat=ref(displayHourFormat.value),language=ref(locale.value)
const defaultView=ref(clientPreferences.value.defaultView)
watch(locale,value=>{language.value=value})
watch(displayTimezone,value=>{timezone.value=value})
watch(displayHourFormat,value=>{hourFormat.value=value})
const error=ref(''),saved=ref(false),timezones=timezoneSuggestions()
function save(){
  error.value='';saved.value=false
  try{
    const zone=normalizeDisplayTimezone(timezone.value)
    saveClientPreferences({timezone:zone,hourFormat:hourFormat.value,defaultView:defaultView.value})
    setLanguage(language.value)

    timezone.value=zone;saved.value=true
  }catch{error.value='invalid_timezone'}
}
</script>
<template><section class="quantity-settings client-settings" data-testid="client-settings">
  <h2>{{ t('client.title') }}</h2><p class="footnote">{{ t('client.note') }}</p>
  <form @submit.prevent="save" @input="saved=false">
    <label>{{ t('language') }}<select v-model="language" :aria-label="t('language')"><option v-for="entry in languages" :key="entry.code" :value="entry.code">{{ entry.nativeName }}</option></select></label>
    <label>{{ t('quantity.timezone') }}<input v-model="timezone" list="client-timezones" required maxlength="100" aria-describedby="client-timezone-help" /></label>
    <datalist id="client-timezones"><option v-for="zone in timezones" :key="zone.value" :value="zone.value">{{ zone.label }}</option></datalist>
    <p id="client-timezone-help" class="footnote">{{ t('quantity.timezoneHelp') }}</p>
    <label>{{ t('quantity.hourFormat') }}<select v-model="hourFormat" :aria-label="t('quantity.hourFormat')"><option value="auto">{{ t('quantity.hourAuto') }}</option><option value="12">12 h</option><option value="24">24 h</option></select></label>
    <label>{{ t('client.defaultView') }}<select v-model="defaultView" :aria-label="t('client.defaultView')"><option v-for="view in defaultViews" :key="view" :value="view">{{ t('workspace.section.'+view) }}</option></select></label>
    <p v-if="error" role="alert">{{ t('quantity.error.'+error) }}</p>
    <p v-if="saved" role="status">{{ t('client.saved') }}</p>
    <p v-if="!storageAvailable" role="status">{{ t('client.noStorage') }}</p>
    <button type="submit">{{ t('client.save') }}</button>
  </form>
</section></template>
