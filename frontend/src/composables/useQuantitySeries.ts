import { priceVersions } from '../pricing-state'
import { displayTimezone } from '../i18n'
import { computed, onUnmounted, ref, watch } from 'vue'
import type { HistoryQuery } from '../browsing'
import { currentUrl, updateUrl } from '../navigation'
import { useApiRequest } from './useApiRequest'
export interface BalancePoint { timestamp:number; balance:number }
export interface BalanceSeries {reconstruction?:boolean;aggregate?:boolean;color?:string;id:string;name:string;opening_balance:number;closing_balance:number;event_count:number;point_count:number;points:BalancePoint[];overview:BalancePoint[]}
export interface CursorState {timestamp:number;balances:{id:string;name:string;balance:number}[]}
export interface SeriesData {
  league_id:string;projection:{id:string|null;state:string};pricing?:{state:string;mode:string;currency:string;revision:string;coverage:string;priced_operations:number;unpriced_operations:number;estimated_operations:number};timezone:string;view:string;unit:string
  unresolved_events:number;item:string|null;items:string[];series:BalanceSeries[];resolution_ms:number|null
  sampled:boolean;series_truncated:boolean;bounds:{start:number;end:number}|null;window:{start:number;end:number}|null
  total_series:BalanceSeries|null
  navigator:{bounds:{start:number;end:number}|null;series:BalanceSeries[];total_series:BalanceSeries|null}
  totals:{added:number;removed:number;net:number;inferred:number}
}
export function useQuantitySeries(props:{leagueId:string;revision:string;settingsHash?:string;projectionId:string|null;query:HistoryQuery;active:boolean;refreshToken:number;view:string}){
  const data=ref<SeriesData|null>(null),error=ref(''),loading=ref(false)
  const selectedItem=computed(()=>new URL(currentUrl.value).searchParams.get('chart_item')||'__all__')
  const valuation=computed(()=>new URL(currentUrl.value).searchParams.get('chart_mode')!=='quantity')
  function chooseMode(value:boolean){
    const url=new URL(currentUrl.value)
    url.searchParams.set('chart_item','__all__')
    url.searchParams.set('chart_mode',value?'value':'quantity')
    url.searchParams.delete('chart_quantity_item')
    url.searchParams.delete('chart_ymin');url.searchParams.delete('chart_ymax')
    updateUrl(url)
  }
  const viewport=computed(()=>{const p=new URL(currentUrl.value).searchParams;return [p.get('chart_from'),p.get('chart_to')]})
  const effectiveQuery=computed(()=>({...props.query,...(viewport.value.every(value=>value!==null)?{from:'',to:''}:{})}))
  const {request,stopped}=useApiRequest(`${import.meta.env.BASE_URL}api/leagues/${encodeURIComponent(props.leagueId)}`)
  let sequence=0,timer:ReturnType<typeof setTimeout>|undefined,lastContext=''
  const context=()=>JSON.stringify([props.active,priceVersions.value[props.leagueId],valuation.value,displayTimezone.value,props.projectionId,props.revision,props.settingsHash,selectedItem.value,props.view,...(['account','account_regex','account_case','account_word','stash','item','item_regex','item_case','item_word'] as Array<keyof HistoryQuery>).map(key=>effectiveQuery.value[key])])
  function chooseItem(value:string){const url=new URL(currentUrl.value);if(value)url.searchParams.set('chart_item',value);else url.searchParams.delete('chart_item');url.searchParams.delete('chart_from');url.searchParams.delete('chart_to');url.searchParams.delete('chart_ymin');url.searchParams.delete('chart_ymax');updateUrl(url)}
  async function load(){
    const current=++sequence,key=context()
    if(!props.active||!props.projectionId){data.value=null;loading.value=false;return}
    if(key!==lastContext)data.value=null
    lastContext=key;loading.value=true;error.value=''
    const params=new URLSearchParams({timezone:displayTimezone.value,revision:props.revision,projection_id:props.projectionId,max_points:'240',view:props.view,mode:valuation.value?'value':'quantity'})
    for(const key of ['account','account_regex','account_case','account_word','stash','item','item_regex','item_case','item_word','from','to'] as Array<keyof HistoryQuery>){
      const value=effectiveQuery.value[key]
      if(key==='stash'){for(const name of effectiveQuery.value.stash)params.append('stash',name)}
      else if(typeof value==='boolean'){if(value)params.set(key,'1')}
      else if(value)params.set(key,String(value))
    }
    if(selectedItem.value==='__all__')params.set('all_items','1');else if(selectedItem.value)params.set('series_item',selectedItem.value)
    const [start,end]=viewport.value
    if(start!==null&&end!==null&&Number.isSafeInteger(Number(start))&&Number.isSafeInteger(Number(end))&&Number(start)<Number(end)){
      params.set('window_start',start);params.set('window_end',end)
    }
    try{
      const result:SeriesData=await request('/quantity-series?'+params)
      if(stopped()||current!==sequence)return
      if(result.league_id!==props.leagueId||result.projection.id!==props.projectionId)throw Error('projection_changed')
      data.value=result
      if(result.pricing?.state==='missing'){
        await request('/refresh',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind:'valuations',trigger:'automatic'})})
        timer=setTimeout(()=>{void load()},1500)
      }
    }catch(cause){if(!stopped()&&current===sequence)error.value=cause instanceof Error?cause.message:'report_unavailable'}
    finally{if(!stopped()&&current===sequence)loading.value=false}
  }
  async function stateAt(timestamp:number):Promise<CursorState>{
    const params=new URLSearchParams({timezone:displayTimezone.value,revision:props.revision,projection_id:props.projectionId??'',view:props.view,at:String(timestamp),mode:valuation.value?'value':'quantity',...(data.value?.pricing?{price_revision:data.value.pricing.revision}:{})})
    for(const key of ['account','account_regex','account_case','account_word','stash','item','item_regex','item_case','item_word'] as Array<keyof HistoryQuery>){
      const value=props.query[key]
      if(key==='stash'){for(const name of props.query.stash)params.append('stash',name)}
      else if(typeof value==='boolean'){if(value)params.set(key,'1')}
      else if(value)params.set(key,String(value))
    }
    if(selectedItem.value==='__all__')params.set('all_items','1')
    else if(data.value?.item)params.set('series_item',data.value.item)
    return await request('/quantity-series?'+params)
  }
  watch(()=>JSON.stringify([context(),effectiveQuery.value.from,effectiveQuery.value.to,props.refreshToken,...viewport.value]),()=>{
    ++sequence;clearTimeout(timer)
    if(context()!==lastContext)data.value=null
    timer=setTimeout(()=>{void load()},180)
  },{immediate:true})
  onUnmounted(()=>{++sequence;clearTimeout(timer)})
  return {data,error,loading,selectedItem,chooseItem,valuation,chooseMode,stateAt,reload:load}
}
