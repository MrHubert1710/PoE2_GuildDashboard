<script setup lang="ts">
import {computed,onUnmounted,ref,watch} from 'vue'
import {currentUrl,updateUrl} from '../navigation'
import {priceVersions} from '../pricing-state'
import {t,number,displayTimezone} from '../i18n'
import type {HistoryQuery} from '../browsing'
import {useApiRequest} from '../composables/useApiRequest'
import CollapsiblePanel from './CollapsiblePanel.vue'
const props=defineProps<{leagueId:string;view:string;query:HistoryQuery;refreshToken:number}>()
const {request,stopped}=useApiRequest(`${import.meta.env.BASE_URL}api/leagues/${encodeURIComponent(props.leagueId)}`)
const active=computed(()=>new URL(currentUrl.value).searchParams.get('chart_mode')!=='quantity'&&props.view!=='state')
const data=ref<any>(null),error=ref(false),busy=ref(false)
const readPage=(key:string)=>{const value=Number(new URL(currentUrl.value).searchParams.get(key));return Number.isInteger(value)&&value>0?value:1}
const page=computed(()=>readPage('valuation_page')),missingPage=computed(()=>readPage('unpriced_page'))
function move(value:number,missing=false){const url=new URL(currentUrl.value),key=missing?'unpriced_page':'valuation_page';if(value>1)url.searchParams.set(key,String(value));else url.searchParams.delete(key);updateUrl(url)}
let timer:ReturnType<typeof setTimeout>|undefined,sequence=0
async function load(){
 const current=++sequence;clearTimeout(timer)
 if(!active.value)return
 try{
  const params=new URLSearchParams({view:props.view,timezone:displayTimezone.value,page:String(page.value),unpriced_page:String(missingPage.value)})
  for(const [key,value] of Object.entries(props.query)){
   if(['league','sort','direction','page','page_size'].includes(key))continue
   if(Array.isArray(value)){for(const item of value)params.append(key,item)}else if(value)params.set(key,String(value===true?1:value))
  }
  const result=await request('/valuations?'+params)
  if(stopped()||current!==sequence)return
  data.value=result;error.value=false
  if(result.state==='ready'&&(result.page!==page.value||result.unpriced_page!==missingPage.value)){
   const url=new URL(currentUrl.value)
   for(const [key,value] of [['valuation_page',result.page],['unpriced_page',result.unpriced_page]] as const){if(value>1)url.searchParams.set(key,String(value));else url.searchParams.delete(key)}
   updateUrl(url,true)
  }
  if(result.price_revision)priceVersions.value={...priceVersions.value,[props.leagueId]:result.price_revision}
  timer=setTimeout(load,result.state!=='ready'?1500:5000)
 }catch{if(current===sequence)error.value=true}
}
async function refreshPrices(){busy.value=true;try{await request('/refresh',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind:'prices',trigger:'manual'})})}catch{error.value=true}finally{busy.value=false}}
void request('/refresh',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind:'prices',trigger:'automatic'})}).catch(()=>{})
watch(()=>JSON.stringify([active.value,props.query,props.refreshToken,props.view,displayTimezone.value,page.value,missingPage.value]),()=>{data.value=null;void load()},{immediate:true})
onUnmounted(()=>{++sequence;clearTimeout(timer)})
</script>
<template><section v-if="active" data-testid="valuation-report">
 <p v-if="error" role="alert">{{ t('pricing.error') }}</p>
 <p v-if="!data||data.state!=='ready'" role="status">{{ t('pricing.pending') }}</p>
 <template v-else>
  <CollapsiblePanel :title="t(data.model==='inventory'?'pricing.inventoryTable':'pricing.table')" :storage-key="'value-table:'+leagueId+':'+view">
   <p class="footnote">{{ t('pricing.currency') }} · {{ t('pricing.historical') }} · {{ t(data.model==='inventory'?'pricing.inventoryCoverage':'pricing.coverage',{priced:data.priced_operations,missing:data.unpriced_operations}) }}</p>
   <p v-if="data.model==='inventory'" class="footnote">{{ t('pricing.inventoryNote') }}</p>
   <p v-if="data.account_filter_ignored" class="footnote">{{ t('pricing.inventoryAccountNote') }}</p>
   <p v-if="!data.rows.length" class="empty-state">{{ t('pricing.noCoverage') }}</p>
   <div v-else-if="data.model==='inventory'" class="transactions-scroll"><table class="transactions"><thead><tr><th>{{ t('chart.group') }}</th><th>{{ t('pricing.quantityHeld') }}</th><th>{{ t('pricing.openingValue') }}</th><th>{{ t('pricing.closingValue') }}</th><th>{{ t('pricing.valueChange') }}</th></tr></thead><tbody><tr v-for="row in data.rows" :key="row.name"><td>{{ view==='summary'?t('chart.total'):row.name }}</td><td>{{ number(row.quantity) }}</td><td>{{ number(row.opening_value,true) }}</td><td>{{ row.quantity>0&&row.unpriced_units===row.quantity?'—':number(row.net,true) }}</td><td>{{ row.quantity>0&&row.unpriced_units===row.quantity?'—':number(row.change,true) }}</td></tr></tbody></table></div>
   <div v-else class="transactions-scroll"><table class="transactions"><thead><tr><th>{{ t('chart.group') }}</th><th>{{ t('added') }}</th><th>{{ t('removed') }}</th><th>{{ t('quantity.balance') }}</th></tr></thead><tbody><tr v-for="row in data.rows" :key="row.name"><td>{{ row.reconstruction?t('quantity.reconstruction'):view==='summary'?t('chart.total'):row.name }}</td><td>{{ number(row.added,true) }}</td><td>{{ number(row.removed,true) }}</td><td>{{ number(row.net,true) }}</td></tr></tbody></table></div>
   <nav v-if="data.pages>1" class="pagination"><button :disabled="page<=1" @click="move(page-1)">{{ t('previous') }}</button><span>{{ page }} / {{ data.pages }}</span><button :disabled="page>=data.pages" @click="move(page+1)">{{ t('next') }}</button></nav>
  </CollapsiblePanel>
  <CollapsiblePanel :title="t('pricing.unpriced')+' ('+data.unpriced_total+')'" :storage-key="'unpriced:'+leagueId+':'+view" :initial-open="data.coverage!=='complete'">
   <p class="footnote">{{ t(data.model==='inventory'?'pricing.inventoryMissingNote':'pricing.missingNote') }}</p>
   <div v-if="data.unpriced.length" class="transactions-scroll"><table class="transactions"><thead><tr><th>{{ t('item') }}</th><th>{{ t(data.model==='inventory'?'pricing.positions':'pricing.operations') }}</th><th>{{ t(data.model==='inventory'?'pricing.quantityHeld':'pricing.units') }}</th><th>{{ t('pricing.reason') }}</th></tr></thead><tbody><tr v-for="row in data.unpriced" :key="row.item_name+row.reason"><td>{{ row.item_name }}</td><td>{{ number(row.operations) }}</td><td>{{ number(row.units) }}</td><td>{{ t('pricing.reason.'+row.reason) }}</td></tr></tbody></table></div>
   <nav v-if="data.unpriced_pages>1" class="pagination"><button :disabled="missingPage<=1" @click="move(missingPage-1,true)">{{ t('previous') }}</button><span>{{ missingPage }} / {{ data.unpriced_pages }}</span><button :disabled="missingPage>=data.unpriced_pages" @click="move(missingPage+1,true)">{{ t('next') }}</button></nav>
  </CollapsiblePanel>
 </template>
</section></template>
