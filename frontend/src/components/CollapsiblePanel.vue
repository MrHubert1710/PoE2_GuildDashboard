<script setup lang="ts">
import { clientPreferences, saveClientPreferences } from '../client-settings'
import { ref, watch } from 'vue'
const props=withDefaults(defineProps<{title:string;storageKey:string;initialOpen?:boolean}>(),{initialOpen:true})
const cacheKey=()=>`poe2guild.panel.${props.storageKey}`
function read(){if(Object.hasOwn(clientPreferences.value.panels,props.storageKey))return clientPreferences.value.panels[props.storageKey]!;try{const value=sessionStorage.getItem(cacheKey());return value===null?props.initialOpen:value==='1'}catch{return props.initialOpen}}
const open=ref(read())
watch(()=>props.storageKey,()=>{open.value=read()})
function toggle(){open.value=!open.value;saveClientPreferences({panels:{...clientPreferences.value.panels,[props.storageKey]:open.value}})}
function changed(event:Event){const value=(event.target as HTMLDetailsElement).open;if(value===open.value)return;open.value=value;saveClientPreferences({panels:{...clientPreferences.value.panels,[props.storageKey]:value}})}
</script>
<template><details class="collapsible-panel" :open="open" @toggle="changed"><summary @click.prevent="toggle"><span>{{ title }}</span><span class="panel-actions" @click.stop><slot name="actions" /></span></summary><div class="panel-body"><slot /></div></details></template>
