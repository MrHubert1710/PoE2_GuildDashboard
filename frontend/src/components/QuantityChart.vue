<script setup lang="ts">
import {clientPreferences,saveClientPreferences} from '../client-settings'
import {computed,defineAsyncComponent,ref,watch} from 'vue'
import type {HistoryQuery} from '../browsing'
import {currentUrl,updateUrl} from '../navigation'
import {useQuantitySeries} from '../composables/useQuantitySeries'
import {t,date,number} from '../i18n'
import {balanceColor} from '../chart-style'
import ColorPicker from './ColorPicker.vue'
import CollapsiblePanel from './CollapsiblePanel.vue'
const TimeSeriesChart=defineAsyncComponent(()=>import('./TimeSeriesChart.vue'))
const props=defineProps<{leagueId:string;revision:string;settingsHash?:string;projectionId:string|null;query:HistoryQuery;active:boolean;refreshToken:number;view:string}>()
const emit=defineEmits<{range:[from:string,to:string]}>()
const {data,error,loading,selectedItem,chooseItem,valuation,chooseMode,priceMode,choosePricing,stateAt,reload}=useQuantitySeries(props)
const colors=computed(()=>clientPreferences.value.colors),picker=ref<{id:string;name:string;color:string;left:number;top:number}|null>(null)
function colorId(series:{id:string;aggregate?:boolean}){return series.aggregate?'combined':props.view+':'+series.id}
function colored<T extends {id:string;aggregate?:boolean}>(series:T){return {...series,color:colors.value[colorId(series)]}}
function openColor(series:{id:string;name:string;aggregate?:boolean;reconstruction?:boolean},event:MouseEvent){
  const box=(event.currentTarget as HTMLElement).getBoundingClientRect()
  picker.value={id:colorId(series),name:seriesLabel(series),color:balanceColor(colored(series),navigator.value.series.findIndex(value=>value.id===series.id)),left:Math.max(8,Math.min(innerWidth-270,box.left)),top:Math.max(8,Math.min(innerHeight-470,box.bottom+6))}
}
function setColor(value:string){if(!picker.value||!/^#[0-9a-f]{6}$/i.test(value))return;saveClientPreferences({colors:{...colors.value,[picker.value.id]:value}});picker.value.color=value}

const chartSeries=computed(()=>(props.view==='summary'?(data.value?.series??[]).map(series=>({...series,aggregate:true})):[...(data.value?.series??[]),...(data.value?.total_series?[data.value.total_series]:[])]).map(colored))
const navigator=computed(()=>{
  const context=data.value?.navigator??{bounds:null,series:[],total_series:null}
  return {...context,series:(props.view==='summary'?context.series.map(series=>({...series,aggregate:true})):[...context.series,...(context.total_series?[context.total_series]:[])]).map(colored)}
})
const seriesLabel=(series:{name:string;aggregate?:boolean;reconstruction?:boolean})=>props.view==='summary'?t('chart.total'):series.aggregate?t('chart.combined'):series.reconstruction?t('quantity.reconstruction'):series.name

const enabled=computed(()=>{
  const all=navigator.value.series.map(series=>series.id),value=new URL(currentUrl.value).searchParams.get('chart_series')
  if(value===null)return all
  const selected=value.split(',').filter(id=>all.includes(id))
  return value&&!selected.length?all:selected
})
const window=computed(()=>{
  const p=new URL(currentUrl.value).searchParams,from=Number(p.get('chart_from')),to=Number(p.get('chart_to'))
  if(p.has('chart_from')&&p.has('chart_to')&&Number.isSafeInteger(from)&&Number.isSafeInteger(to)&&from<to)return {start:from,end:to}
  return data.value?.window??navigator.value.bounds
})
const valueWindow=computed(()=>{const p=new URL(currentUrl.value).searchParams,min=Number(p.get('chart_ymin')),max=Number(p.get('chart_ymax'));return p.has('chart_ymin')&&p.has('chart_ymax')&&Number.isFinite(min)&&Number.isFinite(max)&&min<max?{start:min,end:max}:null})
function valueZoom(value:{start:number;end:number}){const url=new URL(currentUrl.value);url.searchParams.set('chart_ymin',String(value.start));url.searchParams.set('chart_ymax',String(value.end));updateUrl(url,true)}
function resetValues(){const url=new URL(currentUrl.value);url.searchParams.delete('chart_ymin');url.searchParams.delete('chart_ymax');updateUrl(url,true)}
const items=computed(()=>[...new Set([data.value?.item,selectedItem.value,'__all__',...(data.value?.items??[])].filter((value):value is string=>Boolean(value)))])
function toggle(id:string,checked:boolean){const values=new Set(enabled.value);if(checked)values.add(id);else values.delete(id);const url=new URL(currentUrl.value);url.searchParams.set('chart_series',[...values].join(','));updateUrl(url,true)}
function zoom(value:{start:number;end:number}){if(value.start>=value.end)return;const url=new URL(currentUrl.value);url.searchParams.set('chart_from',String(value.start));url.searchParams.set('chart_to',String(value.end));updateUrl(url,true)}
function reset(){
  const url=new URL(currentUrl.value)
  for(const key of ['chart_from','chart_to','chart_base_from','chart_base_to'])url.searchParams.delete(key)
  updateUrl(url,true);emit('range','','')
}
function commit(value:{start:number;end:number}){
  if(!data.value)return
  const url=new URL(currentUrl.value)
  url.searchParams.delete('chart_base_from');url.searchParams.delete('chart_base_to')
  url.searchParams.set('chart_from',String(value.start));url.searchParams.set('chart_to',String(value.end));updateUrl(url,true)
  emit('range',new Date(value.start).toISOString(),new Date(value.end).toISOString())
}
function selectItem(value:string){chooseItem(value)}

let initial=false
watch(data,value=>{if(value&&!initial){initial=true;if(new URL(currentUrl.value).searchParams.has('chart_from')&&window.value)commit(window.value)}})

</script>
<template><CollapsiblePanel :title="t('chart.title')" :storage-key="'chart:'+leagueId+':'+view" class="quantity-chart" data-testid="quantity-chart">
  <div class="chart-controls">
    <label class="check-label chart-mode"><input type="checkbox" role="switch" :checked="valuation" :aria-label="t('chart.valueMode')" @change="chooseMode(($event.target as HTMLInputElement).checked)" />{{ t(valuation?'chart.valueMode':'chart.quantityMode') }}</label>
    <label v-if="!valuation" class="chart-item"><span>{{ t('chart.item') }}</span><select :aria-label="t('chart.item')" :value="selectedItem==='__all__'?'__all__':data?.item??selectedItem" :disabled="!items.length" @change="selectItem(($event.target as HTMLSelectElement).value)"><option v-for="item in items" :key="item" :value="item">{{ item==='__all__'?t('chart.all'):item }}</option></select></label>
    <label v-else class="check-label">{{ t('chart.historicalPrices') }}<input type="checkbox" role="switch" :aria-label="t('chart.currentPrices')" :checked="priceMode==='latest'" @change="choosePricing(($event.target as HTMLInputElement).checked)" />{{ t('chart.currentPrices') }}</label>
    <button type="button" :disabled="loading||!projectionId" @click="reload">{{ t('chart.refresh') }}</button>
    <span v-if="loading" role="status" class="chart-loading">{{ t('chart.loading') }}</span>
  </div>
  <p v-if="valuation" class="footnote valuation-status" data-testid="valuation-status">{{ t('pricing.currency') }} · {{ t(priceMode==='latest'?'pricing.latest':'pricing.historical') }}
    <span v-if="data?.pricing?.state==='missing'" role="status"> · {{ t('pricing.pending') }}</span>
    <span v-else-if="data?.pricing?.coverage==='none'"> · {{ t('pricing.noCoverage') }}</span>
    <span v-else-if="data?.pricing?.coverage==='partial'"> · {{ t('pricing.partial') }}</span>
    <span v-if="data?.pricing?.estimated_operations"> · {{ t('pricing.estimated') }}</span>
  </p>
  <p v-if="error" role="alert">{{ t(`quantity.error.${error}`) }}</p>
  <p v-else-if="!projectionId" role="status">{{ t('quantity.pending') }}</p>
  <p v-else-if="!loading&&!data?.series.length" class="empty-state">{{ t('chart.empty') }}</p>
  <div v-if="data?.series.length" class="chart-legend" :aria-label="t('chart.groups',{count:chartSeries.length})" data-testid="chart-legend">
    <div v-for="series in chartSeries" :key="series.id" class="check-label">
      <input :id="'series-'+leagueId+'-'+view+'-'+series.id" type="checkbox" :checked="enabled.includes(series.id)" @change="toggle(series.id,($event.target as HTMLInputElement).checked)" />
      <button type="button" class="series-color-button" :aria-label="t('chart.colorFor',{name:seriesLabel(series)})" @click="openColor(series,$event)"><i class="series-swatch" :class="{'aggregate-swatch':series.aggregate}" :style="{background:balanceColor(series,navigator.series.findIndex(value=>value.id===series.id)),borderColor:balanceColor(series,navigator.series.findIndex(value=>value.id===series.id))}" aria-hidden="true"></i></button>
      <label :for="'series-'+leagueId+'-'+view+'-'+series.id">{{ seriesLabel(series) }}</label>
    </div>
  </div>
  <div v-if="picker" class="color-picker-backdrop" @click="picker=null"></div>
  <ColorPicker v-if="picker" :name="picker.name" :value="picker.color" :left="picker.left" :top="picker.top" @change="setColor" @close="picker=null" />
  <TimeSeriesChart v-if="data&&navigator.bounds&&navigator.series.length" :series="chartSeries" :unit="data.unit" :view="view" :bounds="navigator.bounds" :context-series="navigator.series" :timezone="data.timezone" :enabled="enabled" :state-at="stateAt" :loaded-window="data.window" :value-window="valueWindow" :window="window" @zoom="zoom" @commit="commit" @value-zoom="valueZoom" @reset-time="reset" @reset-values="resetValues" />
  <CollapsiblePanel :title="t('chart.details')" :storage-key="'chart-info:'+leagueId+':'+view" :initial-open="false" class="chart-info">
    <p v-if="valuation" class="footnote">{{ t('pricing.balanceNote') }}</p>
    <p class="footnote">{{ t('chart.note') }}</p><p class="footnote">{{ t('chart.interaction',{zone:data?.timezone??'UTC'}) }}</p>
    <p v-if="window&&data" class="footnote" data-testid="chart-window">{{ date(new Date(window.start).toISOString(),data.timezone) }} — {{ date(new Date(window.end).toISOString(),data.timezone) }} {{ data.timezone }}</p>
    <p v-if="data" class="footnote">{{ t(data.sampled?'chart.sampled':'chart.exact') }}</p>
    <p v-if="data?.series_truncated" role="alert">{{ t('chart.truncated') }}</p>
    <p v-if="data?.unresolved_events" class="footnote" data-testid="chart-unresolved">{{ t('chart.unresolved',{count:data.unresolved_events}) }}</p>
    <p v-if="data" class="footnote" data-testid="chart-totals">{{ t('chart.balanceTotal',{net:number(data.totals.net)}) }}</p>
    <details v-if="data" class="chart-data"><summary>{{ t('chart.data') }}</summary><div class="transactions-scroll" tabindex="0"><table class="transactions"><thead><tr><th>{{ t('chart.group') }}</th><th>{{ t('quantity.dateZone',{zone:data.timezone}) }}</th><th>{{ t('quantity.balance') }}</th></tr></thead><tbody><template v-for="series in chartSeries" :key="series.id"><tr v-for="(point,index) in series.points" :key="index"><td>{{ seriesLabel(series) }}</td><td>{{ date(new Date(point.timestamp).toISOString(),data.timezone) }}</td><td>{{ number(point.balance) }}</td></tr></template></tbody></table></div></details>
  </CollapsiblePanel>
</CollapsiblePanel></template>
