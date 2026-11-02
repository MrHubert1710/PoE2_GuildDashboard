<script setup lang="ts">
import {computed,onUnmounted,ref,watch} from 'vue'
import type {BalanceSeries} from '../composables/useQuantitySeries'
import {balanceColor} from '../chart-style'
import {clampWindow,navigatorDomain} from '../chart-window'
import type {ChartWindow} from '../chart-window'
import {t,date} from '../i18n'
const props=defineProps<{series:BalanceSeries[];bounds:ChartWindow;window:ChartWindow;enabled:string[]}>()
const emit=defineEmits<{zoom:[window:ChartWindow];commit:[window:ChartWindow];reset:[]}>()
const root=ref<SVGSVGElement|null>(null)
const width=1000,height=34
const domain=ref(navigatorDomain(props.window))
const span=computed(()=>domain.value.end-domain.value.start)
const left=computed(()=>(props.window.start-domain.value.start)/span.value*width)
const right=computed(()=>(props.window.end-domain.value.start)/span.value*width)
let frame:number|undefined
function stopAnimation(){if(frame!==undefined)cancelAnimationFrame(frame);frame=undefined}
function recenter(){
  stopAnimation()
  const target=navigatorDomain(props.window),initial={...domain.value}
  if(matchMedia('(prefers-reduced-motion: reduce)').matches){domain.value=target;return}
  if(initial.start===target.start&&initial.end===target.end)return
  const began=performance.now()
  function tick(now:number){
    const progress=Math.min(1,(now-began)/280),eased=1-Math.pow(1-progress,3)
    domain.value={start:initial.start+(target.start-initial.start)*eased,end:initial.end+(target.end-initial.end)*eased}
    if(progress<1)frame=requestAnimationFrame(tick)
    else{domain.value=target;frame=undefined}
  }
  frame=requestAnimationFrame(tick)
}
watch(()=>[props.window.start,props.window.end,props.bounds.start,props.bounds.end],()=>{if(!drag)recenter()})
onUnmounted(stopAnimation)
const scale=computed(()=>{
  let min=0,max=0
  for(const series of props.series)if(props.enabled.includes(series.id))for(const point of series.overview??series.points){min=Math.min(min,point.balance);max=Math.max(max,point.balance)}
  return {min,max:Math.max(min+1,max)}
})
function path(series:BalanceSeries){
  const points=series.overview??series.points
  return points.map((point,index)=>{
    const x=(point.timestamp-domain.value.start)/span.value*width
    const y=height-8-(point.balance-scale.value.min)/(scale.value.max-scale.value.min)*(height-16)
    return `${index===0?'M':'H'}${x}${index===0?',':'V'}${y}`
  }).join(' ')
}
let drag:{x:number;window:ChartWindow;kind:'move'|'start'|'end';span:number}|null=null
let lastWindow:ChartWindow|null=null
function update(value:ChartWindow){lastWindow=value;emit('zoom',value)}
function down(event:PointerEvent,kind:'move'|'start'|'end'){
  if(event.button!==0||!root.value)return
  event.preventDefault();stopAnimation();lastWindow=null;drag={x:event.clientX,window:{...props.window},kind,span:span.value};root.value.setPointerCapture(event.pointerId)
}
function move(event:PointerEvent){
  if(!drag||!root.value)return
  const delta=(event.clientX-drag.x)/root.value.getBoundingClientRect().width*drag.span
  if(drag.kind==='move')update(clampWindow(drag.window.start+delta,drag.window.end+delta,props.bounds))
  else if(drag.kind==='start')update({start:Math.round(Math.max(props.bounds.start,Math.min(drag.window.end-1,drag.window.start+delta))),end:drag.window.end})
  else update({start:drag.window.start,end:Math.round(Math.min(props.bounds.end,Math.max(drag.window.start+1,drag.window.end+delta)))})
}
function up(event:PointerEvent){if(drag&&lastWindow)emit('commit',lastWindow);drag=null;recenter();if(root.value?.hasPointerCapture(event.pointerId))root.value.releasePointerCapture(event.pointerId)}
function key(event:KeyboardEvent,kind:'move'|'start'|'end'){
  if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return
  event.preventDefault()
  const delta=(props.window.end-props.window.start)/.3*(event.shiftKey ? .1 : .01)*(event.key==='ArrowLeft'?-1:1)
  if(event.key==='Home'||event.key==='End')update(clampWindow(event.key==='Home'?props.bounds.start:props.bounds.end-(props.window.end-props.window.start),event.key==='Home'?props.bounds.start+(props.window.end-props.window.start):props.bounds.end,props.bounds))
  else if(kind==='move')update(clampWindow(props.window.start+delta,props.window.end+delta,props.bounds))
  else if(kind==='start')update({start:Math.round(Math.max(props.bounds.start,Math.min(props.window.end-1,props.window.start+delta))),end:props.window.end})
  else update({start:props.window.start,end:Math.round(Math.min(props.bounds.end,Math.max(props.window.start+1,props.window.end+delta)))})
  if(lastWindow)emit('commit',lastWindow)
}
</script>
<template><div class="series-navigator" data-testid="series-navigator" :data-display-start="domain.start" :data-display-end="domain.end" :data-domain-start="bounds.start" :data-domain-end="bounds.end" :data-window-start="window.start" :data-window-end="window.end">
  <svg role="group" :aria-label="t('chart.navigator')" ref="root" :viewBox="`0 0 ${width} ${height}`" preserveAspectRatio="none" @dblclick.prevent.stop="emit('reset')" @pointermove="move" @pointerup="up" @pointercancel="up">
    <rect :width="width" :height="height" class="navigator-background" />
    <path v-for="(series,index) in series" :key="series.id" :d="path(series)" :stroke="balanceColor(series,index)" :stroke-dasharray="series.aggregate?'4 3':undefined" :opacity="enabled.includes(series.id)?'.65':'0'" fill="none" stroke-width="1" vector-effect="non-scaling-stroke" data-testid="navigator-series" />
    <rect x="0" :width="Math.max(0,left)" :height="height" class="navigator-mask" />
    <rect :x="right" :width="Math.max(0,width-right)" :height="height" class="navigator-mask" />
    <rect :x="left" :width="Math.max(1,right-left)" y="1" :height="height-2" class="navigator-window" role="slider" tabindex="0" :aria-label="t('chart.navigator')" :aria-valuemin="bounds.start" :aria-valuemax="bounds.end" :aria-valuenow="window.start" :aria-valuetext="date(new Date(window.start).toISOString())+' — '+date(new Date(window.end).toISOString())" @pointerdown="down($event,'move')" @keydown="key($event,'move')" data-testid="navigator-window" />
    <rect :x="Math.max(0,Math.min(width-8,left-4))" y="1" width="8" :height="height-2" class="navigator-handle" role="slider" tabindex="0" :aria-label="t('chart.navigatorStart')" :aria-valuemin="bounds.start" :aria-valuemax="window.end-1" :aria-valuenow="window.start" @pointerdown="down($event,'start')" @keydown="key($event,'start')" />
    <rect :x="Math.max(0,Math.min(width-8,right-4))" y="1" width="8" :height="height-2" class="navigator-handle" role="slider" tabindex="0" :aria-label="t('chart.navigatorEnd')" :aria-valuemin="window.start+1" :aria-valuemax="bounds.end" :aria-valuenow="window.end" @pointerdown="down($event,'end')" @keydown="key($event,'end')" />
  </svg>
</div></template>
