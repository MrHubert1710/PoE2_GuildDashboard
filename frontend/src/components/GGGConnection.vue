<script setup lang="ts">
import {onMounted,onUnmounted,ref} from 'vue'
import {t,date} from '../i18n'
import {useApiRequest} from '../composables/useApiRequest'
const {request,stopped}=useApiRequest(`${import.meta.env.BASE_URL}api`)
const data=ref<any>(null),guild=ref(''),session=ref(''),enabled=ref(false),clearSession=ref(false),source=ref<number|null>(null),revision=ref(''),dirty=ref(false),busy=ref(false),error=ref(''),saved=ref(false)
let timer:ReturnType<typeof setTimeout>|undefined
async function load(){
 try{const result=await request('/ggg-connection');if(stopped())return;data.value=result
  if(!dirty.value){guild.value=result.connection.guild_id;enabled.value=Boolean(result.connection.enabled);revision.value=result.connection.revision;source.value=result.connection.source_id??(result.sources.length===1?result.sources[0].id:null)}}catch{error.value='unavailable'}
 if(!stopped())timer=setTimeout(load,5000)
}
async function save(){busy.value=true;error.value='';saved.value=false
 try{const result=await request('/ggg-connection',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({guild_id:guild.value.trim(),session_id:session.value,enabled:enabled.value,clear_session:clearSession.value,revision:revision.value,source_id:source.value})});if(stopped())return;session.value='';clearSession.value=false;revision.value=result.connection.revision;dirty.value=false;saved.value=true;clearTimeout(timer);await load()}
 catch(cause){error.value=cause instanceof Error?cause.message:'unavailable'}finally{busy.value=false}
}
onMounted(load);onUnmounted(()=>clearTimeout(timer))
</script>
<template><section class="quantity-settings" data-testid="ggg-connection">
 <h2>{{ t('ggg.title') }}</h2><p class="footnote">{{ t('ggg.note') }}</p>
 <p v-if="!data" role="status">{{ t('loading') }}</p>
 <form v-else @submit.prevent="save" @input="dirty=true;saved=false">
  <div class="catalog-form">
   <label>GUILD_ID<input v-model="guild" name="guild_id" inputmode="numeric" maxlength="20" autocomplete="off" required /></label>
   <label>SESSION_ID (POESESSID)<input v-model="session" name="session_id" type="password" maxlength="280" autocomplete="new-password" :placeholder="data.connection.session_configured?t('ggg.stored'):t('ggg.empty')" /></label>
   <label v-if="data.sources.length>1">{{ t('ggg.archive') }}<select v-model="source" @change="dirty=true"><option :value="null">{{ t('ggg.chooseArchive') }}</option><option v-for="item in data.sources" :key="item.id" :value="item.id">{{ item.source_key }}</option></select></label>
  </div>
  <p class="footnote">{{ t('ggg.cookieHelp') }}</p>
  <label class="check-label"><input v-model="enabled" type="checkbox" />{{ t('ggg.enabled') }}</label>
  <label v-if="data.connection.session_configured" class="check-label"><input v-model="clearSession" type="checkbox" />{{ t('ggg.clearSession') }}</label>
  <button type="submit" :disabled="busy||!dirty">{{ t('ggg.save') }}</button>
  <p v-if="saved" role="status">{{ t('ggg.saved') }}</p>
  <p class="footnote" data-testid="ggg-state">{{ t('ggg.state') }}: {{ t('ggg.state.'+data.connection.state) }} · {{ t('ggg.secretState') }}: {{ t(data.connection.session_configured?'ggg.configured':'ggg.notConfigured') }}</p>
  <p v-if="data.connection.state==='fetching'" role="status">{{ t('ggg.pages',{count:data.connection.pages}) }}</p>
  <p v-if="data.connection.next_request*1000>Date.now()" class="footnote">{{ t('ggg.nextRequest') }}: {{ date(new Date(data.connection.next_request*1000).toISOString()) }}</p>
  <p v-if="data.connection.checked_at" class="footnote">{{ t('ggg.checked') }}: {{ date(new Date(data.connection.checked_at*1000).toISOString()) }}</p>
  <p v-if="data.connection.error_code" role="alert">{{ t('ggg.error.'+data.connection.error_code) }}</p>
  <details v-if="data.pending.length"><summary>{{ t('ggg.pending') }}</summary><ul><li v-for="item in data.pending" :key="item.league_name">{{ item.league_name }}: {{ item.events }}</li></ul></details>
 </form>
 <p v-if="error" role="alert">{{ t('ggg.error.'+error) }}</p>
</section></template>
