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

export function formatZonedDate(value: string, locale: string, timeZone: string, options?: Intl.DateTimeFormatOptions) {
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
  return new Intl.DateTimeFormat(locale, { ...(options ?? { dateStyle: 'medium', timeStyle: 'short' }), timeZone: target }).format(date)
}


export function localDay(timestamp: number, zone: string) {
  const text=formatZonedDate(new Date(timestamp).toISOString(),'sv-SE',zone,{year:'numeric',month:'2-digit',day:'2-digit'})
  return text
}
export function axisDate(timestamp: number, zone: string, language: string, span: number) {
  const options: Intl.DateTimeFormatOptions = span < 60000
    ? {hour:'2-digit',minute:'2-digit',second:'2-digit',fractionalSecondDigits:3}
    : span < 86400000 ? {hour:'2-digit',minute:'2-digit',...(span<600000?{second:'2-digit'}:{})}
    : span < 31536000000 ? {month:'short',day:'numeric',...(span<604800000?{hour:'2-digit',minute:'2-digit'}:{})}
    : {year:'numeric',month:'short'}
  return formatZonedDate(new Date(timestamp).toISOString(),language,zone,options)
}
