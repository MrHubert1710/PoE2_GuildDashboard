<script setup lang="ts">
import { ref, watch } from 'vue'
const props=withDefaults(defineProps<{title:string;storageKey:string;initialOpen?:boolean}>(),{initialOpen:true})
const cacheKey=()=>`poe2guild.panel.${props.storageKey}`
function read(){try{const value=sessionStorage.getItem(cacheKey());return value===null?props.initialOpen:value==='1'}catch{return props.initialOpen}}
const open=ref(read())
watch(()=>props.storageKey,()=>{open.value=read()})
function changed(event:Event){open.value=(event.target as HTMLDetailsElement).open;try{sessionStorage.setItem(cacheKey(),open.value?'1':'0')}catch{}}
</script>
<template><details class="collapsible-panel" :open="open" @toggle="changed"><summary><span>{{ title }}</span><span class="panel-actions" @click.stop><slot name="actions" /></span></summary><div class="panel-body"><slot /></div></details></template>
