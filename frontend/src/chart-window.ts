import type {BalancePoint} from './composables/useQuantitySeries'
export interface ChartWindow {start:number;end:number}
export function clampWindow(start:number,end:number,bounds:ChartWindow):ChartWindow {
  const width=Math.min(bounds.end-bounds.start,Math.max(1,Math.round(end-start)))
  const first=Math.max(bounds.start,Math.min(bounds.end-width,Math.round(start)))
  return {start:first,end:first+width}
}
export function visiblePoints(overview:BalancePoint[],details:BalancePoint[],loaded:ChartWindow|null,window:ChartWindow):BalancePoint[]{
  const merged=[...overview.filter(point=>!loaded||point.timestamp<loaded.start||point.timestamp>loaded.end),...details]
    .sort((a,b)=>a.timestamp-b.timestamp)
  if(!merged.length)return []
  let balance=merged[0]!.balance
  for(const point of merged){if(point.timestamp>=window.start)break;balance=point.balance}
  const selected:BalancePoint[]=[{timestamp:window.start,balance}]
  for(const point of merged)if(point.timestamp>=window.start&&point.timestamp<window.end){selected.push(point);balance=point.balance}
  selected.push({timestamp:window.end,balance})
  return selected
}

export function clampValueRange(start:number,end:number,bounds:ChartWindow):ChartWindow {
  const width=Math.min(bounds.end-bounds.start,Math.max(Math.min(1,bounds.end-bounds.start),end-start))
  const first=Math.max(bounds.start,Math.min(bounds.end-width,start))
  return {start:first,end:first+width}
}

// A linear context view: the selected time span occupies the central 30%.
export function navigatorDomain(window:ChartWindow):ChartWindow {
  const margin=(window.end-window.start)*(.7/.3)/2
  return {start:window.start-margin,end:window.end+margin}
}
