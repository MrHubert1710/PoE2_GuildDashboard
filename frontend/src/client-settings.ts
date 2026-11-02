import { ref } from 'vue'
import { normalizeDisplayTimezone } from './timezones'

export const preferencesKey = 'path-of-accounting.preferences.v1'
export const defaultViews = ['summary','players','stashes','state','history','archives'] as const
export interface ClientPreferences {
  version: 1; language: string; timezone: string | null; hourFormat: 'auto'|'12'|'24'|null
  defaultView: string; panels: Record<string,boolean>; colors: Record<string,string>
}
export const storageAvailable = ref(true)
function object(value:unknown):Record<string,unknown> {return value!==null&&typeof value==='object'&&!Array.isArray(value)?value as Record<string,unknown>:{}}
function read(key:string):unknown {try{return JSON.parse(localStorage.getItem(key)??'null')}catch{try{localStorage.getItem(key)}catch{storageAvailable.value=false}return null}}
function clean(value:unknown):ClientPreferences {
  const input=object(value),panels=object(input.panels),colors=object(input.colors)
  let zone:string|null=null
  try{if(typeof input.timezone==='string')zone=normalizeDisplayTimezone(input.timezone)}catch{}
  return {version:1,language:typeof input.language==='string'&&/^[a-z-]{2,20}$/i.test(input.language)?input.language:'en',timezone:zone,
    hourFormat:['auto','12','24'].includes(String(input.hourFormat))?input.hourFormat as 'auto'|'12'|'24':null,
    defaultView:defaultViews.includes(input.defaultView as typeof defaultViews[number])?String(input.defaultView):'summary',
    panels:Object.fromEntries(Object.entries(panels).slice(0,500).filter(([key,item])=>key.length<=300&&typeof item==='boolean')) as Record<string,boolean>,
    colors:Object.fromEntries(Object.entries(colors).slice(0,1000).filter(([key,item])=>key.length<=300&&typeof item==='string'&&/^#[0-9a-f]{6}$/i.test(item))) as Record<string,string>}
}
function initial(){
  const saved=read(preferencesKey)
  if(object(saved).version===1)return clean(saved)
  let language='en';try{language=localStorage.getItem('poe2guild.language')??'en'}catch{storageAvailable.value=false}
  return clean({language,colors:read('poe2guild.chart-colors.v1')})
}
export const clientPreferences=ref<ClientPreferences>(initial())
export function saveClientPreferences(patch:Partial<ClientPreferences>){
  clientPreferences.value=clean({...clientPreferences.value,...patch,version:1})
  try{localStorage.setItem(preferencesKey,JSON.stringify(clientPreferences.value));storageAvailable.value=true}catch{storageAvailable.value=false}
}
export function initializeDisplayPreferences(zone:string,hour:string){
  if(clientPreferences.value.timezone===null||clientPreferences.value.hourFormat===null)
    saveClientPreferences({timezone:clientPreferences.value.timezone??zone,hourFormat:clientPreferences.value.hourFormat??(hour as 'auto'|'12'|'24')})
}
window.addEventListener('storage',event=>{if(event.key===preferencesKey)clientPreferences.value=clean(read(preferencesKey))})
