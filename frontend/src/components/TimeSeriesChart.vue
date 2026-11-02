<script setup lang="ts">
import {computed,nextTick,onMounted,onUnmounted,ref,watch} from 'vue'
import * as echarts from 'echarts/core'
import {LineChart} from 'echarts/charts'
import {GridComponent,AriaComponent,MarkLineComponent} from 'echarts/components'
import {SVGRenderer} from 'echarts/renderers'
import type {EChartsOption} from 'echarts'
import type {BalanceSeries,CursorState} from '../composables/useQuantitySeries'
import {t,number,locale,displayHourFormat} from '../i18n'
import {balanceColors,balanceColor} from '../chart-style'
import {clampValueRange,visiblePoints} from '../chart-window'
import type {ChartWindow} from '../chart-window'
import SeriesNavigator from './SeriesNavigator.vue'
import ValueNavigator from './ValueNavigator.vue'
import {axisDate,formatZonedDate} from '../timezones'
echarts.use([LineChart,GridComponent,AriaComponent,MarkLineComponent,SVGRenderer])
const props=defineProps<{unit?:string;series:BalanceSeries[];contextSeries:BalanceSeries[];view:string;bounds:{start:number;end:number};timezone:string;enabled:string[];window:{start:number;end:number}|null;loadedWindow:ChartWindow|null;valueWindow:ChartWindow|null;stateAt:(timestamp:number)=>Promise<CursorState>}>()
const emit=defineEmits<{zoom:[window:{start:number;end:number}];commit:[window:ChartWindow];valueZoom:[window:ChartWindow];resetTime:[];resetValues:[]}>()
const root=ref<HTMLElement|null>(null)
let chart:echarts.ECharts|undefined,observer:ResizeObserver|undefined,hoverTimer:ReturnType<typeof setTimeout>|undefined
const hover=ref<{timestamp:number;x:number;left:number;top:number}|null>(null),cursorState=ref<CursorState|null>(null),cursorError=ref('')
let hoverSequence=0
const cursorRows=computed(()=>{const values=new Map(cursorState.value?.balances.map(row=>[row.id,row.balance])??[]);return plottedSeries.value.map(series=>({id:series.id,name:label(series),color:balanceColor(series,props.contextSeries.findIndex(value=>value.id===series.id)),balance:values.get(series.id)??0}))})
function leave(){++hoverSequence;clearTimeout(hoverTimer);hover.value=null;cursorState.value=null;cursorError.value=''}
function move(event:PointerEvent){
  if(!root.value||!inside(event)){leave();return}
  const box=root.value.getBoundingClientRect(),x=event.clientX-box.left
  const timestamp=Math.round(currentWindow.value.start+(x-65)/(box.width-85)*(currentWindow.value.end-currentWindow.value.start))
  const current=++hoverSequence;clearTimeout(hoverTimer);cursorState.value=null;cursorError.value=''
  hover.value={timestamp,x,left:Math.max(8,Math.min(innerWidth-310,event.clientX+16)),top:Math.max(8,Math.min(innerHeight-190,event.clientY+16))}
  hoverTimer=setTimeout(()=>{void props.stateAt(timestamp).then(value=>{if(current===hoverSequence)cursorState.value=value}).catch(()=>{if(current===hoverSequence)cursorError.value='report_unavailable'})},90)
}
const currentWindow=computed(()=>props.window??props.bounds)
const plottedSeries=computed(()=>props.series.filter(series=>props.enabled.includes(series.id)).map(series=>({...series,visible:visiblePoints(series.overview??series.points,series.points,props.loadedWindow,currentWindow.value)})))
const actualExtrema=computed(()=>{
  let min=Infinity,max=-Infinity
  for(const series of plottedSeries.value)for(const point of series.visible){min=Math.min(min,point.balance);max=Math.max(max,point.balance)}
  return Number.isFinite(min)?{min,max}:null
})
function padded(min:number,max:number){const padding=Math.max(1,(max-min)*.05);return {start:Math.floor(min-padding),end:Math.ceil(max+padding)}}
const fullValueBounds=computed(()=>{let min=0,max=0;for(const series of props.contextSeries)for(const point of series.overview??series.points){min=Math.min(min,point.balance);max=Math.max(max,point.balance)}return padded(min,max)})
const autoValueWindow=computed(()=>{let min=0,max=0;for(const series of plottedSeries.value)for(const point of series.visible){min=Math.min(min,point.balance);max=Math.max(max,point.balance)}const range=padded(min,max);return {start:Math.max(fullValueBounds.value.start,range.start),end:Math.min(fullValueBounds.value.end,range.end)}})
const currentValueWindow=computed(()=>props.valueWindow&&props.valueWindow.start<fullValueBounds.value.end&&props.valueWindow.end>fullValueBounds.value.start?clampValueRange(props.valueWindow.start,props.valueWindow.end,fullValueBounds.value):autoValueWindow.value)
const label=(series:BalanceSeries)=>props.view==='summary'?t('chart.total'):series.aggregate?t('chart.combined'):series.reconstruction?t('quantity.reconstruction'):series.name
function draw(){
  if(!root.value?.clientWidth||!root.value.clientHeight)return
  if(!chart)chart=echarts.init(root.value,undefined,{renderer:'svg'})
  const start=props.window?.start??props.bounds.start,end=props.window?.end??props.bounds.end,span=end-start
  const markerValues=actualExtrema.value?[...new Set([actualExtrema.value.min,actualExtrema.value.max])].filter(value=>value>=currentValueWindow.value.start&&value<=currentValueWindow.value.end):[]
  const labelSpacing=(currentValueWindow.value.end-currentValueWindow.value.start)*16/Math.max(1,root.value.clientHeight-53)
  const crowded=markerValues.length===2&&Math.abs(markerValues[1]!-markerValues[0]!)<labelSpacing
  const axisNumber=(value:number)=>props.unit==='divine_orb'?new Intl.NumberFormat(locale.value,{maximumSignificantDigits:6}).format(value):number(value)
  const options:EChartsOption={
    animation:false,backgroundColor:'transparent',color:balanceColors,
    textStyle:{color:'#b7c4ca',fontFamily:'system-ui'},aria:{enabled:true,description:t('chart.graph')},
    grid:{left:props.unit==='divine_orb'?88:65,right:20,top:18,bottom:35},

    xAxis:{type:'time',min:start,max:end,splitNumber:Math.max(2,Math.min(8,Math.floor(root.value.clientWidth/140))),axisLabel:{color:'#b7c4ca',hideOverlap:true,formatter:value=>axisDate(value,props.timezone,locale.value,span,displayHourFormat.value)},axisLine:{lineStyle:{color:'#46545e'}}},
    yAxis:{type:'value',min:currentValueWindow.value.start,max:currentValueWindow.value.end,minInterval:props.unit==='divine_orb'?0:1,axisLabel:{color:'#b7c4ca',showMinLabel:Boolean(props.valueWindow),showMaxLabel:Boolean(props.valueWindow),formatter:value=>markerValues.some(marker=>Math.abs(marker-value)<labelSpacing)?'':axisNumber(value)},splitLine:{showMinLine:false,showMaxLine:false,lineStyle:{color:'#29363e'}}},
    series:plottedSeries.value.map((series,index)=>({id:series.id,name:label(series),type:'line',step:'end',clip:true,showSymbol:false,symbol:'none',lineStyle:{width:series.aggregate?2.5:2,type:series.aggregate?'dashed':series.reconstruction?'dotted':'solid',color:balanceColor(series,props.contextSeries.findIndex(value=>value.id===series.id))},itemStyle:{color:balanceColor(series,props.contextSeries.findIndex(value=>value.id===series.id))},markLine:index===0?{silent:true,animation:false,symbol:['none','none'],lineStyle:{color:'#a9bfb1',width:1,type:'solid'},label:{show:true,position:'start',align:'right',color:'#d8eadd',fontSize:11,padding:[2,4],backgroundColor:'#182128'},data:markerValues.map((value,markerIndex)=>({yAxis:value,label:{formatter:()=>axisNumber(value),offset:crowded?[0,markerIndex===0?8:-8]:[0,0]}}))}:undefined,data:series.visible.map(point=>[point.timestamp,point.balance])})),
  }
  chart.setOption(options,{notMerge:true,silent:true});chart.resize();root.value.querySelector('svg')?.setAttribute('aria-hidden','true')
}
function inside(event:MouseEvent){
  const box=root.value!.getBoundingClientRect()
  return event.clientX>=box.left+65&&event.clientX<=box.right-20&&event.clientY>=box.top+18&&event.clientY<=box.bottom-35
}
watch(()=>[props.series,props.contextSeries,props.bounds,props.enabled,props.window,props.loadedWindow,props.timezone,props.view,props.valueWindow,locale.value,displayHourFormat.value],()=>{leave();void nextTick(draw)},{deep:true})
onMounted(()=>{observer=new ResizeObserver(()=>{if(root.value?.clientWidth)draw()});if(root.value)observer.observe(root.value);draw()})
onUnmounted(()=>{leave();observer?.disconnect();chart?.dispose()})
</script>
<template><div class="balance-chart"><div ref="root" class="time-series-chart" role="img" :aria-label="t('chart.graph')" data-testid="time-series-chart" :data-window-start="currentWindow.start" :data-window-end="currentWindow.end" :data-actual-min="actualExtrema?.min" :data-actual-max="actualExtrema?.max" :data-value-min="currentValueWindow.start" :data-value-max="currentValueWindow.end" @pointermove="move" @pointerleave="leave"></div>
<div v-if="hover" class="chart-hover-cursor" :style="{left:hover.x+'px'}" aria-hidden="true"></div>
<div v-if="hover" role="tooltip" class="chart-tooltip" :style="{left:hover.left+'px',top:hover.top+'px'}" :data-state-at="hover.timestamp">
  <p>{{ formatZonedDate(new Date(hover.timestamp).toISOString(),locale,timezone,{year:'numeric',month:'short',day:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit',fractionalSecondDigits:3},displayHourFormat) }}</p>
  <p v-if="cursorError">{{ t('quantity.error.'+cursorError) }}</p><p v-else-if="!cursorState" role="status">{{ t('chart.loading') }}</p>
  <div v-else v-for="row in cursorRows" :key="row.id" class="chart-tooltip-row" :data-series-id="row.id"><i :style="{background:row.color}"></i><span>{{ row.name }}</span><strong>{{ number(row.balance) }}</strong></div>
</div>
<ValueNavigator :series="contextSeries" :enabled="enabled" :bounds="fullValueBounds" :window="currentValueWindow" @zoom="emit('valueZoom',$event)" @reset="emit('resetValues')" />
<SeriesNavigator :series="contextSeries" :bounds="bounds" :window="currentWindow" :enabled="enabled" @zoom="emit('zoom',$event)" @commit="emit('commit',$event)" @reset="emit('resetTime')" />
</div></template>
