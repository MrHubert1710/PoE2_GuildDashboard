<script setup lang="ts">
import {onMounted,onUnmounted,reactive,ref} from 'vue'
import {t,date} from '../i18n'
import {useApiRequest} from '../composables/useApiRequest'
const emit=defineEmits<{changed:[deletedId?:string]}>()
const {request,stopped}=useApiRequest(`${import.meta.env.BASE_URL}api/league-catalog`)
const data=ref<any>(null),busy=ref(false),error=ref(''),notice=ref(''),name=ref('')
const edits=reactive<Record<string,any>>({}),dirty=reactive(new Set<string>())
const deleteDialog=ref<HTMLDialogElement|null>(null),deleting=ref<any>(null),deleteError=ref('')
function confirmDelete(league:any){deleting.value={...league};deleteError.value='';deleteDialog.value?.showModal()}
async function remove(){
 if(!deleting.value)return
 busy.value=true;deleteError.value='';notice.value=''
 const league=deleting.value
 try{
  await request('/leagues/'+encodeURIComponent(league.id),{method:'DELETE',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:league.name,version:league.version})})
  if(stopped())return
  dirty.delete(league.id);delete edits[league.id];deleteDialog.value?.close();deleting.value=null
  notice.value='catalog.deleted';clearTimeout(timer);await load();emit('changed',league.id)
 }catch(cause){deleteError.value=cause instanceof Error?cause.message:'unavailable'}finally{busy.value=false}
}
let timer:ReturnType<typeof setTimeout>|undefined
async function load(){
 try{const result=await request('');if(stopped())return;data.value=result;for(const league of result.leagues)if(!dirty.has(league.id))edits[league.id]={monitored:league.monitored,lifecycle_override:league.lifecycle_override??'',version:league.version}}
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
  <div class="transactions-scroll"><table class="transactions"><thead><tr><th>{{ t('league') }}</th><th>{{ t('catalog.monitored') }}</th><th>{{ t('catalog.lifecycle') }}</th><th>{{ t('catalog.observed') }}</th><th></th></tr></thead><tbody><tr v-for="league in data.leagues" :key="league.id" @change="dirty.add(league.id)"><td>{{ league.name }}</td><td><input v-model="edits[league.id].monitored" type="checkbox" :aria-label="t('catalog.monitorFor',{name:league.name})" /></td><td><select v-model="edits[league.id].lifecycle_override" :aria-label="t('catalog.lifecycleFor',{name:league.name})"><option value="">{{ t('catalog.automatic') }}</option><option value="active">{{ t('active') }}</option><option value="ended">{{ t('archived') }}</option><option value="unknown">{{ t('unknown') }}</option></select></td><td>{{ t(league.observed_lifecycle==='ended'?'archived':league.observed_lifecycle) }}<small class="footnote" style="display:block">{{ t('catalog.evidence.'+league.observed_source) }}<template v-if="league.observed_at"> · {{ date(league.observed_at) }}</template></small></td><td><button :disabled="busy||!dirty.has(league.id)" :aria-label="t('catalog.saveFor',{name:league.name})" @click="save(league.id)">{{ t('catalog.save') }}</button> <button class="danger-button" :disabled="busy" :aria-label="t('catalog.deleteFor',{name:league.name})" @click="confirmDelete(league)">{{ t('catalog.delete') }}</button></td></tr></tbody></table></div>
  <h3>{{ t('catalog.discovered') }}</h3>
  <div v-if="data.entries.length" class="transactions-scroll"><table class="transactions"><thead><tr><th>{{ t('league') }}</th><th>{{ t('catalog.provider') }}</th><th>{{ t('catalog.observed') }}</th><th>{{ t('catalog.lastSeen') }}</th><th></th></tr></thead><tbody><tr v-for="entry in data.entries" :key="entry.provider+entry.external_id"><td>{{ entry.name }}<span v-if="!entry.present" class="footnote"> · {{ t('catalog.retained') }}</span></td><td>{{ entry.provider }} · {{ entry.realm }}</td><td>{{ t(entry.lifecycle==='ended'?'archived':entry.lifecycle) }}</td><td>{{ date(entry.last_seen) }}</td><td><span v-if="entry.league_id">{{ t('catalog.added') }}</span><button v-else :disabled="busy" :aria-label="t('catalog.addFor',{name:entry.name})" @click="action('/leagues',{provider:entry.provider,external_id:entry.external_id})">{{ t('catalog.add') }}</button></td></tr></tbody></table></div>
  <p v-else class="footnote">{{ t('catalog.noCandidates') }}</p>
  <form class="catalog-manual" @submit.prevent="add"><label>{{ t('catalog.manualName') }}<input v-model="name" maxlength="200" required /></label><button type="submit" :disabled="busy||!name.trim()">{{ t('catalog.add') }}</button></form>
 </template>
 <p v-if="notice" role="status">{{ t(notice) }}</p><p v-if="error" role="alert">{{ t('catalog.error.'+error) }}</p>
 <dialog ref="deleteDialog" class="delete-league-dialog" :aria-label="t('catalog.deleteTitle')" @cancel="event=>{if(busy)event.preventDefault()}">
  <form @submit.prevent="remove">
   <h2>{{ t('catalog.deleteTitle') }}</h2>
   <p>{{ t('catalog.deleteWarning',{name:deleting?.name??''}) }}</p>
   <p class="footnote">{{ t('catalog.deleteRecovery') }}</p>
   <p v-if="busy" role="status">{{ t('catalog.deleting') }}</p>
   <p v-if="deleteError" role="alert">{{ t('catalog.error.'+deleteError) }}</p>
   <div class="filter-actions"><button type="button" :disabled="busy" autofocus @click="deleteDialog?.close()">{{ t('catalog.cancelDelete') }}</button><button type="submit" class="danger-button" :disabled="busy">{{ t('catalog.confirmDelete') }}</button></div>
  </form>
 </dialog>
</section></template>
<style scoped>
.danger-button{border-color:#e38b82;color:#ffb9b2}.danger-button:hover{background:#592d2c}.delete-league-dialog{box-sizing:border-box;background:var(--panel,#182128);color:inherit;border:2px solid #c66e65;border-radius:8px;max-width:min(540px,90vw);padding:22px}.delete-league-dialog::backdrop{background:#000a}.delete-league-dialog h2{margin-top:0}
</style>
