<script setup lang="ts">
import {computed,ref,watch} from 'vue'
import {hexToHsv,hsvToHex} from '../colors'
import {t} from '../i18n'
const props=defineProps<{name:string;value:string;left:number;top:number}>()
const emit=defineEmits<{change:[value:string];close:[]}>()
const hsv=ref(hexToHsv(props.value)),hex=ref(props.value),wheel=ref<HTMLElement|null>(null)
watch(()=>props.value,value=>{if(value.toLowerCase()!==hsvToHex(hsv.value))hsv.value=hexToHsv(value);hex.value=value})
function publish(){hex.value=hsvToHex(hsv.value);emit('change',hex.value)}
function inputHex(value:string){hex.value=value;if(/^#[0-9a-f]{6}$/i.test(value)){hsv.value=hexToHsv(value);emit('change',value)}}
function pick(event:PointerEvent){
  if(!wheel.value)return
  const box=wheel.value.getBoundingClientRect(),x=(event.clientX-box.left)/box.width*2-1,y=(event.clientY-box.top)/box.height*2-1
  hsv.value={...hsv.value,h:(Math.atan2(y,x)*180/Math.PI+360)%360,s:Math.min(1,Math.hypot(x,y))};publish()
}
function down(event:PointerEvent){if(event.button!==0)return;event.preventDefault();wheel.value?.focus();wheel.value?.setPointerCapture(event.pointerId);pick(event)}
function move(event:PointerEvent){if(wheel.value?.hasPointerCapture(event.pointerId))pick(event)}
function up(event:PointerEvent){if(wheel.value?.hasPointerCapture(event.pointerId))wheel.value.releasePointerCapture(event.pointerId)}
function key(event:KeyboardEvent){
  const step=event.shiftKey?10:1
  if(event.key==='ArrowLeft'||event.key==='ArrowRight')hsv.value.h=(hsv.value.h+(event.key==='ArrowRight'?step:-step)+360)%360
  else if(event.key==='ArrowUp'||event.key==='ArrowDown')hsv.value.s=Math.max(0,Math.min(1,hsv.value.s+(event.key==='ArrowUp'?step:-step)/100))
  else if(event.key==='Home')hsv.value.h=0
  else if(event.key==='End')hsv.value.h=359
  else return
  event.preventDefault();publish()
}
const thumb=computed(()=>({left:50+Math.cos(hsv.value.h*Math.PI/180)*hsv.value.s*50+'%',top:50+Math.sin(hsv.value.h*Math.PI/180)*hsv.value.s*50+'%'}))
const saturationTrack=computed(()=>`linear-gradient(to right,${hsvToHex({...hsv.value,s:0})},${hsvToHex({...hsv.value,s:1})})`)
const brightnessTrack=computed(()=>`linear-gradient(to right,#000,${hsvToHex({...hsv.value,v:1})})`)
</script>
<template><div role="dialog" :aria-label="t('chart.colorFor',{name})" class="chart-color-popup" :style="{left:left+'px',top:top+'px'}" @keydown.esc="emit('close')">
  <h3>{{ name }}</h3>
  <div ref="wheel" class="color-wheel" role="slider" tabindex="0" :aria-label="t('chart.colorWheel')" aria-valuemin="0" aria-valuemax="359" :aria-valuenow="Math.round(hsv.h)%360" :aria-valuetext="t('chart.wheelState',{hue:Math.round(hsv.h),saturation:Math.round(hsv.s*100)})" @pointerdown="down" @pointermove="move" @pointerup="up" @pointercancel="up" @keydown="key"><span class="color-wheel-thumb" :style="thumb"></span></div>
  <label>{{ t('chart.saturation') }} · {{ Math.round(hsv.s*100) }}%<input type="range" min="0" max="100" :value="hsv.s*100" :aria-label="t('chart.saturation')" :style="{background:saturationTrack}" @input="hsv.s=Number(($event.target as HTMLInputElement).value)/100;publish()" /></label>
  <label>{{ t('chart.brightness') }} · {{ Math.round(hsv.v*100) }}%<input type="range" min="0" max="100" :value="hsv.v*100" :aria-label="t('chart.brightness')" :style="{background:brightnessTrack}" @input="hsv.v=Number(($event.target as HTMLInputElement).value)/100;publish()" /></label>
  <label>{{ t('chart.seriesColor') }}<span class="color-hex"><i :style="{background:hsvToHex(hsv)}"></i><input :value="hex" :aria-label="t('chart.seriesColor')" maxlength="7" spellcheck="false" @input="inputHex(($event.target as HTMLInputElement).value)" /></span></label>
  <button type="button" @click="emit('close')">{{ t('chart.closeColor') }}</button>
</div></template>
