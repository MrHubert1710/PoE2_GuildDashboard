<script setup lang="ts">
import {computed,defineAsyncComponent,ref} from 'vue'
import type {HistoryQuery} from '../browsing'
import {currentUrl,updateUrl} from '../navigation'
import {useQuantitySeries} from '../composables/useQuantitySeries'
import {t,date,number} from '../i18n'
import {balanceColors} from '../chart-style'
import {localDay} from '../timezones'
import CollapsiblePanel from './CollapsiblePanel.vue'
const TimeSeriesChart=defineAsyncComponent(()=>import('./TimeSeriesChart.vue'))
const props=defineProps<{leagueId:string;revision:string;settingsHash?:string;projectionId:string|null;query:HistoryQuery;active:boolean;refreshToken:number;view:string}>()
const emit=defineEmits<{range:[from:string,to:string]}>()
const {data,error,loading,selectedItem,chooseItem,reload}=useQuantitySeries(props)
const graph=ref<InstanceType<typeof import('./TimeSeriesChart.vue')['default']>>()
const enabled=computed(()=>{
  const all=data.value?.series.map(series=>series.id)??[],value=new URL(currentUrl.value).searchParams.get('chart_series')
  if(value===null)return all
  const selected=value.split(',').filter(id=>all.includes(id))
  return value&&!selected.length?all:selected
})
const window=computed(()=>{
  if(!data.value?.bounds)return null
  const p=new URL(currentUrl.value).searchParams,from=Number(p.get('chart_from')),to=Number(p.get('chart_to'))
  if(!p.has('chart_from')||!Number.isSafeInteger(from)||!Number.isSafeInteger(to)||from>=to)return null
  const start=Math.max(from,data.value.bounds.start),end=Math.min(to,data.value.bounds.end)
  return start<end?{start,end}:null
})
const items=computed(()=>[...new Set([data.value?.item,selectedItem.value,...(data.value?.items??[])].filter((value):value is string=>Boolean(value)))])
function toggle(id:string,checked:boolean){const values=new Set(enabled.value);if(checked)values.add(id);else values.delete(id);const url=new URL(currentUrl.value);url.searchParams.set('chart_series',[...values].join(','));updateUrl(url,true)}
function zoom(value:{start:number;end:number}){if(value.start>=value.end)return;const url=new URL(currentUrl.value);url.searchParams.set('chart_from',String(value.start));url.searchParams.set('chart_to',String(value.end));updateUrl(url,true)}
function reset(){const url=new URL(currentUrl.value);url.searchParams.delete('chart_from');url.searchParams.delete('chart_to');updateUrl(url,true)}
function applyRange(){if(window.value&&data.value)emit('range',localDay(window.value.start,data.value.timezone),localDay(Math.max(window.value.start,window.value.end-1),data.value.timezone))}
</script>
<template><CollapsiblePanel :title="t('chart.title')" :storage-key="'chart:'+leagueId+':'+view" class="quantity-chart" data-testid="quantity-chart">
  <div class="chart-controls">
    <label class="chart-item"><span>{{ t('chart.item') }}</span><select :aria-label="t('chart.item')" :value="data?.item??selectedItem" :disabled="!items.length" @change="chooseItem(($event.target as HTMLSelectElement).value)"><option v-for="item in items" :key="item" :value="item">{{ item }}</option></select></label>
    <details v-if="data&&data.series.length>1" class="chart-series-picker"><summary>{{ t('chart.groups',{count:data.series.length}) }}</summary><div><label v-for="(series,index) in data.series" :key="series.id" class="check-label"><input type="checkbox" :checked="enabled.includes(series.id)" @change="toggle(series.id,($event.target as HTMLInputElement).checked)" /><i class="series-swatch" :style="{background:balanceColors[index%balanceColors.length]}" aria-hidden="true"></i>{{ series.name }}</label></div></details>
    <button type="button" :disabled="!data?.bounds" @click="graph?.zoomIn()">{{ t('chart.zoom') }}</button><button type="button" @click="reset">{{ t('chart.reset') }}</button><button type="button" :disabled="!window" @click="applyRange">{{ t('chart.apply') }}</button>
    <button type="button" :disabled="loading||!projectionId" @click="reload">{{ t('chart.refresh') }}</button>
    <span v-if="loading" role="status" class="chart-loading">{{ t('chart.loading') }}</span>
  </div>
  <p v-if="error" role="alert">{{ t(`quantity.error.${error}`) }}</p>
  <p v-else-if="!projectionId" role="status">{{ t('quantity.pending') }}</p>
  <p v-else-if="!loading&&!data?.series.length" class="empty-state">{{ t('chart.empty') }}</p>
  <TimeSeriesChart v-if="data?.bounds&&data.series.length" ref="graph" :series="data.series" :view="view" :bounds="data.bounds" :timezone="data.timezone" :enabled="enabled" :window="window" @zoom="zoom" />
  <CollapsiblePanel :title="t('chart.details')" :storage-key="'chart-info:'+leagueId+':'+view" :initial-open="false" class="chart-info">
    <p class="footnote">{{ t('chart.note') }}</p><p class="footnote">{{ t('chart.interaction',{zone:data?.timezone??'UTC'}) }}</p>
    <p v-if="window&&data" class="footnote" data-testid="chart-window">{{ date(new Date(window.start).toISOString(),data.timezone) }} — {{ date(new Date(window.end).toISOString(),data.timezone) }} {{ data.timezone }}</p>
    <p v-if="data" class="footnote">{{ t(data.sampled?'chart.sampled':'chart.exact') }}</p>
    <p v-if="data?.series_truncated" role="alert">{{ t('chart.truncated') }}</p>
    <p v-if="data?.unresolved_events" class="footnote" data-testid="chart-unresolved">{{ t('chart.unresolved',{count:data.unresolved_events}) }}</p>
    <p v-if="data" class="footnote" data-testid="chart-totals">{{ t('chart.balanceTotal',{net:number(data.totals.net)}) }}</p>
    <details v-if="data" class="chart-data"><summary>{{ t('chart.data') }}</summary><div class="transactions-scroll" tabindex="0"><table class="transactions"><thead><tr><th>{{ t('chart.group') }}</th><th>{{ t('quantity.dateZone',{zone:data.timezone}) }}</th><th>{{ t('quantity.balance') }}</th></tr></thead><tbody><template v-for="series in data.series" :key="series.id"><tr v-for="(point,index) in series.points" :key="index"><td>{{ view==='summary'?t('chart.total'):series.name }}</td><td>{{ date(new Date(point.timestamp).toISOString(),data.timezone) }}</td><td>{{ number(point.balance) }}</td></tr></template></tbody></table></div></details>
  </CollapsiblePanel>
</CollapsiblePanel></template>
