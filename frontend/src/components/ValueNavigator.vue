<script setup lang="ts">
import {computed,ref} from 'vue'
import type {ChartWindow} from '../chart-window'
import {clampValueRange} from '../chart-window'
import {t,number} from '../i18n'
const props=defineProps<{bounds:ChartWindow;window:ChartWindow}>()
const emit=defineEmits<{zoom:[window:ChartWindow]}>()
const root=ref<SVGSVGElement|null>(null)
const height=300,width=34,padding=8
const trackHeight=height-2*padding
const span=computed(()=>props.bounds.end-props.bounds.start)
const top=computed(()=>(props.bounds.end-props.window.end)/span.value*trackHeight+padding)
const bottom=computed(()=>(props.bounds.end-props.window.start)/span.value*trackHeight+padding)
let drag:{y:number;window:ChartWindow;kind:'move'|'min'|'max'}|null=null
function down(event:PointerEvent,kind:'move'|'min'|'max'){
  if(event.button!==0||!root.value)return
  event.preventDefault();drag={y:event.clientY,window:{...props.window},kind};root.value.setPointerCapture(event.pointerId)
}
function resize(kind:'move'|'min'|'max',window:ChartWindow,delta:number){
  if(kind==='move')emit('zoom',clampValueRange(window.start+delta,window.end+delta,props.bounds))
  else if(kind==='min')emit('zoom',{start:Math.max(props.bounds.start,Math.min(window.end-1,window.start+delta)),end:window.end})
  else emit('zoom',{start:window.start,end:Math.min(props.bounds.end,Math.max(window.start+1,window.end+delta))})
}
function move(event:PointerEvent){if(drag&&root.value)resize(drag.kind,drag.window,-(event.clientY-drag.y)/root.value.getBoundingClientRect().height*(height/trackHeight)*span.value)}
function up(event:PointerEvent){drag=null;if(root.value?.hasPointerCapture(event.pointerId))root.value.releasePointerCapture(event.pointerId)}
function key(event:KeyboardEvent,kind:'move'|'min'|'max'){
  if(!['ArrowUp','ArrowDown','Home','End'].includes(event.key))return
  event.preventDefault()
  if(event.key==='Home'||event.key==='End'){
    const range=props.window.end-props.window.start
    emit('zoom',event.key==='Home'?{start:props.bounds.end-range,end:props.bounds.end}:{start:props.bounds.start,end:props.bounds.start+range})
  }else resize(kind,props.window,span.value*(event.shiftKey ? .1 : .01)*(event.key==='ArrowUp'?1:-1))
}
</script>
<template><div class="value-navigator" data-testid="value-navigator" :data-domain-min="bounds.start" :data-domain-max="bounds.end" :data-value-min="window.start" :data-value-max="window.end">
  <svg ref="root" role="group" :aria-label="t('chart.valueNavigator')" :viewBox="`0 0 ${width} ${height}`" preserveAspectRatio="none" @pointermove="move" @pointerup="up" @pointercancel="up">
    <path :d="`M8,${padding} H26 M17,${padding} V${height-padding} M8,${height-padding} H26`" class="value-range-track" vector-effect="non-scaling-stroke" aria-hidden="true" />
    <path :d="`M8,${top} H26 M17,${top} V${bottom} M8,${bottom} H26`" class="value-range-selection" vector-effect="non-scaling-stroke" aria-hidden="true" data-testid="value-range-beam" />
    <rect x="1" :y="top" :width="width-2" :height="Math.max(1,bottom-top)" class="navigator-value-window" tabindex="0" role="slider" :aria-label="t('chart.valueNavigator')" :aria-valuemin="bounds.start" :aria-valuemax="bounds.end" :aria-valuenow="window.start" :aria-valuetext="number(window.start)+' — '+number(window.end)" @pointerdown="down($event,'move')" @keydown="key($event,'move')" />
    <rect x="1" :y="top-6" :width="width-2" height="12" class="navigator-value-handle" tabindex="0" role="slider" :aria-label="t('chart.valueMax')" :aria-valuemin="window.start+1" :aria-valuemax="bounds.end" :aria-valuenow="window.end" @pointerdown="down($event,'max')" @keydown="key($event,'max')" />
    <rect x="1" :y="bottom-6" :width="width-2" height="12" class="navigator-value-handle" tabindex="0" role="slider" :aria-label="t('chart.valueMin')" :aria-valuemin="bounds.start" :aria-valuemax="window.end-1" :aria-valuenow="window.start" @pointerdown="down($event,'min')" @keydown="key($event,'min')" />
  </svg>
</div></template>
