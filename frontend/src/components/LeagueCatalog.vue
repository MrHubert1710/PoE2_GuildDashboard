<script setup lang="ts">
import {onMounted,onUnmounted,reactive,ref} from 'vue'
import {t,date} from '../i18n'
import {useApiRequest} from '../composables/useApiRequest'
const emit=defineEmits<{changed:[]}>()
const {request,stopped}=useApiRequest(`${import.meta.env.BASE_URL}api/league-catalog`)
const data=ref<any>(null),busy=ref(false),error=ref(''),notice=ref(''),name=ref('')
const edits=reactive<Record<string,any>>({}),dirty=reactive(new Set<string>())
let timer:ReturnType<typeof setTimeout>|undefined
async function load(){
 try{const result=await request('');if(stopped())return;data.value=result;for(const league of result.leagues)if(!dirty.has(league.id))edits[league.id]={monitored:league.monitored,archived:league.archived,lifecycle_override:league.lifecycle_override??'',version:league.version}}
 catch(cause){error.value=cause instanceof Error?cause.message:'unavailable'}
 if(!stopped())timer=setTimeout(load,5000)
}
async function action(path:string,payload:unknown,method='POST'){
 busy.value=true;error.value='';notice.value=''
 try{const result=await request(path,{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});notice.value=result.outcome==='fresh'?'catalog.fresh':result.outcome==='queued'||result.outcome==='coalesced'?'catalog.fetching':'catalog.saved';clearTimeout(timer);await load();emit('changed')}
 catch(cause){error.value=cause instanceof Error?cause.message:'unavailable'}finally{busy.value=false}
}
async function save(id:string){const edit=edits[id];await action('/leagues/'+encodeURIComponent(id),{...edit,lifecycle_override:edit.lifecycle_override||null},'PUT');if(!error.value){dirty.delete(id);clearTimeout(timer);await load()}}
async function add(){if(!name.value.trim())return;await action('/leagues',{name:name.value.trim()});if(!error.value)name.value=''}
onMounted(load);onUnmounted(()=>clearTimeout(timer))
</script>
<template><section class="quantity-settings" data-testid="league-catalog">
 <h2>{{ t('catalog.title') }}</h2><p class="footnote">{{ t('catalog.note') }}</p>
 <p v-if="!data" role="status">{{ t('loading') }}</p>
 <template v-else>
  <button :disabled="busy||!data.available||['running','queued'].includes(data.job?.state)" @click="action('/refresh',{})">{{ t('catalog.refresh') }}</button>
  <span v-if="['running','queued'].includes(data.job?.state)" role="status"> {{ t('catalog.fetching') }}</span>
  <p v-if="!data.ggg_configured" class="footnote">{{ t('catalog.gggUnavailable') }}</p>
  <p v-if="!data.available" class="footnote">{{ t('catalog.disabled') }}</p>
  <ul class="footnote"><li v-for="source in data.sources" :key="source.provider">{{ source.provider }} · {{ source.last_success_at?date(source.last_success_at):t('catalog.noObservation') }}<span v-if="source.error_code"> · {{ source.error_code==='ggg_catalog_unconfigured'?t('catalog.gggUnavailable'):t('catalog.sourceError')+' ('+source.error_code+')' }}</span></li></ul>
  <h3>{{ t('catalog.local') }}</h3>
  <p class="footnote">{{ t('catalog.lifecycleNote') }}</p>
  <div class="transactions-scroll"><table class="transactions"><thead><tr><th>{{ t('league') }}</th><th>{{ t('catalog.monitored') }}</th><th>{{ t('catalog.archive') }}</th><th>{{ t('catalog.lifecycle') }}</th><th>{{ t('catalog.observed') }}</th><th></th></tr></thead><tbody><tr v-for="league in data.leagues" :key="league.id" @change="dirty.add(league.id)"><td>{{ league.name }}</td><td><input v-model="edits[league.id].monitored" type="checkbox" :aria-label="t('catalog.monitorFor',{name:league.name})" /></td><td><input v-model="edits[league.id].archived" type="checkbox" :aria-label="t('catalog.archiveFor',{name:league.name})" /></td><td><select v-model="edits[league.id].lifecycle_override" :aria-label="t('catalog.lifecycleFor',{name:league.name})"><option value="">{{ t('catalog.automatic') }}</option><option value="active">{{ t('active') }}</option><option value="ended">{{ t('ended') }}</option><option value="unknown">{{ t('unknown') }}</option></select></td><td>{{ t(league.observed_lifecycle) }}<small class="footnote" style="display:block">{{ t('catalog.evidence.'+league.observed_source) }}<template v-if="league.observed_at"> · {{ date(league.observed_at) }}</template></small></td><td><button :disabled="busy||!dirty.has(league.id)" :aria-label="t('catalog.saveFor',{name:league.name})" @click="save(league.id)">{{ t('catalog.save') }}</button></td></tr></tbody></table></div>
  <h3>{{ t('catalog.discovered') }}</h3>
  <div v-if="data.entries.length" class="transactions-scroll"><table class="transactions"><thead><tr><th>{{ t('league') }}</th><th>{{ t('catalog.provider') }}</th><th>{{ t('catalog.observed') }}</th><th>{{ t('catalog.lastSeen') }}</th><th></th></tr></thead><tbody><tr v-for="entry in data.entries" :key="entry.provider+entry.external_id"><td>{{ entry.name }}<span v-if="!entry.present" class="footnote"> · {{ t('catalog.retained') }}</span></td><td>{{ entry.provider }} · {{ entry.realm }}</td><td>{{ t(entry.lifecycle) }}</td><td>{{ date(entry.last_seen) }}</td><td><span v-if="entry.league_id">{{ t('catalog.added') }}</span><button v-else :disabled="busy" :aria-label="t('catalog.addFor',{name:entry.name})" @click="action('/leagues',{provider:entry.provider,external_id:entry.external_id})">{{ t('catalog.add') }}</button></td></tr></tbody></table></div>
  <p v-else class="footnote">{{ t('catalog.noCandidates') }}</p>
  <form class="catalog-manual" @submit.prevent="add"><label>{{ t('catalog.manualName') }}<input v-model="name" maxlength="200" required /></label><button type="submit" :disabled="busy||!name.trim()">{{ t('catalog.add') }}</button></form>
 </template>
 <p v-if="notice" role="status">{{ t(notice) }}</p><p v-if="error" role="alert">{{ t('catalog.error.'+error) }}</p>
</section></template>
