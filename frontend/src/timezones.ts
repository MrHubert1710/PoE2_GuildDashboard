import aliases from '../../shared/timezone-aliases.json'

export function timezoneSuggestions() {
  return [
    ...Object.entries(aliases).map(([value, offset]) => ({ value, label: `${value} (${offset})` })),
    ...Array.from({ length: 29 }, (_, index) => {
      const hour = index - 14
      const value = hour === 0 ? 'UTC+0' : `UTC${hour > 0 ? '+' : ''}${hour}`
      return { value, label: value }
    }),
    ...Intl.supportedValuesOf('timeZone').map(value => ({ value, label: value })),
  ]
}

export function normalizeDisplayTimezone(value:string){
  const input=value.trim(),zone=(aliases as Record<string,string>)[input.toUpperCase()]??input
  if(!zone||zone.length>100)throw new RangeError('invalid_timezone')
  const offset=/^UTC\s*([+-])\s*(\d{1,2})(?:(?::(\d{2}))|(\.\d{1,2}))?$/i.exec(zone)
  if(offset){
    const minutes=Number(offset[2])*60+(offset[4]?Number(offset[4])*60:Number(offset[3]??0))
    if(minutes>840||!Number.isInteger(minutes)||Number(offset[3]??0)>=60)throw new RangeError('invalid_timezone')
    return minutes===0?'UTC':`UTC${offset[1]}${String(Math.floor(minutes/60)).padStart(2,'0')}:${String(minutes%60).padStart(2,'0')}`
  }
  return new Intl.DateTimeFormat('en',{timeZone:zone}).resolvedOptions().timeZone
}

export function formatZonedDate(value: string, locale: string, timeZone: string, options?: Intl.DateTimeFormatOptions, hourFormat: 'auto'|'12'|'24' = 'auto') {
  const input = timeZone.trim()
  const zone = (aliases as Record<string, string>)[input.toUpperCase()] ?? input
  const offset = /^UTC\s*([+-])\s*(\d{1,2})(?:(?::(\d{2}))|(\.\d{1,2}))?$/i.exec(zone)
  let date = new Date(value)
  let target = zone
  if (offset) {
    const minutes = Number(offset[2]) * 60 + (offset[4] ? Number(offset[4]) * 60 : Number(offset[3] ?? 0))
    if (minutes > 840 || !Number.isInteger(minutes) || Number(offset[3] ?? 0) >= 60) throw new RangeError('invalid_timezone')
    date = new Date(date.getTime() + (offset[1] === '+' ? 1 : -1) * minutes * 60000)
    target = 'UTC'
  }
  return new Intl.DateTimeFormat(locale, { ...(options ?? { dateStyle: 'medium', timeStyle: 'short' }), timeZone: target, ...(hourFormat==='auto'?{}:{hourCycle:hourFormat==='12'?'h12':'h23'}) }).format(date)
}


export function localDay(timestamp: number, zone: string) {
  const text=formatZonedDate(new Date(timestamp).toISOString(),'sv-SE',zone,{year:'numeric',month:'2-digit',day:'2-digit'})
  return text
}
export function axisDate(timestamp: number, zone: string, language: string, span: number, hourFormat: 'auto'|'12'|'24' = 'auto') {
  const options: Intl.DateTimeFormatOptions = span < 60000
    ? {hour:'2-digit',minute:'2-digit',second:'2-digit',fractionalSecondDigits:3}
    : span < 86400000 ? {hour:'2-digit',minute:'2-digit',...(span<600000?{second:'2-digit'}:{})}
    : span < 31536000000 ? {month:'short',day:'numeric',...(span<604800000?{hour:'2-digit',minute:'2-digit'}:{})}
    : {year:'numeric',month:'short'}
  return formatZonedDate(new Date(timestamp).toISOString(),language,zone,options,hourFormat)
}

// UTC instants define filters; a local day is only an editor for their boundaries.
export function dayBoundaryUtc(day:string,zone:string,end=false){
  if(!/^\d{4}-\d{2}-\d{2}$/.test(day))throw new RangeError('invalid_date')
  const utc=Date.parse(day+'T00:00:00.000Z')
  if(!Number.isFinite(utc)||new Date(utc).toISOString().slice(0,10)!==day)throw new RangeError('invalid_date')
  const target=new Date(utc+(end?86400000:0)).toISOString().slice(0,10)
  let low=utc+(end?86400000:0)-129600000,high=low+259200000
  while(low<high){const middle=Math.floor((low+high)/2);if(localDay(middle,zone)<target)low=middle+1;else high=middle}
  return new Date(low).toISOString()
}
export function normalizeFilterTimestamp(value:string,end=false){
  if(!value)return ''
  if(/^\d{4}-\d{2}-\d{2}$/.test(value)){
    try{return dayBoundaryUtc(value,'UTC',end)}catch{return value}
  }
  if(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{3})?Z$/.test(value)){
    const stamp=Date.parse(value)
    if(Number.isFinite(stamp)&&new Date(stamp).toISOString().slice(0,10)===value.slice(0,10))return new Date(stamp).toISOString()
  }
  return value
}
