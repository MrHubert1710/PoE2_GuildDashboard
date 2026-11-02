import { computed, onUnmounted, ref, watch } from 'vue'
import type { HistoryQuery } from '../browsing'
import { currentUrl, updateUrl } from '../navigation'
import { useApiRequest } from './useApiRequest'
export interface BalancePoint { timestamp:number; balance:number }
export interface BalanceSeries {id:string;name:string;opening_balance:number;closing_balance:number;event_count:number;point_count:number;points:BalancePoint[];overview:BalancePoint[]}
export interface SeriesData {
  league_id:string;projection:{id:string|null;state:string};timezone:string;view:string;unit:string
  unresolved_events:number;item:string|null;items:string[];series:BalanceSeries[];resolution_ms:number|null
  sampled:boolean;series_truncated:boolean;bounds:{start:number;end:number}|null;window:{start:number;end:number}|null
  totals:{added:number;removed:number;net:number;inferred:number}
}
export function useQuantitySeries(props:{leagueId:string;revision:string;settingsHash?:string;projectionId:string|null;query:HistoryQuery;active:boolean;refreshToken:number;view:string}){
  const data=ref<SeriesData|null>(null),error=ref(''),loading=ref(false)
  const selectedItem=computed(()=>new URL(currentUrl.value).searchParams.get('chart_item')??'')
  const viewport=computed(()=>{const p=new URL(currentUrl.value).searchParams;return [p.get('chart_from'),p.get('chart_to')]})
  const effectiveQuery=computed(()=>{const p=new URL(currentUrl.value).searchParams;return {...props.query,from:p.has('chart_base_from')?p.get('chart_base_from')!:props.query.from,to:p.has('chart_base_to')?p.get('chart_base_to')!:props.query.to}})
  const {request,stopped}=useApiRequest(`${import.meta.env.BASE_URL}api/leagues/${encodeURIComponent(props.leagueId)}`)
  let sequence=0,timer:ReturnType<typeof setTimeout>|undefined,lastContext=''
  const context=()=>JSON.stringify([props.active,props.projectionId,props.revision,props.settingsHash,selectedItem.value,props.view,...(['account','account_regex','account_case','account_word','stash','item','item_regex','item_case','item_word','from','to'] as Array<keyof HistoryQuery>).map(key=>effectiveQuery.value[key])])
  function chooseItem(value:string){const url=new URL(currentUrl.value);if(value)url.searchParams.set('chart_item',value);else url.searchParams.delete('chart_item');url.searchParams.delete('chart_from');url.searchParams.delete('chart_to');url.searchParams.delete('chart_ymin');url.searchParams.delete('chart_ymax');updateUrl(url)}
  async function load(){
    const current=++sequence,key=context()
    if(!props.active||!props.projectionId){data.value=null;loading.value=false;return}
    if(key!==lastContext)data.value=null
    lastContext=key;loading.value=true;error.value=''
    const params=new URLSearchParams({revision:props.revision,projection_id:props.projectionId,max_points:'240',view:props.view})
    for(const key of ['account','account_regex','account_case','account_word','stash','item','item_regex','item_case','item_word','from','to'] as Array<keyof HistoryQuery>){
      const value=effectiveQuery.value[key]
      if(key==='stash'){for(const name of effectiveQuery.value.stash)params.append('stash',name)}
      else if(typeof value==='boolean'){if(value)params.set(key,'1')}
      else if(value)params.set(key,String(value))
    }
    if(selectedItem.value)params.set('series_item',selectedItem.value)
    const [start,end]=viewport.value
    if(start!==null&&end!==null&&Number.isSafeInteger(Number(start))&&Number.isSafeInteger(Number(end))&&Number(start)<Number(end)){
      params.set('window_start',start);params.set('window_end',end)
    }
    try{
      const result:SeriesData=await request('/quantity-series?'+params)
      if(stopped()||current!==sequence)return
      if(result.league_id!==props.leagueId||result.projection.id!==props.projectionId)throw Error('projection_changed')
      data.value=result
    }catch(cause){if(!stopped()&&current===sequence)error.value=cause instanceof Error?cause.message:'report_unavailable'}
    finally{if(!stopped()&&current===sequence)loading.value=false}
  }
  watch(()=>JSON.stringify([context(),props.refreshToken,...viewport.value]),()=>{
    ++sequence;clearTimeout(timer)
    if(context()!==lastContext)data.value=null
    timer=setTimeout(()=>{void load()},180)
  },{immediate:true})
  onUnmounted(()=>{++sequence;clearTimeout(timer)})
  return {data,error,loading,selectedItem,chooseItem,reload:load}
}
