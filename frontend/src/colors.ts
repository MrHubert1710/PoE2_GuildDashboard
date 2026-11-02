export interface Hsv {h:number;s:number;v:number}
export function hexToHsv(hex:string):Hsv {
  const [r,g,b]=[1,3,5].map(index=>parseInt(hex.slice(index,index+2),16)/255) as [number,number,number]
  const max=Math.max(r,g,b),min=Math.min(r,g,b),delta=max-min
  let h=0
  if(delta)h=max===r?60*(((g-b)/delta)%6):max===g?60*((b-r)/delta+2):60*((r-g)/delta+4)
  return {h:(h+360)%360,s:max?delta/max:0,v:max}
}
export function hsvToHex({h,s,v}:Hsv){
  const c=v*s,x=c*(1-Math.abs((h/60)%2-1)),m=v-c
  const [r,g,b]=h<60?[c,x,0]:h<120?[x,c,0]:h<180?[0,c,x]:h<240?[0,x,c]:h<300?[x,0,c]:[c,0,x]
  return '#'+[r!,g!,b!].map(value=>Math.round((value+m)*255).toString(16).padStart(2,'0')).join('')
}
