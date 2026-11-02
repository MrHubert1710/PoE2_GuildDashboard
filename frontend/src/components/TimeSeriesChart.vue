<script setup lang="ts">
import {nextTick,onMounted,onUnmounted,ref,watch} from 'vue'
import * as echarts from 'echarts/core'
import {LineChart} from 'echarts/charts'
import {GridComponent,TooltipComponent,DataZoomComponent,AriaComponent,MarkPointComponent} from 'echarts/components'
import {SVGRenderer} from 'echarts/renderers'
import type {EChartsOption} from 'echarts'
import type {BalanceSeries} from '../composables/useQuantitySeries'
import {t,number,locale} from '../i18n'
import {balanceColors} from '../chart-style'
import {axisDate,formatZonedDate} from '../timezones'
echarts.use([LineChart,GridComponent,TooltipComponent,DataZoomComponent,AriaComponent,MarkPointComponent,SVGRenderer])
const props=defineProps<{series:BalanceSeries[];view:string;bounds:{start:number;end:number};timezone:string;enabled:string[];window:{start:number;end:number}|null}>()
const emit=defineEmits<{zoom:[window:{start:number;end:number}]}>()
const root=ref<HTMLElement|null>(null)
let chart:echarts.ECharts|undefined,observer:ResizeObserver|undefined
const label=(name:string)=>props.view==='summary'?t('chart.total'):name
function draw(){
  if(!root.value?.clientWidth||!root.value.clientHeight)return
  if(!chart){chart=echarts.init(root.value,undefined,{renderer:'svg'});chart.on('datazoom',()=>{
    const zoom=(chart!.getOption().dataZoom as Array<{start:number;end:number}>)[0]!
    const width=props.bounds.end-props.bounds.start
    emit('zoom',{start:Math.round(props.bounds.start+width*zoom.start/100),end:Math.round(props.bounds.start+width*zoom.end/100)})
  })}
  const start=props.window?.start??props.bounds.start,end=props.window?.end??props.bounds.end,span=end-start
  const options:EChartsOption={
    animation:false,backgroundColor:'transparent',color:balanceColors,
    textStyle:{color:'#b7c4ca',fontFamily:'system-ui'},aria:{enabled:true,description:t('chart.graph')},
    grid:{left:65,right:20,top:18,bottom:78},
    tooltip:{trigger:'axis',renderMode:'richText',confine:true,valueFormatter:value=>number(Number(value)),axisPointer:{type:'cross',label:{formatter:params=>params.axisDimension==='x'?formatZonedDate(new Date(Number(params.value)).toISOString(),locale.value,props.timezone,{year:'numeric',month:'short',day:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit',fractionalSecondDigits:3}):number(Number(params.value))}}},
    xAxis:{type:'time',min:props.bounds.start,max:props.bounds.end,splitNumber:Math.max(2,Math.min(8,Math.floor(root.value.clientWidth/140))),axisLabel:{color:'#b7c4ca',hideOverlap:true,formatter:value=>axisDate(value,props.timezone,locale.value,span)},axisLine:{lineStyle:{color:'#46545e'}}},
    yAxis:{type:'value',minInterval:1,axisLabel:{color:'#b7c4ca',formatter:value=>number(value)},splitLine:{lineStyle:{color:'#29363e'}}},
    dataZoom:[{type:'inside',startValue:start,endValue:end,filterMode:'none'},{type:'slider',startValue:start,endValue:end,bottom:12,height:24,showDetail:false,borderColor:'#46545e'}],
    series:props.series.filter(series=>props.enabled.includes(series.id)).map(series=>({id:series.id,name:label(series.name),type:'line',step:'end',showSymbol:series.points.length<64,symbolSize:4,lineStyle:{width:2,color:balanceColors[props.series.indexOf(series)%balanceColors.length]},itemStyle:{color:balanceColors[props.series.indexOf(series)%balanceColors.length]},markPoint:{symbol:'circle',symbolSize:6,label:{show:false},data:[{name:'max',type:'max'},{name:'min',type:'min'}]},data:series.points.map(point=>[point.timestamp,point.balance])})),
  }
  chart.setOption(options,{notMerge:true,silent:true});chart.resize();root.value.querySelector('svg')?.setAttribute('aria-hidden','true')
}
function zoomIn(){const start=props.window?.start??props.bounds.start,end=props.window?.end??props.bounds.end,q=(end-start)/4;if(end-start>2)emit('zoom',{start:Math.round(start+q),end:Math.round(end-q)})}
defineExpose({zoomIn})
watch(()=>[props.series,props.bounds,props.enabled,props.window,props.timezone,props.view,locale.value],()=>{void nextTick(draw)},{deep:true})
onMounted(()=>{observer=new ResizeObserver(()=>{if(root.value?.clientWidth)draw()});if(root.value)observer.observe(root.value);draw()})
onUnmounted(()=>{observer?.disconnect();chart?.dispose()})
</script>
<template><div ref="root" class="time-series-chart" role="img" :aria-label="t('chart.graph')" data-testid="time-series-chart"></div></template>
