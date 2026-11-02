<script setup lang="ts">
import {computed,nextTick,onMounted,onUnmounted,ref,watch} from 'vue'
import * as echarts from 'echarts/core'
import {LineChart} from 'echarts/charts'
import {GridComponent,TooltipComponent,AriaComponent,MarkPointComponent} from 'echarts/components'
import {SVGRenderer} from 'echarts/renderers'
import type {EChartsOption} from 'echarts'
import type {BalanceSeries} from '../composables/useQuantitySeries'
import {t,number,locale,displayHourFormat} from '../i18n'
import {balanceColors} from '../chart-style'
import {clampWindow,clampValueRange,visiblePoints} from '../chart-window'
import type {ChartWindow} from '../chart-window'
import SeriesNavigator from './SeriesNavigator.vue'
import ValueNavigator from './ValueNavigator.vue'
import {axisDate,formatZonedDate} from '../timezones'
echarts.use([LineChart,GridComponent,TooltipComponent,AriaComponent,MarkPointComponent,SVGRenderer])
const props=defineProps<{series:BalanceSeries[];contextSeries:BalanceSeries[];view:string;bounds:{start:number;end:number};timezone:string;enabled:string[];window:{start:number;end:number}|null;loadedWindow:ChartWindow|null;valueWindow:ChartWindow|null}>()
const emit=defineEmits<{zoom:[window:{start:number;end:number}];commit:[window:ChartWindow];valueZoom:[window:ChartWindow]}>()
const root=ref<HTMLElement|null>(null)
let chart:echarts.ECharts|undefined,observer:ResizeObserver|undefined,wheelTimer:ReturnType<typeof setTimeout>|undefined
let lastWindow:ChartWindow|null=null
function update(value:ChartWindow){lastWindow=value;emit('zoom',value)}
const currentWindow=computed(()=>props.window??props.bounds)
const plottedSeries=computed(()=>props.series.filter(series=>props.enabled.includes(series.id)).map(series=>({...series,visible:visiblePoints(series.overview??series.points,series.points,props.loadedWindow,currentWindow.value)})))
function padded(min:number,max:number){const padding=Math.max(1,(max-min)*.05);return {start:Math.floor(min-padding),end:Math.ceil(max+padding)}}
const fullValueBounds=computed(()=>{let min=0,max=0;for(const series of props.contextSeries)for(const point of series.overview??series.points){min=Math.min(min,point.balance);max=Math.max(max,point.balance)}return padded(min,max)})
const autoValueWindow=computed(()=>{let min=0,max=0;for(const series of plottedSeries.value)for(const point of series.visible){min=Math.min(min,point.balance);max=Math.max(max,point.balance)}const range=padded(min,max);return {start:Math.max(fullValueBounds.value.start,range.start),end:Math.min(fullValueBounds.value.end,range.end)}})
const currentValueWindow=computed(()=>props.valueWindow&&props.valueWindow.start<fullValueBounds.value.end&&props.valueWindow.end>fullValueBounds.value.start?clampValueRange(props.valueWindow.start,props.valueWindow.end,fullValueBounds.value):autoValueWindow.value)
const label=(name:string)=>props.view==='summary'?t('chart.total'):name
function draw(){
  if(!root.value?.clientWidth||!root.value.clientHeight)return
  if(!chart)chart=echarts.init(root.value,undefined,{renderer:'svg'})
  const start=props.window?.start??props.bounds.start,end=props.window?.end??props.bounds.end,span=end-start
  const options:EChartsOption={
    animation:false,backgroundColor:'transparent',color:balanceColors,
    textStyle:{color:'#b7c4ca',fontFamily:'system-ui'},aria:{enabled:true,description:t('chart.graph')},
    grid:{left:65,right:20,top:18,bottom:35},
    tooltip:{trigger:'axis',renderMode:'richText',confine:true,valueFormatter:value=>number(Number(value)),axisPointer:{type:'cross',label:{formatter:params=>params.axisDimension==='x'?formatZonedDate(new Date(Number(params.value)).toISOString(),locale.value,props.timezone,{year:'numeric',month:'short',day:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit',fractionalSecondDigits:3},displayHourFormat.value):number(Number(params.value))}}},
    xAxis:{type:'time',min:start,max:end,splitNumber:Math.max(2,Math.min(8,Math.floor(root.value.clientWidth/140))),axisLabel:{color:'#b7c4ca',hideOverlap:true,formatter:value=>axisDate(value,props.timezone,locale.value,span,displayHourFormat.value)},axisLine:{lineStyle:{color:'#46545e'}}},
    yAxis:{type:'value',min:currentValueWindow.value.start,max:currentValueWindow.value.end,minInterval:1,axisLabel:{color:'#b7c4ca',formatter:value=>number(value)},splitLine:{lineStyle:{color:'#29363e'}}},
    series:plottedSeries.value.map(series=>({id:series.id,name:label(series.name),type:'line',step:'end',clip:true,showSymbol:series.visible.length<64,symbolSize:4,lineStyle:{width:2,color:balanceColors[props.contextSeries.findIndex(value=>value.id===series.id)%balanceColors.length]},itemStyle:{color:balanceColors[props.contextSeries.findIndex(value=>value.id===series.id)%balanceColors.length]},markPoint:{symbol:'circle',symbolSize:6,label:{show:false},data:[{name:'max',type:'max'},{name:'min',type:'min'}]},data:series.visible.map(point=>[point.timestamp,point.balance])})),
  }
  chart.setOption(options,{notMerge:true,silent:true});chart.resize();root.value.querySelector('svg')?.setAttribute('aria-hidden','true')
}
function inside(event:MouseEvent){
  const box=root.value!.getBoundingClientRect()
  return event.clientX>=box.left+65&&event.clientX<=box.right-20&&event.clientY>=box.top+18&&event.clientY<=box.bottom-35
}
function wheel(event:WheelEvent){
  if(!root.value||!inside(event))return
  event.preventDefault()
  const box=root.value.getBoundingClientRect(),ratio=Math.max(0,Math.min(1,(event.clientX-box.left-65)/(box.width-85)))
  const window=currentWindow.value,width=window.end-window.start
  const next=Math.max(1,Math.min(props.bounds.end-props.bounds.start,width*Math.exp(Math.max(-2,Math.min(2,event.deltaY*.002)))))
  const anchor=window.start+ratio*width
  const value=clampWindow(anchor-ratio*next,anchor+(1-ratio)*next,props.bounds)
  update(value);clearTimeout(wheelTimer);wheelTimer=setTimeout(()=>{if(currentWindow.value.start===value.start&&currentWindow.value.end===value.end)emit('commit',value)},250)
}
let drag:{x:number;window:ChartWindow}|null=null
function down(event:PointerEvent){
  if(event.button!==0||!root.value||!inside(event))return
  lastWindow=null;drag={x:event.clientX,window:{...currentWindow.value}};root.value.setPointerCapture(event.pointerId)
}
function move(event:PointerEvent){
  if(!drag||!root.value)return
  const delta=(event.clientX-drag.x)/(root.value.clientWidth-85)*(drag.window.end-drag.window.start)
  update(clampWindow(drag.window.start-delta,drag.window.end-delta,props.bounds))
}
function up(event:PointerEvent){if(drag&&lastWindow)emit('commit',lastWindow);drag=null;if(root.value?.hasPointerCapture(event.pointerId))root.value.releasePointerCapture(event.pointerId)}
function zoomIn(){const start=currentWindow.value.start,end=currentWindow.value.end,q=(end-start)/4;if(end-start>2){const value={start:Math.round(start+q),end:Math.round(end-q)};update(value);emit('commit',value)}}
function zoomValuesIn(){const range=currentValueWindow.value,q=(range.end-range.start)/4;emit('valueZoom',clampValueRange(range.start+q,range.end-q,fullValueBounds.value))}
defineExpose({zoomIn,zoomValuesIn})
watch(()=>[props.series,props.contextSeries,props.bounds,props.enabled,props.window,props.loadedWindow,props.timezone,props.view,props.valueWindow,locale.value,displayHourFormat.value],()=>{void nextTick(draw)},{deep:true})
onMounted(()=>{observer=new ResizeObserver(()=>{if(root.value?.clientWidth)draw()});if(root.value)observer.observe(root.value);draw()})
onUnmounted(()=>{clearTimeout(wheelTimer);observer?.disconnect();chart?.dispose()})
</script>
<template><div class="balance-chart"><div ref="root" class="time-series-chart" role="img" :aria-label="t('chart.graph')" data-testid="time-series-chart" :data-window-start="currentWindow.start" :data-window-end="currentWindow.end" :data-value-min="currentValueWindow.start" :data-value-max="currentValueWindow.end" @wheel="wheel" @pointerdown="down" @pointermove="move" @pointerup="up" @pointercancel="up"></div>
<ValueNavigator :series="contextSeries" :time-bounds="bounds" :bounds="fullValueBounds" :window="currentValueWindow" :enabled="enabled" @zoom="emit('valueZoom',$event)" />
<SeriesNavigator :series="contextSeries" :bounds="bounds" :window="currentWindow" :enabled="enabled" @zoom="emit('zoom',$event)" @commit="emit('commit',$event)" />
</div></template>
