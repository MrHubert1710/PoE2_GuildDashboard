<script setup lang="ts">
import {onMounted,onUnmounted,ref} from 'vue'
import {t,date} from '../i18n'
import {useApiRequest} from '../composables/useApiRequest'
import CollapsiblePanel from './CollapsiblePanel.vue'
const props=defineProps<{leagueId:string}>()
const {request,stopped}=useApiRequest(`${import.meta.env.BASE_URL}api/leagues/${encodeURIComponent(props.leagueId)}`)
const data=ref<any>(null),job=ref<any>(null),busy=ref(false),error=ref(false),warnings=ref<any[]>([]),available=ref(true),notice=ref('')
let timer:ReturnType<typeof setTimeout>|undefined
async function load(){
 try{const [prices,status]=await Promise.all([request('/prices'),request('/refresh')]);if(stopped())return;data.value=prices;job.value=status.prices?.job;available.value=Boolean(status.prices?.available);if(job.value?.state==='completed'&&notice.value==='pricing.fetching')notice.value='pricing.updated';warnings.value=status.prices?.last_result?.errors??[];error.value=false}
 catch{error.value=true}
 if(!stopped())timer=setTimeout(load,5000)
}
async function refresh(){busy.value=true;try{const result=await request('/refresh',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind:'prices',trigger:'manual'})});notice.value=result.outcome==='fresh'?'pricing.cacheFresh':result.outcome==='unavailable'?'pricing.sourceError':'pricing.fetching';clearTimeout(timer);await load()}catch{error.value=true}finally{busy.value=false}}
onMounted(load);onUnmounted(()=>clearTimeout(timer))
</script>
<template><section class="quantity-settings" data-testid="price-sources">
 <h2>{{ t('pricing.sources') }}</h2>
 <p class="footnote">{{ t('pricing.sourceNote') }}</p>
 <button :disabled="busy||!available||job?.state==='running'||job?.state==='queued'" @click="refresh">{{ t('pricing.refresh') }}</button>
 <span v-if="job?.state==='running'||job?.state==='queued'" role="status"> {{ t('pricing.fetching') }}</span>
 <p v-if="notice" role="status">{{ t(notice) }}</p>
 <p v-if="!available" role="status">{{ t('pricing.sourceUnavailable') }}</p>
 <p v-if="error||job?.state==='failed'" role="alert">{{ t('pricing.sourceError') }}</p>
 <details v-if="warnings.length"><summary>{{ t('pricing.categoryWarnings',{count:warnings.length}) }}</summary><ul><li v-for="warning in warnings" :key="warning.category">{{ warning.category }}: {{ warning.error }}</li></ul></details>
 <template v-if="data">
  <p v-if="data.undated" class="footnote">{{ t('pricing.estimated') }}</p>
  <CollapsiblePanel :title="t('pricing.categories')+' ('+data.categories.length+')'" :storage-key="'price-categories:'+leagueId" :initial-open="false">
   <ul><li v-for="category in data.categories" :key="category.feed+category.category">{{ category.label }} · {{ category.feed }} · {{ category.category }} · {{ t(category.active?'pricing.available':'pricing.retained') }}</li></ul>
  </CollapsiblePanel>
  <CollapsiblePanel :title="t('pricing.snapshots')+' ('+data.snapshots.length+')'" :storage-key="'price-snapshots:'+leagueId" :initial-open="false">
   <div class="transactions-scroll"><table class="transactions"><thead><tr><th>{{ t('pricing.categories') }}</th><th>{{ t('pricing.priceTime') }}</th><th>{{ t('pricing.provenance') }}</th></tr></thead><tbody><tr v-for="snapshot in data.snapshots" :key="snapshot.id"><td>{{ snapshot.category }} · {{ snapshot.feed }}</td><td>{{ snapshot.effective_at?date(snapshot.effective_at):t('pricing.unknownTime') }}</td><td>{{ t(snapshot.provenance==='legacy_undated'?'pricing.estimated':'pricing.observed') }}</td></tr></tbody></table></div>
  </CollapsiblePanel>
 </template>
</section></template>
